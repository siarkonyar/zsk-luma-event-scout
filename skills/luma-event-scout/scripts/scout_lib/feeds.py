"""Collect upcoming events from followed calendars (iCal) and hosts, filtered to the city and window."""
from __future__ import annotations

from .hosts import fetch_hosted_events, host_entry_to_event
from .http import Fetcher, FetchError
from .ics import parse_ics
from .window import Span, in_bounds, in_span, span

COMPACT_KEYS = (
    "api_id", "name", "start_at", "end_at", "url", "calendar",
    "source", "online", "sold_out", "registered", "clash_with",
)
_LUMA_LINK = "https://luma.com/"


def _norm(text: str) -> str:
    return " ".join(str(text).casefold().split())


def compact_record(event: dict, source: str) -> dict:
    return {
        "api_id": event["api_id"],
        "name": event["name"],
        "start_at": event["start_at"],
        "end_at": event["end_at"],
        "url": event["url"],
        "calendar": event["calendar"],
        "source": source,
        "online": event["online"],
        "sold_out": event["sold_out"],
        "registered": None,
        "clash_with": [],
    }


def _in_place(event: dict, location: dict) -> bool:
    if event.get("online") is True:
        return True
    if event.get("lat") is not None and event.get("lng") is not None:
        return in_bounds(event["lat"], event["lng"], location["bounds"])
    if event.get("city"):
        return _norm(event["city"]) == _norm(location["name"])
    text = event.get("location")
    if text:
        return text.startswith("http") or _norm(location["name"]) in _norm(text)
    return True


def keep_event(event: dict, bounds: Span, location: dict) -> bool:
    return in_span(event["start_at"], bounds) and _in_place(event, location)


def _from_ics(raw: dict, calendar: dict) -> dict:
    location = raw["location"]
    url = location if location and location.startswith(_LUMA_LINK) else f"{_LUMA_LINK}event/{raw['api_id']}"
    return {
        "api_id": raw["api_id"],
        "name": raw["name"],
        "start_at": raw["start_at"],
        "end_at": raw["end_at"],
        "url": url,
        "calendar": calendar["name"],
        "lat": raw["lat"],
        "lng": raw["lng"],
        "city": None,
        "location": location,
        "online": None,
        "sold_out": None,
    }


def _calendar_events(calendar: dict, fetcher: Fetcher, bounds: Span, location: dict):
    raws = parse_ics(fetcher.text(calendar["ics"]))
    source = f"calendar:{calendar['slug']}"
    external = sum(1 for raw in raws if raw["uid_kind"] != "evt")
    events = (_from_ics(raw, calendar) for raw in raws if raw["uid_kind"] == "evt")
    kept = [compact_record(e, source) for e in events if keep_event(e, bounds, location)]
    return kept, external


def _host_events(host: dict, fetcher: Fetcher, bounds: Span, location: dict) -> list:
    source = f"host:{host['username']}"
    kept = []
    for entry in fetch_hosted_events(host["user_id"], fetcher):
        try:
            event = host_entry_to_event(entry)
        except (ValueError, TypeError):
            continue  # an entry without a usable start time
        if keep_event(event, bounds, location):
            kept.append(compact_record(event, source))
    return kept


def collect_feeds(state: dict, windows: list, fetcher: Fetcher) -> dict:
    bounds, location = span(windows), state["location"]
    events, failures, external = [], [], 0
    for calendar in state["followed_calendars"]:
        try:
            kept, skipped = _calendar_events(calendar, fetcher, bounds, location)
        except (FetchError, ValueError) as exc:
            failures.append({"source": f"calendar:{calendar['slug']}", "error": str(exc)})
            continue
        events.extend(kept)
        external += skipped
    for host in state["followed_hosts"]:
        try:
            events.extend(_host_events(host, fetcher, bounds, location))
        except (FetchError, ValueError) as exc:
            failures.append({"source": f"host:{host['username']}", "error": str(exc)})
    return {"events": events, "failures": failures, "skipped_external": external}
