
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from ortools.linear_solver import pywraplp


BED_CAPACITY = {"BED-01": 25.0, "BED-02": 38.0, "BED-03": 35.0}
WORK_START_HOUR = 8
WORK_END_HOUR = 18
EPS = 1e-6
BIG_M = 1_000_000.0


LINE_ALIASES = {
    "LINE-012": "LINE-003",
}


@dataclass
class LineState:
    order_id: str | None = None
    product: str | None = None
    additive: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a rolling 3-day anonymized production schedule.")
    parser.add_argument("--orders", default=str(Path(__file__).resolve().parent / "orders.xlsx"), help="Anonymized order/material/arrival workbook.")
    parser.add_argument("--capacity", default=str(Path(__file__).resolve().parent / "capacity.xlsx"), help="Anonymized relationship/capacity/adjustment workbook.")
    parser.add_argument("--days", type=int, default=3, help="Number of working days to schedule.")
    parser.add_argument("--until-complete", action="store_true", help="Keep rolling until all orders are scheduled.")
    parser.add_argument("--max-periods", type=int, default=5000, help="Safety cap for --until-complete periods.")
    parser.add_argument("--max-no-feasible", type=int, default=20, help="Stop after N consecutive periods with neither production nor setup.")
    parser.add_argument("--checkpoint-every", type=int, default=25, help="Write remaining/inventory snapshots every N periods.")
    parser.add_argument("--stream-dir", default=None, help="Directory for streamed CSV checkpoints.")
    parser.add_argument("--start", default=None, help="Schedule start, e.g. '2030-07-17 08:00:00'.")
    parser.add_argument("--output", default=None, help="Output xlsx path.")
    parser.add_argument("--quiet", action="store_true", help="Reduce solver progress logs.")
    return parser.parse_args()


def normalize_line_name(name) -> str:
    if pd.isna(name):
        return ""
    name = str(name).strip()
    return LINE_ALIASES.get(name, name)


def parse_beds(value) -> set[str]:
    if pd.isna(value):
        return set()
    text = str(value).replace("\uff0c", ",")
    return {part.strip() for part in text.split(",") if part.strip()}


def next_work_period(current: pd.Timestamp) -> pd.Timestamp:
    current = pd.Timestamp(current)
    if current.hour < WORK_START_HOUR:
        return current.normalize() + pd.Timedelta(hours=WORK_START_HOUR)
    if current.hour >= WORK_END_HOUR:
        return current.normalize() + pd.Timedelta(days=1, hours=WORK_START_HOUR)
    return current


def advance_one_work_hour(current: pd.Timestamp) -> pd.Timestamp:
    nxt = current + pd.Timedelta(hours=1)
    if nxt.hour >= WORK_END_HOUR:
        nxt = nxt.normalize() + pd.Timedelta(days=1, hours=WORK_START_HOUR)
    return nxt


def default_start_time(orders: pd.DataFrame) -> pd.Timestamp:
    starts = pd.to_datetime(orders["\u8ba1\u5212\u5f00\u59cb\u65f6\u95f4"], errors="coerce").dropna()
    if starts.empty:
        return pd.Timestamp("2030-05-27 08:00:00")
    first = starts.min().normalize() + pd.Timedelta(hours=WORK_START_HOUR)
    return next_work_period(first)


