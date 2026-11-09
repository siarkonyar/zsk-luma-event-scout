# Luma Event Scout: design

Date: 2026-11-09
Status: draft, builder-checked, awaiting the owner's approval
Evidence: [docs/luma-connector-findings.md](../../luma-connector-findings.md) (connector and feed tests run on 2026-11-09)

## 1. What this is, and why

A Claude Code skill that tells a Luma user which upcoming events in their city they should go to.

The owner will use it for **scheduling**: run it every few days, see what's coming up in the next two
weeks that fits them, and register for events themselves on Luma. So it must be cheap to run often,
and it must never ask the same setup questions twice.

It's personal because it learns what the user likes from the events they've already signed up for on
Luma, plus a few keywords they give. It also watches the calendars and host accounts the user cares
about and surfaces their events the user hasn't registered for yet.

**Who it's for:** any Luma user who installs it, not only the owner (the owner's brief: "provide it
back to our user"). So nothing may assume the owner's account: not the size of their history, not
the name the Luma connector gets in their client, and not that they have any history at all.

## 2. Goals, non-goals, anti-goals

**Goals**

- Recommend upcoming events in the user's city for the **next 14 days**, ranked by fit, each with a
  one-line reason.
- Show events from **followed calendars** and **followed host accounts** that the user hasn't
  registered for.
- Flag events that **clash** with ones the user is already registered for.
- **Remember** the setup (city, keywords, calendars, hosts) and the interest profile between runs.
- Keep the profile fresh **without re-reading the whole history**: refresh only after 5 or more new
  events.

**Non-goals (for now)**

- Registering, RSVPing or buying tickets. The skill gives links; the user registers.
- Managing events the user hosts.
- Running unattended on a timer (cron, GitHub Actions). Sign-in only works inside a Claude client today.
- Pushing events into Google Calendar or other calendar apps.
- Searching several cities in one run. One saved city, with a one-run override.

**Anti-goals (a failure even if it technically works)**

- Asking setup questions again on a normal run.
- Re-reading the user's whole Luma history on every run.
- Calling any Luma tool that changes something (the connector exposes 48 such tools).
- Storing addresses, host names or guest data in the state file.
- Flooding the main conversation with raw search results (each search returns about 25 KB).

## 3. Constraints (from the tests)

- **Data source:** the official Luma MCP connector (`https://mcp.luma.com`), signed in once through
  the Claude client (OAuth; tokens persist and refresh on their own).
- **Allowed connector tools (read-only):** `list_events`, `get_event`, `search_events`,
  `lookup_entity`, `get_self`. Everything else is forbidden, including `send_feedback`.
- `search_events` requires a `query`, returns **at most 10** events per call, has no paging, and
  covers upcoming events only. Date windows (`after` / `before`) are the only way to get more:
  a one-day window with a broad keyword can still fill all 10.
- `list_events` pages at up to 50 per call, but 50 entries are about 110 KB, too much for one tool
  result. Use `limit: 20`.
- Every event carries `guest_info`: `null` = not registered, otherwise `{ approval_status }` with
  `approved`, `pending_approval`, `waitlist` or `invited`. **There is no check-in field.**
- The connector **can't** read a followed calendar's events (no manage access) and **can't** resolve
  host profile links (`lookup_entity` returns `null`).
- **Workarounds (both public, no login, both undocumented):**
  - **Calendar iCal feed:** `https://api.lu.ma/ics/get?entity=calendar&id=<cal-id>`. UIDs are
    `evt-XXXX@events.lu.ma`, matching the connector's `api_id`. Past history in the feed has gaps,
    so use it for future events only. One UID shape is `calev-…` (an external listing).
  - **Host endpoints:** `https://api.luma.com/user/profile?username=<username>` → `user.api_id`, then
    `https://api.luma.com/user/profile/events-hosting?user_api_id=<usr-id>&period=future&pagination_limit=50`
    (paged with `next_cursor`). Hosts can be global, so filter by city.
- **User rules for this repo:** tests first, 80% coverage, small files, immutable data, explicit
  error handling, no hardcoded values.

## 4. Decisions the owner made

1. **Inputs at setup:** city, **exactly 3 keywords**, links to followed **calendars**, and links to
   followed **host accounts** (`luma.com/user/<username>`). The user pastes links; no browser.
