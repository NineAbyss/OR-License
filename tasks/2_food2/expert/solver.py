#!/usr/bin/env python3

import numpy as np
from pyomo.environ import *
import xlsxwriter as xw

INPUT_MAT = np.array([[1, 1, 1, 0],
                      [0, 1, 1, 0],
                      [0, 1, 1, 0],
                      [0, 0, 0, 1]])
MAX_LOOP = 20
MACHINE_NUM = 4
MACHINE_STATE = [0, 1, 2, 3]
DEMAND_NUM = [[4, 4, 4],
              [4, 4, 4],
              [4, 2, 2],
              [5, 2, 3],
              [5, 3, 2]]
PRODUCT_TIME = [50, 38, 45, 30]
TIME_LIMIT = 1800
PRODUCT_DICT = {0: "Product A", 1: "Product B", 2: "some other product", 3: "brine"}
PRIORITY = [1, 2, 3]
PRIORITY_WEIGHT = 50

INPUT_COL = len(INPUT_MAT[0, :])
INPUT_ROW = len(INPUT_MAT)
PRODUCT_NUM = len(INPUT_MAT)
LOOPS = list(range(MAX_LOOP))
MACHINES = list(range(MACHINE_NUM))
DEMANDS = list(range(len(DEMAND_NUM)))
PRODUCTS = list(range(PRODUCT_NUM))
MAX_M = 1000
INITIAL_TIME = [0 for k in MACHINES]
NOW_BATCH = 0
BATCH_NUM = len(DEMAND_NUM)
MACHINE_TIME = [0 for k in MACHINES]
MACHINE_LOOP = [0 for k in MACHINES]
INITIAL_MACHINE_STATE = MACHINE_STATE.copy()



INPUT_FIRST_COL = 0
while(INPUT_MAT[-1, INPUT_FIRST_COL] == 0):
    INPUT_FIRST_COL += 1

class PathmatNode:

    def __init__(self):
        self.enable = []
        self.disable = []
        self.standardize = []

    def add_enable(self, row, col):
        self.enable.append((row, col))

    def add_disable(self, row, col):
        self.disable.append((row, col))

    def add_standardize(self, row, col):
        self.standardize.append((row, col))



class Pathmat:

    def __init__(self, start_column, input_mat):
        self.start_column = start_column
        self.elems = [[] for i in range(PRODUCT_NUM)]
        for i in range(PRODUCT_NUM):
            self.elems[i] = [PathmatNode() for j in range(MAX_LOOP)]

        self.first_halide_column = 0
        while input_mat[-1, self.first_halide_column + self.start_column] != 1:
            self.first_halide_column += 1
        self.second_halide_column = self.first_halide_column
        while input_mat[-1, self.second_halide_column - self.first_halide_column] != 1 and self.second_halide_column < MAX_LOOP:
            self.second_halide_column += 1
        self.third_halide_column = self.second_halide_column
        if self.second_halide_column < MAX_LOOP:
            while input_mat[-1, self.third_halide_column - self.second_halide_column] != 1 and self.third_halide_column < MAX_LOOP:
                self.third_halide_column += 1

        for col in range(self.first_halide_column, MAX_LOOP):
            self.add_new_halide(col, input_mat)

    def add_new_halide(self, col, input_mat):
        for loops in range(col, min(col + INPUT_COL, MAX_LOOP)):
            for products in range(PRODUCT_NUM - 1):
                if input_mat[products, loops - col] > 0:
                    self.elems[products][loops].add_enable(PRODUCT_NUM-1, col)
                    if input_mat[products, loops - col] == 1:
                        self.elems[products][loops].add_standardize(PRODUCT_NUM - 1, col)
                elif input_mat[products, loops - col] == 0 and loops - col < INPUT_FIRST_COL:
                    self.elems[products][loops].add_disable(PRODUCT_NUM-1, col)
        for loops in range(col + 1, min(col + INPUT_COL, MAX_LOOP)):
            if input_mat[-1, loops - col] == 0:
                self.elems[-1][loops].add_disable(PRODUCT_NUM-1, col)
            elif input_mat[-1, loops - col] > 0:
                self.elems[-1][loops].add_enable(PRODUCT_NUM-1, col)
                if input_mat[-1, loops - col] == 1:
                    self.elems[-1][loops].add_standardize(PRODUCT_NUM-1, col)



pathmat_list = [Pathmat(stat, INPUT_MAT) for stat in MACHINE_STATE]

