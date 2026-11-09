# Luma Event Scout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code plugin with a `luma-event-scout` skill that recommends upcoming Luma events in the user's city for the next 14 days, from a cached interest profile, followed calendars and followed hosts.

**Architecture:** A Python standard-library script (`scout.py` + `scout_lib/`) owns all state and bookkeeping: state file, day windows, iCal and host feeds, merge, dedupe and clash check. Two Haiku sub-agents call the Luma connector and write compact JSON files: one searches a keyword day by day, one reads the user's event history. `SKILL.md` drives the flow and does the ranking. The plugin declares the Luma MCP server itself, so tool names have a fixed prefix.

**Tech Stack:** Python 3.9+ (standard library only at runtime), pytest + pytest-cov (dev only, in `.venv`), Claude Code plugin format (`.claude-plugin/plugin.json`, `.mcp.json`, `skills/`, `agents/`).

**Spec:** `docs/superpowers/specs/2026-11-09-luma-event-scout-design.md` (evidence: `docs/luma-connector-findings.md`)

## Global Constraints

- Runtime: Python **3.9** (the local interpreter is 3.9.12). Use `from __future__ import annotations`; no `match`, no `X | Y` outside annotations. Standard library only.
- Connector tools the skill and agents may use: `list_events`, `get_event`, `search_events`, `lookup_entity`, `get_self`, prefixed `mcp__plugin_luma-event-scout_luma__`. No other Luma tool, including `send_feedback`.
- State file: `~/.config/luma-event-scout/state.json`. Per-run files: `~/.cache/luma-event-scout/run/`, overwritten each run.
- Never stored in state: addresses, `geo_address_info`, event host names, guest data, registered events.
- Exactly **3** user keywords; **2** generated keywords; **5** searched per run.
- Window: **14** days, one `search_events` call per day per keyword, in the city's timezone.
- Profile refresh threshold: **5** new past events. History cap: **200** past events. `list_events` page size: **20**.
- Registered statuses (drop from candidates, use for clashes): `approved`, `pending_approval`, `waitlist`, plus `host`. `invited` is **not** registered.
- Missing `end_at`: assume **2 hours** for clash checks.
- Sold-out events are shown with a mark, never hidden.
- Repo rules: tests first; **80%+** coverage; files under 400 lines; functions under 50 lines; never mutate inputs (return new dicts); errors raised with clear messages, never swallowed.
- Commits: `<type>: <description>` (feat, fix, test, docs, chore). No attribution trailer (the owner disabled it globally). Work on branch `feat/luma-event-scout`.

## Review Focus

- **Host paging that doesn't advance:** if `events-hosting` ignores the cursor and returns the same page, fetching stops instead of looping. Test in Task 4.
- **A DST change inside the 14 days:** each window still runs from local midnight to the next local midnight (23 or 25 hours), not a fixed 24 hours. Test in Task 2.
- **Real-world iCal:** folded lines, escaped commas, `TZID=` times, all-day `VALUE=DATE` events and a missing `DTEND` all parse. Test in Task 3.
- **Events with no end time:** a registered event without `end_at` still blocks its first 2 hours, and an event that crosses midnight still clashes. Test in Task 6.
- **Broken or newer state file:** a half-written or `version: 2` file makes every command fail loudly and leaves the file untouched. Tests in Task 1 and Task 7.

## File Structure

```
.claude-plugin/plugin.json          plugin manifest (name: luma-event-scout)
.claude-plugin/marketplace.json     single-plugin marketplace for installs
.mcp.json                           declares the "luma" HTTP server (https://mcp.luma.com)
agents/luma-day-searcher.md         Haiku: one keyword × 14 days → compact JSON file
agents/luma-history-reader.md       Haiku: list_events past/future → compact JSON file
skills/luma-event-scout/SKILL.md    the flow, rules, ranking and output format
skills/luma-event-scout/scripts/scout.py              entry point
skills/luma-event-scout/scripts/scout_lib/__init__.py
skills/luma-event-scout/scripts/scout_lib/constants.py  every constant above
skills/luma-event-scout/scripts/scout_lib/state.py      load/save/validate/update state
skills/luma-event-scout/scripts/scout_lib/window.py     ISO parsing, day windows, bounds
skills/luma-event-scout/scripts/scout_lib/ics.py        iCal → event dicts
skills/luma-event-scout/scripts/scout_lib/http.py       Fetcher (delay, retries, errors)
skills/luma-event-scout/scripts/scout_lib/hosts.py      host links, profile + hosted events
skills/luma-event-scout/scripts/scout_lib/feeds.py      calendars + hosts → filtered compact records
skills/luma-event-scout/scripts/scout_lib/merge.py      dedupe, drop registered, clashes, sort
skills/luma-event-scout/scripts/scout_lib/cli.py        argparse commands, exit codes
tests/conftest.py  tests/fixtures/*  tests/test_<module>.py  tests/test_packaging.py
pyproject.toml  requirements-dev.txt  .gitignore  README.md  docs/manual-checklist.md
```

