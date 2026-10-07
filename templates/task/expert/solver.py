from __future__ import annotations

from itertools import permutations


def _cost(order: list[dict], changeover: int) -> int:
    clock = 0
    total = 0
    previous = None
    for job in order:
        if previous is not None and job["family"] != previous:
            clock += changeover
        clock += job["minutes"]
        total += job["weight"] * clock
        previous = job["family"]
    return total


def solve(instance: dict) -> dict:
    groups: dict[str, list[dict]] = {}
    for job in instance["jobs"]:
        groups.setdefault(job["family"], []).append(job)
    for jobs in groups.values():
        jobs.sort(key=lambda job: (job["minutes"] / job["weight"], job["job_id"]))
    best = None
    for families in permutations(sorted(groups)):
        order = [job for family in families for job in groups[family]]
        cost = _cost(order, instance["changeover_minutes"])
        if best is None or cost < best[0]:
            best = (cost, order)
    return {"sequence": [job["job_id"] for job in best[1]]}
