
from __future__ import annotations


def refine_buy_vol(stockcode: str, vol: float) -> tuple[bool, int]:
    vol = round(vol / 100) * 100
    code = stockcode[2:]
    if code[:2] == "68":
        if vol < 200:
            return False, int(vol)
        return True, int(vol)
    else:
        if vol < 100:
            return False, int(vol)
        return True, int(vol / 100) * 100


def refine_sell_vol(stockcode: str, vol: float, posi_vol: int) -> tuple[bool, bool, int]:
    vol = round(vol / 100) * 100
    if vol >= posi_vol:
        return True, True, posi_vol
    code = stockcode[2:]
    if code[:2] == "68":
        if posi_vol - vol < 200:
            return True, True, posi_vol
        if posi_vol < 200:
            return True, True, posi_vol
        if vol >= 200:
            return False, True, int(vol)
        return False, False, int(vol)
    else:
        if posi_vol - vol < 100:
            return True, True, posi_vol
        if posi_vol < 100:
            return True, True, posi_vol
        if vol >= 100:
            return False, True, int(vol / 100) * 100
        return False, False, int(vol)


def refine_short_sell_vol(stockcode: str, vol: float, avail_vol: int) -> tuple[bool, int]:
    vol = round(vol / 100) * 100
    if vol > avail_vol:
        return True, avail_vol
    code = stockcode[2:]
    if code[:2] == "68":
        if vol < 200:
            return False, int(vol)
        return True, int(vol)
    else:
        if vol < 100:
            return False, int(vol)
        return True, int(vol / 100) * 100


def refine_short_buy_vol(stockcode: str, vol: float, posi_vol: int) -> tuple[bool, bool, int]:
    vol = round(vol / 100) * 100
    code = stockcode[2:]
    if vol > posi_vol:
        return True, True, posi_vol
    if code[:2] == "68":
        if vol < 200:
            return False, False, int(vol)
        if posi_vol - vol < 200:
            return True, True, posi_vol
        return False, True, int(vol)
    else:
        if vol < 100:
            return False, False, int(vol)
        if posi_vol - vol < 100:
            return True, True, posi_vol
        return False, True, int(vol / 100) * 100
