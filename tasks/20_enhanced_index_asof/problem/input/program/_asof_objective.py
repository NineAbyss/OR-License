
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _asof_verifier import verify


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def compute_objective(
    solution: dict[str, Any], testdata: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    result = verify(solution, testdata)
    if not result.valid:
        raise ValueError("; ".join(f"[{rid}] {msg}" for rid, msg in result.violations))
    return 0.0, {"objective_value": 0.0, "note": "evaluation_backtest_score_after_submit"}
