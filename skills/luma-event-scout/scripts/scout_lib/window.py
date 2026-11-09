"""Time parsing, per-day search windows in a city's timezone, and box checks."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Tuple
from zoneinfo import ZoneInfo

Span = Tuple[datetime, datetime]

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 datetime into an aware UTC datetime. Naive values are UTC."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"not an ISO datetime: {value!r}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_today(now: datetime, tz_name: str) -> date:
    return now.astimezone(ZoneInfo(tz_name)).date()


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(0), tzinfo=tz)


def day_windows(start_day: date, days: int, tz_name: str) -> list:
    tz = ZoneInfo(tz_name)
    windows = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        windows.append(
            {
                "date": day.isoformat(),
                "after": to_iso_z(_local_midnight(day, tz)),
                "before": to_iso_z(_local_midnight(day + timedelta(days=1), tz)),
            }
        )
    return windows


def span(windows: list) -> Span:
    if not windows:
        raise ValueError("no windows")
    return parse_iso(windows[0]["after"]), parse_iso(windows[-1]["before"])


def in_span(start_at: str, bounds: Span) -> bool:
    start, end = bounds
    return start <= parse_iso(start_at) < end


def local_day_time(start_at: str, tz_name: str) -> Tuple[str, str]:
    """("Wed 11 Nov", "18:00") in the given timezone, independent of the machine's locale."""
    moment = parse_iso(start_at).astimezone(ZoneInfo(tz_name))
    day = f"{_WEEKDAYS[moment.weekday()]} {moment.day} {_MONTHS[moment.month - 1]}"
    return day, moment.strftime("%H:%M")


def in_bounds(lat: float, lng: float, box: dict) -> bool:
    return box["south"] <= lat <= box["north"] and box["west"] <= lng <= box["east"]