Shared record shapes (used by Tasks 3–7 and the agents):

```python
# Internal event (Tasks 3–5), before compaction. lat/lng/city/location may be None.
{"api_id": "evt-…", "name": str, "start_at": "2026-11-12T18:00:00Z", "end_at": str | None,
 "url": str, "calendar": str, "lat": float | None, "lng": float | None,
 "city": str | None, "location": str | None, "online": bool | None, "sold_out": bool | None}

# Compact record (spec 7.3), produced by feeds and by the day-searcher agent.
{"api_id", "name", "start_at", "end_at", "url", "calendar", "source", "online",
 "sold_out", "registered": None | str, "clash_with": [{"api_id": str, "name": str}]}

# History file (history-reader agent): {"period": "past" | "future", "events": [
#   {"api_id", "name", "start_at", "end_at", "calendar", "hosts": [str],
#    "location_type", "approval_status"}]}   # approval_status "host" when the user hosts
# Discovery file (day-searcher agent): {"keyword": str, "events": [compact], "failed_days": [date]}
```

`clash_with` carries `{api_id, name}` instead of the spec's bare IDs, so the warning can name the clashing event (spec 6.2 step 5 gives the reason).

---

### Task 1: Scaffolding, constants and state

**Files:**
- Create: `pyproject.toml`, `requirements-dev.txt`, `.gitignore`, `tests/conftest.py`
- Create: `skills/luma-event-scout/scripts/scout_lib/__init__.py`, `constants.py`, `state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces (`constants.py`): `STATE_VERSION = 1`, `STATE_PATH`, `RUN_DIR`, `USER_KEYWORD_COUNT = 3`, `GENERATED_KEYWORD_COUNT = 2`, `REFRESH_THRESHOLD = 5`, `WINDOW_DAYS = 14`, `DEFAULT_EVENT_DURATION = timedelta(hours=2)`, `REGISTERED_STATUSES = frozenset({"approved", "pending_approval", "waitlist", "host"})`, `ICS_URL = "https://api.lu.ma/ics/get?entity=calendar&id={cal_id}"`, `HOST_PROFILE_URL = "https://api.luma.com/user/profile"`, `HOST_EVENTS_URL = "https://api.luma.com/user/profile/events-hosting"`, `HOST_PAGE_LIMIT = 50`, `HOST_MAX_PAGES = 10`, `HTTP_TIMEOUT_S = 20`, `HTTP_RETRIES = 2`, `REQUEST_DELAY_S = 0.5`, `USER_AGENT = "luma-event-scout/0.1"`, `ONLINE_LOCATION_TYPES = frozenset({"zoom", "meet", "youtube", "discord", "twitch", "twitter"})`, `EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_NO_STATE = 0, 1, 2, 3`.
- Produces (`state.py`): `class StateError(Exception)`; `normalize_keyword(k: str) -> str`; `load_state(path: Path) -> dict | None`; `save_state(path: Path, state: dict) -> None`; `new_state(location: dict, user_keywords: list[str]) -> dict`; `with_calendar(state, calendar) -> dict`; `without_calendar(state, slug) -> dict`; `with_host(state, host) -> dict`; `without_host(state, username) -> dict`; `new_event_ids(state, ids: list[str]) -> list[str]`; `with_profile(state, profile: dict, seen_ids: list[str], now_iso: str) -> dict`; `all_keywords(state) -> list[str]`; `summary_line(state) -> str`.

- [ ] **Step 1: Scaffold.** `pyproject.toml` with `[tool.pytest.ini_options] pythonpath = ["skills/luma-event-scout/scripts"]`, `testpaths = ["tests"]`, and `[tool.coverage.report] fail_under = 80`. `requirements-dev.txt`: `pytest>=7`, `pytest-cov>=4`. `.gitignore`: `.venv/`, `__pycache__/`, `.coverage`, `htmlcov/`, `.pytest_cache/`. Create the venv: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.
- [ ] **Step 2: Write failing tests** in `tests/test_state.py` (a `tests/conftest.py` fixture `location()` returns `{"query": "Testville, TL", "name": "Testville", "timezone": "Europe/London", "bounds": {"north": 51.7, "south": 51.3, "east": 0.2, "west": -0.5}}`):
  - `test_new_state_has_version_keywords_and_empty_lists`: `s["version"] == 1`, `s["user_keywords"] == ["ai", "founders", "hackathon"]`, `s["followed_calendars"] == []`, `s["followed_hosts"] == []`, `s["profile"] is None`, `s["seen_event_ids"] == []`.
  - `test_new_state_rejects_wrong_keyword_count` (2 and 4 keywords → `StateError`), `test_new_state_rejects_duplicate_keywords` (`["AI", " ai ", "x"]` → `StateError`), `test_new_state_rejects_location_without_bounds`.
  - `test_save_then_load_round_trips`, `test_save_is_atomic_and_private` (no `*.tmp` left behind; file mode `0o600`).
  - `test_load_missing_returns_none`, `test_load_corrupt_raises_and_keeps_file` (bytes unchanged after the failed load), `test_load_newer_version_raises`.
  - `test_with_calendar_does_not_mutate_input` (original dict deep-equal to a copy taken before), `test_with_calendar_replaces_same_cal_id`, `test_without_calendar_unknown_slug_raises`, the same three for hosts (keyed by `user_id` / `username`).
  - `test_new_event_ids_dedupes_and_skips_seen`: seen `["evt-a"]`, input `["evt-a", "evt-b", "evt-b", "evt-c"]` → `["evt-b", "evt-c"]`.
  - `test_with_profile_sets_seen_and_timestamp`, `test_with_profile_rejects_generated_equal_to_user_keyword` (`"AI"` vs user `"ai"`), `test_with_profile_rejects_wrong_generated_count`, `test_with_profile_rejects_weight_out_of_range` (1.5).
  - `test_all_keywords_user_then_generated` (5 items, user first) and before a profile (3 items).
  - `test_summary_line`: with 2 calendars, 1 host and a profile → `'Testville · 3 keywords + 2 generated · 2 calendars · 1 host. Say "change" to edit.'`; with none and no profile → `'Testville · 3 keywords + 0 generated · 0 calendars · 0 hosts. Say "change" to edit.'`
- [ ] **Step 3: Run** `.venv/bin/pytest tests/test_state.py -q`. Expected: FAIL (module not found).
- [ ] **Step 4: Implement `constants.py` and `state.py`.** `normalize_keyword` = casefold, strip, collapse inner whitespace. `save_state` writes `tempfile.NamedTemporaryFile(dir=path.parent, delete=False)`, `chmod 0o600`, then `os.replace`. Every `with_*`/`without_*` returns `{**state, key: new_list}` built from copies.
- [ ] **Step 5: Run** `.venv/bin/pytest tests/test_state.py -q`. Expected: PASS.
- [ ] **Step 6: Commit** `feat: add state file handling for the scout script`.

### Task 2: Time windows and bounds

**Files:** Create `scout_lib/window.py`. Test `tests/test_window.py`.

**Interfaces:**
- Produces: `parse_iso(value: str) -> datetime` (aware, UTC; accepts `Z`, `.000Z`, `+01:00`; raises `ValueError`); `to_iso_z(dt: datetime) -> str` (`"2026-11-12T18:00:00Z"`); `local_today(now: datetime, tz_name: str) -> date`; `day_windows(start_day: date, days: int, tz_name: str) -> list[dict]` with items `{"date": "2026-11-09", "after": iso_z, "before": iso_z}`; `span(windows: list[dict]) -> tuple[datetime, datetime]`; `in_span(start_at: str, bounds: tuple[datetime, datetime]) -> bool` (start inclusive, end exclusive); `in_bounds(lat: float, lng: float, box: dict) -> bool`.

- [ ] **Step 1: Write failing tests:**
  - `test_parse_iso_variants`: `"2026-11-12T18:00:00.000Z"`, `"2026-11-12T18:00:00Z"` and `"2026-11-12T19:00:00+01:00"` are all equal; `"nope"` → `ValueError`.
  - `test_day_windows_count_and_order`: 14 windows, dates consecutive from `start_day`.
  - `test_day_windows_london_winter`: `date(2026, 11, 9)` → first window `after == "2026-11-09T00:00:00Z"`, `before == "2026-11-10T00:00:00Z"`.
  - `test_day_windows_across_dst_end`: `Europe/London`, start `date(2026, 10, 24)`, 3 days → the 25 Oct window is 25 hours long (`after "2026-10-24T23:00:00Z"`, `before "2026-10-26T00:00:00Z"`).
  - `test_local_today_uses_city_timezone`: `now = 2026-11-09T23:30:00Z`, `Asia/Tokyo` → `date(2026, 11, 10)`.
  - `test_in_span_edges` (start inclusive, end exclusive), `test_in_bounds_inside_and_outside`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_window.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `window.py`** with `zoneinfo.ZoneInfo`. Each window is `datetime.combine(day, time(0), tz)` to the next day's local midnight, converted to UTC.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add day windows and bounds checks`.

