#!/usr/bin/env python3

import numpy as np
from pyomo.environ import *
import xlsxwriter as xw


MACHINE_NUM = 11
PRODUCT_NUM = 14
PRODUCT_DICT = {0: "Da", 1: "Db", 2: "Bd", 3: "Bb",
                4: "Da1", 5: "Cc", 6: "Ba", 7: "Be",
                8: "Ac1", 9: "Aa1", 10: "Ca", 11: "Aa",
                12: "Ac", 13: "Bc"}
MACHINE_PRODUCT_LIST = [(0, 1), (2, ), (3, 4, 5), (6, ), (6, ), (7, ), (7, ), (8, 9), (10, ), (11, 12), (13, )]
ORDER = [(11, 9), (12, 8), (8, 9), (0, 4)]
PRODUCT_PRIORITY = [7, 2, 2, 3, 1, 6, 2, 2, 1, 1, 2, 2, 2, 2]
MAX_LOOP = 8
DEMAND = [[1, 1, 2, 1, 2, 1, 6, 5, 1, 2, 1, 2, 1, 2],
          [1, 1, 2, 1, 2, 1, 6, 5, 1, 2, 1, 2, 1, 2],
          [1, 1, 2, 1, 2, 1, 6, 5, 1, 2, 1, 2, 1, 2],
          [1, 1, 2, 1, 2, 1, 6, 5, 1, 2, 1, 2, 1, 2],
          [1, 1, 2, 1, 2, 1, 6, 5, 1, 2, 1, 2, 1, 2]]
PRODUCT_TIME = [30, 15, 70, 30, 10, 20, 30, 60, 30, 20, 20, 60, 50, 50]
TIME_LIMIT = 600


MACHINES = list(range(MACHINE_NUM))
PRODUCTS = list(range(PRODUCT_NUM))
LOOPS = list(range(MAX_LOOP))
INITIAL_TIME = [0 for k in MACHINES]
NOW_BATCH = 0
BATCH_NUM = len(DEMAND)
for j in PRODUCTS:
    for jj in PRODUCTS:
        if jj == j:
            continue
        else:
            if PRODUCT_PRIORITY[j] > PRODUCT_PRIORITY[jj]:
                ORDER.append((j, jj))
            elif PRODUCT_PRIORITY[j] < PRODUCT_PRIORITY[jj]:
                ORDER.append((jj, j))
succ_products = [x[1] for x in ORDER]
pri_products = [x[0] for x in ORDER]
MAX_M = 100

MACHINE_PRODUCT = [[0 for j in PRODUCTS] for k in MACHINES]
for k in MACHINES:
    for j in PRODUCTS:
        if j in MACHINE_PRODUCT_LIST[k]:
            MACHINE_PRODUCT[k][j] = 1

MACHINE_TIME = [0 for k in MACHINES]
MACHINE_LOOP = [0 for k in MACHINES]


def add_var(solver):
    solver.x_kij = Var(MACHINES, LOOPS, PRODUCTS, within=Binary)
    solver.total_time = Var(bounds=(0, None))


def product_constraint(solver, k, i, j):
    return solver.x_kij[k, i, j] <= MACHINE_PRODUCT[k][j]


def colsum_constraint(solver, k, i):
    return sum(solver.x_kij[k, i, j] for j in PRODUCTS) <= 1


def stop_constraint(solver, k, i):
    if i == 0:
        return Constraint.Skip
    else:
        return sum(solver.x_kij[k, i, j] for j in PRODUCTS) <= sum(solver.x_kij[k, i - 1, j] for j in PRODUCTS)


def order_constraint(solver, k, i, j):
    if i == MAX_LOOP - 1:
        return Constraint.Skip
    if j not in succ_products:
        return Constraint.Skip
    else:
        pri_prod_list = [pri_products[m] for m in range(len(succ_products)) if succ_products[m] == j]
        return sum(solver.x_kij[k, i+1, j0] for j0 in pri_prod_list) <= MAX_M * (1 - solver.x_kij[k, i, j])


def demand_constraint(solver, j):
    global NOW_BATCH
    now_demand = DEMAND[NOW_BATCH]
    return sum(sum(solver.x_kij[k, i, j] for i in LOOPS) for k in MACHINES) == now_demand[j]


def objective_constraint(solver, k):
    return solver.total_time >= sum(sum(solver.x_kij[k, i, j] * PRODUCT_TIME[j] for j in PRODUCTS) for i in LOOPS) + INITIAL_TIME[k]


def add_objective(solver):
    solver.value = Objective(expr=solver.total_time,
                             sense=minimize)


