"""Explicit synthetic fixtures for the integrated dashboard demo."""

from research.csi_ingestion import CsiTrace
from research.device_activity import ActivityMonitor


def demo_trace():
    second = 1_000_000
    anchors = [dict(board_us=t * second, session_us=t * second, uncertainty_us=1000) for t in (0, 20)]
    return CsiTrace.model_validate(dict(
        version='csi-quality-input-v1', provenance='synthetic', receiver_id='sim-rx', duration_s=20, channel=6,
        rx_clock=anchors, sniffer_clock=anchors, sniffer_source='SIMULATION', rx_connected=[dict(start_us=0, end_us=20 * second)],
        sequence_kind='tx_contiguous', expected_tx_hz=10, tx_rate_verified=True,
        samples=[dict(ts_us=i * 100_000 + 50_000, seq=i, rssi_dbm=-48 - (i % 2) * 2, noise_floor_dbm=-95)
                 for i in range(200) if i < 100 or i % 5 != 0],
        sniffer_intervals=[dict(start_us=i * second, end_us=(i + 1) * second, channel=6,
                                frame_count=40 if i < 5 else 180,
                                devices={'d' * 32: dict(frames=24, bytes=2800)}) for i in range(20)],
    ))


def demo_activity(trace):
    """Run the simulated sniffer counts through the same monitor as UART."""
    device_id = next(iter(trace.sniffer_intervals[0].devices))
    monitor = ActivityMonitor([dict(id=device_id, name='Thiết bị mô phỏng', channel=trace.channel)])
    common = dict(boot_id=device_id[:16], channel=trace.channel)
    status = dict(type='status', registered_devices=1, invalid_frames=0,
                  off_channel_frames=0, unattributed_frames=0, serial_errors=0)
    monitor.feed(common | status | dict(ts_us=0, seq=0, rx_callbacks=0), 0)
    total = 0
    for index, span in enumerate(trace.sniffer_intervals):
        counts = span.devices[device_id]
        stamp = span.end_us / 1_000_000
        monitor.feed(common | dict(type='activity_sample', seq=2 * index + 1,
                                   ts_us=span.start_us, duration_us=span.end_us - span.start_us,
                                   device_id=device_id, frame_kind='data', n_frames=counts.frames,
                                   n_bytes=counts.bytes, rssi_max_dbm=-47), stamp)
        total += span.frame_count
        monitor.feed(common | status | dict(ts_us=span.end_us, seq=2 * index + 2, rx_callbacks=total), stamp)
        yield from monitor.completed
