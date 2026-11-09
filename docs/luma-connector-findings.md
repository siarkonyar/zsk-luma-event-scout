# Luma connector findings

Tested on 2026-11-09 against the official Luma MCP server (`https://mcp.luma.com`), signed in as the
project owner. Only read-only tools were called. No tool that creates, updates, invites, approves,
deletes or sends anything was called.

This file holds no personal data. It uses field names, counts and made-up example shapes only.

## TL;DR

| Question | Answer |
|---|---|
| Can the connector read a **followed** calendar's events? | **No.** `lookup_entity` returns only the calendar's ID, name, slug and avatar. `list_calendar_events` returns "You don't have manage access to this calendar." |
| Do connector event IDs match the iCal feed? | **Yes.** iCal `UID` is `evt-XXXX@events.lu.ma`, and the part before `@` is the connector's `api_id`. An ID from `list_events(future)` was found in the test feed. |
| Is iCal still needed? | **Yes**, for followed calendars. Everything else (history, upcoming registrations, discovery) comes from the connector. |
| Does the connector say whether the user is registered? | **Yes.** Every event has `guest_info`: `null` = not registered, otherwise `{ approval_status }`. This also holds for `search_events` results. |

## 1. Tools

The server exposes **74 tools**: 26 read-only and 48 that change something.

### Read-only tools (26)

The first five are the ones the scout needs. The rest only work on calendars or events the user
manages.

| Tool | Purpose | Parameters (`*` = required) |
|---|---|---|
| `list_events` | Events the user is hosting or attending, past or upcoming | `period` (`future`\|`past`), `status` (`host`\|`approved`\|`session`\|`pending_approval`\|`invited`\|`declined`\|`waitlist`), `after` (datetime), `before` (datetime), `limit` (int, max 50), `cursor` (string) |
| `get_event` | One event, scoped to the user's role (`manage` / `guest` / `public` view) | `event_id`* |
| `search_events` | Search upcoming public events | `query`* (string), `location` (free text), `latitude` + `longitude` (number), `after`, `before` |
| `lookup_entity` | Resolve a luma.com / lu.ma URL or slug to an event or calendar ID | `slug`* (slug or full URL) |
| `get_self` | The signed-in user's profile | none |
| `list_calendars` | Calendars the user **manages** | none |
| `get_calendar` | One managed calendar | `calendar_id`* |
| `list_calendar_events` | Events on a **managed** calendar | `calendar_id`*, `period`, `status` (`approved`\|`pending`), `after`, `before`, `limit`, `cursor` |
| `list_pending_calendar_events` | Pending submissions across managed calendars | `organization_id`, `limit`, `cursor` |
| `list_calendar_admins` | Admins of a managed calendar | `calendar_id`* |
| `list_calendar_contacts` | Audience of a managed calendar | `calendar_id`*, `query`, `tags`, `calendar_membership_tier_id`, `membership_status`, `sort_column`, `limit`, `cursor` |
| `list_calendar_contact_tags` | Contact tags on a managed calendar | `calendar_id`* |
| `list_calendar_event_tags` | Event tags on a managed calendar | `calendar_id`* |
| `list_membership_tiers` | Membership tiers of a managed calendar | `calendar_id`*, `limit`, `cursor` |
| `list_guests` | Guests of a managed event | `event_id`*, `approval_status`, `query`, `limit`, `cursor` |
| `get_guest` | One guest of a managed event | `event_id`*, `id`* |
| `list_blasts` | Emails sent to a managed event's guests | `event_id`* |
| `list_coupons` | Coupons on a managed event or calendar | `event_id` or `calendar_id`, `limit`, `cursor` |
| `list_event_feedback` | Written feedback on a managed event | `event_id`*, `limit`, `cursor` |
| `get_event_feedback_summary` | Rating counts for a managed event | `event_id`* |
| `list_organizations` | Organizations the user admins | none |
| `list_organization_admins` | Admins of an organization | `organization_id`* |
| `list_organization_calendars` | Calendars in an organization | `organization_id`*, `limit`, `cursor` |
| `search_people` | People to invite to a managed event | `event_id`*, `query`, `limit`, `cursor` |
| `search_places` | Google Maps venue search (for creating events) | `query`* |
| `search_cover_images` | Stock cover images (for creating events) | `query`*, `limit`, `cursor` |

### Tools that change something (48): the skill must never call these

Required parameters are listed. Most also take many optional fields.

