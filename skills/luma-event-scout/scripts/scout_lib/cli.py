"""Command-line interface for the luma-event-scout skill. Results go to stdout as JSON."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import state as st
from .constants import (
    EXIT_ERROR,
    EXIT_NO_STATE,
    EXIT_OK,
    EXIT_USAGE,
    ICS_URL,
    REFRESH_THRESHOLD,
    RUN_DIR,
    STATE_PATH,
    WINDOW_DAYS,
)
from .feeds import collect_feeds
from .hosts import HostError, resolve_host
from .http import Fetcher, FetchError
from .merge import merge_candidates
from .window import day_windows, local_today, parse_iso, to_iso_z

_BOUNDS_META = ("NORTH", "SOUTH", "EAST", "WEST")


class NoState(Exception):
    """There is no state file yet."""


class Context:
    def __init__(self, args, fetcher: Fetcher, now: datetime):
        self.args, self.fetcher, self.now = args, fetcher, now

    def load(self) -> dict:
        state = st.load_state(self.args.state)
        if state is None:
            raise NoState()
        return state

    def save(self, state: dict) -> None:
        st.save_state(self.args.state, state)

    def today(self, tz_name: str) -> str:
        return local_today(self.now, tz_name).isoformat()


def _emit(payload) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return EXIT_OK


def _read_json(path: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def _write_json(path: str, payload) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _events_of(data) -> list:
    if isinstance(data, dict):
        events = data.get("events", [])
        return events if isinstance(events, list) else []
    return data if isinstance(data, list) else []


def _read_optional(path: str, label: str, failures: list):
    """Read a run file written by a sub-agent; a missing or broken one becomes a named failure."""
    try:
        return _read_json(path)
    except FileNotFoundError:
        failures.append(f"{label}: missing")
    except (OSError, ValueError) as exc:
        failures.append(f"{label}: {exc}")
    return None


def _check_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone {name!r}") from exc
    return name


def _bounds(values: list) -> dict:
    return dict(zip(("north", "south", "east", "west"), values))


def _location(args) -> dict:
    return {
        "query": args.location_query,
        "name": args.location_name,
        "timezone": _check_timezone(args.timezone),
        "bounds": _bounds(args.bounds),
    }


def _show_payload(state: dict) -> dict:
    profile = state.get("profile") or {}
    return {
        "summary": st.summary_line(state),
        "location": state["location"],
        "user_keywords": state["user_keywords"],
        "generated_keywords": profile.get("generated_keywords", []),
        "keywords": st.all_keywords(state),
        "calendars": state["followed_calendars"],
        "hosts": state["followed_hosts"],
        "has_profile": bool(state.get("profile")),
        "last_profiled_at": profile.get("last_profiled_at"),
        "profile": state.get("profile"),
    }


def _save_and_show(ctx: Context, state: dict) -> int:
    ctx.save(state)
    return _emit(_show_payload(state))


def cmd_show(ctx: Context) -> int:
    return _emit(_show_payload(ctx.load()))


def cmd_init(ctx: Context) -> int:
    if ctx.args.state.exists() and not ctx.args.force:
        raise st.StateError(f"state already exists at {ctx.args.state}; use --force to replace it")
    return _save_and_show(ctx, st.new_state(_location(ctx.args), ctx.args.keywords))


def cmd_set_keywords(ctx: Context) -> int:
    return _save_and_show(ctx, st.with_user_keywords(ctx.load(), ctx.args.keywords))


def cmd_set_generated(ctx: Context) -> int:
    return _save_and_show(ctx, st.with_generated_keywords(ctx.load(), ctx.args.keywords))


def cmd_set_location(ctx: Context) -> int:
    return _save_and_show(ctx, st.with_location(ctx.load(), _location(ctx.args)))


def cmd_calendars(ctx: Context) -> int:
    state, args = ctx.load(), ctx.args
    if args.action == "list":
        return _emit(state["followed_calendars"])
    if args.action == "rm":
        return _save_and_show(ctx, st.without_calendar(state, args.slug))
    calendar = {
        "url": args.url,
        "cal_id": args.cal_id,
        "name": args.name,
        "slug": args.slug,
        "ics": ICS_URL.format(cal_id=args.cal_id),
        "added_at": ctx.today(state["location"]["timezone"]),
    }
    return _save_and_show(ctx, st.with_calendar(state, calendar))


def cmd_hosts(ctx: Context) -> int:
    state, args = ctx.load(), ctx.args
    if args.action == "list":
        return _emit(state["followed_hosts"])
    if args.action == "rm":
        return _save_and_show(ctx, st.without_host(state, args.username))
    host = resolve_host(args.value, ctx.fetcher, ctx.today(state["location"]["timezone"]))
    return _save_and_show(ctx, st.with_host(state, host))


def cmd_prepare_run(ctx: Context) -> int:
    run_dir = ctx.args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    for old in run_dir.glob("*.json"):
        old.unlink()
    return _emit({"run_dir": str(run_dir)})


def _windows_for(ctx: Context, state: dict, tz_override) -> tuple:
    tz_name = _check_timezone(tz_override or state["location"]["timezone"])
    return tz_name, day_windows(local_today(ctx.now, tz_name), ctx.args.days, tz_name)


def cmd_windows(ctx: Context) -> int:
    tz_name, windows = _windows_for(ctx, ctx.load(), ctx.args.timezone)
    return _emit({"timezone": tz_name, "windows": windows})


def cmd_new_events(ctx: Context) -> int:
    ids = [e["api_id"] for e in _events_of(_read_json(ctx.args.history))]
    new = st.new_event_ids(ctx.load(), ids)
    refresh = len(new) >= REFRESH_THRESHOLD
    return _emit({"count": len(new), "new_ids": new, "threshold": REFRESH_THRESHOLD, "refresh": refresh})


def cmd_save_profile(ctx: Context) -> int:
    profile = _read_json(ctx.args.profile)
    ids = [e["api_id"] for e in _events_of(_read_json(ctx.args.history))]
    return _save_and_show(ctx, st.with_profile(ctx.load(), profile, ids, to_iso_z(ctx.now)))


def _feeds_state(state: dict, args) -> dict:
    if args.location_name is None and args.bounds is None:
        return state
    if args.location_name is None or args.bounds is None:
        raise ValueError("--location-name and --bounds must be given together")
    override = {**state["location"], "name": args.location_name, "bounds": _bounds(args.bounds)}
    return {**state, "location": override}


def cmd_feeds(ctx: Context) -> int:
    state = ctx.load()
    _, windows = _windows_for(ctx, state, ctx.args.timezone)
    result = collect_feeds(_feeds_state(state, ctx.args), windows, ctx.fetcher)
    _write_json(ctx.args.out, result)
    summary = {k: result[k] for k in ("failures", "skipped_external")}
    return _emit({"events": len(result["events"]), **summary})


def cmd_merge(ctx: Context) -> int:
    args, failures = ctx.args, []
    discovery = []
    for path in args.discovery:
        data = _read_optional(path, f"discovery file {Path(path).name}", failures)
        if data is not None:
            discovery.append(data)
    feeds = _read_optional(args.feeds, "feeds", failures) or {}
    registered = _events_of(_read_optional(args.registered, "registered events (clash check skipped)", failures))
    tz_name = _check_timezone(args.timezone) if args.timezone else None
    merged = merge_candidates(discovery, feeds, registered, tz_name)
    result = {**merged, "failures": [*failures, *merged["failures"]]}
    _write_json(args.out, result)
    return _emit({"counts": result["counts"], "failures": result["failures"]})


HANDLERS = {
    "show": cmd_show,
    "init": cmd_init,
    "set-keywords": cmd_set_keywords,
    "set-generated": cmd_set_generated,
    "set-location": cmd_set_location,
    "calendars": cmd_calendars,
    "hosts": cmd_hosts,
    "prepare-run": cmd_prepare_run,
    "windows": cmd_windows,
    "new-events": cmd_new_events,
    "save-profile": cmd_save_profile,
    "feeds": cmd_feeds,
    "merge": cmd_merge,
}


def _add_location_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--location-query", required=True)
    parser.add_argument("--location-name", required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--bounds", nargs=4, type=float, metavar=_BOUNDS_META, required=True)


def _add_setup_commands(sub) -> None:
    sub.add_parser("show", help="print the saved settings and profile summary")
    init = sub.add_parser("init", help="create the state file")
    _add_location_args(init)
    init.add_argument("--keywords", nargs=3, required=True, metavar="KEYWORD")
    init.add_argument("--force", action="store_true", help="replace an existing state file")
    keywords = sub.add_parser("set-keywords", help="replace the user's 3 keywords")
    keywords.add_argument("keywords", nargs=3, metavar="KEYWORD")
    generated = sub.add_parser("set-generated", help="replace the 2 generated keywords, keeping the profile")
    generated.add_argument("keywords", nargs=2, metavar="KEYWORD")
    _add_location_args(sub.add_parser("set-location", help="change the saved city"))
    profile = sub.add_parser("save-profile", help="store an updated profile")
    profile.add_argument("profile")
    profile.add_argument("--history", required=True)


def _add_follow_commands(sub) -> None:
    calendars = sub.add_parser("calendars", help="manage followed calendars").add_subparsers(
        dest="action", required=True
    )
    add = calendars.add_parser("add")
    for flag in ("--url", "--cal-id", "--name", "--slug"):
        add.add_argument(flag, required=True)
    calendars.add_parser("rm").add_argument("slug")
    calendars.add_parser("list")
    hosts = sub.add_parser("hosts", help="manage followed hosts").add_subparsers(dest="action", required=True)
    hosts.add_parser("add").add_argument("value", help="luma.com/user/<username> link or username")
    hosts.add_parser("rm").add_argument("username")
    hosts.add_parser("list")


def _add_run_commands(sub) -> None:
    sub.add_parser("prepare-run", help="empty and create the run directory")
    windows = sub.add_parser("windows", help="day windows for the search")
    windows.add_argument("--days", type=int, default=WINDOW_DAYS)
    windows.add_argument("--timezone")
    history = sub.add_parser("new-events", help="count past events not yet profiled")
    history.add_argument("--history", required=True)
    feeds = sub.add_parser("feeds", help="fetch followed calendars and hosts")
    feeds.add_argument("--days", type=int, default=WINDOW_DAYS)
    feeds.add_argument("--timezone")
    feeds.add_argument("--location-name")
    feeds.add_argument("--bounds", nargs=4, type=float, metavar=_BOUNDS_META)
    feeds.add_argument("--out", required=True)
    merge = sub.add_parser("merge", help="combine discovery and feeds into candidates")
    merge.add_argument("--discovery", nargs="+", required=True)
    for flag in ("--feeds", "--registered", "--out"):
        merge.add_argument(flag, required=True)
    merge.add_argument("--timezone", help="add local_day / local_time in this timezone")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scout.py", description="Bookkeeping for luma-event-scout.")
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--run-dir", type=Path, default=RUN_DIR)
    parser.add_argument("--now", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    _add_setup_commands(sub)
    _add_follow_commands(sub)
    _add_run_commands(sub)
    return parser


def main(argv: list = None, *, fetcher: Fetcher = None, now: datetime = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    try:
        moment = now or (parse_iso(args.now) if args.now else datetime.now(timezone.utc))
        return HANDLERS[args.command](Context(args, fetcher or Fetcher(), moment))
    except NoState:
        print("error: no state; run setup", file=sys.stderr)
        return EXIT_NO_STATE
    except KeyError as exc:
        print(f"error: missing field {exc}", file=sys.stderr)
        return EXIT_ERROR
    except (st.StateError, HostError, FetchError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
