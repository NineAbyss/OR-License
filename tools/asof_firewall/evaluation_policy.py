
from __future__ import annotations

import math


def asof_evaluation_valid(scored: dict) -> bool:
    cost = scored.get("mean_cost")
    invalid_environment = scored.get("eval_infrastructure_failure")
    invalid_initial = scored.get("eval_initial_strategy_failure")
    evaluation_summary = (
        scored.get("windows", {}).get("evaluation", {})
        if isinstance(scored, dict)
        else {}
    )
    terminal_failure = evaluation_summary.get("failure_class")
    invalid_target_days = evaluation_summary.get("invalid_target_days")
    if invalid_target_days is None:
        invalid_target_days = evaluation_summary.get("strategy_contract_failure_days") or []
    program_error_days = evaluation_summary.get("program_error_days") or []
    infrastructure_days = evaluation_summary.get("infrastructure_failure_days") or []
    initial_failure_days = evaluation_summary.get("initial_strategy_failure_days") or []
    completed_window = evaluation_summary.get("run_completed")
    if completed_window is None:
        completed_window = not terminal_failure
    return bool(
        isinstance(cost, (int, float))
        and math.isfinite(cost)
        and (scored.get("contract") != "longshort-asof-1"
             or evaluation_summary.get("covers_full_window") is True)
        and not (
            invalid_environment
            or invalid_initial
            or terminal_failure
            or invalid_target_days
            or program_error_days
            or infrastructure_days
            or initial_failure_days
            or not completed_window
        )
    )


__all__ = ["asof_evaluation_valid"]