def handle_data(solver, result_list_time, result_list_order, result_list_batch, now_batch):
    global INITIAL_TIME
    global MACHINE_TIME
    global MACHINE_LOOP
    for k in MACHINES:
        for i in LOOPS:
            if sum(solver.x_kij[k, i, j].value for j in PRODUCTS) == 0:
                MACHINE_LOOP[k] += i
                MACHINE_TIME[k] += sum(sum(solver.x_kij[k, i0, j].value * PRODUCT_TIME[j] for j in PRODUCTS) for i0 in LOOPS)
                break
            for j in PRODUCTS:
                if solver.x_kij[k, i, j].value == 1:
                    result_list_order[k][i+MACHINE_LOOP[k]] = PRODUCT_DICT[j]
                    result_list_batch[k][i+MACHINE_LOOP[k]] = now_batch
                    result_list_time[k][i+MACHINE_LOOP[k]] = result_list_time[k][i+MACHINE_LOOP[k]-1] + PRODUCT_TIME[j]
                    break
    max_time = max(MACHINE_TIME)
    print("DEBUG: for batch %d, consuming time %d, total %d" % (now_batch, solver.total_time.value, max_time))
    for k in MACHINES:
        INITIAL_TIME[k] = MACHINE_TIME[k] - max_time


def print_time(result_list_time):
    global MACHINE_LOOP
    workbook = xw.Workbook("Sub-scheduling result time.xlsx")
    worksheet = workbook.add_worksheet("Scheduled result batches")
    worksheet.activate()
    worksheet.write_column('A2', list(range(1, MACHINE_NUM + 1)))
    worksheet.write_row('B1', ["the" + str(i) + "lock up" for i in range(max(MACHINE_LOOP))])
    for k in MACHINES:
        for i in range(MACHINE_LOOP[k]):
            worksheet.write(k+1, i+1, result_list_time[k][i])
    workbook.close()


def print_order(result_list_order):
    global MACHINE_LOOP
    workbook = xw.Workbook("Scheduling result order.xlsx")
    worksheet = workbook.add_worksheet("Scheduling result order")
    worksheet.activate()
    worksheet.write_column('A2', list(range(1, MACHINE_NUM + 1)))
    worksheet.write_row('B1', ["the" + str(i) + "lock up" for i in range(max(MACHINE_LOOP))])
    for k in MACHINES:
        for i in range(MACHINE_LOOP[k]):
            worksheet.write(k+1, i+1, result_list_order[k][i])
    workbook.close()


def print_batch(result_list_batch):
    global MACHINE_LOOP
    workbook = xw.Workbook("Scheduled result batches.xlsx")
    worksheet = workbook.add_worksheet("Scheduled result batches")
    worksheet.activate()
    worksheet.write_column('A2', list(range(1, MACHINE_NUM + 1)))
    worksheet.write_row('B1', ["the" + str(i) + "lock up" for i in range(max(MACHINE_LOOP))])
    for k in MACHINES:
        for i in range(MACHINE_LOOP[k]):
            worksheet.write(k+1, i+1, result_list_batch[k][i] + 1)
    workbook.close()


def print_result(result_list_time, result_list_order, result_list_batch):
    print_time(result_list_time)
    print_order(result_list_order)
    print_batch(result_list_batch)


if __name__ == '__main__':
    solver = ConcreteModel()
    opt = SolverFactory('cbc')
    result_list_time = [[0 for i in range(MAX_LOOP * BATCH_NUM)] for k in MACHINES]
    result_list_order = [[0 for i in range(MAX_LOOP * BATCH_NUM)] for k in MACHINES]
    result_list_batch = [[0 for i in range(MAX_LOOP * BATCH_NUM)] for k in MACHINES]
    for batch in range(BATCH_NUM):
        NOW_BATCH = batch
        solver.clear()
        add_var(solver)
        solver.prod_cons = Constraint(MACHINES, LOOPS, PRODUCTS, rule=product_constraint)
        solver.colsum_cons = Constraint(MACHINES, LOOPS, rule=colsum_constraint)
        solver.stop_cons = Constraint(MACHINES, LOOPS, rule=stop_constraint)
        solver.order_cons = Constraint(MACHINES, LOOPS, PRODUCTS, rule=order_constraint)
        solver.demand_cons = Constraint(PRODUCTS, rule=demand_constraint)
        solver.obj_cons = Constraint(MACHINES, rule=objective_constraint)
        add_objective(solver)
        opt.solve(solver, tee=True, timelimit=TIME_LIMIT)
        handle_data(solver, result_list_time, result_list_order, result_list_batch, batch)
    print_result(result_list_time, result_list_order, result_list_batch)



