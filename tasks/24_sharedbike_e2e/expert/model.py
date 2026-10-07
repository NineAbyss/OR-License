from __future__ import annotations

def optimize_lookahead(current_stock: dict[str, float], current_period: int, pipeline: defaultdict) -> dict:
    periods = list(range(current_period, current_period + LOOKAHEAD_HOURS))
    local_periods = range(len(periods))
    move_keys = [(i, j, k) for (i, j) in routes for k in local_periods]

    model = gp.Model(f"rolling_horizon_{current_period}", env=GRB_ENV)
    model.Params.TimeLimit = TIME_LIMIT_SECONDS
    model.Params.MIPGap = MIP_GAP
    model.Params.Threads = 8
    model.Params.Seed = 0

    x = model.addVars(move_keys, vtype=VARIABLE_TYPE, lb=0, name="move")
    inventory = model.addVars(stations, range(LOOKAHEAD_HOURS + 1), lb=0, name="inventory")
    unmet = model.addVars(stations, local_periods, lb=0, name="unmet")
    overflow = model.addVars(stations, local_periods, lb=0, name="overflow")
    terminal_gap = model.addVars(stations, lb=0, name="terminal_gap")

    for station in stations:
        model.addConstr(
            inventory[station, 0] == min(max(current_stock.get(station, 0.0), 0.0), capacity[station]),
            name=f"initial_inventory_{station}",
        )
        for k in range(LOOKAHEAD_HOURS + 1):
            model.addConstr(inventory[station, k] <= capacity[station], name=f"capacity_{station}_{k}")

    for k, period in enumerate(periods):
        model.addConstr(
            gp.quicksum(x[i, j, k] for i, j in routes) <= FLEET_MOVE_LIMIT_PER_HOUR,
            name=f"fleet_limit_{k}",
        )

        for station in stations:
            outflow = gp.quicksum(x[station, j, k] for j in out_neighbors[station])
            model.addConstr(outflow <= inventory[station, k], name=f"dispatch_available_{station}_{k}")

            next_period = period + 1
            fixed_arrivals = float(pipeline.get((next_period, station), 0.0))
            decision_arrivals = gp.quicksum(
                x[j, station, s]
                for j in in_neighbors[station]
                for s in range(k + 1)
                if s + lead_time[(j, station)] == k + 1
            )

            demand = float(known_demand[(period, station)])
            returns = float(known_return[(period, station)])
            model.addConstr(unmet[station, k] <= demand, name=f"unmet_cap_{station}_{k}")
            model.addConstr(
                inventory[station, k] - outflow + fixed_arrivals + decision_arrivals + unmet[station, k] >= demand,
                name=f"service_before_returns_{station}_{k}",
            )
            model.addConstr(
                inventory[station, k + 1]
                == inventory[station, k]
                - outflow
                - demand
                + unmet[station, k]
                + returns
                + fixed_arrivals
                + decision_arrivals
                - overflow[station, k],
                name=f"inventory_balance_{station}_{k}",
            )

    terminal_period = current_period + LOOKAHEAD_HOURS
    for station in stations:
        target = float(target_inventory.get((terminal_period, station), target_inventory[(periods[-1], station)]))
        model.addConstr(terminal_gap[station] >= target - inventory[station, LOOKAHEAD_HOURS])

    move_cost = gp.quicksum(
        (DISCOUNT_FACTOR**k) * route_cost[i, j] * x[i, j, k] for i, j, k in move_keys
    )
    unmet_cost = gp.quicksum(
        (DISCOUNT_FACTOR**k) * penalty[station] * unmet[station, k]
        for station in stations
        for k in local_periods
    )
    overflow_cost = gp.quicksum(
        (DISCOUNT_FACTOR**k) * OVERFLOW_PENALTY * overflow[station, k]
        for station in stations
        for k in local_periods
    )
    terminal_cost = TERMINAL_TARGET_WEIGHT * gp.quicksum(
        penalty[station] * terminal_gap[station] for station in stations
    )
    model.setObjective(move_cost + unmet_cost + overflow_cost + terminal_cost, GRB.MINIMIZE)
    model.optimize()

    if model.SolCount == 0:
        raise RuntimeError(f"No solution found at period={current_period}; status={model.Status}")

    first_moves = []
    for i, j in routes:
        qty = float(x[i, j, 0].X)
        if qty > 1e-6:
            if VARIABLE_TYPE == GRB.INTEGER:
                qty = round(qty)
            first_moves.append(
                {
                    "from_station": i,
                    "to_station": j,
                    "bikes_moved": qty,
                    "cost_per_bike": route_cost[i, j],
                    "lead_time": lead_time[(i, j)],
                }
            )

    return {
        "objective": float(model.ObjVal),
        "status": int(model.Status),
        "gap": float(model.MIPGap) if model.IsMIP else 0.0,
        "first_moves": first_moves,
        "future_moves": [dict(offset=k, from_station=i, to_station=j, bikes_moved=int(round(x[i,j,k].X))) for i,j,k in move_keys if k > 0 and x[i,j,k].X > 1e-6],
        "first_unmet": {station: float(unmet[station, 0].X) for station in stations},
        "first_inventory_end": {station: float(inventory[station, 1].X) for station in stations},
    }
