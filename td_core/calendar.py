"""沪深交易日。

2026 年按国务院放假安排中的工作日休市；周末调休上班日不开市。
2027 年节假日是暂行估计，交易所公布后应改这张表。
"""

from __future__ import annotations

from datetime import date, timedelta

# 只列工作日休市。周末本身就不是交易日。
_CLOSED_2026 = {
    date(2026, 1, 1),
    date(2026, 1, 2),
    date(2026, 2, 16),
    date(2026, 2, 17),
    date(2026, 2, 18),
    date(2026, 2, 19),
    date(2026, 2, 20),
    date(2026, 2, 23),
    date(2026, 4, 6),
    date(2026, 5, 1),
    date(2026, 5, 4),
    date(2026, 5, 5),
    date(2026, 6, 19),
    date(2026, 9, 25),
    date(2026, 10, 1),
    date(2026, 10, 2),
    date(2026, 10, 5),
    date(2026, 10, 6),
    date(2026, 10, 7),
}

# 暂行：元旦、估计的春节工作日、清明、劳动节、端午、中秋、国庆。
_CLOSED_2027 = {
    date(2027, 1, 1),
    date(2027, 2, 5),
    date(2027, 2, 8),
    date(2027, 2, 9),
    date(2027, 2, 10),
    date(2027, 2, 11),
    date(2027, 2, 12),
    date(2027, 4, 5),
    date(2027, 5, 3),
    date(2027, 5, 4),
    date(2027, 5, 5),
    date(2027, 6, 9),
    date(2027, 9, 15),
    date(2027, 10, 1),
    date(2027, 10, 4),
    date(2027, 10, 5),
    date(2027, 10, 6),
    date(2027, 10, 7),
}

_CLOSED = _CLOSED_2026 | _CLOSED_2027


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in _CLOSED


def add_trading_days(start: date, n: int) -> date:
    """start 之后的第 n 个交易日，不含 start 当天。"""
    if n < 0:
        raise ValueError("交易日步长不能为负")
    day = start
    left = n
    while left > 0:
        day += timedelta(days=1)
        if is_trading_day(day):
            left -= 1
    return day


def nth_trading_day_inclusive(start: date, n: int) -> date:
    """从 start 当天起算的第 n 个交易日。start 若休市，则从之后第一个交易日开始数。"""
    if n <= 0:
        raise ValueError("交易日序号必须从 1 开始")
    day = start
    seen = 0
    while True:
        if is_trading_day(day):
            seen += 1
            if seen == n:
                return day
        day += timedelta(days=1)


def calendar_warning(days: list[date]) -> str | None:
    if any(day.year < 2026 or day.year > 2027 for day in days):
        return "交易日历只内置了 2026 年休市和 2027 年暂行估计；超出这段的冷静期只排除周末。"
    if any(day.year == 2027 for day in days):
        return "2027 年节假日是暂行估计，冷静期天数可能随交易所日历修订。"
    return None
