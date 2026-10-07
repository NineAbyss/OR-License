
from __future__ import annotations

import copy
from typing import Any

from _food_objective import compute_schedule_objective
from _food_verifier import (
    PRODUCTS,
    VerificationResult,
    normalize_solution_schema,
    output_to_mip_rounds,
    verify as verify_stage,
)


STAGE_COST_OFFSET = 10.0


def extract_stages(solution: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(solution, dict):
        return [], ["MS1: top-level output must be a JSON object"]

    has_stages = "stages" in solution
    has_pots = "pots" in solution
    if has_stages and has_pots:
        return [], ["MS1: top level cannot contain both stages and pots"]

    if has_stages:
        stages = solution.get("stages")
        if not isinstance(stages, list):
            return [], ["MS1: top-level stages must be a nonempty list"]
        if not stages:
            return [], ["MS1: stages must contain at least one production stage"]
        normalized: list[dict[str, Any]] = []
        violations: list[str] = []
        for stage_index, stage in enumerate(stages, start=1):
            if not isinstance(stage, dict):
                violations.append(f"MS1: stage {stage_index} must be a JSON object")
                normalized.append({"pots": []})
                continue
            if "pots" not in stage:
                violations.append(f"MS1: stage {stage_index} is missing pots")
            normalized.append(copy.deepcopy(stage))
        return normalized, violations

    if has_pots:
        return [copy.deepcopy(solution)], []

    return [], ["MS1: top level must contain stages (or pots for legacy output)"]


def _stage_product_counts(
    stage: dict[str, Any],
) -> tuple[list[int], list[int], int]:
    batch1 = [0] * len(PRODUCTS)
    batch2 = [0] * len(PRODUCTS)
    product_total = 0
    product_index = {product: index for index, product in enumerate(PRODUCTS)}

    for pot in stage.get("pots", []):
        if not isinstance(pot, dict):
            continue
        for record in pot.get("rounds", []):
            if not isinstance(record, dict):
                continue
            product = record.get("product")
            if product not in product_index:
                continue
            product_total += 1
            batch = record.get("batch")
            if batch == 1:
                batch1[product_index[product]] += 1
            elif batch == 2:
                batch2[product_index[product]] += 1
    return batch1, batch2, product_total


def _normalize_stage(
    stage: dict[str, Any], stage_index: int
) -> tuple[dict[str, Any], list[str]]:
    normalized, violations = normalize_solution_schema(stage)
    return normalized, [f"stage {stage_index}: {item}" for item in violations]


def _localize_stage(
    stage: dict[str, Any],
    current_states: list[int],
    original_testdata: dict[str, Any],
    *,
    is_multistage: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    local_solution = copy.deepcopy(stage)
    batch1, batch2, _ = _stage_product_counts(stage)

    if is_multistage:
        for pot in local_solution.get("pots", []):
            for record in pot.get("rounds", []):
                if record.get("product") in PRODUCTS:
                    record["batch"] = 1
        local_demand = [left + right for left, right in zip(batch1, batch2)]
        demand1 = local_demand
        demand2 = [0] * len(PRODUCTS)
    else:
        demand1 = list(original_testdata["demand1"])
        demand2 = list(original_testdata["demand2"])

    local_testdata = {
        "stateinitial": list(current_states),
        "demand1": demand1,
        "demand2": demand2,
        "yuliu": list(original_testdata.get("yuliu", [0, 0, 0])),
    }
    return local_solution, local_testdata


def derive_next_states(
    stage: dict[str, Any], current_states: list[int]
) -> list[int]:
    stage, _ = normalize_solution_schema(stage)
    next_states = list(current_states)
    pots = stage.get("pots", [])
    for pot_index, state in enumerate(current_states):
        if pot_index >= len(pots) or not isinstance(pots[pot_index], dict):
            continue
        for mip_round in output_to_mip_rounds(
            pots[pot_index].get("rounds", [])
        ):
            if mip_round.get("has_brine"):
                state = 0
            if mip_round.get("product") in PRODUCTS:
                state += 1
        next_states[pot_index] = state
    return next_states


def _add_global_demand_checks(
    result: VerificationResult,
    stages: list[dict[str, Any]],
    testdata: dict[str, Any],
) -> None:
    total_batch1 = [0] * len(PRODUCTS)
    total_batch2 = [0] * len(PRODUCTS)
    is_multistage = len(stages) > 1

    for stage_index, stage in enumerate(stages):
        batch1, batch2, product_total = _stage_product_counts(stage)
        if product_total == 0:
            result.add_hard(f"MS2: stage {stage_index + 1} schedules no products")

        if is_multistage and stage_index == 0 and any(batch2):
            result.add_hard("MS3: the first stage of a multistage plan may schedule only original batch 1")
        if is_multistage and stage_index > 0 and any(batch1):
            result.add_hard(
                f"MS3: stage {stage_index + 1} of a multistage plan may schedule only original batch 2"
            )

        total_batch1 = [
            left + right for left, right in zip(total_batch1, batch1)
        ]
        total_batch2 = [
            left + right for left, right in zip(total_batch2, batch2)
        ]

    for product_index, product in enumerate(PRODUCTS):
        expected1 = testdata["demand1"][product_index]
        expected2 = testdata["demand2"][product_index]
        if total_batch1[product_index] != expected1:
            result.add_hard(
                f"MS4: {product} original batch-1 output={total_batch1[product_index]}, "
                f"demand={expected1}"
            )
        if total_batch2[product_index] != expected2:
            result.add_hard(
                f"MS4: {product} original batch-2 output={total_batch2[product_index]}, "
                f"demand={expected2}"
            )


def verify_multistage(
    solution: Any,
    testdata: dict[str, Any],
    *,
    level: int = 3,
) -> VerificationResult:
    result = VerificationResult()
    raw_stages, top_violations = extract_stages(solution)
    for violation in top_violations:
        result.add_hard(violation)
    if not raw_stages:
        return result

    stages: list[dict[str, Any]] = []
    for stage_index, stage in enumerate(raw_stages, start=1):
        normalized, violations = _normalize_stage(stage, stage_index)
        stages.append(normalized)
        for violation in violations:
            result.add_hard(violation)

    _add_global_demand_checks(result, stages, testdata)

    is_multistage = len(stages) > 1
    current_states = list(testdata["stateinitial"])
    for stage_index, stage in enumerate(stages, start=1):
        local_solution, local_testdata = _localize_stage(
            stage,
            current_states,
            testdata,
            is_multistage=is_multistage,
        )
        stage_result = verify_stage(
            local_solution,
            local_testdata,
            level=level,
            split=is_multistage and stage_index > 1,
        )
        for violation in stage_result.hard_violations:
            result.add_hard(f"stage {stage_index}: {violation}")
        current_states = derive_next_states(stage, current_states)

    return result


def evaluate_multistage(
    solution: Any,
    testdata: dict[str, Any],
    *,
    level: int = 3,
    optime: bool = True,
) -> tuple[float, dict[str, Any]]:
    raw_stages, violations = extract_stages(solution)
    if violations or not raw_stages:
        return float("inf"), {
            "stage_count": 0,
            "soft_score": float("inf"),
            "within_stage_cost": float("inf"),
            "stage_cost_offset": STAGE_COST_OFFSET,
            "schema_violations": violations,
        }

    stages = [
        _normalize_stage(stage, stage_index)[0]
        for stage_index, stage in enumerate(raw_stages, start=1)
    ]
    del level
    soft_score, objective_details = compute_schedule_objective(
        stages, testdata, optime=optime
    )
    current_states = list(testdata["stateinitial"])
    for stage in stages:
        current_states = derive_next_states(stage, current_states)

    stage_count_penalty = STAGE_COST_OFFSET * (len(stages) - 1)
    encoded_cost = stage_count_penalty + soft_score
    return encoded_cost, {
        "stage_count": len(stages),
        "soft_score": soft_score,
        "within_stage_cost": soft_score,
        "stage_count_penalty": stage_count_penalty,
        "stage_cost_offset": STAGE_COST_OFFSET,
        "encoded_cost": encoded_cost,
        "next_stateinitial": current_states,
        "objective": objective_details,
    }
