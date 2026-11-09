from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from fakes import RecordingSleep, RoutingOpener, fixture_text
from scout_lib import state as st
from scout_lib.feeds import COMPACT_KEYS, collect_feeds, compact_record, keep_event
from scout_lib.http import Fetcher
from scout_lib.window import day_windows, span

ICS_PREFIX = "https://api.lu.ma/ics/get"
HOST_EVENTS_PREFIX = "https://api.luma.com/user/profile/events-hosting"


@pytest.fixture
def windows():
    return day_windows(date(2026, 11, 9), 14, "Europe/London")


@pytest.fixture
def followed(location, keywords, calendar, host):
    return st.with_host(st.with_calendar(st.new_state(location, keywords), calendar), host)


def host_pages(request):
    query = parse_qs(urlparse(request.full_url).query)
    name = "host_events_page2.json" if "pagination_cursor" in query else "host_events_page1.json"
    return json.loads(fixture_text(name))


def fetcher_with(ics_response):
    opener = RoutingOpener({ICS_PREFIX: ics_response, HOST_EVENTS_PREFIX: host_pages})
    return Fetcher(opener=opener, sleep=RecordingSleep())


def event(**overrides):
    base = {
        "api_id": "evt-1", "name": "E", "start_at": "2026-11-12T18:00:00Z", "end_at": None,
        "url": "https://luma.com/x", "calendar": "C", "lat": None, "lng": None,
        "city": None, "location": None, "online": None, "sold_out": None,
    }
    return {**base, **overrides}


@pytest.mark.parametrize(
    "overrides, kept",
    [
        ({"online": True, "lat": 40.0, "lng": 10.0}, True),
        ({"lat": 40.0, "lng": 10.0}, False),
        ({"lat": 51.5, "lng": -0.1}, True),
        ({"city": "  testville "}, True),
        ({"city": "Elsewhere"}, False),
        ({"location": "Hall, 1 Road, Testville"}, True),
        ({"location": "Hall, 1 Road, Elsewhere"}, False),
        ({"location": "https://luma.com/event/evt-1"}, True),
        ({}, True),
        ({"start_at": "2026-11-23T00:00:00Z"}, False),
        ({"start_at": "2026-11-08T23:00:00Z", "online": True}, False),
    ],
)
def test_keep_event_rules(overrides, kept, windows, location):
    assert keep_event(event(**overrides), span(windows), location) is kept


def test_compact_record_has_exact_keys():
    record = compact_record(event(), "host:h")
    assert tuple(record) == COMPACT_KEYS
    assert record["source"] == "host:h"
    assert record["registered"] is None and record["clash_with"] == []


def test_collect_feeds_combines_calendar_and_host_events(followed, windows):
    result = collect_feeds(followed, windows, fetcher_with(fixture_text("calendar.ics")))
    by_id = {e["api_id"]: e for e in result["events"]}
    assert set(by_id) == {"evt-A1", "evt-B2", "evt-C3", "evt-D4", "evt-H1", "evt-H2", "evt-H3"}
    assert by_id["evt-A1"]["source"] == "calendar:test-cal"
    assert by_id["evt-A1"]["calendar"] == "Test Calendar"
    assert by_id["evt-A1"]["url"] == "https://luma.com/event/evt-A1"
    assert by_id["evt-B2"]["url"] == "https://luma.com/event/evt-B2"
    assert by_id["evt-H1"]["source"] == "host:test_hosts"
    assert by_id["evt-H1"]["sold_out"] is True
    assert by_id["evt-H2"]["online"] is True
    assert all(tuple(e) == COMPACT_KEYS for e in result["events"])
    assert result["failures"] == []


def test_collect_feeds_counts_external_listings(followed, windows):
    result = collect_feeds(followed, windows, fetcher_with(fixture_text("calendar.ics")))
    assert result["skipped_external"] == 1


def test_collect_feeds_records_failure_and_continues(followed, windows):
    result = collect_feeds(followed, windows, fetcher_with(404))
    assert [f["source"] for f in result["failures"]] == ["calendar:test-cal"]
    assert "404" in result["failures"][0]["error"]
    assert {e["api_id"] for e in result["events"]} == {"evt-H1", "evt-H2", "evt-H3"}


def test_collect_feeds_rejects_html_as_failure(followed, windows):
    result = collect_feeds(followed, windows, fetcher_with("<html>Not found</html>"))
    assert result["failures"] == [{"source": "calendar:test-cal", "error": "not an iCal feed"}]


def test_collect_feeds_records_host_failure(location, keywords, host, windows):
    state = st.with_host(st.new_state(location, keywords), host)
    opener = RoutingOpener({HOST_EVENTS_PREFIX: 500})
    result = collect_feeds(state, windows, Fetcher(opener=opener, sleep=RecordingSleep()))
    assert [f["source"] for f in result["failures"]] == ["host:test_hosts"]
    assert result["events"] == []


def test_collect_feeds_survives_malformed_host_entries(location, keywords, host, windows):
    state = st.with_host(st.new_state(location, keywords), host)
    good = json.loads(fixture_text("host_events_page1.json"))["entries"][1]
    weird = {"api_id": "evt-W", "event": {"api_id": "evt-W", "name": "W",
             "start_at": "2026-11-12T18:00:00Z", "coordinate": [1, 2],
             "geo_address_info": "Somewhere", "location_type": "zoom"}, "calendar": "Cal"}
    page = {"entries": [{"api_id": "evt-S", "event": "oops"}, weird, "junk", good], "has_more": False}
    opener = RoutingOpener({HOST_EVENTS_PREFIX: page})
    result = collect_feeds(state, windows, Fetcher(opener=opener, sleep=RecordingSleep()))
    assert {e["api_id"] for e in result["events"]} == {"evt-W", "evt-H2"}
    assert result["failures"] == []


def test_collect_feeds_records_unexpected_errors_per_source(followed, windows):
    def explode(request):
        raise RuntimeError("surprise")

    opener = RoutingOpener({ICS_PREFIX: fixture_text("calendar.ics"), HOST_EVENTS_PREFIX: explode})
    result = collect_feeds(followed, windows, Fetcher(opener=opener, sleep=RecordingSleep()))
    assert result["failures"] == [{"source": "host:test_hosts", "error": "RuntimeError: surprise"}]
    assert {e["source"] for e in result["events"]} == {"calendar:test-cal"}


def test_collect_feeds_skips_host_entry_without_start(location, keywords, host, windows):
    state = st.with_host(st.new_state(location, keywords), host)
    broken = {"entries": [{"api_id": "evt-bad", "event": {"api_id": "evt-bad"}}], "has_more": False}
    opener = RoutingOpener({HOST_EVENTS_PREFIX: broken})
    result = collect_feeds(state, windows, Fetcher(opener=opener, sleep=RecordingSleep()))
    assert result["events"] == [] and result["failures"] == []
