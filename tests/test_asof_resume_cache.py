import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/asof_firewall"))
from resume_cache import ResumeDivergence, check_sources, load_verified_day, recorded_bytes

HOLDINGS = [{"stockcode": "000001.SZ", "volume": 100.0, "close": 10.0}]


def _write_day(calls, day, *, nav=1e6, status="ok", target=b"instrument,weight\nA,1\n"):
    call = calls / day
    call.mkdir(parents=True)
    (call / "target_weights.csv").write_bytes(target)
    record = {"decision_day": day, "mode": "rebalance", "status": status,
              "final_action": "target_delivered", "verifier_result": {"valid": True},
              "nav": nav, "cash": 0.0, "actual_holdings": HOLDINGS,
              "raw_target_b64": base64.b64encode(target).decode("ascii")}
    (call / "daily_record.json").write_text(json.dumps(record), encoding="utf-8")
    return call


def _load(calls, day, nav=1e6):
    return load_verified_day(calls, day, "rebalance", profile_key="enhanced_index",
                             nav=nav, cash=0.0, holdings=HOLDINGS)


def test_verified_day_is_reused_and_binds_target_bytes(tmp_path):
    calls = tmp_path / "evaluation_calls"
    _write_day(calls, "2025-06-03")
    record, call = _load(calls, "2025-06-03")
    assert recorded_bytes(record, "raw_target_b64") == (call / "target_weights.csv").read_bytes()


def test_missing_or_failed_day_is_live_frontier(tmp_path):
    calls = tmp_path / "evaluation_calls"
    _write_day(calls, "2025-06-04", status="rebalance_infrastructure_failure")
    assert _load(calls, "2025-06-03") is None
    assert _load(calls, "2025-06-04") is None


def test_changed_broker_state_diverges(tmp_path):
    calls = tmp_path / "evaluation_calls"
    _write_day(calls, "2025-06-03")
    with pytest.raises(ResumeDivergence):
        _load(calls, "2025-06-03", nav=2e6)


def test_legacy_record_without_full_target_starts_live(tmp_path):
    calls = tmp_path / "evaluation_calls"
    call = _write_day(calls, "2025-06-03", target=b"x" * 20000)
    record = json.loads((call / "daily_record.json").read_text())
    record.pop("raw_target_b64")
    (call / "daily_record.json").write_text(json.dumps(record))
    assert _load(calls, "2025-06-03") is None


def test_solver_sources_must_match_frozen_run(tmp_path):
    calls = tmp_path / "evaluation_calls"
    calls.mkdir()
    (tmp_path / "solver_source_original.py").write_bytes(b"print(1)\n")
    (tmp_path / "solver_source_evaluation.py").write_bytes(b"print(2)\n")
    same = {"solver_source_original.py": b"print(1)\n", "solver_source_evaluation.py": b"print(2)\n"}
    check_sources(calls, same)
    with pytest.raises(ResumeDivergence):
        check_sources(calls, dict(same, **{"solver_source_evaluation.py": b"print(3)\n"}))
    with pytest.raises(ResumeDivergence):
        check_sources(calls, {})
