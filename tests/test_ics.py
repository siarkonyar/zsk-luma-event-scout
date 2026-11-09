from __future__ import annotations

from pathlib import Path

import pytest

from scout_lib.ics import parse_ics

FIXTURE = Path(__file__).parent / "fixtures" / "calendar.ics"


@pytest.fixture(params=["lf", "crlf"])
def events(request):
    text = FIXTURE.read_text(encoding="utf-8")
    if request.param == "crlf":
        text = text.replace("\n", "\r\n")
    return {e["api_id"]: e for e in parse_ics(text)}


def test_parses_five_events_with_ids(events):
    assert list(events) == ["evt-A1", "evt-B2", "evt-C3", "evt-D4", "calev-XYZ"]
    kinds = [e["uid_kind"] for e in events.values()]
    assert kinds == ["evt", "evt", "evt", "evt", "other"]


def test_utc_and_geo(events):
    a = events["evt-A1"]
    assert a["start_at"] == "2026-11-12T18:00:00Z"
    assert a["end_at"] == "2026-11-12T21:00:00Z"
    assert (a["lat"], a["lng"]) == (51.5, -0.12)
    assert a["location"] == "Test Hub, 1 Test Street, Testville"


def test_tzid_converted_to_utc(events):
    b = events["evt-B2"]
    assert b["start_at"] == "2026-11-12T18:00:00Z"
    assert b["end_at"] == "2026-11-12T20:00:00Z"
    assert b["lat"] is None and b["lng"] is None


def test_all_day_without_dtend(events):
    c = events["evt-C3"]
    assert c["start_at"] == "2026-11-13T00:00:00Z"
    assert c["end_at"] is None
    assert c["location"] is None


def test_folded_and_escaped_summary(events):
    assert events["evt-D4"]["name"] == "Builders, Founders & Friends Night"


def test_tzid_in_summer_time():
    text = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:evt-S1@events.lu.ma\n"
        "DTSTART;TZID=Europe/London:20260701T180000\nSUMMARY:Summer\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    assert parse_ics(text)[0]["start_at"] == "2026-07-01T17:00:00Z"


def test_event_without_uid_or_start_is_skipped():
    text = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:No uid\nDTSTART:20261112T180000Z\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:evt-X@events.lu.ma\nSUMMARY:No start\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    assert parse_ics(text) == []


def test_rejects_non_ical():
    with pytest.raises(ValueError):
        parse_ics("<html><body>Not found</body></html>")
