"""Offline CSI receive quality and same-channel traffic context."""

from bisect import bisect_left
from dataclasses import dataclass
from math import ceil
from statistics import median, pstdev, pvariance
from typing import Annotated

from pydantic import Field

from research.csi_ingestion import ClockAnchor, Record


SECOND = 1_000_000
Positive = Annotated[float, Field(gt=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]


class QualityRules(Record):
    min_coverage: Annotated[float, Field(gt=0, le=1)] = 0.8
    min_rx_hz: Positive = 5.0
    max_loss_fraction: Fraction = 0.10
    max_interarrival_p95_us: Positive = 500_000.0
    max_rssi_variance_db2: Positive = 25.0
    activity_elevated_fps: Positive = 100.0
    max_sync_error_us: Positive = 50_000.0
    max_drift_ppm: Positive = 200.0


@dataclass(frozen=True)
class ClockFit:
    first: ClockAnchor | None = None
    last: ClockAnchor | None = None
    scale: float | None = None
    error_us: float | None = None
    reason: str | None = None

    def project(self, tick):
        if self.reason or not self.first.board_us <= tick <= self.last.board_us:
            return None
        return self.first.session_us + round((tick - self.first.board_us) * self.scale)

    def summary(self):
        return dict(aligned=self.reason is None, reason=self.reason, sync_error_us=self.error_us,
                    clock_offset_us=self.first.session_us - self.first.board_us if self.first else None,
                    offset_at_board_us=self.first.board_us if self.first else None,
                    drift_ppm=(self.scale - 1) * SECOND if self.scale is not None else None)


def fit_clock(anchors, rules):
    if len(anchors) < 2:
        return ClockFit(reason='missing_clock_anchors')
    if any(a.board_us >= b.board_us or a.session_us >= b.session_us for a, b in zip(anchors, anchors[1:])):
        return ClockFit(reason='nonmonotonic_clock_anchors')
    first, last = anchors[0], anchors[-1]
    scale = (last.session_us - first.session_us) / (last.board_us - first.board_us)
    error = max(abs((anchor.board_us - first.board_us) * scale - (anchor.session_us - first.session_us))
                + anchor.uncertainty_us for anchor in anchors)
    reason = None
    if abs(scale - 1) * SECOND > rules.max_drift_ppm:
        reason = 'clock_drift_exceeded'
    elif error > rules.max_sync_error_us:
        reason = 'clock_uncertainty_exceeded'
    return ClockFit(first, last, scale, error, reason)


def project_intervals(rows, clock):
    if clock.reason:
        return []
    output = []
    for row in rows:
        start, end = clock.project(row.start_us), clock.project(row.end_us)
        if start is not None and end is not None and end > start:
            output.append((start, end, row))
    return output


def intersection(rows, start, end):
    return sum(max(0, min(end, high) - max(start, low)) for low, high, _ in rows)


def within(rows, start, end):
    return [(low, high, row) for low, high, row in rows if start <= low and high <= end]


def loss_measure(trace, samples, full_coverage, window_s):
    if not full_coverage:
        return None, None, None, 'loss_requires_full_rx_coverage'
    expected_tx_hz = trace.expected_tx_hz if trace.tx_rate_verified else None
    unique = len(samples)
    if trace.sequence_kind == 'tx_contiguous' and samples:
        sequences = [sample.seq for sample in samples]
        if None in sequences:
            return None, None, None, 'missing_tx_sequence'
        deltas = []
        for previous, current in zip(sequences, sequences[1:]):
            delta = current - previous
            if trace.seq_modulus is not None:
                delta %= trace.seq_modulus
            if delta < 0 or (trace.seq_modulus is not None and delta * 2 >= trace.seq_modulus):
                return None, None, None, 'ambiguous_tx_sequence'
            if delta:
                deltas.append(delta)
        unique = len(deltas) + 1
        if expected_tx_hz is None and deltas:
            expected = sum(deltas) + 1
            return expected - unique, expected, 'tx_sequence_interior', None
    if expected_tx_hz is not None:
        expected = expected_tx_hz * window_s
        if unique > expected:
            return None, None, None, 'expected_tx_rate_mismatch'
        return expected - unique, expected, 'expected_tx_rate', None
    return None, None, None, 'loss_evidence_unavailable'


def telemetry_count(rows, field, start, end):
    supported = [(low, high, value) for low, high, row in within(rows, start, end)
                 if (value := getattr(row, field)) is not None]
    if sum(high - low for low, high, _ in supported) != end - start:
        return None
    return sum(value for _, _, value in supported)


def sniffer_activity(rows, start, end, channel, rules, sync_error):
    matching = [(low, high, row) for low, high, row in within(rows, start, end) if row.channel == channel]
    covered_us = sum(high - low for low, high, _ in matching)
    coverage = covered_us / (end - start)
    if sync_error is None or sync_error > rules.max_sync_error_us:
        return None, None, coverage, 'sniffer_clock_not_aligned'
    if coverage < rules.min_coverage:
        different_channel = any(low < end and high > start and row.channel != channel for low, high, row in rows)
        return None, None, coverage, 'sniffer_other_channel' if different_channel else 'sniffer_insufficient_coverage'
    rate = sum(row.frame_count for _, _, row in matching) * SECOND / covered_us
    return rate, 'ELEVATED' if rate >= rules.activity_elevated_fps else 'LOW', coverage, None


def registered_activity(rows, start, end, channel, rules):
    matched = [(low, high, row.devices) for low, high, row in within(rows, start, end)
               if row.channel == channel and row.devices is not None]
    duration = sum(high - low for low, high, _ in matched)
    if not duration or duration / (end - start) < rules.min_coverage:
        return None
    observed = {device for _, _, devices in matched for device, counts in devices.items() if counts.frames}
    frames = sum(counts.frames for _, _, devices in matched for counts in devices.values())
    byte_count = sum(counts.bytes for _, _, devices in matched for counts in devices.values())
    return dict(active_devices=len(observed), frames_per_s=frames * SECOND / duration,
                bytes_per_s=byte_count * SECOND / duration)


def csi_impairments(rate, loss, p95, variance, rules):
    limits = ((rate, rules.min_rx_hz, 'low_rx_rate', True),
              (loss, rules.max_loss_fraction, 'high_packet_loss', False),
              (p95, rules.max_interarrival_p95_us, 'irregular_csi_arrivals', False),
              (variance, rules.max_rssi_variance_db2, 'high_rssi_variance', False))
    return [reason for value, limit, reason, lower in limits
            if value is not None and (value < limit if lower else value > limit)]


def quality_window(trace, rules, samples, rx_spans, telemetry, sniffer, start, end, rx_aligned, sync_error):
    coverage_us = intersection(rx_spans, start, end)
    coverage = coverage_us / (end - start)
    observed = len(samples)
    if trace.sequence_kind == 'tx_contiguous':
        samples = [item for index, item in enumerate(samples)
                   if not index or item[1].seq is None or item[1].seq != samples[index - 1][1].seq]
    rate = len(samples) * SECOND / coverage_us if coverage_us and rx_aligned else None
    lost, expected, loss_basis, loss_reason = loss_measure(trace, [row for _, row, _ in samples],
                                                            coverage_us == end - start, (end - start) // SECOND)
    loss_fraction = lost / expected if expected else None
    # A capture gap is missing evidence, not a long packet interarrival.
    continuous_gaps = [b[0] - a[0] for a, b in zip(samples, samples[1:]) if a[2] == b[2]]
    gaps = sorted(continuous_gaps)
    filtered = telemetry_count(telemetry, 'n_filtered', start, end)
    emitted = telemetry_count(telemetry, 'n_rx_emitted', start, end)
    window_s = (end - start) / SECOND
    p95_gap = gaps[ceil(0.95 * len(gaps)) - 1] if gaps else None
    rssis = [row.rssi_dbm for _, row, _ in samples if row.rssi_dbm is not None]
    noises = [row.noise_floor_dbm for _, row, _ in samples if row.noise_floor_dbm is not None]
    variance = pvariance(rssis) if len(rssis) >= 2 else None

    reasons = []
    if trace.receiver_id is None:
        reasons.append('receiver_id_unavailable')
    if not rx_aligned:
        reasons.append('rx_clock_not_aligned')
    if coverage < rules.min_coverage:
        reasons.append('rx_insufficient_coverage')
    if reasons:
        quality = 'UNKNOWN'
    else:
        reasons = csi_impairments(rate, loss_fraction, p95_gap, variance, rules)
        quality = 'DEGRADED' if reasons else 'GOOD'

    sniffer_rate, indicator, sniffer_coverage, activity_reason = sniffer_activity(
        sniffer, start, end, trace.channel, rules, sync_error)
    return dict(start_us=start, end_us=end, quality=quality, reasons=reasons, rx_coverage=coverage,
                data_valid=quality != 'UNKNOWN', csi_received=observed if rate is not None else None, csi_receive_hz=rate,
                expected_packets=expected, lost_packets=lost, packet_loss_fraction=loss_fraction,
                loss_basis=loss_basis, loss_unavailable_reason=loss_reason,
                tx_packet_rate=trace.expected_tx_hz if trace.tx_rate_verified else None,
                jitter_ms=pstdev(gaps) / 1000 if len(gaps) >= 2 else None,
                interarrival_median_us=median(gaps) if gaps else None, interarrival_p95_us=p95_gap,
                rssi_median_dbm=median(rssis) if rssis else None, rssi_variance_db2=variance,
                noise_floor_median_dbm=median(noises) if noises else None,
                rx_emitted_hz=emitted / window_s if emitted is not None else None,
                n_filtered=filtered, n_filtered_hz=filtered / window_s if filtered is not None else None,
                sniffer_coverage=sniffer_coverage, sniffer_frames_per_s=sniffer_rate,
                channel_activity_indicator=indicator, activity_unavailable_reason=activity_reason,
                registered_activity=registered_activity(sniffer, start, end, trace.channel, rules) if indicator else None,
                comparison_ready=quality != 'UNKNOWN' and indicator is not None)


def timeline(trace, rules, window_s):
    if window_s not in (1, 10):
        raise ValueError('Window must be 1 or 10 seconds')
    rx_clock = fit_clock(trace.rx_clock, rules)
    sniffer_clock = fit_clock(trace.sniffer_clock, rules)
    rx_spans = project_intervals(trace.rx_connected, rx_clock)
    contiguous = []
    for low, high, row in rx_spans:
        if contiguous and contiguous[-1][1] == low:
            contiguous[-1] = (contiguous[-1][0], high, row)
        else:
            contiguous.append((low, high, row))
    rx_spans = contiguous
    telemetry = project_intervals(trace.rx_telemetry, rx_clock)
    sniffer = project_intervals(trace.sniffer_intervals, sniffer_clock)
    samples = []
    # Both normalized lists are monotonic. Keep samples supported by declared RX coverage.
    span_index = 0
    if rx_spans:
        for sample in trace.samples:
            tick = rx_clock.project(sample.ts_us)
            if tick is None or not 0 <= tick < trace.duration_s * SECOND:
                continue
            while span_index < len(rx_spans) and rx_spans[span_index][1] <= tick:
                span_index += 1
            if span_index < len(rx_spans) and rx_spans[span_index][0] <= tick:
                samples.append((tick, sample, span_index))

    sync_error = None if rx_clock.reason or sniffer_clock.reason else rx_clock.error_us + sniffer_clock.error_us
    stamps = [tick for tick, _, _ in samples]
    width = window_s * SECOND
    windows = []
    for start in range(0, trace.duration_s * SECOND - width + 1, width):
        end = start + width
        rows = samples[bisect_left(stamps, start):bisect_left(stamps, end)]
        windows.append(quality_window(trace, rules, rows, rx_spans, telemetry, sniffer, start, end,
                                      not rx_clock.reason, sync_error))
    return dict(version='csi-quality-timeline-v1', provenance=trace.provenance, heuristic_uncalibrated=True,
                channel=trace.channel, receiver_id=trace.receiver_id, window_s=window_s, rules=rules.model_dump(),
                receive_rate_basis='normalized_rx_records_deduplicated_when_tx_sequence_verified',
                clocks=dict(rx=rx_clock.summary(), sniffer=sniffer_clock.summary(), combined_error_us=sync_error,
                            comparison_aligned=sync_error is not None and sync_error <= rules.max_sync_error_us),
                supported_rx_samples=len(samples), input_rx_samples=len(trace.samples),
                input_rx_intervals=len(trace.rx_connected), input_sniffer_intervals=len(trace.sniffer_intervals), windows=windows)


def quality_result(report, row, offset_us=0, *, unavailable=None):
    """The quality projection shared by timeline and experiment export."""
    fields = ('csi_receive_hz', 'tx_packet_rate', 'packet_loss_fraction', 'jitter_ms',
              'rssi_median_dbm', 'noise_floor_median_dbm', 'n_filtered', 'rx_coverage',
              'loss_basis', 'loss_unavailable_reason')
    values = {field: row.get(field) if row and not unavailable else None for field in fields}
    return dict(values, receiver_id=report.get('receiver_id') if report else None,
                channel=report['channel'] if report else None,
                window_start_us=row['start_us'] + offset_us if row else None,
                window_end_us=row['end_us'] + offset_us if row else None,
                quality=row['quality'] if row and not unavailable and report.get('receiver_id') else 'UNKNOWN',
                data_valid=bool(row and report.get('receiver_id') and row['quality'] != 'UNKNOWN' and not unavailable),
                reasons=[unavailable] if unavailable else row['reasons'] or (
                    ['receiver_id_unavailable'] if not report.get('receiver_id') else []) if row else [])
