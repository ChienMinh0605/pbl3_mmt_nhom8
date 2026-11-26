import pytest

from research.reliability_evaluation import Study, evaluate


def session(name, digest, *, synthetic=True):
    return dict(session_id=name, group_id=name, recording_sha256=digest * 64,
                provenance='synthetic' if synthetic else 'measured', windows=[
                    dict(start_s=0, end_s=1, fall=False, scores={'A': .15, 'B': .2, 'C': .1},
                         device_truth=False, device_observed=False, quality_truth='GOOD', quality_estimate='GOOD'),
                    dict(start_s=1, end_s=2, fall=True, scores={'A': .9, 'B': .8, 'C': .7}),
                    dict(start_s=2, end_s=3, fall=True, scores={'A': .9, 'B': .8, 'C': None}),
                ])


def test_common_windows_metrics_and_development_only_thresholds():
    dev = session('dev', 'a')
    held_out = session('test', 'b')
    study = Study.model_validate(dict(development=[dev], test=[held_out]))
    with pytest.raises(ValueError, match='Synthetic'):
        evaluate(study)
    first = evaluate(study, allow_synthetic=True)
    assert first['synthetic'] and first['common_windows'] == 2 and first['total_test_windows'] == 3
    assert first['device_activity']['accuracy'] == first['csi_quality']['accuracy'] == 1
    assert first['methods']['A']['fall_recall'] == 1 and first['methods']['A']['mean_detection_delay_s'] == 1
    held_out['windows'][1]['scores']['A'] = .1
    revised = evaluate(Study.model_validate(dict(development=[dev], test=[held_out])), allow_synthetic=True)
    assert revised['methods']['A']['threshold'] == first['methods']['A']['threshold']
    assert revised['methods']['A']['fall_recall'] == 0 and revised['methods']['A']['mean_detection_delay_s'] is None


@pytest.mark.parametrize(('change', 'message'), [({'group_id': 'dev'}, 'capture group'),
                                                ({'session_id': 'dev'}, 'session_id'),
                                                ({'recording_sha256': 'a' * 64}, 'recording_sha256')])
def test_rejects_session_group_and_duplicate_trace_leakage(change, message):
    with pytest.raises(ValueError, match=message):
        Study.model_validate(dict(development=[session('dev', 'a')], test=[session('test', 'b') | change]))
