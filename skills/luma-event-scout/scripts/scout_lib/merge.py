"""Combine discovery and feed events: dedupe, drop what the user is in, flag clashes, sort.

Inputs come from sub-agents and public endpoints, so every record is checked; malformed ones
are skipped and counted in `failures` instead of stopping the merge.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from .constants import DEFAULT_EVENT_DURATION, REGISTERED_STATUSES
from .window import local_day_time, parse_iso

_SOURCE_PRIORITY = ("host:", "calendar:", "discovery:")
_FILLABLE = ("registered", "sold_out", "online", "end_at")


def _priority(source: str) -> int:
    for rank, prefix in enumerate(_SOURCE_PRIORITY):
        if source.startswith(prefix):
            return rank
    return len(_SOURCE_PRIORITY)


def _is_time(value) -> bool:
    try:
        parse_iso(value)
    except (ValueError, TypeError):
        return False
    return True


def _interval(start_at: str, end_at: Optional[str]) -> Tuple[datetime, datetime]:
    start = parse_iso(start_at)
    end = parse_iso(end_at) if end_at else start + DEFAULT_EVENT_DURATION
    return start, end if end > start else start + DEFAULT_EVENT_DURATION


def _clean(record, default_source: Optional[str]) -> Optional[dict]:
    if not isinstance(record, dict) or not isinstance(record.get("api_id"), str) or not record["api_id"]:
        return None
    if not _is_time(record.get("start_at")):
        return None
    source = record.get("source") or default_source
    if not isinstance(source, str) or not source:
        return None
    end_at = record.get("end_at") if _is_time(record.get("end_at")) else None
    return {**record, "name": str(record.get("name") or ""), "source": source, "end_at": end_at, "clash_with": []}


def _clean_all(records, default_source: Optional[str], label: str, failures: list) -> list:
    items = records if isinstance(records, list) else []
    cleaned = [c for c in (_clean(r, default_source) for r in items) if c is not None]
    skipped = len(items) - len(cleaned)
    if skipped:
        noun = "record" if skipped == 1 else "records"
        failures.append(f"{label}: skipped {skipped} malformed {noun}")
    return cleaned


def _gather(discovery: list, feeds: dict, failures: list) -> list:
    feeds = feeds if isinstance(feeds, dict) else {}
    for item in feeds.get("failures", []) if isinstance(feeds.get("failures"), list) else []:
        if isinstance(item, dict):
            failures.append(f"{item.get('source')}: {item.get('error')}")
    records = _clean_all(feeds.get("events"), None, "feeds", failures)
    for index, result in enumerate(discovery, start=1):
        if not isinstance(result, dict) or not isinstance(result.get("events", []), list):
            failures.append(f"discovery result {index}: not a discovery result")
            continue
        keyword = result.get("keyword") or f"#{index}"
        records += _clean_all(result.get("events", []), f"discovery:{keyword}", f"discovery:{keyword}", failures)
        failed_days = result.get("failed_days") if isinstance(result.get("failed_days"), list) else []
        failures.extend(f"discovery:{keyword} {day}" for day in failed_days)
    return records


def _usable_registered(registered) -> list:
    items = registered if isinstance(registered, list) else []
    return [
        r for r in items
        if isinstance(r, dict) and isinstance(r.get("api_id"), str) and _is_time(r.get("start_at"))
    ]


def find_clashes(candidate: dict, registered: list) -> list:
    c_start, c_end = _interval(candidate["start_at"], candidate.get("end_at"))
    clashes = []
    for other in registered:
        if other.get("approval_status") not in REGISTERED_STATUSES:
            continue
        if other.get("api_id") == candidate["api_id"]:
            continue
        end_at = other.get("end_at") if _is_time(other.get("end_at")) else None
        r_start, r_end = _interval(other["start_at"], end_at)
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
            by_id[key] = record
    return by_id, duplicates


def _local_fields(record: dict, tz_name: Optional[str]) -> dict:
    if not tz_name:
        return {}
    day, clock = local_day_time(record["start_at"], tz_name)
    return {"local_day": day, "local_time": clock}


def merge_candidates(discovery: list, feeds: dict, registered: list, tz_name: Optional[str] = None) -> dict:
    """With `tz_name`, each candidate also gets `local_day` / `local_time` in that timezone."""
    failures: list = []
    by_id, duplicates = _dedupe(_gather(discovery, feeds, failures))
    usable = _usable_registered(registered)
    statuses = {r["api_id"]: r.get("approval_status") for r in usable}
    candidates, dropped = [], 0
    for record in by_id.values():
        status = record.get("registered") or statuses.get(record["api_id"])
        if status in REGISTERED_STATUSES:
            dropped += 1
            continue
        clashes = find_clashes(record, usable)
        candidates.append({**record, "registered": status, "clash_with": clashes, **_local_fields(record, tz_name)})
    candidates.sort(key=lambda c: (parse_iso(c["start_at"]), c["name"]))
    return {
        "candidates": candidates,
        "counts": {"candidates": len(candidates), "dropped_registered": dropped, "duplicates": duplicates},
        "failures": failures,
    }
