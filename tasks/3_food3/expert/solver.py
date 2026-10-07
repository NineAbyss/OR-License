
def solve(testdata):
    machine_num = testdata['machine_num']
    machine_state = testdata['machine_state']
    max_loop = testdata['max_loop']
    halide_loop = testdata['halide_loop']
    demand = testdata['demand']
    product_time = testdata['product_time']
    product_names = testdata['product_names']

    product_name = product_names[0]
    brine_name = product_names[-1]
    prod_time = product_time[0]
    brine_time = product_time[1]

    MACHINES = list(range(machine_num))
    LOOPS = list(range(max_loop))

    new_halide = [[] for _ in MACHINES]
    for k in MACHINES:
        for i in LOOPS:
            if (i + machine_state[k]) % halide_loop == 0 and i != 0:
                new_halide[k].append(i)

    result_list = [[[0, 0] for _ in LOOPS] for _ in MACHINES]

    now_batch = 0
    remain_demand = [d[0] for d in demand]
    break_flag = False

    for i in LOOPS:
        if break_flag:
            break
        for k in MACHINES:
            has_brine = 1 if i in new_halide[k] else 0
            result_list[k][i][1] = has_brine
            result_list[k][i][0] = now_batch + 1
            remain_demand[now_batch] -= 1
            if remain_demand[now_batch] == 0:
                now_batch += 1
            if now_batch >= len(demand):
                break_flag = True
                break

    machines = []
    for k in MACHINES:
        rounds_list = []
        for i in LOOPS:
            batch = result_list[k][i][0]
            has_brine = result_list[k][i][1]
            if batch == 0:
                break
            if has_brine:
                rounds_list.append({
                    "product": brine_name,
                    "batch": 0
                })
            rounds_list.append({
                "product": product_name,
                "batch": batch
            })
        machines.append({
            "machine_id": k + 1,
            "initial_state": machine_state[k],
            "rounds": rounds_list
        })

    return {"machines": machines}


