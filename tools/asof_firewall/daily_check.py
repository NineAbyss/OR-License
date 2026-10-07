#!/usr/bin/env python3

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ABS_TOL = 1e-6
REL_TOL = 1e-6
WEIGHT_SUM_TOL = 5e-3
NAME_CAP_REL_TOL = 1e-2
COVERAGE_REL_TOL = 5e-3
EXPOSURE_REL_TOL = 1.5e-2
CONSTRAINED_STYLE_FACTORS = ("beta", "size")


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= ABS_TOL + REL_TOL * max(abs(left), abs(right), 1.0)


def _leq(left: float, right: float) -> bool:
    return left <= right or _close(left, right)


def _coverage_met(observed: float, required: float) -> bool:
    return _leq(required, observed + COVERAGE_REL_TOL * required)


def load_pack(pack_root: Path, date: str) -> dict[str, Any]:
    table = pd.read_csv(pack_root / "cross_section" / f"{date}.csv")
    table["instrument"] = table["instrument"].map(str)
    with np.load(pack_root / "factors" / f"{date}.npz", allow_pickle=True) as handle:
        asset_ids = [str(item) for item in handle["asset_ids"]]
        factor_names = [str(item) for item in handle["factor_names"]]
        industry_factors = [str(item) for item in handle["industry_factors"]]
        exposures = np.asarray(handle["exposures"], dtype=float)
        covariance = np.asarray(handle["factor_covariance"], dtype=float)
    if asset_ids != table["instrument"].tolist():
        raise RuntimeError(f"{date}: pack CSV and npz disagree on asset order")
    pack = {
        "asset_ids": asset_ids,
        "benchmark": table["benchmark_weight"].to_numpy(dtype=float),
        "constituent": table["is_constituent"].to_numpy(dtype=bool),
        "variance": table["specific_variance"].to_numpy(dtype=float),
        "factor_names": factor_names,
        "industry_factors": industry_factors,
        "exposures": exposures,
        "covariance": covariance,
    }
    if "borrow_capacity_weight" in table.columns:
        pack["borrow"] = table["borrow_capacity_weight"].to_numpy(dtype=float)
    if "is_suspended" in table.columns:
        pack["suspended"] = table["is_suspended"].to_numpy(dtype=bool)
    if "close" in table.columns:
        pack["close"] = table["close"].to_numpy(dtype=float)
    if "is_core_index" in table.columns:
        pack["core"] = table["is_core_index"].to_numpy(dtype=bool)
    if "score_available" in table.columns:
        pack["scored"] = table["score_available"].to_numpy(dtype=bool)
    return pack


def tracking_error(active: np.ndarray, pack: dict[str, Any]) -> float:
    factor_active = pack["exposures"].T @ active
    systematic = float(factor_active @ pack["covariance"] @ factor_active)
    specific = float(np.dot(pack["variance"], np.square(active)))
    return float(math.sqrt(max(systematic + specific, 0.0)))


def align_weights(
    frame: pd.DataFrame, pack: dict[str, Any]
) -> tuple[np.ndarray, list[str]]:
    series = (
        frame.assign(instrument=frame["instrument"].map(str))
        .groupby("instrument")["weight"]
        .sum()
    )
    known = set(pack["asset_ids"])
    unknown = sorted(
        name for name, value in series.items() if name not in known and abs(value) > ABS_TOL
    )
    weights = np.array(
        [float(series.get(asset, 0.0)) for asset in pack["asset_ids"]], dtype=float
    )
    return weights, unknown


def unscored_violations(
    weights: np.ndarray, pack: dict[str, Any], rule: str = "H8"
) -> list[str]:
    scored = pack.get("scored")
    if scored is None:
        return []
    blocked = pack.get("suspended")
    stuck = (
        np.zeros(len(weights), dtype=bool)
        if blocked is None
        else np.asarray(blocked, dtype=bool)
    )
    live = ~np.asarray(scored, dtype=bool) & ~stuck
    held = np.where(live & (np.abs(weights) > ABS_TOL))[0]
    if not held.size:
        return []
    i = int(held[int(np.argmax(np.abs(weights[held])))])
    return [
        f"[{rule}] {pack['asset_ids'][i]} has no valid score and is not halted; "
        f"weight {float(weights[i])} must be 0 ({held.size} names)"
    ]


