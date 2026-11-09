"""Load, validate, update and save the scout's state file.

Every update function returns a new state dict and never mutates its input.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from .constants import GENERATED_KEYWORD_COUNT, STATE_VERSION, USER_KEYWORD_COUNT

_BOUND_KEYS = ("north", "south", "east", "west")


class StateError(Exception):
    """The state file or a requested change to it is invalid."""


def normalize_keyword(keyword: str) -> str:
    return " ".join(str(keyword).casefold().split())


def _clean_keywords(keywords: list, count: int, label: str) -> list:
    if not isinstance(keywords, list) or len(keywords) != count:
        raise StateError(f"{label}: exactly {count} keywords are required")
    cleaned = [" ".join(str(k).split()) for k in keywords]
    if any(not k for k in cleaned):
        raise StateError(f"{label}: keywords must not be empty")
    normalized = [normalize_keyword(k) for k in cleaned]
    if len(set(normalized)) != len(normalized):
        raise StateError(f"{label}: keywords must be different from each other")
    return cleaned


def _validate_location(location: dict) -> dict:
    if not isinstance(location, dict):
        raise StateError("location must be an object")
    for key in ("query", "name", "timezone"):
        if not isinstance(location.get(key), str) or not location[key].strip():
            raise StateError(f"location.{key} is required")
    bounds = location.get("bounds")
    if not isinstance(bounds, dict) or any(
        not isinstance(bounds.get(k), (int, float)) for k in _BOUND_KEYS
    ):
        raise StateError("location.bounds needs numeric north, south, east, west")
    if bounds["north"] < bounds["south"]:
        raise StateError("location.bounds: north must not be below south")
    return copy.deepcopy(location)


def new_state(location: dict, user_keywords: list) -> dict:
    return {
        "version": STATE_VERSION,
        "location": _validate_location(location),
        "user_keywords": _clean_keywords(user_keywords, USER_KEYWORD_COUNT, "user keywords"),
        "followed_calendars": [],
        "followed_hosts": [],
        "profile": None,
        "seen_event_ids": [],
    }


def with_user_keywords(state: dict, keywords: list) -> dict:
    cleaned = _clean_keywords(keywords, USER_KEYWORD_COUNT, "user keywords")
    generated = {normalize_keyword(k) for k in (state.get("profile") or {}).get("generated_keywords", [])}
    clashes = [k for k in cleaned if normalize_keyword(k) in generated]
    if clashes:
        raise StateError(f"user keywords repeat the generated keywords {clashes}; regenerate the profile")
    return {**state, "user_keywords": cleaned}


def with_location(state: dict, location: dict) -> dict:
    return {**state, "location": _validate_location(location)}


def load_state(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StateError(f"cannot read state file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise StateError(f"state file {path} is not a JSON object")
    if data.get("version") != STATE_VERSION:
        raise StateError(
            f"state file {path} has version {data.get('version')!r}; expected {STATE_VERSION}"
        )
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=".state-", suffix=".tmp", delete=False, encoding="utf-8"
    )
    try:
        with handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(handle.name, 0o600)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def _upsert(items: list, new_item: dict, key: str) -> list:
    replaced = [copy.deepcopy(new_item) if i.get(key) == new_item[key] else i for i in items]
    if any(i.get(key) == new_item[key] for i in items):
        return replaced
    return [*items, copy.deepcopy(new_item)]


def _remove(items: list, key: str, value: str, label: str) -> list:
    kept = [i for i in items if i.get(key) != value]
    if len(kept) == len(items):
        raise StateError(f"no followed {label} {value!r}")
    return kept


def with_calendar(state: dict, calendar: dict) -> dict:
    for key in ("url", "cal_id", "name", "slug", "ics"):
        if not calendar.get(key):
            raise StateError(f"calendar.{key} is required")
    return {**state, "followed_calendars": _upsert(state["followed_calendars"], calendar, "cal_id")}


def without_calendar(state: dict, slug: str) -> dict:
    kept = _remove(state["followed_calendars"], "slug", slug, "calendar")
    return {**state, "followed_calendars": kept}


def with_host(state: dict, host: dict) -> dict:
    for key in ("url", "username", "user_id"):
        if not host.get(key):
            raise StateError(f"host.{key} is required")
    return {**state, "followed_hosts": _upsert(state["followed_hosts"], host, "user_id")}


def without_host(state: dict, username: str) -> dict:
    kept = _remove(state["followed_hosts"], "username", username, "host")
    return {**state, "followed_hosts": kept}


def _dedupe(ids: list) -> list:
    return list(dict.fromkeys(ids))


def new_event_ids(state: dict, ids: list) -> list:
    seen = set(state["seen_event_ids"])
    return [i for i in _dedupe(ids) if i not in seen]


def _validate_interests(interests: list) -> None:
    if not isinstance(interests, list):
        raise StateError("profile.interests must be a list")
    for item in interests:
        weight = item.get("weight") if isinstance(item, dict) else None
        if not isinstance(item, dict) or not str(item.get("tag", "")).strip():
            raise StateError("every interest needs a tag")
        if not isinstance(weight, (int, float)) or not 0 <= weight <= 1:
            raise StateError(f"interest {item.get('tag')!r}: weight must be between 0 and 1")
        count = item.get("evidence_count", 0)
        if not isinstance(count, int) or count < 0:
            raise StateError(f"interest {item.get('tag')!r}: evidence_count must be >= 0")


def _check_generated(state: dict, keywords: list) -> list:
    generated = _clean_keywords(keywords, GENERATED_KEYWORD_COUNT, "generated keywords")
    user = {normalize_keyword(k) for k in state["user_keywords"]}
    clashes = [k for k in generated if normalize_keyword(k) in user]
    if clashes:
        raise StateError(f"generated keywords repeat the user's keywords: {clashes}")
    return generated


def _validate_profile(state: dict, profile: dict) -> dict:
    """Return a profile with only the known fields, so nothing else reaches the state file."""
    if not isinstance(profile, dict) or not str(profile.get("summary", "")).strip():
        raise StateError("profile.summary is required")
    _validate_interests(profile.get("interests"))
    built = profile.get("built_from_events", 0)
    if not isinstance(built, int) or isinstance(built, bool) or built < 0:
        raise StateError("profile.built_from_events must be a whole number >= 0")
    interests = [
        {"tag": str(i["tag"]).strip(), "weight": i["weight"], "evidence_count": i.get("evidence_count", 0)}
        for i in profile["interests"]
    ]
    return {
        "summary": str(profile["summary"]).strip(),
        "interests": interests,
        "generated_keywords": _check_generated(state, profile.get("generated_keywords")),
        "built_from_events": built,
    }


def with_generated_keywords(state: dict, keywords: list) -> dict:
    profile = state.get("profile")
    if not profile:
        raise StateError("there is no profile yet; build one before changing generated keywords")
    return {**state, "profile": {**profile, "generated_keywords": _check_generated(state, keywords)}}


def with_profile(state: dict, profile: dict, seen_ids: list, now_iso: str) -> dict:
    validated = _validate_profile(state, profile)
    return {
        **state,
        "profile": {**validated, "last_profiled_at": now_iso},
        "seen_event_ids": _dedupe([*state["seen_event_ids"], *seen_ids]),
    }


def all_keywords(state: dict) -> list:
    generated = (state.get("profile") or {}).get("generated_keywords", [])
    return [*state["user_keywords"], *generated]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def summary_line(state: dict) -> str:
    generated = len((state.get("profile") or {}).get("generated_keywords", []))
    parts = [
        state["location"]["name"],
        f"{len(state['user_keywords'])} keywords + {generated} generated",
        _plural(len(state["followed_calendars"]), "calendar"),
        _plural(len(state["followed_hosts"]), "host"),
    ]
    return " · ".join(parts) + '. Say "change" to edit.'
