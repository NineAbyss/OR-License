
from __future__ import annotations

_CLI_DESCRIPTION = """Canonical food4 objective, recomputed from production actions."""

import argparse
import json
import math
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _to_mip_rounds(records: list[dict[str, Any]], brine_name: str) -> list[dict[str, Any]]:
    rounds: list[dict[str, Any]] = []
    index = 0
    while index < len(records):
        record = records[index]
        if record["product"] == brine_name:
            item = {"product": None, "batch": 0, "has_brine": True}
            if index + 1 < len(records) and records[index + 1]["product"] != brine_name:
                item = {
                    "product": records[index + 1]["product"],
                    "batch": records[index + 1]["batch"],
                    "has_brine": True,
                }
                index += 2
            else:
                index += 1
            rounds.append(item)
        else:
            rounds.append({"product": record["product"], "batch": record["batch"], "has_brine": False})
            index += 1
    return rounds


def compute_process_preferences(
    solution: dict[str, Any], testdata: dict[str, Any],
) -> dict[str, Any]:
    a, b, c, d, _e, brine = testdata["product_names"]
    machine_num = int(testdata["machine_num"])
    max_loop = int(testdata["max_loop"])
    machines = solution["machines"]
    if len(machines) != machine_num:
        raise ValueError("process preferences require exactly machine_num machines")
    if machine_num <= 0 or max_loop < 0:
        raise ValueError("machine_num must be positive and max_loop nonnegative")

    eligible = [
        idx for idx in range(machine_num)
        if testdata["machine_state"][idx] != 0
        and testdata["yesterday_product"][idx] != 1
    ]
    fallback_pairs = {(b, b), (b, c), (b, d), (c, b), (d, b)}
    abc = {a, b, c}
    interleaving_count = first_b_count = 0
    outside_slots = variety_shortages = b_shortages = 0
    evidence = []
    for idx, machine in enumerate(machines):
        rounds = _to_mip_rounds(machine["rounds"], brine)
        if len(rounds) > max_loop:
            raise ValueError("process preferences require rounds within max_loop")
        previous = None
        fallback_locations = []
        for round_idx, item in enumerate(rounds):
            if item["has_brine"]:
                previous = None
            product = item["product"]
            if (previous, product) in fallback_pairs:
                fallback_locations.append(round_idx)
            previous = product
        interleaving_count += len(fallback_locations)

        first = rounds[0] if rounds else None
        first_b_violation = idx in eligible and (
            first is None or (not first["has_brine"] and first["product"] != b)
        )
        first_b_count += int(first_b_violation)

        first_two = [item["product"] for item in rounds[:2]]
        first_two += [None] * (2 - len(first_two))
        outside = sum(product not in abc for product in first_two)
        variety = int(len(set(first_two) & abc) < 2)
        missing_b = int(b not in first_two)
        outside_slots += outside
        variety_shortages += variety
        b_shortages += missing_b
        evidence.append({
            "machine_id": idx + 1,
            "b_substitution_round_indices": fallback_locations,
            "first_round_b_applicable": idx in eligible,
            "first_round_b_violation": bool(first_b_violation),
            "first_two_products": first_two,
            "outside_or_missing_slots": outside,
            "two_varieties_shortage": variety,
            "b_priority_shortage": missing_b,
        })

    adjacency_bound = machine_num * max(0, max_loop - 1)
    p1 = interleaving_count / max(1, adjacency_bound)
    p2 = first_b_count / max(1, len(eligible))
    p3_range = outside_slots / (2 * machine_num)
    p3_variety = variety_shortages / machine_num
    p3_b = b_shortages / machine_num
    p3 = (p3_range + p3_variety + p3_b) / 3
    return {
        "metric_version": "food4-process-preferences-1",
        "value": max(p1, p2, p3),
        "aggregation": "chebyshev_max",
        "direction": "lower_is_better",
        "included_in_objective": True,
        "components": {
            "a_interleaving": {
                "value": p1, "violations": interleaving_count,
                "normalization_bound": adjacency_bound,
            },
            "first_round_b": {
                "value": p2, "violations": first_b_count,
                "eligible_machines": len(eligible),
            },
            "first_two_mix": {
                "value": p3,
                "abc_range": {"value": p3_range, "violations": outside_slots, "normalization_bound": 2 * machine_num},
                "two_varieties": {"value": p3_variety, "violations": variety_shortages, "normalization_bound": machine_num},
                "b_priority": {"value": p3_b, "violations": b_shortages, "normalization_bound": machine_num},
            },
        },
        "per_machine": evidence,
    }


def compute_objective(
    solution: dict[str, Any],
    testdata: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    product_names = list(testdata["product_names"])
    product_index = {name: idx for idx, name in enumerate(product_names)}
    product_time = list(testdata["product_time"])
    order_weight = float(testdata["order_weight"])
    process_weight = float(testdata.get("process_weight", 30.0))
    if not math.isfinite(process_weight) or process_weight < 0:
        raise ValueError("process_weight must be finite and nonnegative")
    brine_name = product_names[-1]

    completion_times: list[float] = []
    batch_ordering_sum = 0.0
    for machine in solution["machines"]:
        records = machine["rounds"]
        completion_times.append(sum(
            float(product_time[product_index[record["product"]]])
            for record in records
        ))
        for round_idx, mip_round in enumerate(_to_mip_rounds(records, brine_name)):
            if mip_round["product"] is not None:
                batch_ordering_sum += round_idx * (int(mip_round["batch"]) - 1)

    makespan = max(completion_times, default=0.0)
    weighted_reward = order_weight * batch_ordering_sum
    base_objective = makespan - weighted_reward
    process_preferences = compute_process_preferences(solution, testdata)
    process_penalty = process_weight * process_preferences["value"]
    objective = base_objective + process_penalty
    details = {
        "objective_value": round(objective, 6),
        "base_objective_value": round(base_objective, 6),
        "process_preferences": process_preferences,
        "components": {
            "makespan": {
                "value": round(makespan, 6),
                "completion_times": [round(value, 6) for value in completion_times],
                "source": "recomputed_from_product_time",
            },
            "batch_ordering": {
                "raw": round(batch_ordering_sum, 6),
                "weighted": round(weighted_reward, 6),
                "weight": order_weight,
                "direction": "subtracted_reward",
            },
            "process_penalty": {
                "raw": process_preferences["value"],
                "weight": process_weight,
                "weighted": round(process_penalty, 6),
                "direction": "added_penalty",
            },
        },
    }
    return objective, details


def main() -> None:
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    parser.add_argument("--solution", required=True)
    parser.add_argument("--testdata", required=True)
    args = parser.parse_args()
    objective, details = compute_objective(load_json(args.solution), load_json(args.testdata))
    print(json.dumps({"objective": objective, "details": details}, indent=2))


if __name__ == "__main__":
    main()
