"""Parse a Luma calendar's iCal feed into plain event dicts."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from .window import to_iso_z

_UNESCAPES = {"n": "\n", "N": "\n", ",": ",", ";": ";", "\\": "\\"}
_DATE_ONLY = re.compile(r"\d{8}")


def _unfold(text: str) -> list:
    lines: list = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    return re.sub(r"\\(.)", lambda m: _UNESCAPES.get(m.group(1), m.group(1)), value)


def _split_property(line: str) -> Tuple[str, dict, str]:
    head, _, value = line.partition(":")
    name, *param_parts = head.split(";")
    params = {}
    for part in param_parts:
        key, _, val = part.partition("=")
        params[key.upper()] = val.strip('"')
    return name.upper(), params, value


def _parse_datetime(value: str, params: dict) -> str:
    if params.get("VALUE") == "DATE" or _DATE_ONLY.fullmatch(value):
        day = datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
        return to_iso_z(day)
    if value.endswith("Z"):
        moment = datetime.strptime(value[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return to_iso_z(moment)
    tz = ZoneInfo(params["TZID"]) if "TZID" in params else timezone.utc
    return to_iso_z(datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz))


def _parse_geo(value: str) -> Tuple[Optional[float], Optional[float]]:
    try:
        lat, lng = (float(part) for part in value.split(";", 1))
    except ValueError:
        return None, None
    return lat, lng


def _build_event(props: dict) -> Optional[dict]:
    if "UID" not in props or "DTSTART" not in props:
        return None
    api_id = props["UID"][1].strip().split("@", 1)[0]
    try:
        start_params, start_value = props["DTSTART"]
        start_at = _parse_datetime(start_value, start_params)
        end_at = None
        if "DTEND" in props:
            end_params, end_value = props["DTEND"]
            end_at = _parse_datetime(end_value, end_params)
    except (ValueError, KeyError):
        return None
    lat, lng = _parse_geo(props["GEO"][1]) if "GEO" in props else (None, None)
    location = _unescape(props["LOCATION"][1]).strip() if "LOCATION" in props else None
    return {
        "api_id": api_id,
        "uid_kind": "evt" if api_id.startswith("evt-") else "other",
        "name": _unescape(props.get("SUMMARY", ({}, ""))[1]).strip(),
        "start_at": start_at,
        "end_at": end_at,
        "location": location or None,
        "lat": lat,
        "lng": lng,
    }


def parse_ics(text: str) -> list:
    """Return one dict per VEVENT that has a UID and a start time."""
    if "BEGIN:VCALENDAR" not in text:
        raise ValueError("not an iCal feed")
    events: list = []
    props: Optional[dict] = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            props = {}
        elif line == "END:VEVENT" and props is not None:
            event = _build_event(props)
            if event:
                events.append(event)
            props = None
        elif props is not None and ":" in line:
            name, params, value = _split_property(line)
            props.setdefault(name, (params, value))
    return events
