"""Evaluate externally generated A/B/C predictions on a frozen session split."""

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Annotated, Literal

from pydantic import Field, model_validator

from research.csi_ingestion import Record


METHODS = ('A', 'B', 'C')
Score = Annotated[float, Field(ge=0, le=1)]
Identifier = Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')]
Label = Literal['GOOD', 'DEGRADED', 'UNKNOWN']


class Window(Record):
    start_s: Annotated[float, Field(ge=0)]
    end_s: Annotated[float, Field(gt=0)]
    fall: bool | None
    scores: dict[Literal['A', 'B', 'C'], Score | None]
    device_truth: bool | None = None
    device_observed: bool | None = None
    quality_truth: Label | None = None
    quality_estimate: Label | None = None


class Session(Record):
    session_id: Identifier
    group_id: Identifier
    recording_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    provenance: Literal['measured', 'synthetic']
    windows: list[Window] = Field(min_length=1)

    @model_validator(mode='after')
    def check_windows(self):
        previous = 0
        for row in self.windows:
            if row.start_s < previous or row.start_s >= row.end_s:
                raise ValueError('Windows must be ordered, non-overlapping and positive in duration')
            previous = row.end_s
        return self


class Study(Record):
    development: list[Session] = Field(min_length=1)
    test: list[Session] = Field(min_length=1)

    @model_validator(mode='after')
    def disjoint_split(self):
        sessions = self.development + self.test
        for key in ('session_id', 'recording_sha256'):
            if len({getattr(session, key) for session in sessions}) != len(sessions):
                raise ValueError(f'Duplicate {key} across the study')
        if {session.group_id for session in self.development} & {session.group_id for session in self.test}:
            raise ValueError('A capture group cannot cross the development/test split')
        return self


def supported(row):
    return row.fall is not None and all(row.scores.get(method) is not None for method in METHODS)


def f1(tp, fp, fn):
    denominator = 2 * tp + fp + fn
    return 2 * tp / denominator if denominator else None


def freeze_thresholds(development):
    rows = [row for session in development for row in session.windows if supported(row)]
    if {row.fall for row in rows} != {False, True}:
        raise ValueError('Development needs positive and negative ground truth with scores from A/B/C')
    thresholds = {}
    for method in METHODS:
        def score(threshold):
            tp = sum(row.fall and row.scores[method] >= threshold for row in rows)
            fp = sum(not row.fall and row.scores[method] >= threshold for row in rows)
            fn = sum(row.fall and row.scores[method] < threshold for row in rows)
            return f1(tp, fp, fn), threshold

        thresholds[method] = max((step / 100 for step in range(101)), key=score)
    return thresholds


def fall_segments(windows):
    start, end, current = None, None, []
    for row in windows:
        if current and (row.start_s != end or row.fall is not True):
            yield start, current
            current = []
        if row.fall is True:
            if not current:
                start = row.start_s
            current.append(row)
            end = row.end_s
    if current:
        yield start, current


def score_test(test, method, threshold):
    matrix = Counter()
    false_alarms, quiet_seconds, event_count = 0, 0., 0
    delays = []
    for session in test:
        previous_alarm, previous_end = False, None
        for row in session.windows:
            if not supported(row):
                previous_alarm, previous_end = False, None
                continue
            detected = row.scores[method] >= threshold
            matrix[row.fall, detected] += 1
            false_alarm = not row.fall and detected
            if not row.fall:
                quiet_seconds += row.end_s - row.start_s
            if false_alarm and (not previous_alarm or previous_end != row.start_s):
                false_alarms += 1
            previous_alarm, previous_end = false_alarm, row.end_s
        for start, activity in fall_segments(session.windows):
            eligible = [row for row in activity if supported(row)]
            if eligible:
                event_count += 1
                detection = next((row for row in eligible if row.scores[method] >= threshold), None)
                if detection:
                    delays.append(detection.end_s - start)

    return dict(threshold=threshold, window_f1=f1(matrix[True, True], matrix[False, True], matrix[True, False]),
                false_alarms=false_alarms if quiet_seconds else None,
                false_alarms_per_hour=false_alarms * 3600 / quiet_seconds if quiet_seconds else None,
                negative_time_s=quiet_seconds, scorable_falls=event_count,
                fall_recall=len(delays) / event_count if event_count else None,
                mean_detection_delay_s=mean(delays) if delays else None, detection_delays_s=delays)


def categorical(rows, truth_attr, predicted_attr):
    pairs = [pair for row in rows if None not in (pair := (getattr(row, truth_attr), getattr(row, predicted_attr)))]
    confusion = Counter(pairs)
    return dict(labeled=len(pairs), accuracy=sum(a == b for a, b in pairs) / len(pairs) if pairs else None,
                confusion=[dict(truth=a, estimate=b, n=count) for (a, b), count in sorted(confusion.items())])


def evaluate(study, *, allow_synthetic=False):
    synthetic = any(session.provenance == 'synthetic' for session in study.development + study.test)
    if synthetic and not allow_synthetic:
        raise ValueError('Synthetic input requires --allow-synthetic and is not an experimental result')
    thresholds = freeze_thresholds(study.development)
    rows = [row for session in study.test for row in session.windows]
    return dict(version='reliability-evaluation-v1', synthetic=synthetic,
                development_sessions=[session.session_id for session in study.development],
                test_sessions=[session.session_id for session in study.test],
                common_windows=sum(supported(row) for row in rows), total_test_windows=len(rows),
                device_activity=categorical(rows, 'device_truth', 'device_observed'),
                csi_quality=categorical(rows, 'quality_truth', 'quality_estimate'),
                methods={method: score_test(study.test, method, thresholds[method]) for method in METHODS})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('study', type=Path)
    parser.add_argument('--allow-synthetic', action='store_true')
    args = parser.parse_args()
    print(json.dumps(evaluate(Study.model_validate_json(args.study.read_bytes()),
                              allow_synthetic=args.allow_synthetic), indent=2))


if __name__ == '__main__':
    main()