### Task 3: iCal parsing

**Files:** Create `scout_lib/ics.py`, `tests/fixtures/calendar.ics` (synthetic). Test `tests/test_ics.py`.

**Interfaces:**
- Consumes: `window.parse_iso`, `window.to_iso_z`.
- Produces: `parse_ics(text: str) -> list[dict]`. Each item has `api_id`, `uid_kind` (`"evt"` or `"other"`), `name`, `start_at`, `end_at` (`None` if no `DTEND`), `location` (unescaped text or `None`), `lat`, `lng` (from `GEO:lat;lng`, else `None`). Raises `ValueError("not an iCal feed")` when there's no `BEGIN:VCALENDAR`.

- [ ] **Step 1: Write the fixture** with 5 VEVENTs: (a) UTC times with a `GEO`; (b) `DTSTART;TZID=Europe/London:20261112T180000`; (c) `DTSTART;VALUE=DATE:20261113` with no `DTEND`; (d) a `SUMMARY` folded over two lines with `\,` inside; (e) `UID:calev-XYZ@events.lu.ma`. Use CRLF line endings.
- [ ] **Step 2: Write failing tests:**
  - `test_parses_five_events_with_ids`: IDs `evt-A1`…`evt-D4` and `calev-XYZ`; `uid_kind` is `"evt"` for the first four and `"other"` for the last.
  - `test_utc_and_geo`: (a) → `start_at == "2026-11-12T18:00:00Z"`, `lat == 51.5`, `lng == -0.12`.
  - `test_tzid_converted_to_utc`: (b) → `"2026-11-12T18:00:00Z"` (London is UTC+0 in November).
  - `test_all_day_without_dtend`: (c) → `start_at == "2026-11-13T00:00:00Z"`, `end_at is None`.
  - `test_folded_and_escaped_summary`: (d) → `name == "Builders, Founders & Friends Night"`.
  - `test_rejects_non_ical`: `parse_ics("<html>")` → `ValueError`.
