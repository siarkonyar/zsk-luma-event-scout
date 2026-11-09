"""Combine discovery and feed events: dedupe, drop what the user is in, flag clashes, sort."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from .constants import DEFAULT_EVENT_DURATION, REGISTERED_STATUSES
from .window import parse_iso

_SOURCE_PRIORITY = ("host:", "calendar:", "discovery:")
_FILLABLE = ("registered", "sold_out", "online", "end_at")


def _priority(source: str) -> int:
    for rank, prefix in enumerate(_SOURCE_PRIORITY):
        if source.startswith(prefix):
            return rank
    return len(_SOURCE_PRIORITY)


def _interval(start_at: str, end_at: Optional[str]) -> Tuple[datetime, datetime]:
    start = parse_iso(start_at)
    end = parse_iso(end_at) if end_at else start + DEFAULT_EVENT_DURATION
    return start, end if end > start else start + DEFAULT_EVENT_DURATION


def find_clashes(candidate: dict, registered: list) -> list:
    c_start, c_end = _interval(candidate["start_at"], candidate.get("end_at"))
    clashes = []
    for other in registered:
        if other.get("approval_status") not in REGISTERED_STATUSES:
            continue
        if other.get("api_id") == candidate["api_id"]:
            continue
        r_start, r_end = _interval(other["start_at"], other.get("end_at"))
        if c_start < r_end and r_start < c_end:
            clashes.append({"api_id": other["api_id"], "name": other.get("name") or ""})
    return clashes


def _combine(existing: dict, incoming: dict) -> dict:
    better_incoming = _priority(incoming["source"]) < _priority(existing["source"])
    best, other = (incoming, existing) if better_incoming else (existing, incoming)
    merged = dict(best)
    for key in _FILLABLE:
        if merged.get(key) is None and other.get(key) is not None:
            merged[key] = other[key]
    return merged


def _dedupe(records: list) -> Tuple[dict, int]:
    by_id: dict = {}
    duplicates = 0
    for record in records:
        key = record["api_id"]
        if key in by_id:
            duplicates += 1
            by_id[key] = _combine(by_id[key], record)
        else:
            by_id[key] = dict(record)
    return by_id, duplicates


def _failures(discovery: list, feeds: dict) -> list:
    messages = [f"{f['source']}: {f['error']}" for f in feeds.get("failures", [])]
    for result in discovery:
        messages.extend(f"discovery:{result['keyword']} {day}" for day in result.get("failed_days", []))
    return messages


def merge_candidates(discovery: list, feeds: dict, registered: list) -> dict:
    records = [*feeds.get("events", []), *(e for d in discovery for e in d.get("events", []))]
    by_id, duplicates = _dedupe(records)
    statuses = {r["api_id"]: r.get("approval_status") for r in registered}
    candidates, dropped = [], 0
    for record in by_id.values():
        status = record.get("registered") or statuses.get(record["api_id"])
        if status in REGISTERED_STATUSES:
            dropped += 1
            continue
        candidates.append({**record, "registered": status, "clash_with": find_clashes(record, registered)})
    candidates.sort(key=lambda c: (parse_iso(c["start_at"]), c["name"]))
    return {
        "candidates": candidates,
        "counts": {"candidates": len(candidates), "dropped_registered": dropped, "duplicates": duplicates},
        "failures": _failures(discovery, feeds),
    }