def add_var(solver):
    solver.x_kij = Var(MACHINES, LOOPS, PRODUCTS, within=Binary)
    solver.obj = Var(bounds=(0, None))


def add_enable_rule(solver, machine, i, j):
    _pathmat = pathmat_list[machine]
    enable_list = _pathmat.elems[j][i].enable
    if len(enable_list) > 0:
        return MAX_M * sum(solver.x_kij[machine, enable_elem[1], enable_elem[0]] for enable_elem in enable_list) >= \
               solver.x_kij[machine, i, j]
    else:
        if i + _pathmat.start_column >= INPUT_COL:
            return solver.x_kij[machine, i, j] <= 0
        elif INPUT_MAT[j][i + _pathmat.start_column] > 0:
            return Constraint.Skip
        else:
            return solver.x_kij[machine, i, j] <= 0


def add_enable(solver):
    solver.enable_constraint = Constraint(MACHINES, LOOPS, PRODUCTS, rule=add_enable_rule)


def add_disable_rule(solver, machine, i, j):
    _pathmat = pathmat_list[machine]
    disable_list = _pathmat.elems[j][i].disable
    if len(disable_list) > 0:
        return sum(solver.x_kij[machine, disable_elem[1], disable_elem[0]] for disable_elem in disable_list) <= (
                1 - solver.x_kij[machine, i, j]) * MAX_M
    else:
        return Constraint.Skip


def add_disable(solver):
    solver.disable_constraint = Constraint(MACHINES, LOOPS, PRODUCTS, rule=add_disable_rule)


def stop_constraint(solver, k, i):
    if i < MAX_LOOP - 1:
        return sum(solver.x_kij[k, i, j] for j in range(PRODUCT_NUM - 1)) >= sum(
            solver.x_kij[k, i + 1, j] for j in range(PRODUCT_NUM - 1))
    else:
        return Constraint.Skip


def colsum_constraint(solver, k, i):
    return sum(solver.x_kij[k, i, j] for j in range(PRODUCT_NUM - 1)) <= 1


def demand_constraint(solver, j):
    if j < PRODUCT_NUM - 1:
        now_demand_num = DEMAND_NUM[NOW_BATCH]
        return sum(sum(solver.x_kij[k, i, j] for i in LOOPS) for k in MACHINES) >= now_demand_num[j]
    else:
        return Constraint.Skip


def obj_constraint(solver, k):
    return solver.obj >= sum(sum(solver.x_kij[k, i, j] * PRODUCT_TIME[j] for i in LOOPS) for j in PRODUCTS) + INITIAL_TIME[k]


def add_objective(solver):
    solver.obj_constriant = Constraint(MACHINES, rule=obj_constraint)
    solver.value = Objective(expr=solver.obj + PRIORITY_WEIGHT*sum(sum(sum(i*solver.x_kij[k, i, j]*PRIORITY[j] for j in range(PRODUCT_NUM-1)) for i in LOOPS) for k in MACHINES),
                             sense=minimize)


def construct_model(solver):
    global pathmat_list
    pathmat_list = [Pathmat(stat, INPUT_MAT) for stat in MACHINE_STATE]
    solver.clear()
    add_var(solver)
    add_enable(solver)
    add_disable(solver)
    solver.stop_cons = Constraint(MACHINES, LOOPS, rule=stop_constraint)
    solver.colsum_cons = Constraint(MACHINES, LOOPS, rule=colsum_constraint)
    solver.demand_cons = Constraint(range(PRODUCT_NUM-1), rule=demand_constraint)
    solver.obj_cons = Constraint(MACHINES, rule=obj_constraint)
    add_objective(solver)