- [ ] **Step 3: Run** `.venv/bin/pytest tests/test_ics.py -q`. Expected: FAIL.
- [ ] **Step 4: Implement `parse_ics`.** Unfold lines (a line starting with a space or tab continues the previous one), split each property line at the first `:` into name;params and value, unescape `\n \, \; \\`, and take the `api_id` from the UID before `@`. Floating times with no `TZID` and no `Z` are read as UTC.
- [ ] **Step 5: Run** the same command. Expected: PASS.
- [ ] **Step 6: Commit** `feat: parse Luma calendar iCal feeds`.

### Task 4: HTTP fetcher and host accounts

**Files:** Create `scout_lib/http.py`, `scout_lib/hosts.py`, `tests/fixtures/host_profile.json`, `tests/fixtures/host_events_page1.json`, `host_events_page2.json` (synthetic). Test `tests/test_http.py`, `tests/test_hosts.py`.

**Interfaces:**
- Produces (`http.py`): `class FetchError(Exception)`; `class Fetcher` with `__init__(self, opener=urllib.request.urlopen, sleep=time.sleep, delay_s=REQUEST_DELAY_S, retries=HTTP_RETRIES, timeout_s=HTTP_TIMEOUT_S)`, `text(self, url: str, params: dict | None = None) -> str` and `json(self, url: str, params: dict | None = None) -> dict`. It sends `User-Agent: USER_AGENT`, sleeps `delay_s` before every request after the first, retries `URLError`, 429 and 5xx with `sleep(2 ** attempt)`, and raises `FetchError("<status> for <url>")` on other 4xx or after the retries run out.
- Produces (`hosts.py`): `class HostError(Exception)`; `parse_username(value: str) -> str`; `resolve_host(value: str, fetcher: Fetcher, today: str) -> dict` returning `{"url": "https://luma.com/user/<u>", "username", "user_id", "name", "added_at": today}`; `fetch_hosted_events(user_id: str, fetcher: Fetcher) -> list[dict]` (raw entries); `host_entry_to_event(entry: dict) -> dict` (internal event shape).

