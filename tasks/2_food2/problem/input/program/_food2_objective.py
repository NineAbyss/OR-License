
from __future__ import annotations

_CLI_DESCRIPTION = """Canonical food2 weighted objective, recomputed from production actions."""

import argparse
import json
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
            item = {"product": None, "batch": 0}
            if index + 1 < len(records) and records[index + 1]["product"] != brine_name:
                item = {
                    "product": records[index + 1]["product"],
                    "batch": records[index + 1]["batch"],
                }
                index += 2
            else:
                index += 1
            rounds.append(item)
        else:
            rounds.append({"product": record["product"], "batch": record["batch"]})
            index += 1
    return rounds


def compute_objective(
    solution: dict[str, Any],
    testdata: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    product_names = list(testdata["product_names"])
    product_index = {name: idx for idx, name in enumerate(product_names)}
    product_time = list(testdata["product_time"])
    priorities = list(testdata["priority"])
    priority_weight = float(testdata["priority_weight"])
    batch_num = len(testdata["demand_num"])
    brine_name = product_names[-1]

    completion_times: list[float] = []
    per_batch_priority = [0.0 for _ in range(batch_num)]
    for machine in solution["machines"]:
        records = machine["rounds"]
        completion_times.append(sum(
            float(product_time[product_index[record["product"]]])
            for record in records
        ))
        by_batch: list[list[dict[str, Any]]] = [[] for _ in range(batch_num)]
        current_batch = 0
        for record in records:
            if record["product"] != brine_name:
                current_batch = int(record["batch"]) - 1
            by_batch[current_batch].append(record)
        for batch_idx, segment in enumerate(by_batch):
            for round_idx, mip_round in enumerate(_to_mip_rounds(segment, brine_name)):
                product = mip_round["product"]
                if product is not None:
                    per_batch_priority[batch_idx] += round_idx * priorities[product_index[product]]

    makespan = max(completion_times, default=0.0)
    raw_priority = sum(per_batch_priority)
    weighted_priority = priority_weight * raw_priority
    objective = makespan + weighted_priority
    details = {
        "objective_value": round(objective, 6),
        "components": {
            "makespan": {
                "value": round(makespan, 6),
                "completion_times": [round(value, 6) for value in completion_times],
                "source": "recomputed_from_product_time",
            },
            "priority_penalty": {
                "raw": round(raw_priority, 6),
                "weighted": round(weighted_priority, 6),
                "weight": priority_weight,
                "per_batch": [round(value, 6) for value in per_batch_priority],
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
