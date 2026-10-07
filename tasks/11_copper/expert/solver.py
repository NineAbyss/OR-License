
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import pulp as lp
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: pulp. Install it in the Python environment used to "
        "run this script, for example: python3 -m pip install pulp"
    ) from exc


ELEMENTS = ["Cu", "S", "Fe", "SiO2", "CaO", "As", "Bi", "Sb", "Zn", "Pb", "F", "Ni", "MgO", "Al2O3"]
ELEMENT_ALIASES = {
    "AL2O3": "Al2O3",
    "Al2O3": "Al2O3",
}
SINGLE_ELEMENT_CONSTRAINTS = set(ELEMENTS)


def as_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def as_optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    return float(value)


def element_key(name: str) -> str:
    return ELEMENT_ALIASES.get(name, name)


def mineral_value(mineral: Dict[str, Any], name: str, warnings: List[str], mineral_index: int) -> float:
    candidates = [name]
    if name == "Al2O3":
        candidates.append("AL2O3")
    for key in candidates:
        if key in mineral:
            return as_float(mineral.get(key), 0.0)
    warnings.append(
        "mineral[%s] %s missing element %s; treated as 0"
        % (mineral_index, mineral.get("pk_material", "<unknown>"), name)
    )
    return 0.0


def choose_solver(time_limit: int, msg: bool):
    if hasattr(lp, "PULP_CBC_CMD"):
        return lp.PULP_CBC_CMD(msg=msg, timeLimit=time_limit)
    return None


def add_abs_diff(prob, diff_var, expr):
    prob += diff_var >= expr
    prob += diff_var >= -expr


