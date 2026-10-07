from __future__ import annotations

import numpy as np
import pandas as pd


def align_ei(scores, market, held=None):
    from tasks.quant_shared.snapshot_day import align_universe

    held = {str(k): float(v) for k, v in (held or {}).items() if float(v) != 0}
    scores = scores.replace([np.inf, -np.inf], np.nan).dropna()
    aligned = align_universe(scores=scores, market=market, extra_keep=set(held),
                             keep_untradable=True, include_constituents=False)
    missing = set(held) - set(aligned['asset_ids'])
    if missing:
        raise ValueError(f'held stocks missing usable market/risk data: {sorted(missing)}')
    names = aligned['asset_ids']
    aligned['has_score'] = [name in scores.index for name in names]
    aligned['previous_weight'] = [held.get(name, 0.0) for name in names]
    aligned['must_hold'] = [name in held and halted for name, halted in
                            zip(names, aligned['is_suspended'])]
    aligned['must_liquidate'] = [name in held and not halted and
        (name not in scores.index or not tradable)
        for name, halted, tradable in zip(names, aligned['is_suspended'], aligned['is_tradable'])]
    return aligned


def check_targets(frame, table, held=None):
    target = frame.assign(instrument=frame.instrument.map(str)).groupby('instrument').weight.sum()
    table = table.copy().set_index('instrument')
    table.index = table.index.map(str)
    held = {str(k): float(v) for k, v in (held or {}).items() if abs(float(v)) > 1e-12}
    if "must_hold" not in table.columns:
        suspended = table.get("is_suspended", pd.Series(False, index=table.index)).astype(bool)
        score_available = table.get(
            "score_available", table.get("score", pd.Series(index=table.index)).notna()
        ).astype(bool)
        is_st = table.get("is_st", pd.Series(False, index=table.index)).astype(bool)
        is_delisted = table.get("is_delisted", pd.Series(False, index=table.index)).astype(bool)
        tradable = ~suspended & ~is_st & ~is_delisted
        table["previous_weight"] = [held.get(name, 0.0) for name in table.index]
        table["must_hold"] = [name in held and bool(suspended.loc[name]) for name in table.index]
        table["must_liquidate"] = [
            name in held and not bool(suspended.loc[name])
            and (not bool(score_available.loc[name]) or not bool(tradable.loc[name]))
            for name in table.index
        ]
        table["is_tradable"] = tradable
    errors = []
    for name, weight in target.items():
        if name not in table.index and abs(weight) > 1e-6:
            errors.append(f'[EI_UNIVERSE] {name}: outside daily prediction/holding pool')
    for name, row in table.iterrows():
        weight = float(target.get(name, 0.0))
        if row.must_hold:
            if abs(weight - row.previous_weight) > 1e-6:
                errors.append(f'[EI_HOLD] {name}: suspended holding must stay at {row.previous_weight}')
        elif row.must_liquidate or not row.is_tradable:
            if abs(weight) > 1e-6:
                errors.append(f'[EI_EXIT] {name}: target must be zero')
    return errors