def load_inputs(order_path: Path, capacity_path: Path):
    orders = pd.read_excel(order_path, "\u8ba2\u5355")
    materials = pd.read_excel(order_path, "\u7269\u6599")
    arrivals = pd.read_excel(order_path, "\u539f\u6599\u5230\u8d27")
    capacity = pd.read_excel(capacity_path, "\u4ea7\u80fd")
    relation = pd.read_excel(capacity_path, "\u4ea7\u54c1\u4ea7\u7ebf\u5173\u7cfb", dtype={"\u5e72\u71e5\u5e8a": "str"})
    adjustments = pd.read_excel(capacity_path, "\u4ea7\u80fd\u8c03\u8282")

    orders = orders.copy()
    orders["\u5269\u4f59\u6570\u91cf"] = pd.to_numeric(orders["\u8ba1\u5212\u4ea7\u51fa\u6570\u91cf"], errors="coerce").fillna(0).astype(float)
    orders["\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4"] = pd.to_datetime(orders["\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4"], errors="coerce")
    orders["\u8ba1\u5212\u5f00\u59cb\u65f6\u95f4"] = pd.to_datetime(orders["\u8ba1\u5212\u5f00\u59cb\u65f6\u95f4"], errors="coerce")
    orders.index = list(range(len(orders)))

    materials = materials.copy()
    materials["\u5355\u4f4d\u7528\u91cf"] = pd.to_numeric(materials["\u5355\u4f4d\u7528\u91cf"], errors="coerce").fillna(0.0)
    materials["\u73b0\u5b58\u91cf"] = pd.to_numeric(materials["\u73b0\u5b58\u91cf"], errors="coerce").fillna(0.0)

    arrivals = arrivals.copy()
    if not arrivals.empty:
        arrivals["\u8ba1\u5212\u5230\u8fbe\u65e5\u671f"] = pd.to_datetime(arrivals["\u8ba1\u5212\u5230\u8fbe\u65e5\u671f"], errors="coerce")
        arrivals["\u6570\u91cf"] = pd.to_numeric(arrivals["\u6570\u91cf"], errors="coerce").fillna(0.0)

    capacity = capacity.copy()
    capacity["\u4ea7\u7ebf"] = capacity["\u4ea7\u7ebf"].map(normalize_line_name)
    capacity["\u7406\u8bba\u4ea7\u91cfT/h"] = pd.to_numeric(capacity["\u7406\u8bba\u4ea7\u91cfT/h"], errors="coerce").fillna(0.0)

    adjustments = adjustments.copy()
    if not adjustments.empty:
        adjustments["\u751f\u4ea7\u7ebf"] = adjustments["\u751f\u4ea7\u7ebf"].map(normalize_line_name)
        adjustments["\u5f00\u59cb\u65f6\u95f4"] = pd.to_datetime(adjustments["\u5f00\u59cb\u65f6\u95f4"], errors="coerce")
        adjustments["\u7ed3\u675f\u65f6\u95f4"] = pd.to_datetime(adjustments["\u7ed3\u675f\u65f6\u95f4"], errors="coerce")

    return orders, materials, arrivals, capacity, relation, adjustments


def build_material_maps(materials: pd.DataFrame):
    stock = (
        materials.dropna(subset=["\u7269\u6599\u7f16\u7801"])
        .groupby("\u7269\u6599\u7f16\u7801", dropna=False)["\u73b0\u5b58\u91cf"]
        .max()
        .astype(float)
        .to_dict()
    )
    usage: dict[int, dict[str, float]] = {}
    for _, row in materials.iterrows():
        order_id = row.get("\u751f\u4ea7\u8ba2\u5355\u53f7")
        material = row.get("\u7269\u6599\u7f16\u7801")
        if pd.isna(order_id) or pd.isna(material):
            continue
        usage.setdefault(str(order_id), {})
        usage[str(order_id)][str(material)] = usage[str(order_id)].get(str(material), 0.0) + float(row["\u5355\u4f4d\u7528\u91cf"])
        stock.setdefault(str(material), float(row["\u73b0\u5b58\u91cf"]))
    return stock, usage


def build_compatibility(orders: pd.DataFrame, relation: pd.DataFrame, capacity: pd.DataFrame):
    line_cols = list(relation.columns[2:])
    line_beds = {row["\u4ea7\u7ebf"]: parse_beds(row["\u5e72\u71e5\u5e8a"]) for _, row in capacity.iterrows()}
    line_caps = {row["\u4ea7\u7ebf"]: float(row["\u7406\u8bba\u4ea7\u91cfT/h"]) for _, row in capacity.iterrows()}
    relation_by_product = {row["\u54c1\u540d"]: row for _, row in relation.iterrows()}

    compatibility: dict[tuple[int, str], set[str]] = {}
    missing = []
    for idx, order in orders.iterrows():
        product = order["\u4ea7\u54c1"]
        rel = relation_by_product.get(product)
        if rel is None:
            missing.append(product)
            continue
        product_beds = parse_beds(rel["\u5e72\u71e5\u5e8a"])
        for raw_line in line_cols:
            if rel.get(raw_line) != 1:
                continue
            line = normalize_line_name(raw_line)
            if line not in line_caps or line_caps[line] <= 0:
                continue
            beds = product_beds & line_beds.get(line, set())
            if beds:
                compatibility[(idx, line)] = beds
    if missing:
        raise ValueError("\u4ea7\u80fd\u5173\u7cfb\u8868\u7f3a\u5c11\u4ea7\u54c1: " + ", ".join(sorted(set(map(str, missing)))))
    return compatibility, line_caps, line_beds