- [ ] **Step 1: Write failing tests** with a fake opener (records requests and returns queued `(status, body)` pairs) and a fake `sleep` that records its calls:
  - `test_fetcher_sends_user_agent_and_params`, `test_fetcher_retries_5xx_then_succeeds` (sleep calls `[1, 2]`), `test_fetcher_raises_on_404_without_retry`, `test_fetcher_delays_between_requests` (second request preceded by `sleep(0.5)`).
  - `test_parse_username_forms`: `https://luma.com/user/ai_builders`, `lu.ma/user/ai_builders`, `@ai_builders` and `ai_builders` all → `"ai_builders"`; `https://luma.com/some-calendar` → `HostError`.
  - `test_resolve_host_returns_record` (from `host_profile.json`: `user.api_id "usr-HOST1"`, `name "Test Hosts"`), `test_resolve_host_missing_user_raises`.
  - `test_fetch_hosted_events_pages_with_cursor`: page 1 `has_more: true, next_cursor "c2"` and page 2 `has_more: false` → 3 entries; the second request carries `pagination_cursor=c2`, `period=future`, `pagination_limit=50`.
  - `test_fetch_hosted_events_stops_when_page_repeats` (Review Focus): page 2 equals page 1 → stops with page 1's entries, 2 requests total.
  - `test_host_entry_to_event`: slug url `"abcd1234"` → `"https://luma.com/abcd1234"`; `coordinate` → `lat`/`lng`; `geo_address_info.city` → `city`; `location_type "zoom"` → `online True`, `"offline"` → `False`, `"unknown"` → `None`; `ticket_info.is_sold_out` → `sold_out`; `calendar.name` → `calendar`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_http.py tests/test_hosts.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `http.py` and `hosts.py`.** `parse_username` matches `(?:https?://)?(?:www\.)?(?:luma\.com|lu\.ma)/user/([A-Za-z0-9_.-]+)` first, then a bare `@?[A-Za-z0-9_.-]+` with no `/` or `.com`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: resolve Luma host accounts and fetch their events`.

### Task 5: Feeds (followed calendars and hosts)

**Files:** Create `scout_lib/feeds.py`. Test `tests/test_feeds.py`.

**Interfaces:**
- Consumes: `ics.parse_ics`, `hosts.fetch_hosted_events`, `hosts.host_entry_to_event`, `window.span`, `window.in_span`, `window.in_bounds`, `http.Fetcher`, `http.FetchError`, `constants.ICS_URL`.
- Produces: `compact_record(event: dict, source: str) -> dict` (internal → compact; `registered None`, `clash_with []`); `keep_event(event: dict, bounds: tuple[datetime, datetime], location: dict) -> bool`; `collect_feeds(state: dict, windows: list[dict], fetcher: Fetcher) -> dict` returning `{"events": [compact], "failures": [{"source": str, "error": str}], "skipped_external": int}`.
- Place rule in `keep_event` (after the time window check passes): online `True` → keep; coordinates present → `in_bounds`; else `city` present → its normalized form equals `location["name"]`'s; else `location` text present → keep if it contains the city name (casefold) or starts with `http`; else keep.
- iCal events: `url` is `location` when it starts with `https://luma.com/`, else `https://luma.com/event/<api_id>`; `online None`; `sold_out None`; `calendar` is the followed calendar's `name`; `source "calendar:<slug>"`. `uid_kind "other"` events are counted in `skipped_external`. Host events get `source "host:<username>"`.

