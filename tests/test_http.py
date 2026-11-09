from __future__ import annotations

import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

from fakes import FakeOpener, RecordingSleep
from scout_lib.http import Fetcher, FetchError


def make(responses):
    opener, sleep = FakeOpener(responses), RecordingSleep()
    return Fetcher(opener=opener, sleep=sleep), opener, sleep


def test_fetcher_sends_user_agent_and_params():
    fetcher, opener, _ = make(['{"ok": true}'])
    assert fetcher.json("https://api.example.test/x", {"a": "1", "b": "two"}) == {"ok": True}
    request = opener.requests[0]
    assert request.get_header("User-agent") == "luma-event-scout/0.1"
    assert parse_qs(urlparse(request.full_url).query) == {"a": ["1"], "b": ["two"]}


def test_fetcher_retries_5xx_then_succeeds():
    fetcher, opener, sleep = make([503, 502, "fine"])
    assert fetcher.text("https://api.example.test/x") == "fine"
    assert len(opener.requests) == 3
    assert sleep.calls == [1, 2]


def test_fetcher_retries_429_and_url_errors():
    fetcher, _, sleep = make([429, urllib.error.URLError("down"), "ok"])
    assert fetcher.text("https://api.example.test/x") == "ok"
    assert sleep.calls == [1, 2]


def test_fetcher_retries_incomplete_read():
    import http.client

    fetcher, _, sleep = make([http.client.IncompleteRead(b"partial"), "ok"])
    assert fetcher.text("https://api.example.test/x") == "ok"
    assert sleep.calls == [1]


def test_fetcher_raises_on_404_without_retry():
    fetcher, opener, sleep = make([404])
    with pytest.raises(FetchError, match="404"):
        fetcher.text("https://api.example.test/missing")
    assert len(opener.requests) == 1
    assert sleep.calls == []


def test_fetcher_gives_up_after_retries():
    fetcher, opener, _ = make([500, 500, 500])
    with pytest.raises(FetchError, match="500"):
        fetcher.text("https://api.example.test/x")
    assert len(opener.requests) == 3


def test_fetcher_delays_between_requests():
    fetcher, _, sleep = make(["one", "two"])
    fetcher.text("https://api.example.test/1")
    assert sleep.calls == []
    fetcher.text("https://api.example.test/2")
    assert sleep.calls == [0.5]


def test_fetcher_json_rejects_invalid_json():
    fetcher, _, _ = make(["<html>"])
    with pytest.raises(FetchError, match="JSON"):
        fetcher.json("https://api.example.test/x")