def line_capacity_for_period(
    line: str,
    base_capacity: float,
    period_start: pd.Timestamp,
    adjustments: pd.DataFrame,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    cap = base_capacity
    if adjustments.empty:
        return cap, reasons

    period_end = period_start + pd.Timedelta(hours=1)
    rows = adjustments[adjustments["\u751f\u4ea7\u7ebf"] == line]
    for _, row in rows.iterrows():
        start = row.get("\u5f00\u59cb\u65f6\u95f4")
        end = row.get("\u7ed3\u675f\u65f6\u95f4")
        if pd.isna(start) or pd.isna(end):
            continue
        adjustment_type = str(row.get("\u8c03\u6574\u7c7b\u578b", ""))
        reason = str(row.get("\u8c03\u6574\u539f\u56e0", ""))

        if "\u8fd0\u884c\u65f6\u95f4\u9650\u5b9a" in adjustment_type and period_start.date() == start.date():
            if not (period_start >= start and period_end <= end):
                cap = 0.0
                reasons.append("\u8fd0\u884c\u65f6\u95f4\u9650\u5b9a")
            continue

        overlaps = period_start < end and period_end > start
        if not overlaps:
            continue
        if "\u51cf\u4ea7\u7ebf\u4ea7\u80fd" in adjustment_type or "\u6545\u969c" in reason or "\u5237\u6d17" in reason:
            cap = 0.0
            reasons.append(adjustment_type or reason)
    return max(cap, 0.0), reasons


def apply_arrivals(
    stock: dict[str, float],
    arrivals: pd.DataFrame,
    applied_arrival_rows: set[int],
    current_time: pd.Timestamp,
) -> list[dict]:
    applied = []
    if arrivals.empty:
        return applied
    for idx, row in arrivals.iterrows():
        if idx in applied_arrival_rows:
            continue
        arrival_time = row.get("\u8ba1\u5212\u5230\u8fbe\u65e5\u671f")
        if pd.isna(arrival_time) or arrival_time > current_time:
            continue
        material = str(row["\u7269\u6599\u7f16\u7801"])
        qty = float(row["\u6570\u91cf"])
        stock[material] = stock.get(material, 0.0) + qty
        applied_arrival_rows.add(idx)
        applied.append({"\u65f6\u95f4": current_time, "\u7269\u6599\u7f16\u7801": material, "\u5230\u8d27\u6570\u91cf": qty, "\u8ba1\u5212\u5230\u8fbe\u65e5\u671f": arrival_time})
    return applied


def changeover_hours(order: pd.Series, state: LineState) -> float:
    if state.order_id == str(order["\u751f\u4ea7\u8ba2\u5355\u53f7"]):
        return 0.0
    if state.additive is not None and state.additive == str(order["\u6dfb\u52a0\u5242"]):
        return 0.5
    if state.additive is None:
        return 0.0
    return 1.0


def can_follow_old_brine_rule(order: pd.Series, state: LineState) -> bool:
    product = str(order["\u4ea7\u54c1"])
    if product != "PRODUCT-003":
        return True
    prev = state.product or ""
    return prev in {"PRODUCT-001", "PRODUCT-002", "PRODUCT-003"}


def period_objective_weight(order: pd.Series, current_time: pd.Timestamp) -> float:
    due = order.get("\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4")
    if pd.isna(due):
        hours_to_due = 24.0 * 365.0
    else:
        hours_to_due = max((pd.Timestamp(due) - current_time).total_seconds() / 3600.0, 1.0)
    insert_multiplier = 1000.0 if int(order.get("\u662f\u5426\u63d2\u5355", 0)) == 1 else 1.0
    return BIG_M * insert_multiplier / hours_to_due


def append_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, mode="a", index=False, header=not path.exists(), encoding="utf-8-sig")


def write_snapshot(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def csv_to_frame(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def build_remaining_frame(orders: pd.DataFrame) -> pd.DataFrame:
    remaining = orders.copy()
    remaining["\u5df2\u6392\u6570\u91cf"] = remaining["\u8ba1\u5212\u4ea7\u51fa\u6570\u91cf"].astype(float) - remaining["\u5269\u4f59\u6570\u91cf"].astype(float)
    return remaining.sort_values(["\u662f\u5426\u63d2\u5355", "\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4"], ascending=[False, True])


def inventory_frame(stock: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"\u7269\u6599\u7f16\u7801": material, "\u671f\u672b\u5e93\u5b58": qty} for material, qty in sorted(stock.items())]
    )