def check_day(
    frame: pd.DataFrame,
    pack: dict[str, Any],
    params: dict[str, float],
) -> list[str]:
    violations: list[str] = []
    weights, unknown = align_weights(frame, pack)
    if unknown:
        violations.append(
            f"[H0] {len(unknown)} ids outside the day's universe, first={unknown[:3]}"
        )
    if not np.isfinite(weights).all():
        violations.append("[H0] non-finite weight")
        return violations
    if np.any(weights < -ABS_TOL):
        violations.append(f"[H1] found negative weight {float(np.min(weights))}")
    violations.extend(unscored_violations(weights, pack))
    total = float(weights.sum())
    if abs(total - 1.0) > WEIGHT_SUM_TOL:
        violations.append(f"[H2] weights sum to {total}, expected 1")
    component = float(weights[pack["constituent"]].sum())
    component_min = float(params.get("component_min", 0.60))
    if not _coverage_met(component, component_min):
        violations.append(
            f"[H3] constituent weight {component} < component_min "
            f"{component_min}"
        )
    if not params:
        return violations
    active = weights - pack["benchmark"]
    te = tracking_error(active, pack)
    if not _leq(te, float(params["tracking_error_ub"])):
        violations.append(
            f"[H4] tracking error {te} exceeds {params['tracking_error_ub']}"
        )
    lookup = {name: i for i, name in enumerate(pack["factor_names"])}
    style_bound = float(params["style_bound"])
    for name in CONSTRAINED_STYLE_FACTORS:
        if name not in lookup:
            continue
        value = float(active @ pack["exposures"][:, lookup[name]])
        if not _leq(abs(value), style_bound):
            violations.append(
                f"[H5] {name} active exposure {value} outside ±{style_bound}"
            )
    industry_bound = float(params["industry_bound"])
    for name in pack["industry_factors"]:
        value = float(active @ pack["exposures"][:, lookup[name]])
        if not _leq(abs(value), industry_bound):
            violations.append(
                f"[H6] industry {name} active exposure {value} outside ±{industry_bound}"
            )
    return violations


