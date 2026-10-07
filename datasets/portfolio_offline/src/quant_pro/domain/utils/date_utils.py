
from __future__ import annotations

from datetime import datetime

from quant_pro.domain.ports.calendar import TradingCalendarPort



def format_date(date: str | object) -> str:
    date_str = str(date)
    if "-" not in date_str:
        raise ValueError("日期格式不正确")
    try:
        datetime_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return datetime_obj.strftime("%Y-%m-%d")
    except ValueError:
        pass
    try:
        datetime_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return datetime_obj.strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError("日期格式不正确") from None




def get_next_trade_day(
    date: str,
    calendar: TradingCalendarPort,
    n: int = 1,
) -> str:
    if n == 0:
        return date
    return calendar.next_trade_day(date, n)


def get_previous_trade_day(
    date: str,
    calendar: TradingCalendarPort,
    n: int = 1,
) -> str:
    if n == 0:
        return date
    return calendar.previous_trade_day(date, n)


def get_next_trade_days(
    date: str,
    n: int,
    calendar: TradingCalendarPort,
) -> str:
    return get_next_trade_day(date, calendar, n)


def get_previous_trade_days(
    date: str,
    n: int,
    calendar: TradingCalendarPort,
) -> str:
    return get_previous_trade_day(date, calendar, n)