def build_summary(
    orders: pd.DataFrame,
    schedule: pd.DataFrame,
    remaining: pd.DataFrame,
    args: argparse.Namespace,
    start_time: pd.Timestamp,
    current_time: pd.Timestamp,
    periods_run: int,
    stop_reason: str,
) -> pd.DataFrame:
    scheduled_qty = float(schedule["\u672c\u6b21\u5206\u914d\u6570\u91cf"].sum()) if not schedule.empty else 0.0
    return pd.DataFrame(
        [
            {"\u6307\u6807": "\u8f93\u5165\u8ba2\u5355\u6570", "\u503c": len(orders)},
            {"\u6307\u6807": "\u8fd0\u884c\u6a21\u5f0f", "\u503c": "\u5168\u91cf\u6eda\u52a8\u5230\u5b8c\u6210" if args.until_complete else "\u56fa\u5b9a\u5929\u6570\u7a97\u53e3"},
            {"\u6307\u6807": "\u8ba1\u5212\u5929\u6570\u53c2\u6570", "\u503c": args.days},
            {"\u6307\u6807": "\u5b9e\u9645\u8fd0\u884c\u5c0f\u65f6\u6bb5", "\u503c": periods_run},
            {"\u6307\u6807": "\u6392\u4ea7\u5f00\u59cb", "\u503c": start_time},
            {"\u6307\u6807": "\u6392\u4ea7\u7ed3\u675f", "\u503c": current_time},
            {"\u6307\u6807": "\u505c\u6b62\u539f\u56e0", "\u503c": stop_reason},
            {"\u6307\u6807": "\u603b\u9700\u6c42\u91cf", "\u503c": float(orders["\u8ba1\u5212\u4ea7\u51fa\u6570\u91cf"].sum())},
            {"\u6307\u6807": "\u5df2\u6392\u4ea7\u91cf", "\u503c": scheduled_qty},
            {"\u6307\u6807": "\u5269\u4f59\u672a\u6392\u91cf", "\u503c": float(remaining["\u5269\u4f59\u6570\u91cf"].sum())},
            {"\u6307\u6807": "\u5df2\u6392\u8ba2\u5355\u6570", "\u503c": int((remaining["\u5df2\u6392\u6570\u91cf"] > EPS).sum())},
            {"\u6307\u6807": "\u5b8c\u6210\u8ba2\u5355\u6570", "\u503c": int((remaining["\u5269\u4f59\u6570\u91cf"] <= EPS).sum())},
            {"\u6307\u6807": "\u5269\u4f59\u672a\u5b8c\u6210\u8ba2\u5355\u6570", "\u503c": int((remaining["\u5269\u4f59\u6570\u91cf"] > EPS).sum())},
            {"\u6307\u6807": "\u63d2\u5355\u6570", "\u503c": int((orders["\u662f\u5426\u63d2\u5355"] == 1).sum())},
            {
                "\u6307\u6807": "\u63d2\u5355\u5df2\u6392\u91cf",
                "\u503c": float(remaining.loc[remaining["\u662f\u5426\u63d2\u5355"] == 1, "\u5df2\u6392\u6570\u91cf"].sum()),
            },
            {
                "\u6307\u6807": "\u8bf4\u660e",
                "\u503c": "\u6d41\u5f0f\u8fd0\u884c\u6bcf\u5c0f\u65f6\u6bb5\u8ffd\u52a0\u5199CSV\uff1b\u6700\u7ec8\u518d\u6c47\u603b\u4e3aExcel\u3002LINE-006 \u4e0e LINE-007 \u540c\u5c0f\u65f6\u53ea\u80fd\u751f\u4ea7\u540c\u4e00\u8ba2\u5355\uff1bPRODUCT-003 \u9700\u7d27\u63a5 PRODUCT-001\u3001PRODUCT-002 \u6216\u8fde\u7eed\u7684 PRODUCT-003\uff0c\u4f46\u4e0d\u4f1a\u9501\u5b9a\u4ea7\u7ebf\u76f4\u5230\u5168\u90e8 PRODUCT-003 \u5b8c\u6210\u3002",
            },
        ]
    )


def material_can_start(order_id: str, stock: dict[str, float], usage: dict[str, dict[str, float]]) -> bool:
    order_usage = usage.get(order_id, {})
    if not order_usage:
        return True
    for material, unit_usage in order_usage.items():
        if unit_usage > 0 and stock.get(material, 0.0) / unit_usage <= EPS:
            return False
    return True