def check_day_longshort(
    frame: pd.DataFrame,
    pack: dict[str, Any],
    params: dict[str, float],
    prior: dict[str, float] | None = None,
) -> list[str]:
    violations: list[str] = []
    held = prior or {}
    weights, unknown = align_weights(frame, pack)
    if unknown:
        violations.append(
            f"[H0] {len(unknown)} ids outside the day's universe, first={unknown[:3]}"
        )
    if not np.isfinite(weights).all():
        violations.append("[H0] non-finite weight")
        return violations

    carried = np.array(
        [float(held.get(asset, 0.0)) for asset in pack["asset_ids"]], dtype=float
    )
    inherited = np.abs(carried)
    violations.extend(unscored_violations(weights, pack))
    if params:
        cap = float(params["name_cap"])
        allowance = np.maximum(cap, inherited) * (1.0 + NAME_CAP_REL_TOL)
        breach = np.where(np.abs(weights) > allowance + ABS_TOL)[0]
        if breach.size:
            i = int(breach[np.argmax(np.abs(weights[breach]) - allowance[breach])])
            violations.append(
                f"[H1] {pack['asset_ids'][i]} weight {float(weights[i])} exceeds "
                f"name_cap {cap} and its inherited {float(inherited[i])} "
                f"({breach.size} names)"
            )

    long_w = np.clip(weights, 0.0, None)
    short_w = np.clip(-weights, 0.0, None)
    for side, series, key in (
        ("long", long_w, "long_budget"),
        ("short", short_w, "short_budget"),
    ):
        total = float(series.sum())
        target = float(params.get(key, 1.0))
        if abs(total - target) > WEIGHT_SUM_TOL:
            violations.append(f"[H2] {side} budget {total} != {target}")
    net = float(weights.sum())
    if abs(net) > WEIGHT_SUM_TOL:
        violations.append(f"[H2] net exposure {net} != 0")

    halted = pack.get("suspended")
    if halted is not None:
        stuck = np.asarray(halted, dtype=bool)
        moved = np.where(stuck & (np.abs(weights - carried) > ABS_TOL))[0]
        if moved.size:
            i = int(moved[int(np.argmax(np.abs(weights[moved] - carried[moved])))])
            violations.append(
                f"[H7] {pack['asset_ids'][i]} is halted; weight {float(weights[i])} "
                f"differs from held {float(carried[i])} ({moved.size} names)"
            )

    if not params:
        minimum = 0.60
        gross = float(long_w.sum() + short_w.sum())
        combined = float((long_w + short_w)[pack["constituent"]].sum())
        required = minimum * gross
        if not _leq(required, combined + COVERAGE_REL_TOL * max(required, 1.0)):
            violations.append(
                f"[H4] combined constituent coverage {combined} < component_min "
                f"{minimum} of gross {gross} (requires {required})"
            )
        return violations

    borrow = pack.get("borrow")
    if borrow is None:
        violations.append("[H3] pack carries no borrow capacity to check against")
    else:
        inherited_short = np.array(
            [max(-float(held.get(asset, 0.0)), 0.0) for asset in pack["asset_ids"]],
            dtype=float,
        )
        room = (np.asarray(borrow, dtype=float) + inherited_short) * (
            1.0 + NAME_CAP_REL_TOL
        )
        overflow = np.where(short_w > room + ABS_TOL)[0]
        if overflow.size:
            i = int(overflow[int(np.argmax(short_w[overflow] - room[overflow]))])
            violations.append(
                f"[H3] {pack['asset_ids'][i]} short {short_w[i]} exceeds "
                f"borrow {float(borrow[i])} plus inherited "
                f"{float(inherited_short[i])} ({overflow.size} names)"
            )

    minimum = float(params["component_min"])
    constituent = pack["constituent"]
    for side, series in (("long", long_w), ("short", short_w)):
        covered = float(series[constituent].sum())
        if not _leq(minimum, covered + COVERAGE_REL_TOL * max(minimum, 1.0)):
            violations.append(
                f"[H4] {side} constituent coverage {covered} < component_min {minimum}"
            )

    lookup = {name: i for i, name in enumerate(pack["factor_names"])}

    def allowance(column: np.ndarray, bound: float) -> float:
        drifted = abs(float(carried @ column)) if carried.any() else 0.0
        return max(bound, drifted) * (1.0 + EXPOSURE_REL_TOL)

    style_bound = float(params["style_bound"])
    for name in CONSTRAINED_STYLE_FACTORS:
        if name not in lookup:
            continue
        column = pack["exposures"][:, lookup[name]]
        value = float(weights @ column)
        if not _leq(abs(value), allowance(column, style_bound)):
            violations.append(f"[H5] {name} net exposure {value} outside ±{style_bound}")

    industry_bound = float(params["industry_bound"])
    for name in pack["industry_factors"]:
        column = pack["exposures"][:, lookup[name]]
        value = float(weights @ column)
        if not _leq(abs(value), allowance(column, industry_bound)):
            violations.append(
                f"[H6] industry {name} net exposure {value} outside ±{industry_bound}"
            )
    return violations


