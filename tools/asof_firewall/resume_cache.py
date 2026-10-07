from __future__ import annotations

import base64
import json
import math
from pathlib import Path
from typing import Any

SOURCE_FILES = ("solver_source_original.py", "solver_source_evaluation.py")


class ResumeDivergence(RuntimeError):
    pass


def _same_number(left: Any, right: Any, *, abs_tol: float = 1e-5) -> bool:
    try:
        a, b = float(left), float(right)
    except (TypeError, ValueError):
        return left is None and right is None
    return math.isfinite(a) and math.isfinite(b) and math.isclose(
        a, b, rel_tol=1e-10, abs_tol=abs_tol
    )


def _holdings(rows: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    result: dict[str, tuple[float, float]] = {}
    for row in rows:
        code = str(row.get("stockcode") or row.get("instrument") or "")
        if not code or code in result:
            raise ResumeDivergence("cached/current holdings have missing or duplicate codes")
        result[code] = (float(row["volume"]), float(row["close"]))
    return result


def recorded_bytes(record: dict[str, Any], key: str) -> bytes | None:
    value = record.get(key)
    if value is None:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as exc:
        raise ResumeDivergence(f"cached {key} is not valid base64") from exc


def check_sources(calls_root: Path, sources: dict[str, bytes]) -> None:
    if set(sources) != set(SOURCE_FILES) or not all(sources.values()):
        raise ResumeDivergence("current solver sources are unavailable")
    for name in SOURCE_FILES:
        path = Path(calls_root).parent / name
        try:
            earlier = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        except OSError:
            earlier = None
        if earlier != sources[name]:
            raise ResumeDivergence(f"{name} differs from the cached run")


def load_verified_day(
    calls_root: Path,
    day: str,
    mode: str,
    *,
    profile_key: str,
    nav: float,
    cash: float | None,
    holdings: list[dict[str, Any]],
) -> tuple[dict[str, Any], Path] | None:
    call = calls_root / day
    record_path = call / "daily_record.json"
    if not record_path.is_file() or record_path.is_symlink():
        return None
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ResumeDivergence(f"{day}: unreadable resume record: {exc}") from exc
    if record.get("status") != "ok":
        return None
    if record.get("decision_day") != day or record.get("mode") != mode:
        raise ResumeDivergence(f"{day}: cached decision day or mode differs")
    if record.get("final_action") != "target_delivered" or (
        record.get("verifier_result") or {}
    ).get("valid") is not True:
        raise ResumeDivergence(f"{day}: cached target lacks successful verification")
    if not _same_number(record.get("nav"), nav):
        raise ResumeDivergence(f"{day}: pre-decision NAV differs")
    if not _same_number(record.get("cash"), cash):
        raise ResumeDivergence(f"{day}: pre-decision cash differs")
    earlier = _holdings(record.get("actual_holdings") or [])
    current = _holdings(holdings)
    if earlier.keys() != current.keys():
        raise ResumeDivergence(f"{day}: pre-decision stock names differ")
    for code in earlier:
        old_volume, old_close = earlier[code]
        new_volume, new_close = current[code]
        if not _same_number(old_volume, new_volume, abs_tol=1e-8):
            raise ResumeDivergence(f"{day}: {code} share count differs")
        if not _same_number(old_close, new_close, abs_tol=1e-6):
            raise ResumeDivergence(f"{day}: {code} close differs")
    required = ["target_weights.csv"]
    if profile_key == "sif":
        required.append("ic_hedge.csv")
    elif profile_key == "longshort":
        if not (call / "delivered_target.csv").is_file():
            return None
        required.append("delivered_target.csv")
    elif profile_key != "enhanced_index":
        raise ResumeDivergence(f"unknown resume profile {profile_key}")
    for name in required:
        path = call / name
        if not path.is_file() or path.is_symlink():
            raise ResumeDivergence(f"{day}: cached {name} is missing or unsafe")
    if (record.get("raw_target_b64") is None and
            (call / "target_weights.csv").stat().st_size > 16000):
        return None
    return record, call
