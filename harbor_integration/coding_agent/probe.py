import importlib.metadata
import json
import os
import platform


def probe(*, include_gurobi=False, include_mosek=False, include_copt=False):
    versions = {"Python": platform.python_version()}
    packages = ("ortools", "highspy", "pyomo", "numpy", "pandas", "scipy", "duckdb", "pyarrow", "PyYAML")
    for name in packages + (("gurobipy",) if include_gurobi else ()) + (("mosek",) if include_mosek else ()) + (("coptpy",) if include_copt else ()):
        versions[name] = importlib.metadata.version(name)
    from ortools.sat.python import cp_model
    for workers in (1, 8):
        model = cp_model.CpModel()
        x = [model.new_bool_var(f"x{i}") for i in range(40)]
        model.add(sum(x) >= 20)
        model.minimize(sum(x))
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = workers
        solver.parameters.max_time_in_seconds = 5
        assert solver.solve(model) == cp_model.OPTIMAL
        assert solver.objective_value == 20
    import highspy
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    v = h.addVariable(lb=0, ub=10)
    h.addConstr(v >= 3)
    h.minimize(v)
    assert abs(h.getObjectiveValue() - 3) < 1e-8
    from ortools.linear_solver import pywraplp
    linear = pywraplp.Solver.CreateSolver("GLOP")
    variable = linear.NumVar(3, 10, "x")
    linear.Minimize(variable)
    assert linear.Solve() == pywraplp.Solver.OPTIMAL
    from scipy.optimize import milp, linprog, Bounds
    assert milp([1.0], integrality=[1], bounds=Bounds([3], [10])).fun == 3
    assert linprog([1.0], bounds=[(3, 10)], method="highs").fun == 3
    import pyomo.environ as pyo
    m = pyo.ConcreteModel()
    m.x = pyo.Var(bounds=(0, 10))
    m.c = pyo.Constraint(expr=m.x >= 3)
    m.obj = pyo.Objective(expr=m.x)
    pyo.SolverFactory("appsi_highs").solve(m)
    assert abs(pyo.value(m.obj) - 3) < 1e-8
    checks = ["ortools_workers_1_8", "ortools_linear", "scipy_milp_linprog",
              "highs_optimum", "pyomo_highs_optimum"]
    inventory = {"versions": versions, "checks": checks}
    if include_gurobi:
        import gurobipy as gp
        with gp.Env(empty=True) as env:
            env.setParam("OutputFlag", 0)
            env.start()
            with gp.Model(env=env) as model:
                model.setParam("Threads", 1)
                model.setParam("TimeLimit", 10)
                variables = model.addVars(2100, vtype=gp.GRB.BINARY)
                model.addConstr(variables.sum() >= 1)
                model.setObjective(variables.sum())
                model.optimize()
                assert model.Status == gp.GRB.OPTIMAL
        checks.append("gurobi_large_mip")
        inventory["gurobi_license"] = "WLS 完整许可证已通过超过 2000 变量的模型验证"
        inventory["gurobi_license_en"] = "WLS full license validated with a model of more than 2000 variables"
    if include_copt:
        import coptpy as cp
        from coptpy import COPT
        env = cp.Envr()
        model = env.createModel("orle_copt_preflight")
        x = model.addVar(lb=3, ub=10)
        model.setObjective(x, sense=COPT.MINIMIZE)
        model.solve()
        assert model.status == COPT.OPTIMAL and abs(model.objval - 3) < 1e-8
        checks.append("copt_optimum")
        inventory["copt_license"] = "Web License validated with a solved optimization model"
    if include_mosek:
        import mosek.fusion as mf
        with mf.Model("orle_mosek_preflight") as model:
            x = model.variable("x", 1, mf.Domain.greaterThan(3.0))
            model.objective(mf.ObjectiveSense.Minimize, x.index(0))
            model.solve()
            assert abs(x.level()[0] - 3.0) < 1e-7
        checks.append("mosek_fusion_optimum")
        inventory["mosek_license"] = "validated with a solved optimization model"
    return inventory


if __name__ == "__main__":
    print("ORLE_INVENTORY=" + json.dumps(
        probe(include_gurobi=os.environ.get("ORLE_PROBE_GUROBI") == "1",
              include_mosek=os.environ.get("ORLE_PROBE_MOSEK") == "1",
              include_copt=os.environ.get("ORLE_PROBE_COPT") == "1"), ensure_ascii=False))