def choose_setup_rows(
    period_no: int,
    current_time: pd.Timestamp,
    orders: pd.DataFrame,
    compatibility: dict[tuple[int, str], set[str]],
    line_caps: dict[str, float],
    adjustments: pd.DataFrame,
    stock: dict[str, float],
    usage: dict[str, dict[str, float]],
    line_states: dict[str, LineState],
    used_lines: set[str],
) -> list[dict]:
    setup_rows = []
    for line, state in line_states.items():
        if line in used_lines:
            continue
        cap, reasons = line_capacity_for_period(line, line_caps.get(line, 0.0), current_time, adjustments)
        if cap <= 0:
            continue
        candidates = []
        for idx, order in orders.iterrows():
            if float(order["\u5269\u4f59\u6570\u91cf"]) <= EPS:
                continue
            if (idx, line) not in compatibility:
                continue
            if not can_follow_old_brine_rule(order, state):
                continue
            changeover = changeover_hours(order, state)
            if changeover < 1.0:
                continue
            order_id = str(order["\u751f\u4ea7\u8ba2\u5355\u53f7"])
            if not material_can_start(order_id, stock, usage):
                continue
            candidates.append((period_objective_weight(order, current_time), idx, order, changeover, reasons))
        if not candidates:
            continue
        _, idx, order, changeover, reasons = max(candidates, key=lambda item: item[0])
        setup_rows.append(
            {
                "\u65f6\u6bb5": period_no,
                "\u5f00\u59cb\u65f6\u95f4": current_time,
                "\u7ed3\u675f\u65f6\u95f4": current_time + pd.Timedelta(hours=1),
                "\u7b2c\u5929\u6570": (period_no - 1) // (WORK_END_HOUR - WORK_START_HOUR) + 1,
                "\u5c0f\u65f6\u6570": current_time.hour,
                "\u5e8f\u53f7": idx,
                "\u751f\u4ea7\u5de5\u5382": order.get("\u751f\u4ea7\u5de5\u5382"),
                "\u751f\u4ea7\u8ba2\u5355\u53f7": str(order["\u751f\u4ea7\u8ba2\u5355\u53f7"]),
                "\u9500\u552e\u8ba2\u5355\u53f7": order.get("\u9500\u552e\u8ba2\u5355\u53f7"),
                "\u4ea7\u54c1": order.get("\u4ea7\u54c1"),
                "\u662f\u5426\u63d2\u5355": order.get("\u662f\u5426\u63d2\u5355"),
                "\u8ba1\u5212\u5f00\u59cb\u65f6\u95f4": order.get("\u8ba1\u5212\u5f00\u59cb\u65f6\u95f4"),
                "\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4": order.get("\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4"),
                "\u8ba1\u5212\u4ea7\u51fa\u6570\u91cf": order.get("\u8ba1\u5212\u4ea7\u51fa\u6570\u91cf"),
                "\u6392\u524d\u5269\u4f59\u6570\u91cf": order.get("\u5269\u4f59\u6570\u91cf"),
                "\u672c\u6b21\u5206\u914d\u6570\u91cf": 0.0,
                "\u6392\u540e\u5269\u4f59\u6570\u91cf": order.get("\u5269\u4f59\u6570\u91cf"),
                "\u6dfb\u52a0\u5242": order.get("\u6dfb\u52a0\u5242"),
                "\u4ea7\u7ebf": line,
                "\u5e72\u71e5\u5e8a\u5206\u914d": "",
                "\u6362\u4ea7\u65f6\u95f4h": changeover,
                "\u6709\u6548\u751f\u4ea7\u65f6\u95f4h": 0.0,
                "\u76ee\u6807\u6743\u91cd": period_objective_weight(order, current_time),
                "\u8c03\u8282\u539f\u56e0": "\u6362\u4ea7\u51c6\u5907" if not reasons else "\u6362\u4ea7\u51c6\u5907;" + ";".join(reasons),
            }
        )
    return setup_rows


