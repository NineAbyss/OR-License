import json

import pytest

from test_model_review_per_epoch import (CASES, GOOD, BAD, ROOT, run_review,
                                         fake_payload)


@pytest.mark.parametrize('case', sorted(CASES))
def test_uncertain_is_protocol_error(case, tmp_path):
    def reply(b, g, c):
        p = fake_payload(b, g, c)
        p['epochs'][0]['checks'][0]['status'] = 'uncertain'
        return p
    r = run_review(case, tmp_path, {i: GOOD for i in range(8)}, reply)
    assert r['report']['status'] is None
    assert r['report']['service_status'] == 'error'
    assert isinstance(r['error'], r['module'].ModelReviewUnavailable)


@pytest.mark.parametrize('case', sorted(CASES))
def test_format_retry_has_specific_feedback(case, tmp_path):
    attempts = []

    def reply(b, g, c):
        attempts.append(1)
        return {'checks': []} if len(attempts) == 1 else fake_payload(b, g, c)
    r = run_review(case, tmp_path, {i: GOOD for i in range(8)}, reply)
    assert r['result'] == (True, '')
    feedback = r['calls'][1]['messages'][-1]['content']
    assert 'epochs' in feedback and 'expected_epochs' in feedback
    assert r['report']['service_status'] == 'completed'


@pytest.mark.parametrize('case', sorted(CASES))
def test_decisive_fail_survives_later_transport_failure(case, tmp_path):
    def reply(b, g, c):
        if 0 in g['epochs']:
            return fake_payload(b, g, c, failing_epochs=g['epochs'])
        raise OSError('secret must not enter report')
    r = run_review(case, tmp_path, {i: BAD if i == 0 else GOOD for i in range(8)}, reply)
    assert r['error'] is None and r['result'][0] is False
    assert r['report']['status'] == 'fail'
    assert r['report']['rounds']['0'] == 'fail'
    assert 'secret' not in json.dumps(r['report'])


@pytest.mark.parametrize('case', sorted(CASES))
def test_missing_organizer_source_is_service_error(case, tmp_path):
    r = run_review(case, tmp_path, {i: GOOD for i in range(8)}, fake_payload, source_error_epoch=3)
    assert r['report']['service_status'] == 'error'
    assert r['report']['status'] is None
    assert not r['calls']


def test_worker_service_error_is_not_a_false_verdict(tmp_path):
    import subprocess
    import sys
    program = tmp_path / 'program'
    program.mkdir()
    (program / 'verifier.py').write_text('class ModelReviewUnavailable(RuntimeError): pass\ndef verify(i,o): raise ModelReviewUnavailable("service unavailable")\n')
    (program / 'evaluator.py').write_text('def evaluate(i,o): raise AssertionError("must not score")\n')
    worker = ROOT / 'harbor_integration/coding_agent/judge_worker.py'
    done = subprocess.run([sys.executable, str(worker), str(program), 'input', 'output'],
                          capture_output=True, text=True, check=True)
    row = json.loads(done.stdout.split('=', 1)[1])
    assert row['validity'] is None
    assert row['review_service_error'] is True and 'pending_review' not in row


def test_checkpoint_resume_skips_completed_group(tmp_path):
    case = '31_sharedbike_robust_e2e'
    attempts = []

    def interrupted(b, g, c):
        if 0 not in g['epochs']:
            raise OSError('offline')
        return fake_payload(b, g, c)
    r = run_review(case, tmp_path, {i: BAD if i == 0 else GOOD for i in range(8)}, interrupted)
    assert r['report']['status'] is None
    assert len(r['report']['group_results']) == 1
    m = r['module']

    def resumed(policy, messages, key):
        epochs = json.loads(messages[1]['content'])['expected_epochs']
        attempts.append(epochs)
        g = next(g for g in r['bundle']['groups'] if g['epochs'] == epochs)
        return fake_payload(r['bundle'], g, r['criteria']), {}, 'fake'
    m._request = resumed
    assert m.review_after_deterministic(tmp_path / 'input01.json', tmp_path / '01.json', tmp_path / 'program')[0]
    assert len(attempts) == 1 and 0 not in attempts[0]