| Tool | What it changes | Required parameters |
|---|---|---|
| `create_event` / `update_event` | Creates or edits an event | `name`, `start_at`, `timezone` / `event_id` |
| `create_calendar` / `update_calendar` | Creates or edits a team calendar | `name` / `calendar_id` |
| `add_calendar_event` / `remove_calendar_events` | Lists or unlists events on a calendar | `calendar_id`, `event` / `calendar_event_ids` |
| `approve_calendar_events` / `reject_calendar_events` | Handles event submissions | `calendar_id`, `calendar_event_ids` |
| `add_calendar_to_organization` | Moves a calendar into an organization | `organization_id`, `calendar_id` |
| `add_calendar_admins` / `remove_calendar_admins` | Calendar admins | `calendar_id`, `emails` |
| `add_organization_admins` / `remove_organization_admins` | Organization admins | `organization_id`, `emails` |
| `add_host` / `update_host` / `remove_host` | Event hosts | `event_id`, `email` |
| `invite_guests` | Emails invites | `event_id`, `guests` |
| `update_guest_status` | Approves, declines or waitlists a guest | `event_id`, `guest_id`, `status` |
| `update_guest_tickets` | Adds or removes a guest's tickets | `event_id`, `guest_id` |
| `create_blast` / `update_blast` / `delete_blast` | Emails to guests | `event_id`, `content_md` / `blast_id` / `blast_id` |
| `create_ticket_type` / `update_ticket_type` / `delete_ticket_type` | Ticket types | `name`, `type`, `event_id` / `ticket_type_id` / `ticket_type_id` |
| `create_coupon` / `update_coupon` | Coupons | `code`, `discount` / `coupon_id` |
| `add_registration_question` / `update_registration_question` / `delete_registration_question` / `reorder_registration_questions` | Registration questions | `event_id` plus `question`, `question_id` or `question_ids` |
| `import_calendar_contacts` | Adds contacts | `calendar_id`, `contacts` |
| `update_calendar_contact_status` | Removes, blocks or restores a contact | `calendar_id`, `contact`, `status` |
| `add_to_membership` / `update_membership_status` | Memberships | `calendar_id`, `email`, `membership_tier_id` / `calendar_id`, `contact`, `status` |
| `create_calendar_contact_tag` / `update_calendar_contact_tag` / `delete_calendar_contact_tag` | Contact tags | `calendar_id` plus `name` or `tag_id` |
| `apply_calendar_contact_tag` / `unapply_calendar_contact_tag` | Tags or untags contacts | `calendar_id`, `tag`, `contacts` |
| `create_calendar_event_tag` / `update_calendar_event_tag` / `delete_calendar_event_tag` | Event tags | `calendar_id` plus `name` or `tag_id` |
| `apply_calendar_event_tag` / `unapply_calendar_event_tag` | Tags or untags events | `calendar_id`, `tag`, `event_ids` |
| `update_self` | The user's public profile | none (all optional) |
| `create_image_upload_url` | Creates a CDN upload URL | `content_type` |
| `send_feedback` | Sends a note to the Luma team | `kind`, `message` |

`send_feedback`'s own description tells the model to call it unprompted when a tool fails. The skill
should say explicitly whether that is allowed. My recommendation: don't call it without asking the
user, since it sends text to Luma.

## 2. Your events (past): `list_events(period: "past")`

- **Count:** 58 past events across 2 pages (50 + 8). `status: "host"` returned 0.
- **Paging:** `limit` max 50, response is `{ entries, has_more, next_cursor }`. Pass `next_cursor` back
  as `cursor`. Past events sort newest-first. `after` / `before` filter on start time.
- **Size:** one page of 50 is about 110 KB of JSON, too big for one Claude Code tool result (it spilled
  to a file). Use `limit: 20` or less, or `after: <last_profiled_at>` to fetch only new events.
- **Fields on each entry:** `api_id`, `name`, `cover_url`, `start_at`, `end_at`, `timezone`,
  `location_type`, `geo_address_info`, `virtual_info`, `visibility`, `url`, `calendar`, `hosts`,
  `guest_count`, `ticket_info`, `manager_info`, `host_info`, `guest_info`.
