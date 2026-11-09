"""Follow Luma host accounts: resolve a profile link and list the events they host."""
from __future__ import annotations

import re
from typing import Optional

from .constants import (
    HOST_EVENTS_URL,
    HOST_MAX_PAGES,
    HOST_PAGE_LIMIT,
    HOST_PROFILE_URL,
    ONLINE_LOCATION_TYPES,
)
from .http import Fetcher
from .window import parse_iso, to_iso_z

_PROFILE_LINK = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:luma\.com|lu\.ma)/user/([A-Za-z0-9_.-]+)/?(?:[?#].*)?$"
)
_BARE_USERNAME = re.compile(r"^@?([A-Za-z0-9_-][A-Za-z0-9_.-]*)$")


class HostError(Exception):
    """A host link is not usable."""


def parse_username(value: str) -> str:
    text = (value or "").strip()
    match = _PROFILE_LINK.match(text)
    if match:
        return match.group(1)
    if "/" not in text and ".com" not in text and ".ma" not in text:
        bare = _BARE_USERNAME.match(text)
        if bare:
            return bare.group(1)
    raise HostError(f"not a Luma host profile link: {value!r} (expected luma.com/user/<username>)")


def resolve_host(value: str, fetcher: Fetcher, today: str) -> dict:
    username = parse_username(value)
    data = fetcher.json(HOST_PROFILE_URL, {"username": username})
    user = data.get("user")
    if not isinstance(user, dict) or not user.get("api_id"):
        raise HostError(f"no Luma user called {username!r}")
    handle = user.get("username") or username
    return {
        "url": f"https://luma.com/user/{handle}",
        "username": handle,
        "user_id": user["api_id"],
        "name": user.get("name") or handle,
        "added_at": today,
    }


def _entry_id(entry: dict) -> Optional[str]:
    return (entry.get("event") or {}).get("api_id") or entry.get("api_id")


def fetch_hosted_events(user_id: str, fetcher: Fetcher) -> list:
    """All upcoming events the host runs. Stops if a page brings nothing new."""
    params = {"user_api_id": user_id, "period": "future", "pagination_limit": str(HOST_PAGE_LIMIT)}
    entries: list = []
    seen: set = set()
    for _ in range(HOST_MAX_PAGES):
        page = fetcher.json(HOST_EVENTS_URL, params)
        fresh = [e for e in page.get("entries") or [] if isinstance(e, dict) and _entry_id(e) not in seen]
        if not fresh:
            break
        entries.extend(fresh)
        seen.update(_entry_id(e) for e in fresh)
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not cursor:
            break
        params = {**params, "pagination_cursor": cursor}
    return entries


def online_from_location_type(location_type: Optional[str]) -> Optional[bool]:
    if location_type in ONLINE_LOCATION_TYPES:
        return True
    if location_type == "offline":
        return False
    return None


def _event_url(slug: str, api_id: str) -> str:
    if not slug:
        return f"https://luma.com/event/{api_id}"
    return slug if slug.startswith("http") else f"https://luma.com/{slug}"


def _optional_time(value) -> Optional[str]:
    return to_iso_z(parse_iso(value)) if value else None


def host_entry_to_event(entry: dict) -> dict:
    event = entry.get("event") or {}
    coordinate = event.get("coordinate") or {}
    lat, lng = coordinate.get("latitude"), coordinate.get("longitude")
    has_point = isinstance(lat, (int, float)) and isinstance(lng, (int, float))
    api_id = _entry_id(entry)
    return {
        "api_id": api_id,
        "name": event.get("name") or "",
        "start_at": to_iso_z(parse_iso(event.get("start_at") or entry.get("start_at"))),
        "end_at": _optional_time(event.get("end_at")),
        "url": _event_url(event.get("url") or "", api_id),
        "calendar": (entry.get("calendar") or {}).get("name") or "",
        "lat": lat if has_point else None,
        "lng": lng if has_point else None,
        "city": (event.get("geo_address_info") or {}).get("city"),
        "location": None,
        "online": online_from_location_type(event.get("location_type")),
        "sold_out": (entry.get("ticket_info") or {}).get("is_sold_out"),
    }