def check_day_sif(
    frame: pd.DataFrame,
    pack: dict[str, Any],
    params: dict[str, float],
    *,
    position: pd.DataFrame | None = None,
    stock_budget: float | None = None,
) -> list[str]:
    violations: list[str] = []
    weights, unknown = align_weights(frame, pack)
    if unknown:
        violations.append(
            f"[H0] {len(unknown)} ids outside the day's universe, first={unknown[:3]}"
        )
    if not np.isfinite(weights).all():
        violations.append("[H0] non-finite weight")
        return violations
    if np.any(weights < -ABS_TOL):
        violations.append(f"[H1] found negative weight {float(np.min(weights))}")
    violations.extend(unscored_violations(weights, pack))
    if stock_budget is not None and pack.get("suspended") is not None:
        budget = float(stock_budget)
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError("SIF stock_budget must be positive and finite")
        stuck = np.asarray(pack["suspended"], dtype=bool)
        prices = pack.get("close")
        if prices is None:
            raise ValueError("SIF cross section has no close for halted target check")
        held_shares: dict[str, float] = {}
        if position is not None and not position.empty:
            held = position.assign(stockcode=position["stockcode"].map(str))
            held_shares = held.groupby("stockcode")["volume"].sum().to_dict()
        moved: list[tuple[str, int, float]] = []
        for i in np.where(stuck)[0]:
            price = float(prices[i])
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"invalid close for halted {pack['asset_ids'][i]}")
            target_shares = int(float(weights[i]) * budget / price)
            name = pack["asset_ids"][i]
            actual_shares = float(held_shares.get(name, 0.0))
            if abs(target_shares - actual_shares) > ABS_TOL:
                moved.append((name, target_shares, actual_shares))
        if moved:
            name, target_shares, actual_shares = moved[0]
            violations.append(
                f"[H7] {name} is halted; target {target_shares} shares differs "
                f"from held {actual_shares:g} ({len(moved)} names)"
            )
    if params:
        cap = float(params["name_cap"])
        if np.any(weights > cap * (1.0 + NAME_CAP_REL_TOL) + ABS_TOL):
            violations.append(
                f"[H1] weight {float(np.max(weights))} exceeds name_cap {cap}"
            )
    total = float(weights.sum())
    if abs(total - 1.0) > WEIGHT_SUM_TOL:
        violations.append(f"[H2] weights sum to {total}, expected 1")
    core = pack.get("core", pack["constituent"])
    component = float(weights[core].sum())
    component_min = float(params.get("component_min", 0.60))
    if not _coverage_met(component, component_min):
        violations.append(
            f"[H5] core-index weight {component} < component_min "
            f"{component_min}"
        )
    if not params:
        return violations
    lookup = {name: i for i, name in enumerate(pack["factor_names"])}
    beta_i = lookup["beta"]
    bench_beta = float(pack["benchmark"] @ pack["exposures"][:, beta_i])
    sigma_beta = float(
        math.sqrt(max(float(pack["covariance"][beta_i, beta_i]), 0.0))
    )
    port_beta = float(weights @ pack["exposures"][:, beta_i])
    lower = bench_beta + float(params["beta_signed_lb_sigma"]) * sigma_beta
    upper = bench_beta + float(params["beta_signed_ub_sigma"]) * sigma_beta
    slack = ABS_TOL + EXPOSURE_REL_TOL * max(sigma_beta, 1e-12)
    if port_beta < lower - slack or port_beta > upper + slack:
        violations.append(
            f"[H6] portfolio beta {port_beta} outside [{lower}, {upper}]"
        )
    active = weights - pack["benchmark"]
    size_bound = float(params["size_bound"])
    style_bound = float(params["style_bound"])
    for name in pack["factor_names"]:
        if name in pack["industry_factors"] or name == "beta":
            continue
        value = float(active @ pack["exposures"][:, lookup[name]])
        bound = size_bound if name == "size" else style_bound
        if not _leq(abs(value), bound * (1.0 + EXPOSURE_REL_TOL)):
            violations.append(f"[H7] {name} active exposure {value} outside ±{bound}")
    industry_bound = float(params["industry_bound"])
    for name in pack["industry_factors"]:
        value = float(active @ pack["exposures"][:, lookup[name]])
        if not _leq(abs(value), industry_bound * (1.0 + EXPOSURE_REL_TOL)):
            violations.append(
                f"[H7] industry {name} active exposure {value} outside ±{industry_bound}"
            )
    return violations


CHECKERS = {
    "enhanced_index": check_day,
    "longshort": check_day_longshort,
    "sif": check_day_sif,
}


def check_for(profile_key: str):
    return CHECKERS[profile_key]