def solve_material_composition(data: Dict[str, Any], time_limit: int = 60, msg: bool = True) -> Dict[str, Any]:
    warnings: List[str] = []
    prob = lp.LpProblem("Material_Composition", lp.LpMinimize)

    base = data["BaseParam"]
    env = data["EnvironmentData"]
    minerals = env["mineral"]
    element_ratios = data["ElementRatio"]

    max_mineral_num = int(base["max_mineral_num"])
    planning_horizon = float(base["planning_horizon"])
    daily_production_weight = float(base["daily_production_weight"])
    minimum_ratio_used = float(base.get("minimum_ratio_used") or 0)
    selection_type = int(env.get("mineral_select", 0))

    mineral_range = range(len(minerals))
    element_range = range(len(ELEMENTS))
    element_cons_range = range(len(element_ratios))
    element_index = {name: idx for idx, name in enumerate(ELEMENTS)}

    mineral_names = [m.get("pk_material", "mineral_%s" % i) for i, m in enumerate(minerals)]
    mineral_element = []
    for i, mineral in enumerate(minerals):
        mineral_element.append([mineral_value(mineral, name, warnings, i) / 100.0 for name in ELEMENTS])

    mineral_ratio = lp.LpVariable.dicts("mineral_ratio", mineral_range, lowBound=0, cat="Continuous")
    element_ratio = lp.LpVariable.dicts("element_ratio", element_range, lowBound=0, cat="Continuous")
    element_ratio_diff = lp.LpVariable.dicts("element_ratio_diff", element_cons_range, lowBound=0)
    mineral_num_diff = lp.LpVariable("mineral_num_diff", lowBound=0)
    mineral_used = lp.LpVariable.dicts("mineral_used", mineral_range, cat="Binary")

    prob += lp.lpSum(mineral_ratio[i] for i in mineral_range) == 100
    if selection_type != 2:
        prob += lp.lpSum(mineral_used[i] for i in mineral_range) <= max_mineral_num

    prob += mineral_num_diff >= max_mineral_num - lp.lpSum(mineral_used[i] for i in mineral_range)
    prob += mineral_num_diff >= lp.lpSum(mineral_used[i] for i in mineral_range) - max_mineral_num

    for i in mineral_range:
        prob += 100 * mineral_used[i] >= mineral_ratio[i]

    for j in element_range:
        prob += element_ratio[j] == lp.lpSum(mineral_ratio[i] * mineral_element[i][j] for i in mineral_range)

    quality_weights: List[float] = []
    for row_index, row in enumerate(element_ratios):
        name = element_key(row["elementproject"])
        lb = as_optional_float(row.get("element_lb"))
        ub = as_optional_float(row.get("element_ub"))
        opt = as_optional_float(row.get("element_opt"))
        quality_weights.append(as_float(row.get("weight_rat"), 0.0))

        if name == "S/Cu":
            s_idx = element_index["S"]
            cu_idx = element_index["Cu"]
            if ub is not None:
                prob += element_ratio[s_idx] - ub * element_ratio[cu_idx] <= 0
            if lb is not None:
                prob += element_ratio[s_idx] - lb * element_ratio[cu_idx] >= 0
            if opt is not None:
                add_abs_diff(prob, element_ratio_diff[row_index], element_ratio[s_idx] - opt * element_ratio[cu_idx])
        elif name == "Fe/SiO2":
            fe_idx = element_index["Fe"]
            sio2_idx = element_index["SiO2"]
            if ub is not None:
                prob += element_ratio[fe_idx] - ub * element_ratio[sio2_idx] <= 0
            if lb is not None:
                prob += element_ratio[fe_idx] - lb * element_ratio[sio2_idx] >= 0
            if opt is not None:
                add_abs_diff(prob, element_ratio_diff[row_index], element_ratio[fe_idx] - opt * element_ratio[sio2_idx])
        elif name in SINGLE_ELEMENT_CONSTRAINTS:
            idx = element_index[name]
            if ub is not None:
                prob += element_ratio[idx] <= ub
            if lb is not None:
                prob += element_ratio[idx] >= lb
            if opt is not None:
                add_abs_diff(prob, element_ratio_diff[row_index], element_ratio[idx] - opt)
        else:
            warnings.append("unsupported element constraint %s; ignored" % row["elementproject"])

    selected_any = False
    prices: List[float] = []
    for i, mineral in enumerate(minerals):
        inventory = as_float(mineral.get("mineral_inv"), 0.0)
        lb = as_optional_float(mineral.get("mineral_lb"))
        ub = as_optional_float(mineral.get("mineral_ub"))
        prices.append(as_float(mineral.get("mineral_pri"), 0.0))

        prob += mineral_ratio[i] * planning_horizon * daily_production_weight / 100.0 <= inventory
        if lb is not None and lb > 0:
            prob += mineral_ratio[i] >= lb
            prob += mineral_used[i] <= mineral_ratio[i]
        else:
            prob += mineral_ratio[i] >= mineral_used[i] * max(minimum_ratio_used, 1.0)
        if ub is not None:
            prob += mineral_ratio[i] <= ub

        forced = mineral.get("select") == "Y"
        selected_any = selected_any or forced

    if selected_any:
        for i, mineral in enumerate(minerals):
            forced = mineral.get("select") == "Y"
            if selection_type == 2:
                prob += mineral_used[i] == (1 if forced else 0)
            elif selection_type == 1 and forced:
                prob += mineral_used[i] == 1

    objective_config = data.get("OptimaloBject", {})
    best_price = objective_config.get("best_price") == "Y"
    best_quality = objective_config.get("best_quality") == "Y"
    integrate_best = objective_config.get("integrate_best") == "Y"
    price_weight = as_float(objective_config.get("prict_weight"), 1.0 if best_price else 0.0)
    quality_weight = as_float(objective_config.get("quality_weight"), 1.0)

    if best_price:
        wq = 0.1
        wp = price_weight
    elif integrate_best:
        wq = quality_weight
        wp = price_weight
    elif best_quality:
        wq = 1.0
        wp = 0.0
    else:
        wq = 1.0
        wp = 0.0

    objective = (
        lp.lpSum(wq * quality_weights[i] * element_ratio_diff[i] for i in element_cons_range)
        + wq * mineral_num_diff
    )
    if wp:
        objective += lp.lpSum(wp * prices[i] * mineral_ratio[i] for i in mineral_range) / 100.0
    prob += objective

    solver = choose_solver(time_limit=time_limit, msg=msg)
    if solver is None:
        prob.solve()
    else:
        prob.solve(solver)

    status = lp.LpStatus[prob.status]
    if status == "Optimal":
        output_mineral_ratio = {
            mineral_names[i]: (None if mineral_ratio[i].varValue is None else round(float(mineral_ratio[i].varValue), 6))
            for i in mineral_range
        }
        output_elements = {
            name: (None if element_ratio[j].varValue is None else round(float(element_ratio[j].varValue), 6))
            for name, j in element_index.items()
        }
        selected_count = sum(1 for value in output_mineral_ratio.values() if value is not None and value > 1e-7)
        objective_value = None if prob.objective.value() is None else float(prob.objective.value())
    else:
        output_mineral_ratio = {mineral_names[i]: None for i in mineral_range}
        output_elements = {name: None for name in element_index}
        selected_count = None
        objective_value = None

    return {
        "status": status,
        "statue": 1 if status == "Optimal" else 0,
        "objective": objective_value,
        "mineral_ratio": output_mineral_ratio,
        "element_ratio": output_elements,
        "selected_count": selected_count,
        "warnings": warnings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(Path(__file__).resolve().parent / "input.json"), help="Input JSON file. Defaults to input.json.")
    parser.add_argument("--output-dir", default="outputs", help="Directory for non-overwriting outputs.")
    parser.add_argument("--time-limit", type=int, default=60)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def resolve_input_path(raw_path: str, script_dir: Path) -> Path:
    input_path = Path(raw_path)
    if input_path.is_absolute():
        return input_path
    cwd_path = Path.cwd() / input_path
    if cwd_path.exists():
        return cwd_path
    script_path = script_dir / input_path
    if script_path.exists():
        return script_path
    package_path = script_dir.parent / input_path
    if package_path.exists():
        return package_path
    return script_path


def resolve_output_dir(raw_path: str) -> Path:
    output_dir = Path(raw_path)
    if output_dir.is_absolute():
        return output_dir
    return Path.cwd() / output_dir


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    input_path = resolve_input_path(args.input, base_dir)
    with input_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    result = solve_material_composition(data, time_limit=args.time_limit, msg=not args.quiet)
    result["input_file"] = str(input_path)
    result["generated_at"] = datetime.now().isoformat(timespec="seconds")

    output_dir = resolve_output_dir(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / ("%s_result_%s.json" % (input_path.stem, datetime.now().strftime("%Y%m%d_%H%M%S")))
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print("status:", result["status"])
    print("selected_count:", result["selected_count"])
    print("output:", output_path)
    if result["warnings"]:
        print("warnings:", len(result["warnings"]))


if __name__ == "__main__":
    main()