2. **What counts as an interest signal:** every past event in `list_events(period: "past")`,
   whatever its `approval_status` (pending and waitlisted ones count), and events the user hosted.
3. **Profile refresh:** only when **5 or more** new past events have appeared since the last refresh,
   and only those new events are read.
4. **Keywords per run: 5.** The user's 3, plus **2 broad keywords the skill generates** from the
   profile. The generated ones must be broad (aim: fetch as many events as possible) and must not
   repeat or near-repeat the user's keywords. If they collide, the skill picks other broad themes.
5. **Discovery window: the next 14 days, one search per day per keyword** (70 searches per run).
6. **Searching runs on Haiku sub-agents**, in parallel. The main model only does the judgment
   (ranking, reasons).
7. **Output:** sorted by date, with a link, a one-line reason, and a clash warning where relevant.
   The skill never registers the user.

## 5. Decisions I made (the owner has seen these; flagged so they can be checked)

- **State file location:** `~/.config/luma-event-scout/state.json`, outside the repo (personal
  data never reaches git) and outside the skill folder (survives skill updates).
- **A Python script does all bookkeeping** (state, diffs, feeds, merging, clash check), standard
  library only. The model never hand-edits JSON or counts.
- **One Haiku sub-agent per keyword** (5 agents, 14 searches each, about 100k tokens each). A
  one-agent-per-week split would put 28+ searches in one agent, too close to its context limit.
- **The sub-agents write their results to files** and return only a path and a count, so raw results
  never enter the main conversation.
- **Followed calendars and hosts use the same 14-day window** as discovery, so the output is one
  consistent schedule. Their feeds cost no tokens, so widening this later is free.
- **Online events from followed calendars and hosts are kept** (the user follows them on purpose) and
  marked "online". Discovery is in-city only.
- **Generated keywords are stored with the profile** and recalculated only on a profile refresh,
  not on every run.
- **City bounds come from the connector:** the `resolved_location.bounds` of the first
  `search_events` call is saved and used to filter calendar and host events by coordinates. If an
  event has no coordinates, it's kept when its city name matches.
- **First-run history is read by a Haiku sub-agent** that returns a compact list (title, calendar
  name, host names, date, location type), so the main model builds the profile without loading
  about 150 KB of raw history.
- **History cap:** the first run reads at most the **200 most recent** past events (10 pages of 20).
  Heavy users' older history adds little and would overflow one sub-agent.
- **No history:** if a user has no past events, the profile starts from their 3 keywords alone, and
  the 2 generated keywords are broader parent themes of those 3.