- [ ] **Step 1: Write failing tests** with a fake fetcher returning the Task 3 fixture for an iCal URL and the Task 4 fixtures for host URLs:
  - `test_keep_event_rules`: one case per branch (online outside the box kept; coordinates outside dropped; city match kept; text containing the city kept; URL-only location kept; outside the window dropped).
  - `test_collect_feeds_combines_calendar_and_host_events` (sources tagged correctly, every record has exactly the compact keys).
  - `test_collect_feeds_counts_external_listings` (`skipped_external == 1`).
  - `test_collect_feeds_records_failure_and_continues`: the iCal URL raises `FetchError` → `failures == [{"source": "calendar:test-cal", "error": …}]` and host events still returned.
  - `test_collect_feeds_rejects_html_as_failure` (the iCal URL returns HTML → recorded failure, not a crash).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_feeds.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `feeds.py`.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: collect events from followed calendars and hosts`.

### Task 6: Merge, registered events and clashes

**Files:** Create `scout_lib/merge.py`. Test `tests/test_merge.py`.

**Interfaces:**
- Consumes: `window.parse_iso`, `constants.REGISTERED_STATUSES`, `constants.DEFAULT_EVENT_DURATION`.
- Produces: `find_clashes(candidate: dict, registered: list[dict]) -> list[dict]` (`[{"api_id", "name"}]`); `merge_candidates(discovery: list[dict], feeds: dict, registered: list[dict]) -> dict` returning `{"candidates": [compact], "counts": {"candidates": int, "dropped_registered": int, "duplicates": int}, "failures": [str]}`.
- Rules: dedupe by `api_id`, keeping the highest-priority source (`host:` > `calendar:` > `discovery:`). Fill `registered` from the registered list when it's `None`. Drop candidates whose `registered` is in `REGISTERED_STATUSES`; keep `invited`. Overlap is `c_start < r_end and r_start < c_end`, with a missing end = start + 2 h. Only registered events with a registered status count for clashes. Sort by `(start_at, name)`. `failures` = feed failures as `"<source>: <error>"` plus `"discovery:<keyword> <date>"` for each failed day.

- [ ] **Step 1: Write failing tests:**
  - `test_dedupe_prefers_followed_source`: the same `evt-1` from `discovery:ai` and `calendar:c` → one record with `source "calendar:c"`, `counts.duplicates == 1`.
  - `test_drops_registered_keeps_invited`: registered `[evt-2 approved, evt-3 invited]` → `evt-2` dropped, `evt-3` kept with `registered "invited"`; a discovery record already carrying `registered "waitlist"` is dropped.
  - `test_clash_detected_and_named`: candidate 18:00–21:00 against registered 19:00–20:00 named `"Other"` → `clash_with == [{"api_id": "evt-r", "name": "Other"}]`.
  - `test_clash_with_missing_end_uses_two_hours` (Review Focus): registered starts 18:00 with no end; candidate 19:30–20:00 → clash; candidate 20:00–21:00 → no clash.
  - `test_clash_across_midnight`: candidate 23:00–01:00 against registered 00:30–02:00 the next day → clash.
  - `test_sorted_and_failures_listed`: output order by `start_at`; `failures` includes `"calendar:c: boom"` and `"discovery:ai 2026-11-10"`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_merge.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `merge.py`.**
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat: merge candidates, drop registered events and flag clashes`.

### Task 7: Command-line interface

