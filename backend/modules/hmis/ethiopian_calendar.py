"""Ethiopian Calendar utilities for HMIS monthly reporting."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Tuple, Optional

ETHIOPIAN_MONTHS = [
    "Meskerem",  # 1
    "Tikimt",    # 2
    "Hidar",     # 3
    "Tahsas",    # 4
    "Tir",       # 5
    "Yekatit",   # 6
    "Megabit",   # 7
    "Miazia",    # 8
    "Ginbot",    # 9
    "Sene",      # 10
    "Hamle",     # 11
    "Nehase",    # 12
    "Pagume",    # 13
]


def ethiopian_to_gregorian(ey: int, em: int, ed: int) -> date:
    """Convert an Ethiopian calendar date to a Gregorian date."""
    epoch = date(8, 8, 27)  # 1 Meskerem 1 = 27 Aug 8 AD (proleptic Gregorian)
    days = 365 * (ey - 1) + (ey - 1) // 4 + 30 * (em - 1) + (ed - 1)
    return epoch + timedelta(days=days)


def gregorian_to_ethiopian(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    """Convert a Gregorian calendar date to Ethiopian (year, month, day)."""
    target = date(gy, gm, gd)
    # Estimate Ethiopian year
    ey = gy - 8
    # Binary/linear search near ey
    for candidate_y in [gy - 9, gy - 8, gy - 7]:
        new_year = ethiopian_to_gregorian(candidate_y, 1, 1)
        if new_year <= target:
            ey = candidate_y
    days_diff = (target - ethiopian_to_gregorian(ey, 1, 1)).days
    if days_diff < 360:
        em = (days_diff // 30) + 1
        ed = (days_diff % 30) + 1
    else:
        em = 13
        ed = days_diff - 360 + 1
    return ey, em, ed


def ethiopian_month_window(arg1: int, arg2: int) -> Tuple[str, str]:
    """Gregorian (start, end) for one Ethiopian month.

    Accepts either (month_index, eth_year) or (eth_year, month_index).
    Pagume is 5 days (6 in a leap year).
    Returns ISO date strings, end inclusive.
    """
    if arg1 > 100:
        eth_year, month_index = arg1, arg2
    else:
        month_index, eth_year = arg1, arg2

    last_day = 30
    if month_index == 13:  # Pagume
        last_day = 6 if eth_year % 4 == 0 else 5
    start = ethiopian_to_gregorian(eth_year, month_index, 1)
    end = ethiopian_to_gregorian(eth_year, month_index, last_day)
    return start.isoformat(), end.isoformat()


def current_ethiopian_year() -> int:
    today = datetime.now()
    gy = today.year
    # Ethiopian new year starts on Sep 11 (or Sep 12 in leap years)
    return gy - 7 if (today.month, today.day) >= (9, 11) else gy - 8


def get_ethiopian_years_list() -> list[str]:
    curr = current_ethiopian_year()
    return [str(y) for y in range(curr - 15, curr + 2)]


def get_calendar_info(year: Optional[int] = None, month: Optional[int] = None) -> dict:
    curr_year = year or current_ethiopian_year()
    target_month = month or 1
    windows = {}
    for idx, name in enumerate(ETHIOPIAN_MONTHS, 1):
        s, e = ethiopian_month_window(idx, curr_year)
        windows[name] = {"month_index": idx, "start": s, "end": e}

    s_target, e_target = ethiopian_month_window(target_month, curr_year)

    return {
        "year": curr_year,
        "month": target_month,
        "month_name": ETHIOPIAN_MONTHS[target_month - 1] if 1 <= target_month <= 13 else "",
        "gregorian_start": s_target,
        "gregorian_end": e_target,
        "current_year": curr_year,
        "months": ETHIOPIAN_MONTHS,
        "available_years": get_ethiopian_years_list(),
        "current_year_windows": windows,
    }