def solve_period(
    period_no: int,
    current_time: pd.Timestamp,
    orders: pd.DataFrame,
    compatibility: dict[tuple[int, str], set[str]],
    line_caps: dict[str, float],
    adjustments: pd.DataFrame,
    stock: dict[str, float],
    usage: dict[str, dict[str, float]],
    line_states: dict[str, LineState],
    quiet: bool,
):
    active_indices = [idx for idx, row in orders.iterrows() if float(row["\u5269\u4f59\u6570\u91cf"]) > EPS]
    if not active_indices:
        return [], [], 0.0

    solver = pywraplp.Solver.CreateSolver("CBC")
    if solver is None:
        raise RuntimeError("OR-Tools CBC solver is unavailable.")

    qty = {}
    use = {}
    bed_qty = {}
    line_order_vars: dict[str, list[tuple[int, object]]] = {}
    order_vars: dict[int, list[object]] = {}
    objective = solver.Objective()
    active_line_caps = {}
    line_block_reasons = {}

    for line, base_cap in line_caps.items():
        cap, reasons = line_capacity_for_period(line, base_cap, current_time, adjustments)
        active_line_caps[line] = cap
        if reasons:
            line_block_reasons[line] = ";".join(reasons)

    for idx in active_indices:
        order = orders.loc[idx]
        order_id = str(order["\u751f\u4ea7\u8ba2\u5355\u53f7"])
        remaining = float(order["\u5269\u4f59\u6570\u91cf"])
        weight = period_objective_weight(order, current_time)
        for line, cap in active_line_caps.items():
            beds = compatibility.get((idx, line))
            if not beds or cap <= 0:
                continue
            state = line_states[line]
            if not can_follow_old_brine_rule(order, state):
                continue
            changeover = changeover_hours(order, state)
            productive_hours = max(1.0 - changeover, 0.0)
            if productive_hours <= EPS:
                continue

            key = (idx, line)
            use[key] = solver.IntVar(0.0, 1.0, f"x_{idx}_{line}")
            qty[key] = solver.NumVar(0.0, remaining, f"q_{idx}_{line}")
            solver.Add(qty[key] <= remaining)
            solver.Add(qty[key] <= cap * productive_hours * use[key])
            objective.SetCoefficient(qty[key], weight)

            line_order_vars.setdefault(line, []).append((idx, use[key]))
            order_vars.setdefault(idx, []).append(qty[key])

            bed_terms = []
            for bed in sorted(beds):
                bkey = (idx, line, bed)
                bed_qty[bkey] = solver.NumVar(0.0, remaining, f"e_{idx}_{line}_{bed}")
                bed_terms.append(bed_qty[bkey])
            solver.Add(sum(bed_terms) == qty[key])

    if not qty:
        return [], [], 0.0

    for idx, vars_for_order in order_vars.items():
        solver.Add(sum(vars_for_order) <= float(orders.loc[idx, "\u5269\u4f59\u6570\u91cf"]))

    for line, pairs in line_order_vars.items():
        solver.Add(sum(var for _, var in pairs) <= 1)

    big_pack_lines = [line for line in ("LINE-006", "LINE-007") if line in line_order_vars]
    if len(big_pack_lines) == 2:
        north_pairs = line_order_vars["LINE-006"]
        south_pairs = line_order_vars["LINE-007"]
        for north_idx, north_var in north_pairs:
            for south_idx, south_var in south_pairs:
                if north_idx != south_idx:
                    solver.Add(north_var + south_var <= 1)

    for bed, cap in BED_CAPACITY.items():
        terms = [var for (_, _, b), var in bed_qty.items() if b == bed]
        if terms:
            solver.Add(sum(terms) <= cap)

    material_terms: dict[str, list] = {}
    for (idx, line), qvar in qty.items():
        order_id = str(orders.loc[idx, "\u751f\u4ea7\u8ba2\u5355\u53f7"])
        for material, unit_usage in usage.get(order_id, {}).items():
            if unit_usage:
                material_terms.setdefault(material, []).append(unit_usage * qvar)
    for material, terms in material_terms.items():
        solver.Add(sum(terms) <= stock.get(material, 0.0))

    objective.SetMaximization()
    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        raise RuntimeError(f"Period {period_no} solve failed with status {status}.")

    rows = []
    consumption: dict[str, float] = {}
    for (idx, line), qvar in qty.items():
        amount = round(float(qvar.solution_value()), 6)
        if amount <= EPS:
            continue
        order = orders.loc[idx]
        order_id = str(order["\u751f\u4ea7\u8ba2\u5355\u53f7"])
        state = line_states[line]
        changeover = changeover_hours(order, state)
        productive_hours = max(1.0 - changeover, 0.0)
        bed_alloc = {}
        for bed in sorted(compatibility[(idx, line)]):
            bvar = bed_qty.get((idx, line, bed))
            if bvar is None:
                continue
            bamount = round(float(bvar.solution_value()), 6)
            if bamount > EPS:
                bed_alloc[bed] = bamount
        for material, unit_usage in usage.get(order_id, {}).items():
            consumption[material] = consumption.get(material, 0.0) + unit_usage * amount
        rows.append(
            {
                "\u65f6\u6bb5": period_no,
                "\u5f00\u59cb\u65f6\u95f4": current_time,
                "\u7ed3\u675f\u65f6\u95f4": current_time + pd.Timedelta(hours=1),
                "\u7b2c\u5929\u6570": (period_no - 1) // (WORK_END_HOUR - WORK_START_HOUR) + 1,
                "\u5c0f\u65f6\u6570": current_time.hour,
                "\u5e8f\u53f7": idx,
                "\u751f\u4ea7\u5de5\u5382": order.get("\u751f\u4ea7\u5de5\u5382"),
                "\u751f\u4ea7\u8ba2\u5355\u53f7": order_id,
                "\u9500\u552e\u8ba2\u5355\u53f7": order.get("\u9500\u552e\u8ba2\u5355\u53f7"),
                "\u4ea7\u54c1": order.get("\u4ea7\u54c1"),
                "\u662f\u5426\u63d2\u5355": order.get("\u662f\u5426\u63d2\u5355"),
                "\u8ba1\u5212\u5f00\u59cb\u65f6\u95f4": order.get("\u8ba1\u5212\u5f00\u59cb\u65f6\u95f4"),
                "\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4": order.get("\u8ba1\u5212\u5b8c\u6210\u65f6\u95f4"),
                "\u8ba1\u5212\u4ea7\u51fa\u6570\u91cf": order.get("\u8ba1\u5212\u4ea7\u51fa\u6570\u91cf"),
                "\u6392\u524d\u5269\u4f59\u6570\u91cf": order.get("\u5269\u4f59\u6570\u91cf"),
                "\u672c\u6b21\u5206\u914d\u6570\u91cf": amount,
                "\u6392\u540e\u5269\u4f59\u6570\u91cf": max(float(order.get("\u5269\u4f59\u6570\u91cf")) - amount, 0.0),
                "\u6dfb\u52a0\u5242": order.get("\u6dfb\u52a0\u5242"),
                "\u4ea7\u7ebf": line,
                "\u5e72\u71e5\u5e8a\u5206\u914d": ";".join(f"{bed}:{value:g}" for bed, value in bed_alloc.items()),
                "\u6362\u4ea7\u65f6\u95f4h": changeover,
                "\u6709\u6548\u751f\u4ea7\u65f6\u95f4h": productive_hours,
                "\u76ee\u6807\u6743\u91cd": period_objective_weight(order, current_time),
                "\u8c03\u8282\u539f\u56e0": line_block_reasons.get(line, ""),
            }
        )

    for material, amount in consumption.items():
        stock[material] = max(stock.get(material, 0.0) - amount, 0.0)

    if not quiet:
        print(
            f"period={period_no} time={current_time} rows={len(rows)} "
            f"qty={sum(r['\u672c\u6b21\u5206\u914d\u6570\u91cf'] for r in rows):.3f} obj={objective.Value():.2f}"
        )
    return rows, [{"\u65f6\u95f4": current_time, "\u7269\u6599\u7f16\u7801": k, "\u6d88\u8017\u6570\u91cf": v} for k, v in consumption.items()], objective.Value()