**Files:** Create `scout_lib/cli.py`, `skills/luma-event-scout/scripts/scout.py`. Test `tests/test_cli.py`.

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: list[str] | None = None, *, fetcher: Fetcher | None = None, now: datetime | None = None) -> int`. Global options come before the command: `--state PATH`, `--run-dir PATH`, `--now ISO` (tests and debugging). Output is JSON on stdout, errors go to stderr as `error: <message>`. `StateError`, `HostError`, `FetchError`, `ValueError` and `OSError` → exit 1; `argparse` errors → exit 2; no state → exit 3 with `error: no state; run setup`.
- Commands:
  - `show` → `{"summary", "location", "user_keywords", "generated_keywords", "keywords", "calendars", "hosts", "has_profile", "last_profiled_at"}`.
  - `init --location-query Q --location-name N --timezone TZ --bounds NORTH SOUTH EAST WEST --keywords K1 K2 K3 [--force]`. Refuses to overwrite existing state without `--force`. Validates the timezone with `ZoneInfo`.
  - `set-keywords K1 K2 K3` (same validation as `init`; also fails if one equals a generated keyword, so the skill regenerates) and `set-location --location-query Q --location-name N --timezone TZ --bounds N S E W`: the "change" flow, keeping profile, calendars and hosts.
  - `calendars add --url U --cal-id C --name N --slug S` (builds `ics` from `ICS_URL`, `added_at` = today) / `calendars rm SLUG` / `calendars list`.
  - `hosts add VALUE` (calls `resolve_host`) / `hosts rm USERNAME` / `hosts list`.
  - `prepare-run` → deletes `*.json` in the run dir, creates the dir, prints `{"run_dir": path}`.
  - `windows [--days 14] [--timezone TZ]` → `{"timezone", "windows"}`, today taken in the city timezone. `--timezone` is the one-run city override.
  - `new-events --history FILE` → `{"count", "new_ids", "threshold": 5, "refresh": count >= 5}`.
  - `save-profile PROFILE_FILE --history FILE` → saves via `with_profile` (seen IDs = every `api_id` in the history file) and prints `show`'s output.
  - `feeds [--days 14] [--timezone TZ --location-name N --bounds N S E W] --out FILE` → writes the `collect_feeds` result; prints `{"events": n, "failures": [...], "skipped_external": n}`. The optional flags are the one-run city override; the saved state isn't changed.
  - `merge --discovery FILE [FILE ...] --feeds FILE --registered FILE --out FILE` → writes the `merge_candidates` result; prints its `counts` and `failures`.
- `scout.py` adds its own directory to `sys.path` and runs `raise SystemExit(main())`.

- [ ] **Step 1: Write failing tests** (with `tmp_path` state and run dirs, a fake fetcher, `--now 2026-11-09T12:00:00Z`):
  - `test_show_without_state_exits_3`.
  - `test_init_then_show` (summary line matches Task 1's format; `keywords` has 3 entries).
  - `test_init_refuses_overwrite_without_force`, `test_init_rejects_bad_timezone`.
  - `test_set_keywords_keeps_profile_and_calendars`, `test_set_keywords_rejects_collision_with_generated`, `test_set_location_keeps_profile`.
  - `test_feeds_city_override_does_not_change_state` (state file bytes unchanged after `feeds --location-name Other …`).
  - `test_calendars_add_list_rm` (the `ics` URL ends with `id=cal-T1`).
  - `test_hosts_add_uses_resolver` (fake fetcher; the stored `user_id` is `"usr-HOST1"`).
  - `test_windows_outputs_14_days`.
  - `test_new_events_and_refresh_flag`: history with 5 unseen IDs → `refresh true`; with 4 → `false`.
  - `test_save_profile_then_show_has_5_keywords`.
  - `test_feeds_and_merge_end_to_end` (fake fetcher, one discovery file, one registered file → candidates sorted, a registered event dropped).
  - `test_corrupt_state_fails_and_is_untouched` (Review Focus): every command exits 1 and the file's bytes are unchanged.
  - `test_script_entry_runs`: `subprocess.run([sys.executable, "skills/luma-event-scout/scripts/scout.py", "--state", tmp, "show"])` → exit code 3.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_cli.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `cli.py` and `scout.py`.** Keep each command handler in its own function under 50 lines, with a dispatch dict from command name to handler.
- [ ] **Step 4: Run** `.venv/bin/pytest -q --cov=scout_lib --cov-report=term-missing`. Expected: all PASS, total coverage ≥ 80%.
- [ ] **Step 5: Commit** `feat: add scout.py command-line interface`.

### Task 8: Plugin manifest, MCP server and sub-agents

**Files:** Create `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.mcp.json`, `agents/luma-day-searcher.md`, `agents/luma-history-reader.md`. Test `tests/test_packaging.py`.

**Interfaces:**
- Produces: plugin name `luma-event-scout`; MCP server key `luma` → `{"type": "http", "url": "https://mcp.luma.com"}`; tool prefix `mcp__plugin_luma-event-scout_luma__`; agent names `luma-day-searcher` and `luma-history-reader`, both `model: haiku`.
- `luma-day-searcher` tools: `mcp__plugin_luma-event-scout_luma__search_events, Write`. Input (in the prompt it's given): `keyword`, `location_query`, `windows` (from `scout.py windows`), `output_path`. For each window it calls `search_events(query=keyword, location=location_query, after=w.after, before=w.before)`. It maps every entry to a compact record (`calendar` = `calendar.name`; `online` from `location_type` the same way as Task 4; `sold_out` = `ticket_info.is_sold_out`; `registered` = `guest_info.approval_status` or `null`; `source "discovery:<keyword>"`). It records failed dates, writes the discovery file, and replies with one line: `<output_path> · <n> events · failed: [dates]`. It never writes addresses or host names.
- `luma-history-reader` tools: `mcp__plugin_luma-event-scout_luma__list_events, Write`. Input: `period` (`past` | `future`), optional `after`, `cap` (200 for past), `output_path`. It pages `list_events(period, after, limit=20, cursor)` until `has_more` is false or `cap` is reached, and writes the history file (`approval_status` = `"host"` when `host_info` or `manager_info` is non-null). It replies `<output_path> · <n> events`.

- [ ] **Step 1: Write failing tests** in `tests/test_packaging.py` (parse frontmatter with a tiny `---` splitter):
  - `test_plugin_manifest` (name, version, description present), `test_marketplace_lists_plugin` (source `"./"`).
  - `test_mcp_declares_luma_http`.
  - `test_agents_use_haiku_and_allowed_tools_only`: every `mcp__…luma__` tool in an agent's `tools` is in `{list_events, get_event, search_events, lookup_entity, get_self}`, and the only non-MCP tool is `Write`.
  - `test_no_forbidden_luma_tool_named_anywhere`: scan `agents/*.md` and `skills/**/SKILL.md` for `mcp__plugin_luma-event-scout_luma__(\w+)`; every match is in the allowlist.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_packaging.py -q`. Expected: FAIL.
