from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from scout_lib import window as w


def test_parse_iso_variants():
    a = w.parse_iso("2026-11-12T18:00:00.000Z")
    b = w.parse_iso("2026-11-12T18:00:00Z")
    c = w.parse_iso("2026-11-12T19:00:00+01:00")
    assert a == b == c
    assert a.tzinfo is not None
    with pytest.raises(ValueError):
        w.parse_iso("nope")


def test_to_iso_z():
    dt = datetime(2026, 11, 12, 19, 0, tzinfo=timezone(timedelta(hours=1)))
    assert w.to_iso_z(dt) == "2026-11-12T18:00:00Z"


def test_day_windows_count_and_order():
    wins = w.day_windows(date(2026, 11, 9), 14, "Europe/London")
    assert len(wins) == 14
    assert [x["date"] for x in wins] == [
        (date(2026, 11, 9) + timedelta(days=i)).isoformat() for i in range(14)
    ]
    for prev, nxt in zip(wins, wins[1:]):
        assert prev["before"] == nxt["after"]


def test_day_windows_london_winter():
    first = w.day_windows(date(2026, 11, 9), 14, "Europe/London")[0]
    assert first == {
        "date": "2026-11-09",
        "after": "2026-11-09T00:00:00Z",
        "before": "2026-11-10T00:00:00Z",
    }


def test_day_windows_across_dst_end():
    wins = w.day_windows(date(2026, 10, 24), 3, "Europe/London")
    oct25 = wins[1]
    assert oct25["date"] == "2026-10-25"
    assert oct25["after"] == "2026-10-24T23:00:00Z"
    assert oct25["before"] == "2026-10-26T00:00:00Z"
    length = w.parse_iso(oct25["before"]) - w.parse_iso(oct25["after"])
    assert length == timedelta(hours=25)


def test_local_today_uses_city_timezone():
    now = datetime(2026, 11, 9, 23, 30, tzinfo=timezone.utc)
    assert w.local_today(now, "Asia/Tokyo") == date(2026, 11, 10)
    assert w.local_today(now, "Europe/London") == date(2026, 11, 9)


def test_span_and_in_span_edges():
    wins = w.day_windows(date(2026, 11, 9), 2, "Europe/London")
    bounds = w.span(wins)
    assert w.in_span("2026-11-09T00:00:00Z", bounds)
    assert w.in_span("2026-11-10T23:59:59Z", bounds)
    assert not w.in_span("2026-11-11T00:00:00Z", bounds)
    assert not w.in_span("2026-11-08T23:59:59Z", bounds)


def test_local_day_time_in_city_timezone():
    assert w.local_day_time("2026-11-11T18:00:00Z", "Europe/London") == ("Wed 11 Nov", "18:00")
    assert w.local_day_time("2026-11-11T18:00:00Z", "Europe/Berlin") == ("Wed 11 Nov", "19:00")
    assert w.local_day_time("2026-11-11T23:30:00Z", "Asia/Tokyo") == ("Thu 12 Nov", "08:30")
    assert w.local_day_time("2026-07-01T17:00:00Z", "Europe/London") == ("Wed 1 Jul", "18:00")


def test_in_bounds_inside_and_outside(location):
    box = location["bounds"]
    assert w.in_bounds(51.5, -0.1, box)
    assert not w.in_bounds(52.5, -0.1, box)
    assert not w.in_bounds(51.5, 1.0, box)