def run_schedule(args: argparse.Namespace) -> Path:
    order_path = Path(args.orders)
    capacity_path = Path(args.capacity)
    orders, materials, arrivals, capacity, relation, adjustments = load_inputs(order_path, capacity_path)
    stock, usage = build_material_maps(materials)
    compatibility, line_caps, _ = build_compatibility(orders, relation, capacity)

    start_time = pd.Timestamp(args.start) if args.start else default_start_time(orders)
    current_time = next_work_period(start_time)
    output = Path(args.output) if args.output else Path(f"result_rolling_anonymized_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")
    stream_dir = Path(args.stream_dir) if args.stream_dir else output.with_suffix("").with_name(output.stem + "_stream")
    stream_dir.mkdir(parents=True, exist_ok=True)

    schedule_csv = stream_dir / "schedule.csv"
    consumption_csv = stream_dir / "consumption.csv"
    arrival_csv = stream_dir / "arrivals.csv"
    objective_csv = stream_dir / "objective.csv"
    progress_csv = stream_dir / "progress.csv"
    for path in (schedule_csv, consumption_csv, arrival_csv, objective_csv, progress_csv):
        if path.exists():
            path.unlink()

    line_states = {line: LineState() for line in line_caps}
    applied_arrival_rows: set[int] = set()
    stop_reason = ""
    period_no = 0
    no_feasible_streak = 0
    fixed_periods = args.days * (WORK_END_HOUR - WORK_START_HOUR)
    max_periods = args.max_periods if args.until_complete else fixed_periods

    while period_no < max_periods:
        if args.until_complete and float(orders["\u5269\u4f59\u6570\u91cf"].sum()) <= EPS:
            stop_reason = "\u6240\u6709\u8ba2\u5355\u5df2\u6392\u5b8c"
            break
        if not args.until_complete and period_no >= fixed_periods:
            stop_reason = "\u8fbe\u5230\u56fa\u5b9a\u6392\u4ea7\u7a97\u53e3"
            break

        period_no += 1
        arrival_rows = apply_arrivals(stock, arrivals, applied_arrival_rows, current_time)
        append_rows(arrival_csv, arrival_rows)
        rows, consumption, objective_value = solve_period(
            period_no,
            current_time,
            orders,
            compatibility,
            line_caps,
            adjustments,
            stock,
            usage,
            line_states,
            args.quiet,
        )
        used_lines = {row["\u4ea7\u7ebf"] for row in rows}
        setup_rows = choose_setup_rows(
            period_no,
            current_time,
            orders,
            compatibility,
            line_caps,
            adjustments,
            stock,
            usage,
            line_states,
            used_lines,
        )

        if not rows and not setup_rows:
            no_feasible_streak += 1
            append_rows(
                progress_csv,
                [
                    {
                        "\u65f6\u6bb5": period_no,
                        "\u5f00\u59cb\u65f6\u95f4": current_time,
                        "\u672c\u65f6\u6bb5\u4ea7\u91cf": 0.0,
                        "\u5269\u4f59\u672a\u6392\u91cf": float(orders["\u5269\u4f59\u6570\u91cf"].sum()),
                        "\u5907\u6ce8": "no feasible production",
                    }
                ],
            )
            print(f"period={period_no} time={current_time} no feasible production")
            if no_feasible_streak >= args.max_no_feasible:
                stop_reason = f"\u8fde\u7eed{args.max_no_feasible}\u4e2a\u65f6\u6bb5\u65e0\u53ef\u884c\u751f\u4ea7\u6216\u6362\u4ea7"
                break
            current_time = advance_one_work_hour(current_time)
            continue
        no_feasible_streak = 0

        for row in rows:
            idx = int(row["\u5e8f\u53f7"])
            orders.at[idx, "\u5269\u4f59\u6570\u91cf"] = max(float(orders.at[idx, "\u5269\u4f59\u6570\u91cf"]) - float(row["\u672c\u6b21\u5206\u914d\u6570\u91cf"]), 0.0)
            line_states[row["\u4ea7\u7ebf"]] = LineState(
                order_id=str(row["\u751f\u4ea7\u8ba2\u5355\u53f7"]),
                product=str(row["\u4ea7\u54c1"]),
                additive=str(row["\u6dfb\u52a0\u5242"]),
            )
        for row in setup_rows:
            line_states[row["\u4ea7\u7ebf"]] = LineState(
                order_id=str(row["\u751f\u4ea7\u8ba2\u5355\u53f7"]),
                product=str(row["\u4ea7\u54c1"]),
                additive=str(row["\u6dfb\u52a0\u5242"]),
            )

        append_rows(schedule_csv, rows + setup_rows)
        append_rows(consumption_csv, consumption)
        append_rows(objective_csv, [{"\u65f6\u6bb5": period_no, "\u5f00\u59cb\u65f6\u95f4": current_time, "\u76ee\u6807\u51fd\u6570\u503c": objective_value}])
        append_rows(
            progress_csv,
            [
                {
                    "\u65f6\u6bb5": period_no,
                    "\u5f00\u59cb\u65f6\u95f4": current_time,
                    "\u672c\u65f6\u6bb5\u4ea7\u91cf": sum(float(row["\u672c\u6b21\u5206\u914d\u6570\u91cf"]) for row in rows),
                    "\u5269\u4f59\u672a\u6392\u91cf": float(orders["\u5269\u4f59\u6570\u91cf"].sum()),
                    "\u5907\u6ce8": "setup only" if setup_rows and not rows else ("with setup" if setup_rows else ""),
                }
            ],
        )

        if period_no % max(args.checkpoint_every, 1) == 0:
            write_snapshot(stream_dir / "remaining_checkpoint.csv", build_remaining_frame(orders))
            write_snapshot(stream_dir / "inventory_checkpoint.csv", inventory_frame(stock))
            print(
                f"checkpoint period={period_no} remaining={float(orders['\u5269\u4f59\u6570\u91cf'].sum()):.3f} "
                f"stream_dir={stream_dir}"
            )
        current_time = advance_one_work_hour(current_time)

    if not stop_reason:
        stop_reason = "\u8fbe\u5230\u6700\u5927\u65f6\u6bb5\u4e0a\u9650" if args.until_complete else "\u8fbe\u5230\u56fa\u5b9a\u6392\u4ea7\u7a97\u53e3"

    remaining = build_remaining_frame(orders)
    inventory = inventory_frame(stock)
    schedule = csv_to_frame(schedule_csv)
    summary = build_summary(orders, schedule, remaining, args, start_time, current_time, period_no, stop_reason)
    write_snapshot(stream_dir / "remaining_final.csv", remaining)
    write_snapshot(stream_dir / "inventory_final.csv", inventory)
    write_snapshot(stream_dir / "summary.csv", summary)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="\u6c47\u603b", index=False)
        schedule.to_excel(writer, sheet_name="\u6392\u4ea7\u660e\u7ec6", index=False)
        remaining.to_excel(writer, sheet_name="\u5269\u4f59\u8ba2\u5355", index=False)
        inventory.to_excel(writer, sheet_name="\u671f\u672b\u5e93\u5b58", index=False)
        csv_to_frame(arrival_csv).to_excel(writer, sheet_name="\u5230\u8d27\u8bb0\u5f55", index=False)
        csv_to_frame(consumption_csv).to_excel(writer, sheet_name="\u6d88\u8017\u8bb0\u5f55", index=False)
        csv_to_frame(objective_csv).to_excel(writer, sheet_name="\u76ee\u6807\u51fd\u6570", index=False)
        csv_to_frame(progress_csv).to_excel(writer, sheet_name="\u8fd0\u884c\u8fdb\u5ea6", index=False)

    print("\u7ed3\u679c\u5df2\u5199\u5165:", output)
    print("\u6d41\u5f0f\u660e\u7ec6\u76ee\u5f55:", stream_dir)
    return output


if __name__ == "__main__":
    run_schedule(parse_args())