- [ ] **Step 3: Write the manifests and the two agent files** with the contracts above as their instructions.
- [ ] **Step 4: Run** the same command. Expected: PASS (the SKILL.md scan passes vacuously until Task 9).
- [ ] **Step 5: Commit** `feat: add plugin manifest, Luma MCP config and Haiku sub-agents`.

### Task 9: The skill (`SKILL.md`)

**Files:** Create `skills/luma-event-scout/SKILL.md`. Modify `tests/test_packaging.py` (add a test).

**Interfaces:**
- Consumes: every `scout.py` command (Task 7), both agents (Task 8), connector tools `lookup_entity`, `search_events` (setup probe), `get_event` (refresh), with the full prefixed names.
- Frontmatter: `name: luma-event-scout`; `description` says it finds upcoming Luma events in the user's city that fit their interests, from their history, keywords, followed calendars and hosts; triggers on "find events", "what's on", "luma events this week".
- Body sections, in order: **Rules** (read-only allowlist, never register, never call other Luma tools, never store personal data, never hand-edit `state.json`); **Paths** (`python3 <skill-dir>/scripts/scout.py`, run dir); **First run** (spec 6.1 steps 1–8 with exact commands: probe search → `init --bounds … --timezone …` with the timezone from the probe's events; `lookup_entity` for each calendar → `calendars add`; `hosts add`; history agent with `cap 200` → build the profile JSON → `save-profile`); **Normal run** (spec 6.2 steps 1–8: `show` → history agent `past` with `after: last_profiled_at` → `new-events` → refresh when `refresh: true` using `get_event` on the new IDs → `prepare-run` → `windows` → 5 day-searcher agents in parallel, one per keyword, files `discovery-<n>.json` → `feeds` → history agent `future` → `registered.json` → `merge` → rank); **Ranking and output** (the spec 8 format; show every followed-source candidate and the best 15–20 discovery matches; sold-out marked; "you're invited" marked; clash warnings name the event; a final "Skipped:" line from `failures`); **Changing settings** ("change" → which field; edits go through `scout.py`); **Errors** (spec 9 table).
- Generated keywords: when building or refreshing the profile, pick 2 broad themes that aren't the same as, or near-synonyms of, the user's 3. With no history, use broader parent themes of the user's 3.

- [ ] **Step 1: Write the failing test** `test_skill_frontmatter_and_sections`: `name == "luma-event-scout"`; the body contains the headings `## Rules`, `## First run`, `## Normal run`, `## Ranking and output`, `## Errors`; it references `scout.py`, `luma-day-searcher` and `luma-history-reader`; and it contains no Luma tool name outside the allowlist (the Task 8 scan now covers a real file).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_packaging.py -q`. Expected: FAIL.
- [ ] **Step 3: Write `SKILL.md`** (under 200 lines).
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: add the luma-event-scout skill`.

### Task 10: README, manual checklist and live smoke test

**Files:** Create `README.md`, `docs/manual-checklist.md`.

- [ ] **Step 1: Write `README.md`:** what it does; install (`/plugin marketplace add siarkonyar/zsk-luma-event-scout`, then `/plugin install luma-event-scout@zsk-luma-event-scout`); sign in once via `/mcp` → `plugin:luma-event-scout:luma`; the permissions to expect (writes under `~/.cache/luma-event-scout/run/` and `~/.config/luma-event-scout/`); privacy (what's stored, what never is); cost (about 70 Haiku searches per run); a short flow diagram; development (`python3 -m venv .venv`, `pytest --cov`).
- [ ] **Step 2: Write `docs/manual-checklist.md`:** setup with one calendar and one host; normal run; force a refresh (delete 5 IDs from `seen_event_ids` with `scout.py`-free test state); a failing feed (bad calendar ID); city override; "change" flow. Each item has its expected result.
- [ ] **Step 3: Live smoke test of the script (no login needed):** in a temp state, `init` with the bounds of a large city, `calendars add` for a public calendar, `hosts add` for a public host profile, then `feeds --days 14`. Expected: `events > 0`, `failures == []`. The connector parts of the checklist need the plugin installed and signed in, so they're for the owner.
- [ ] **Step 4: Run** `.venv/bin/pytest -q --cov=scout_lib`. Expected: PASS, ≥ 80%.
- [ ] **Step 5: Commit** `docs: add README and manual test checklist`.
