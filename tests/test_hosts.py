from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from fakes import FakeOpener, RecordingSleep, fixture_text
from scout_lib.hosts import (
    HostError,
    fetch_hosted_events,
    host_entry_to_event,
    parse_username,
    resolve_host,
)
from scout_lib.http import Fetcher

PAGE1 = fixture_text("host_events_page1.json")
PAGE2 = fixture_text("host_events_page2.json")


def fetcher_for(responses):
    opener = FakeOpener(responses)
    return Fetcher(opener=opener, sleep=RecordingSleep()), opener


@pytest.mark.parametrize(
    "value",
    [
        "https://luma.com/user/ai_builders",
        "lu.ma/user/ai_builders",
        "https://www.luma.com/user/ai_builders?tab=hosting",
        "@ai_builders",
        "ai_builders",
    ],
)
def test_parse_username_forms(value):
    assert parse_username(value) == "ai_builders"


@pytest.mark.parametrize("value", ["https://luma.com/some-calendar", "https://example.com/user/x", ""])
def test_parse_username_rejects_non_profile_links(value):
    with pytest.raises(HostError):
        parse_username(value)


def test_resolve_host_returns_record():
    fetcher, opener = fetcher_for([fixture_text("host_profile.json")])
    host = resolve_host("https://luma.com/user/test_hosts", fetcher, "2026-11-09")
    assert host == {
        "url": "https://luma.com/user/test_hosts",
        "username": "test_hosts",
        "user_id": "usr-HOST1",
        "name": "Test Hosts",
        "added_at": "2026-11-09",
    }
    assert parse_qs(urlparse(opener.urls[0]).query) == {"username": ["test_hosts"]}


def test_resolve_host_missing_user_raises():
    fetcher, _ = fetcher_for([json.dumps({"user": None})])
    with pytest.raises(HostError):
        resolve_host("nobody_here", fetcher, "2026-11-09")


def test_fetch_hosted_events_pages_with_cursor():
    fetcher, opener = fetcher_for([PAGE1, PAGE2])
    entries = fetch_hosted_events("usr-HOST1", fetcher)
    assert [e["api_id"] for e in entries] == ["evt-H1", "evt-H2", "evt-H3"]
    first = parse_qs(urlparse(opener.urls[0]).query)
    second = parse_qs(urlparse(opener.urls[1]).query)
    assert first == {"user_api_id": ["usr-HOST1"], "period": ["future"], "pagination_limit": ["50"]}
    assert second["pagination_cursor"] == ["c2"]
    assert second["period"] == ["future"] and second["pagination_limit"] == ["50"]


def test_fetch_hosted_events_stops_when_page_repeats():
    fetcher, opener = fetcher_for([PAGE1, PAGE1])
    entries = fetch_hosted_events("usr-HOST1", fetcher)
    assert [e["api_id"] for e in entries] == ["evt-H1", "evt-H2"]
    assert len(opener.requests) == 2


def test_host_entry_to_event():
    entries = json.loads(PAGE1)["entries"] + json.loads(PAGE2)["entries"]
    offline, zoom, unknown = (host_entry_to_event(e) for e in entries)
    assert offline == {
        "api_id": "evt-H1",
        "name": "Host Meetup Testville",
        "start_at": "2026-11-12T18:00:00Z",
        "end_at": "2026-11-12T21:00:00Z",
        "url": "https://luma.com/abcd1234",
        "calendar": "Test Hosts Calendar",
        "lat": 51.52,
        "lng": -0.08,
        "city": "Testville",
        "location": None,
        "online": False,
        "sold_out": True,
    }
    assert zoom["online"] is True and zoom["lat"] is None
    assert unknown["online"] is None and unknown["city"] is None
    assert unknown["end_at"] is None