def test_changed_evidence_discards_checkpoint(tmp_path):
    case = '31_sharedbike_robust_e2e'

    def interrupted(b, g, c):
        if 0 not in g['epochs']:
            raise OSError('offline')
        return fake_payload(b, g, c)
    r = run_review(case, tmp_path, {i: BAD if i == 0 else GOOD for i in range(8)}, interrupted)
    assert len(r['report']['group_results']) == 1
    binding = (tmp_path / '01.model_review.binding.json')
    assert binding.is_file()
    binding.write_text(binding.read_text() + ' ', encoding='utf-8')
    attempts = []
    m = r['module']

    def resumed(policy, messages, key):
        epochs = json.loads(messages[1]['content'])['expected_epochs']
        attempts.append(epochs)
        g = next(g for g in r['bundle']['groups'] if g['epochs'] == epochs)
        return fake_payload(r['bundle'], g, r['criteria']), {}, 'fake'
    m._request = resumed
    assert m.review_after_deterministic(tmp_path / 'input01.json', tmp_path / '01.json', tmp_path / 'program')[0]
    assert len(attempts) == len(r['bundle']['groups'])


def test_insufficient_acceptance_evidence_is_labeled_fail(tmp_path):
    def reply(b, g, c):
        p = fake_payload(b, g, c)
        check = p['epochs'][0]['checks'][0]
        check.update(status='fail', reason_code='insufficient_evidence',
                     missing_requirement='model objective linkage', evidence=[])
        return p
    r = run_review('31_sharedbike_robust_e2e', tmp_path, {i: GOOD for i in range(8)}, reply)
    assert r['report']['status'] == 'fail'
    assert r['report']['group_payloads'][0]['epochs'][0]['checks'][0]['reason'].startswith('未满足验收证据要求')


@pytest.mark.parametrize('case', sorted(CASES))
def test_effective_prompt_has_single_binary_protocol(case):
    import re
    import importlib.util
    p = ROOT / 'tasks' / case / 'problem/input/program/_model_review.py'
    spec = importlib.util.spec_from_file_location('prompt_check', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    policy = json.loads(p.with_name('_model_review_policy.json').read_text())
    kind = policy['optimization_kind']
    b = {'epochs': [{'epoch': 0, 'submission_b64': 's', 'input_b64': 'i', 'files': [],
                     'solver_calls': [], 'evidence_gaps': []}]}
    prompt = m.build_review_messages(b, {'epochs': [0]}, p.with_name('_model_review_contract.md').read_text(), kind)[0]['content']
    assert not re.search(r'\buncertain\b|needs_review|pending_review', prompt)
    assert not re.search(r'sha256|\bhash', prompt)
    assert 'status (pass or fail only)' in prompt
    assert 'top-level epochs and warnings arrays' in prompt


def test_verifier_summary_has_no_score_for_service_error():
    from workflow.judgment_results import summarize_judgments
    result = summarize_judgments([{'validity': None, 'cost': None, 'review_service_error': True}])
    assert result['success'] is None and result['valid_cases'] is None
    assert result['review_service_error'] is True and result['mean_cost'] is None


def test_service_error_reward_payload_omits_zero():
    from workflow.judgment_results import summarize_judgments, judgment_rewards
    error = summarize_judgments([{'validity': None, 'cost': None, 'review_service_error': True}])
    assert 'reward' not in judgment_rewards(error)
    fail = summarize_judgments([{'validity': False, 'cost': None}])
    assert judgment_rewards(fail)['reward'] == 0
    passed = summarize_judgments([{'validity': True, 'cost': 12.5}])
    assert judgment_rewards(passed)['mean_cost'] == 12.5