- **Sold-out events are shown, marked "sold out"**, not hidden: a waitlist may still be open, and
  pending and waitlisted registrations are common (20 of the owner's 58 past events). Feed events
  from iCal carry no ticket data, so they're shown without that mark and cost no extra calls.
- **`invited` counts as not registered** (the user hasn't signed up) and is marked "you're invited".
- **Setup runs one probe search** (`search_events` with the first keyword and the city) to get
  `resolved_location.bounds`. The city's timezone is taken from the `timezone` of the in-city events
  it returns, since `resolved_location` has none.
- **Per-run files** (sub-agent results, feeds, registered events, candidates) go in
  `~/.cache/luma-event-scout/run/`, overwritten each run. Only the latest run is kept.

## 6. How it works

### 6.1 First run (setup)

1. Check that the `luma` connector is available. If not, tell the user how to connect it and stop.
2. Ask, in one message: city, exactly 3 keywords, followed calendar links (optional), followed host
   links (optional).
2a. Probe search: `search_events(query: <first keyword>, location: <city>)`. Save
   `resolved_location` (name, bounds) and the timezone of the returned events. If the resolved place
   isn't what the user meant, ask them to qualify the city.
3. For each calendar link: call `lookup_entity(link)`. Save `cal_id`, `name` and `slug`, and build
   the iCal URL. Reject links that don't resolve to a calendar.
4. For each host link: the script calls the profile endpoint, then saves `username`, `user_id` and
   `name`. Reject links that don't resolve.
5. History: a Haiku sub-agent pages `list_events(period: "past", limit: 20)` up to the 200-event cap
   and writes a compact list to a file.
6. The main model builds the profile from that list plus the 3 keywords: a short summary, weighted
   interest tags, and the 2 broad generated keywords.
7. The script saves everything, including `seen_event_ids` and `last_profiled_at`.
8. Continue straight into a normal run.

### 6.2 Normal run

1. `scout.py show`. No state → first run. Otherwise print one line, e.g.
   `<city> · 3 keywords + 2 generated · 2 calendars · 1 host. Say "change" to edit.`
   A one-run override is allowed ("search Berlin this time") without changing the saved city.
2. **Profile check:** `list_events(period: "past", after: last_profiled_at, limit: 20)`, paged.
   `scout.py new-events` counts IDs not in `seen_event_ids`.
   - Fewer than 5 new: keep the profile.
   - 5 or more: `get_event` on each new one for `description_md`. The main model updates (doesn't
     rebuild) the profile and the 2 generated keywords. `scout.py save-profile`.
3. **Discovery:** start 5 Haiku sub-agents in parallel, one per keyword. Each runs
   `search_events(query, location, after: day 00:00, before: next day 00:00)` for each of the next
   14 days in the city's timezone, and writes a compact JSON file (see 7.3).
4. **Followed sources:** `scout.py feeds --days 14` downloads each calendar's iCal and each host's
   upcoming events, keeps those in the window and inside the city bounds (online events kept), and
   writes a compact JSON file.
5. **Registered events:** `list_events(period: "future")`, paged. These go to a run file as
   `{ api_id, name, start_at, end_at, approval_status }` (the name is there so clash warnings can say
   what clashes; the run file is overwritten next run and never copied into the state file).
6. **Merge:** `scout.py merge` dedupes by `api_id`, drops events the user is registered for, flags
   clashes (time overlap with a registered event), sorts by start time, and writes the candidate list.
7. **Rank:** the main model reads the candidate list (compact), picks what fits, and writes one
   reason per event. Every unregistered event from a followed calendar or host is shown. Discovery
   results are filtered to the ones that fit the profile.
8. Print the result (see 8).

## 7. Data shapes

### 7.1 State file (`~/.config/luma-event-scout/state.json`)

Example values are made up.

```json
{
  "version": 1,
  "location": {
    "query": "<city>, <country>",
    "name": "<city>",
    "timezone": "Europe/Example",
    "bounds": { "north": 0.0, "south": 0.0, "east": 0.0, "west": 0.0 }
  },
  "user_keywords": ["<kw1>", "<kw2>", "<kw3>"],
  "followed_calendars": [{
    "url": "https://luma.com/<slug>",
    "cal_id": "cal-AbCdEf123456789",
    "name": "<calendar name>",
    "slug": "<slug>",
    "ics": "https://api.lu.ma/ics/get?entity=calendar&id=cal-AbCdEf123456789",
    "added_at": "2026-11-09"
  }],
  "followed_hosts": [{
    "url": "https://luma.com/user/<username>",
    "username": "<username>",
    "user_id": "usr-AbCdEf123456789",
    "name": "<display name>",
    "added_at": "2026-11-09"
  }],
  "profile": {
    "summary": "<two or three sentences>",
    "interests": [{ "tag": "<topic>", "weight": 0.8, "evidence_count": 6 }],
    "generated_keywords": ["<broad1>", "<broad2>"],
    "built_from_events": 58,
    "last_profiled_at": "2026-11-09T00:00:00Z"
  },
  "seen_event_ids": ["evt-AbCdEf123456789"]
}
```

Never stored: addresses, `geo_address_info`, host names of events, guest data, registered events.

### 7.2 Script commands (`scout.py`)

| Command | Does |
|---|---|
| `show` | Prints the state summary, or exits with a "no state" code |
| `init --location-json <file> --keywords k1 k2 k3` | Creates the state (exactly 3 keywords enforced) |
| `calendars add --url --cal-id --name --slug` / `rm <slug>` / `list` | Manages calendars (the skill resolves the ID with `lookup_entity` first) |
| `hosts add <profile-url>` / `rm <username>` / `list` | Manages hosts (the script resolves the username itself) |
| `new-events <ids-file>` | Prints the count and the list of IDs not in `seen_event_ids` |
| `save-profile <profile-file> --seen <ids-file>` | Replaces the profile, adds the IDs, sets `last_profiled_at` |
| `feeds --days 14 --out <file>` | Fetches calendar and host events, filters by window and bounds, writes compact JSON |
| `merge --discovery <files…> --feeds <file> --registered <file> --out <file>` | Dedupes, drops registered, flags clashes, sorts |

All writes create a new state object and replace the file atomically (write a temp file, then rename).

### 7.3 Compact event record (sub-agents, feeds, merge)

```json
{
  "api_id": "evt-AbCdEf123456789",
  "name": "<event title>",
  "start_at": "2026-11-12T18:00:00.000Z",
  "end_at": "2026-11-12T21:00:00.000Z",
  "url": "https://luma.com/abcd1234",
  "calendar": "<calendar name>",
  "source": "discovery:<keyword> | calendar:<slug> | host:<username>",
  "online": false,
  "sold_out": false,
  "registered": null,
  "clash_with": ["evt-…"]
}
```

`registered` is `null` or the `approval_status`. Sub-agents write `registered` from `guest_info`;
feed events get it from the registered-events file during `merge`. `sold_out` is `null` when the
source doesn't say (iCal events).

### 7.4 Sub-agent contract

- **Model:** Haiku. **Tools:** `mcp__luma__search_events` (discovery agent) or `mcp__luma__list_events`
  (history agent), plus writing its output file. Nothing else.
- **Input:** keyword, location query, timezone, the 14 dates, output path.
- **Output:** the file, plus a final message with only the path, the number of events, and any
  failed days.

## 8. What the user sees

```
<city> · 5 keywords · 2 calendars · 1 host

Wed 11 Nov  18:00  <event title>              fits: <one-line reason>
                   luma.com/xxxx              ⚠ clashes with <registered event title>
Sat 14 Nov  10:00  <event title>              from a calendar you follow
                   luma.com/yyyy
…
Thu 19 Nov  18:30  <event title>              fits: <one-line reason>
                   luma.com/zzzz              sold out (waitlist may be open)
…
Skipped: 1 host feed failed (<username>)
```

Sold-out events stay in the list with a "sold out" mark. The "skipped" line only reports sources or
days that failed.

## 9. Errors

| Situation | Behaviour |
|---|---|
| Luma connector missing or signed out | Stop with clear "connect Luma" steps |
| `resolved_location` doesn't match the saved city | Warn and ask once whether to continue |
| A sub-agent fails or some days fail | Continue with what came back, and name the missing keyword/days in the "skipped" line |
| An iCal or host endpoint fails or changes shape | Skip that source, say which one, keep the rest |
| State file unreadable or wrong version | Don't overwrite it; tell the user and offer to start setup again |
| A pasted link doesn't resolve | Reject it at setup with the reason |

## 10. Cost per normal run (estimates)

- Discovery: 70 searches on Haiku, roughly 500k tokens (about 7k per search).
- Feeds and merge: no tokens (script).
- Main model: the profile check (usually one small `list_events` page), one `list_events(future)`,
  and ranking the compact candidate list.
- A profile refresh adds one `get_event` per new event (5 or more).

## 11. Testing

- The script is built test-first: state create/update (immutability, atomic write, version check),
  `new-events` diff, iCal parsing (folded lines, `evt-` vs `calev-` UIDs, time zones, all-day events),
  host endpoint parsing and paging, window and bounds filtering, merge dedupe, registered removal,
  clash detection. Fixtures are synthetic, never real account data. Target 80%+ coverage.
- Skill-level: a manual checklist run against the live connector (setup, normal run, refresh
  trigger at 5 new events, failing feed).

## 12. Left to the builder

- File layout and packaging, and the sub-agent definitions. Because other people install it, install
  instructions are a real deliverable, and the Luma tool names can't be hard-coded as `mcp__luma__*`:
  a user who adds Luma through claude.ai's connector list gets a different prefix, and sub-agent tool
  lists must match exactly. One way out: package it as a plugin that declares the Luma server itself,
  so the prefix is fixed. The builder picks the approach.
- Exact prompt wording for the skill, sub-agents and profile update.
- The profile's tag vocabulary and weighting, and the ranking heuristic.
- How many discovery results to show (suggested: everything from followed sources, plus the best
  15–20 discovery matches).
- Retry/backoff details for the public endpoints, and a polite delay between requests.

## 13. Known risks

- The iCal URL and the host endpoints are undocumented. If Luma changes them, those sources break;
  discovery and history (official connector) keep working.
- Broad keywords will often hit the 10-per-day cap, so discovery is wide but not complete.
- "Attended" means "had a registration": there is no check-in data.
