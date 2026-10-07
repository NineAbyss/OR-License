
from pathlib import Path

import pandas as pd
from ortools.linear_solver import pywraplp


BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "input.xlsx"
OUTPUT_FILE = BASE_DIR / "result.xlsx"
SHEET_NAME = "8\u6708"

data = pd.read_excel(INPUT_FILE, sheet_name=SHEET_NAME)

solver = pywraplp.Solver("LinearExample", pywraplp.Solver.GLOP_LINEAR_PROGRAMMING)

num = len(data.index)

product_codes = {i + 1: f"M{i + 1:02d}" for i in range(num)}

relation_targets = [[] for _ in range(num)]
relation_targets[1 - 1] = [4, 5, 19]
relation_targets[2 - 1] = [5]
relation_targets[4 - 1] = [19]
relation_targets[5 - 1] = [6, 7, 8, 9, 10, 11, 12, 13]
relation_targets[14 - 1] = [15, 16]
relation_targets[17 - 1] = [2, 14]
relation_targets[18 - 1] = [2, 3, 4, 5]
relation_targets[19 - 1] = [20]
relation_targets[20 - 1] = [14]
relation_targets[21 - 1] = [20]

target_sequence = []
num_internal_flows = 0
for i in range(num):
    num_internal_flows += len(relation_targets[i])
    if relation_targets[i]:
        target_sequence.extend(relation_targets[i])

input_flow_indexes = [[] for _ in range(num)]
for i in range(num):
    input_flow_indexes[i] = [
        j for j in range(len(target_sequence)) if target_sequence[j] - 1 == i
    ]

consumption_coefficients = [[] for _ in range(num)]
consumption_coefficients[2 - 1] = [0.011, 0.31]
consumption_coefficients[3 - 1] = [1]
consumption_coefficients[4 - 1] = [0.148, 0.13]
consumption_coefficients[5 - 1] = [0.008, 0.005, 1.4]
consumption_coefficients[6 - 1] = [0.6]
consumption_coefficients[7 - 1] = [0.71]
consumption_coefficients[8 - 1] = [0.854]
consumption_coefficients[9 - 1] = [0.854]
consumption_coefficients[10 - 1] = [0.562]
consumption_coefficients[11 - 1] = [0.91]
consumption_coefficients[12 - 1] = [0.91]
consumption_coefficients[13 - 1] = [0.846]
consumption_coefficients[14 - 1] = [0.06, 1.02]
consumption_coefficients[15 - 1] = [0.507]
consumption_coefficients[16 - 1] = [0.2333]
consumption_coefficients[19 - 1] = [0.014, 0.041]
consumption_coefficients[20 - 1] = [0.303, 0.74]

x = [[]] * num
s = [[]] * num
z = [[]] * num
y = [[]] * num_internal_flows

for i in range(num):
    x[i] = solver.NumVar(0, float(data["\u6700\u5927\u4ea7\u80fd"][i]), "x" + str(i))

for i in range(num):
    s[i] = solver.NumVar(
        float(data["\u6700\u5c0f\u5e93\u5b58"][i]), float(data["\u6700\u5927\u5e93\u5b58"][i]), "s" + str(i)
    )

for i in range(num):
    z[i] = solver.NumVar(0, float(data["\u9500\u552e\u91cf"][i]), "z" + str(i))

for i in range(num_internal_flows):
    y[i] = solver.NumVar(0, solver.infinity(), "y" + str(i))

balance_constraints = []
flow_index = 0
for i in range(num):
    balance_constraints.append("constraint" + str(i) + "of time balance")
    balance_constraints[i] = solver.Constraint(
        float(data["\u671f\u521d\u5e93\u5b58"][i]), float(data["\u671f\u521d\u5e93\u5b58"][i])
    )
    balance_constraints[i].SetCoefficient(x[i], -1)
    balance_constraints[i].SetCoefficient(s[i], 1)
    balance_constraints[i].SetCoefficient(z[i], 1)
    for _ in range(len(relation_targets[i])):
        balance_constraints[i].SetCoefficient(y[flow_index], 1)
        flow_index += 1

material_constraints = []
for i in range(num_internal_flows):
    material_constraints.append("constraint" + str(i) + "of material balance")

constraint_index = 0
for k in range(num):
    if input_flow_indexes[k]:
        for j in range(len(input_flow_indexes[k])):
            material_constraints[constraint_index] = solver.Constraint(0, 0)
            material_constraints[constraint_index].SetCoefficient(
                x[k], -consumption_coefficients[k][j]
            )
            material_constraints[constraint_index].SetCoefficient(
                y[input_flow_indexes[k][j]], 1
            )
            constraint_index += 1

joint_constraint_1 = solver.Constraint(0, 0)
joint_constraint_1.SetCoefficient(x[17], 1)
joint_constraint_1.SetCoefficient(x[0], -0.92)

joint_constraint_2 = solver.Constraint(0, 0)
joint_constraint_2.SetCoefficient(x[16], 1)
joint_constraint_2.SetCoefficient(x[0], -0.025)

objective = solver.Objective()
for i in range(num):
    objective.SetCoefficient(z[i], float(data["\u9500\u552e\u4ef7"][i]))
    objective.SetCoefficient(x[i], float(-data["\u5355\u4f4d\u5236\u9020\u6210\u672c"][i]))

objective.SetMaximization()

result_status = solver.Solve()
assert result_status == pywraplp.Solver.OPTIMAL
assert solver.VerifySolution(1e-7, True)

print("Number of variables =", solver.NumVariables())
print("Number of constraints =", solver.NumConstraints())
print("Optimal objective value = %d" % solver.Objective().Value())

production_result = []
ending_inventory_result = []
sales_result = []

print("Solution:")
for i in range(num):
    print("%s = %f" % (product_codes[i + 1], x[i].solution_value()))
    production_result.append(x[i].solution_value())
    ending_inventory_result.append(s[i].solution_value())
    sales_result.append(z[i].solution_value())

result = data.copy()
result.insert(0, "product_code", [product_codes[i + 1] for i in range(num)])
if "\u4e3b\u4ea7\u54c1" in result.columns:
    result = result.drop(columns=["\u4e3b\u4ea7\u54c1"])

result["calculated_production"] = production_result
result["calculated_ending_inventory"] = ending_inventory_result
result["calculated_sales"] = sales_result

for k in range(num):
    if input_flow_indexes[k]:
        for j in range(len(input_flow_indexes[k])):
            result.loc[k, "internal_consumption_" + str(j)] = y[
                input_flow_indexes[k][j]
            ].solution_value()

result.to_excel(OUTPUT_FILE, index=False)
