import json
import os
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from serial.tools import list_ports
from research.collector import ProbeService
from research.dashboard import DashboardConfig
from research.detectors import ProbeConfig
from backend.app.api.probe import configure, router
from backend.app.api.device_activity import router as activity_router
from backend.app.api.csi_quality import router as csi_quality_router
from backend.app.api.csi_reliability import router as reliability_router
from backend.app.api.device_csi_experiments import router as experiments_router
ROOT=Path(__file__).resolve().parents[2]
load_dotenv(ROOT/'.env')
def rooted(value):
    p=Path(value);return p if p.is_absolute() else ROOT/p
svc=None
@asynccontextmanager
async def lifespan(app):
    global svc
    cfg_path=rooted(os.getenv('WIFI_PROBE_CONFIG','configs/probe.json'))
    cfg=ProbeConfig(**json.loads(cfg_path.read_text()))
    dashboard_path = os.getenv('WIFI_DASHBOARD_CONFIG')
    dashboard = DashboardConfig.model_validate_json(rooted(dashboard_path).read_text()) if dashboard_path else DashboardConfig()
    simulation_port = os.getenv('WIFI_SIMULATION_PTY')
    data_root = rooted(os.getenv('WIFI_PROBE_DATA_DIR', 'data/runtime')).resolve()
    if simulation_port:
        sim_root = rooted(os.environ['WIFI_SIMULATION_DATA_DIR']).resolve()
        if sim_root.is_relative_to(data_root) or data_root.is_relative_to(sim_root):
            raise ValueError('Thư mục SIMULATION phải tách khỏi dữ liệu LIVE')
        data_root = sim_root
    service = ProbeService(data_root, cfg, dashboard, simulation_port=simulation_port)
    svc = app.state.probe_service = service
    configure(service,cfg_path)
    try:
        yield
    finally:
        try:
            await service.stop()
        finally:
            service.store.close()
app=FastAPI(title='WiFi Device Detection — Sherlock adaptation',version='1.1.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173','http://localhost:8000','http://127.0.0.1:8000'],allow_methods=['GET','POST','PUT','PATCH','DELETE'],allow_headers=['Content-Type'])
app.include_router(router)
app.include_router(activity_router)
app.include_router(csi_quality_router)
app.include_router(reliability_router)
app.include_router(experiments_router)
@app.get('/api/ports')
async def ports():
    if svc and svc.simulation_port:
        return [dict(device=svc.simulation_port, description='Python PTY · SIMULATION')]
    ports = sorted(list_ports.comports(), key=lambda port: (port.vid is None, port.device))
    return [dict(device=port.device, description=port.description) for port in ports]
@app.get('/api/health')
async def health():return dict(ok=True,scope='probe-only',algorithm='Sherlock adaptation',capabilities=['probe-v1','device-activity-v2','csi-quality-synthetic-replay','csi-reliability-v1'])
if (ROOT/'frontend/dist').is_dir():app.mount('/',StaticFiles(directory=ROOT/'frontend/dist',html=True),name='dashboard')
