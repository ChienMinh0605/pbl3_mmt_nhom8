import ProbePanel from './legacy-probe/ProbePanel';
import {useState} from 'react';
import DeviceCsiPanel from './device-csi/DeviceCsiPanel';
export default function Dashboard() {
  const [legacy, setLegacy] = useState(window.location.hash === '#legacy');
  function show(next: boolean) {
    setLegacy(next);
    window.history.replaceState(null, '', next ? '#legacy' : '#device-activity');
  }
  return <div className={`detect-app${legacy ? '' : ' q1-console'}`}>
    <header className="detect-header">
      <div className="detect-header-inner">
        <a href="#device-activity" onClick={() => show(false)} className="detect-brand">
          {legacy && <span className="detect-mark" aria-hidden="true"><i/><i/><i/><i/></span>}
          <span>WiFi Device Sherlock</span>
        </a>
        <nav className="detect-nav" aria-label="Màn hình nghiên cứu">
          <button aria-pressed={!legacy} onClick={() => show(false)}>Device Activity Monitoring</button>
          <button aria-pressed={legacy} onClick={() => show(true)}>Legacy / Probe</button>
        </nav>
        {legacy ? <span className="detect-board">ESP32-C3 · 2.4 GHz</span> : <div id="q1-header-status"/>}
      </div>
    </header>
    <main className="detect-main">
      {legacy ? <ProbePanel/> : <DeviceCsiPanel/>}
    </main>
  </div>;
}