- **`evt-` ID:** yes, `api_id` always starts with `evt-`.
- **Calendar:** always `calendar: { api_id, name, slug }`. `slug` is `null` for 12 of 50 (mostly
  calendars named "Personal", which are a host's own calendar). `api_id` is always present.
- **Host vs guest:** `host_info` / `manager_info` are non-null only when the user hosts or manages the
  event, and `status: "host"` filters to those. All 58 here were guest entries.
- **Registration status:** `guest_info.approval_status`. Across the 58 past events: `approved` 37,
  `pending_approval` 12, `waitlist` 8, `invited` 1. `declined` is left out unless asked for.
  **No check-in field exists**, so "attended" can only mean "had a registration".
- **No description, tags or category** in the list. `get_event` (guest view) adds `description_md` and
  `registration_availability`, at one call per event.

Example shape (made up):

```json
{
  "api_id": "evt-AbCdEf123456789",
  "name": "<event title>",
  "start_at": "2026-01-15T18:00:00.000Z",
  "end_at": "2026-01-15T21:00:00.000Z",
  "timezone": "Europe/Example",
  "location_type": "offline",
  "url": "https://luma.com/abcd1234",
  "calendar": { "api_id": "cal-AbCdEf123456789", "name": "<calendar name>", "slug": "<slug or null>" },
  "hosts": [{ "api_id": "usr-…", "name": "<host>" }],
  "ticket_info": { "is_free": true, "is_sold_out": false, "require_approval": true },
  "host_info": null,
  "manager_info": null,
  "guest_info": { "approval_status": "approved" }
}
```

## 3. Your events (upcoming): `list_events(period: "future")`

- **Count:** 9 upcoming, one page (`has_more: false`). Sorted soonest-first.
- **Fields:** same as past. `start_at`, `end_at` and `timezone` are always present, which is enough
  for a clash check.
- **Status split:** `approved` 4, `pending_approval` 5.
- **ID match with iCal:** iCal `UID` is `evt-XXXX@events.lu.ma`, and stripping `@events.lu.ma` gives the
  connector's `api_id`. An ID from this list was found in the test calendar's feed. So "events the
  user isn't registered for" = feed IDs minus the `list_events(future)` IDs.

## 4. Discover search: `search_events`

- **`query` is required.** A location-only search is not possible. The skill has to run one search per
  interest or keyword.
- **Location:** `location` is free text ("<neighbourhood>", "<city>, <country>", a landmark). It's
  geocoded server-side and echoed back as `resolved_location { name, formatted_address, coordinate,
  bounds }`. Check it matches what the user meant. The other option is `latitude` + `longitude`, which
  ranks nearby events first but doesn't exclude others. Don't combine the two.
- **Dates:** `after` / `before` are optional. Only upcoming events are searchable, so "no time frame"
  just means leaving them out.
- **Limit and paging:** no `limit` or `cursor`. Each call returned one ranked page of **10** events.
- **Fields:** same entry shape as `list_events`, including `api_id` (`evt-`), `calendar { api_id,
  name, slug }`, `hosts`, `ticket_info`.
- **Registration is marked:** `guest_info` is `null` for events the user hasn't registered for and
  `{ approval_status }` for ones they have, so search results need no extra diff.

### Web alternatives tested (no connector)

| Source | What came back | Verdict |
|---|---|---|
| General web search (`WebSearch`, limited to luma.com) | 10 links, mixing events from past years, undated pages and calendar pages. No registration status, no reliable dates | Not usable as the main source |
| Luma city iCal feed (`https://api.lu.ma/ics/get?entity=discover&id=<discplace-…>`, the place ID read from the city page `luma.com/<city>`) | 50 events, all in the **next ~10 days**, titled "What's Happening in <city>" | A curated, capped subset. It had **0 of the 10** events the connector's `search_events("ai")` found, even though several fall inside its window |
| Luma city page HTML (`luma.com/<city>`) | 20 events embedded in `__NEXT_DATA__` | Even smaller than the feed |

### Getting past the 10-result cap

| Test (`query: "ai"`, large city) | Result |
|---|---|
| No date window | 10 events, spread over the coming weeks |
| `after`/`before` = one week | 10 **different** events, all inside that week (0 overlap with the unwindowed 10) |
| `after`/`before` = one day | 10 events, all on that day. **The cap is hit even for a single day** (2 overlap with the unwindowed 10) |
| Luma's public discover endpoint (`api.luma.com/discover/get-paginated-events?slug=<city>`, paginated, no login) | 67 events over ~4 weeks, 2 pages. Only 1–2 of each connector set of 10 were in it, so it's a curated subset too |

So `search_events` has by far the widest coverage, and date windows are the lever:

- **Split windows until under the cap:** search a week. If it returns 10, split it into days. A window
  that returns fewer than 10 is complete for that query.
- **Use narrow queries** ("agents", "hackathon", "evals", "founders") rather than one broad word, because
  a broad word can hit the cap within a single day where most events start at the same hour.
- **Cost:** each call returns about 25 KB of JSON (much of it `geo_address_info`). Run the searches
  in a subagent that hands back a compact list (`api_id`, name, start, calendar, url, `guest_info`)
  so the main conversation stays small, and cap the number of calls per run.

**Verdict:** keep `search_events` as the discovery source. The required `query` isn't really a
limitation: the profile's interest tags plus the user's keywords become the queries, which is the
personalization anyway. The city feed is an optional broad net for the next ~10 days (things outside
known interests), deduped and checked against `list_events(future)` like any feed.

## 5. Calendar lookup by link: `lookup_entity` and `list_calendar_events`

Test input: the public calendar `https://luma.com/encode-club`.

- `lookup_entity` returned **only basic info**, with no events:

  ```json
  { "entity": { "type": "calendar",
                "calendar": { "id": "cal-…", "name": "…", "slug": "…", "avatar_url": "…" } } }
  ```

- `list_calendar_events` on that calendar ID returned the error
  **"You don't have manage access to this calendar."**
- The iCal feed (`https://api.lu.ma/ics/get?entity=calendar&id=<cal_id>`, fetched with curl, no login)
  returned `200 text/calendar` with 246 `VEVENT`s, **26 of them in the future**. VEVENT fields:
  `UID`, `SUMMARY`, `DESCRIPTION`, `DTSTART`, `DTEND`, `DTSTAMP`, `LOCATION`, `GEO`, `ORGANIZER`,
  `STATUS`, `SEQUENCE`.
- Feed quirks:
  - 245 UIDs are `evt-…@events.lu.ma`, and 1 is `calev-…@events.lu.ma`, an external listing with no Luma
    event. Skip it, or show it with its link but no registration status.
  - Past history in the feed is **incomplete**: there's a gap of more than a year before the current
    month. Use the feed for **future events only**, never as history.
  - `STATUS` is `TENTATIVE` for every event, so it means nothing.
  - The URL format is not documented. Luma's help page documents only the "Add iCal Subscription"
    button.

**Verdict:** iCal is still needed for followed calendars. The connector does replace the HTML step:
`lookup_entity(<pasted link>)` gives the `cal-` ID officially, and the iCal URL is built from that.

## 6. Following a host account (`luma.com/user/<username>`)

Test input: the public host profile of an organization that runs meetups in many cities.

| Source | Result |
|---|---|
| Connector `lookup_entity("https://luma.com/user/<username>")` | `{ "entity": null }`. User profiles aren't supported |
| Profile page HTML | No events embedded; they load client-side |
| iCal `entity=user&id=usr-…` | 404 |
| `GET https://api.luma.com/user/profile?username=<username>` (no login) | 200, gives `user.api_id` (`usr-…`) |
| `GET https://api.luma.com/user/profile/events-hosting?user_api_id=<usr-…>&period=future&pagination_limit=50` (no login) | 200, `{ entries, has_more, next_cursor }`, here 27 upcoming hosted events with `evt-` IDs and `start_at` |

These two endpoints are the ones luma.com's own profile page calls. They're undocumented, so they
carry the same "might change" risk as the iCal URL. They need no login, so the script can call them
and they cost no tokens.

Hosts can be global: this one's 27 events were spread across many cities. The script has to filter
by the user's city (from `geo_address_info` or the coordinates) and by the 2-week window.

## What this means for the design

1. **Followed calendars (one-time setup per calendar):** the user pastes a calendar link, the skill
   calls `lookup_entity`, and the script stores the result. No HTML parsing and no browser.

   ```json
   "followed_calendars": [{
     "url": "https://luma.com/<slug>",
     "cal_id": "cal-AbCdEf123456789",
     "name": "<calendar name>",
     "slug": "<slug>",
     "ics": "https://api.lu.ma/ics/get?entity=calendar&id=cal-AbCdEf123456789",
     "added_at": "2026-11-09"
   }]
   ```

2. **Each run, followed calendars:** the script downloads each `ics`, keeps future `evt-` events, and
   strips `@events.lu.ma`. The skill then removes any ID that appears in `list_events(future)`, and
   what's left is "not registered yet".
3. **Each run, discovery:** run several `search_events(query, location)` calls, one per profile
   interest or keyword. Merge them by `api_id`. `guest_info == null` means not registered. Expect at
   most 10 results per query.
4. **Profile refresh (the 5-new-events rule):** use
   `list_events(period: "past", after: <last_profiled_at>, limit: 20)` to fetch only new events, and
   dedupe against `seen_event_ids`. Titles, calendar names and hosts are enough to profile. Call
   `get_event` for `description_md` only on the new events, at most a handful per refresh. The first
   run needs about 3 pages of 20 for this account's 58 past events.
5. **What counts as "attended":** every past entry, whatever its `approval_status`, plus hosted events,
   as the user decided. There is no check-in signal to filter on anyway.
6. **Clash check:** one `list_events(period: "future")` call per run gives `start_at`, `end_at` and
   `timezone` for every registration. Flag overlaps, and mark `pending_approval` / `waitlist`
   differently from `approved`. Fetch this fresh each run instead of caching it.
7. **State file:** store IDs, calendar links and the profile only. Don't store `geo_address_info`,
   host names or guest data. Approved events include exact addresses, and none of that is needed
   later.
8. **Read-only guard:** the skill's instructions should allow only `list_events`, `get_event`,
   `search_events`, `lookup_entity` and `get_self`, and forbid the 48 write tools, including
   `send_feedback`.

## Tool calls made in this test

`list_events` ×4 (future; past page 1; past page 2; past with `status: "host"`), `get_event` ×1,
`search_events` ×2, `lookup_entity` ×1, `list_calendar_events` ×1 (returned the access error).
No write tools.