def handle_data(solver, result_list_time, result_list_order, result_list_batch, now_batch):
    global INITIAL_TIME
    global MACHINE_TIME
    global MACHINE_LOOP
    global MACHINE_STATE
    debug_mat = np.zeros(shape=(MACHINE_NUM, PRODUCT_NUM,  MAX_LOOP))
    for k in MACHINES:
        for i in LOOPS:
            for j in PRODUCTS:
                debug_mat[k, j, i] = solver.x_kij[k, i, j].value
    for k in MACHINES:
        read_loop = 0
        for i in LOOPS:
            if sum(solver.x_kij[k, i, j].value for j in PRODUCTS) == 0:
                MACHINE_LOOP[k] += read_loop
                MACHINE_TIME[k] += sum(sum(solver.x_kij[k, i0, j].value * PRODUCT_TIME[j] for j in PRODUCTS) for i0 in LOOPS)
                break
            if solver.x_kij[k, i, PRODUCT_NUM-1].value == 1:
                result_list_order[k][read_loop+MACHINE_LOOP[k]] = PRODUCT_DICT[PRODUCT_NUM-1]
                result_list_batch[k][read_loop+MACHINE_LOOP[k]] = -1
                result_list_time[k][read_loop+MACHINE_LOOP[k]] = result_list_time[k][read_loop+MACHINE_LOOP[k]-1] + PRODUCT_TIME[PRODUCT_NUM-1]
                read_loop += 1
            for j in range(PRODUCT_NUM-1):
                if solver.x_kij[k, i, j].value == 1:
                    result_list_order[k][read_loop+MACHINE_LOOP[k]] = PRODUCT_DICT[j]
                    result_list_batch[k][read_loop+MACHINE_LOOP[k]] = now_batch
                    result_list_time[k][read_loop+MACHINE_LOOP[k]] = result_list_time[k][read_loop+MACHINE_LOOP[k]-1] + PRODUCT_TIME[j]
                    read_loop += 1

            if MACHINE_STATE[k] == INPUT_COL - 1:
                MACHINE_STATE[k] = 1
            else:
                MACHINE_STATE[k] = (MACHINE_STATE[k] + 1) % INPUT_COL
            if solver.x_kij[k, i, PRODUCT_NUM-1].value == 1 and sum(solver.x_kij[k, i, j].value for j in range(PRODUCT_NUM-1)) == 0:
                MACHINE_STATE[k] = 0

    max_time = max(MACHINE_TIME)
    print("DEBUG: for batch %d, consuming time %d, total %d" % (now_batch, solver.obj.value, max_time))
    print("DEBUG: ", MACHINE_STATE)
    for k in MACHINES:
        INITIAL_TIME[k] = MACHINE_TIME[k] - max_time


def print_time(result_list_time):
    global MACHINE_LOOP
    workbook = xw.Workbook("Sub-scheduling result time.xlsx")
    worksheet = workbook.add_worksheet("Scheduled result batches")
    worksheet.activate()
    worksheet.write_column('A2', list(range(1, MACHINE_NUM + 1)))
    worksheet.write_row('C1', ["the" + str(i) + "lock up" for i in range(max(MACHINE_LOOP))])
    worksheet.write(0, 1, "Initial laps")
    worksheet.write_column('B2', INITIAL_MACHINE_STATE)
    for k in MACHINES:
        for i in range(MACHINE_LOOP[k]):
            worksheet.write(k+1, i+2, result_list_time[k][i])
    workbook.close()


def print_order(result_list_order):
    global MACHINE_LOOP
    workbook = xw.Workbook("Scheduling result order.xlsx")
    worksheet = workbook.add_worksheet("Scheduling result order")
    worksheet.activate()
    worksheet.write_column('A2', list(range(1, MACHINE_NUM + 1)))
    worksheet.write_row('C1', ["the" + str(i) + "lock up" for i in range(max(MACHINE_LOOP))])
    worksheet.write(0, 1, "Initial laps")
    worksheet.write_column('B2', INITIAL_MACHINE_STATE)
    for k in MACHINES:
        for i in range(MACHINE_LOOP[k]):
            worksheet.write(k+1, i+2, result_list_order[k][i])
    workbook.close()


def print_batch(result_list_batch):
    global MACHINE_LOOP
    workbook = xw.Workbook("Scheduled result batches.xlsx")
    worksheet = workbook.add_worksheet("Scheduled result batches")
    worksheet.activate()
    worksheet.write_column('A2', list(range(1, MACHINE_NUM + 1)))
    worksheet.write_row('C1', ["the" + str(i) + "lock up" for i in range(max(MACHINE_LOOP))])
    worksheet.write(0, 1, "Initial laps")
    worksheet.write_column('B2', INITIAL_MACHINE_STATE)
    for k in MACHINES:
        for i in range(MACHINE_LOOP[k]):
            worksheet.write(k+1, i+2, result_list_batch[k][i] + 1)
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
    inf_flag = False
    for batch in range(BATCH_NUM):
        NOW_BATCH = batch
        construct_model(solver)
        result = opt.solve(solver, tee=True, timelimit=TIME_LIMIT)
        if result.solver.termination_condition == TerminationCondition.infeasible or result.solver.termination_condition == TerminationCondition.intermediateNonInteger:
            inf_flag = True
            break
        handle_data(solver, result_list_time, result_list_order, result_list_batch, batch)
    if not inf_flag:
        print_result(result_list_time, result_list_order, result_list_batch)
    else:
        print("infeasible")






