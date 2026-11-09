# Manual test checklist

Run these after installing the plugin and signing in (`/mcp` → `plugin:luma-event-scout:luma`).
They cover what the automated tests can't: the live connector, the sub-agents and the skill's flow.

To keep your real settings safe while testing, you can point the script at a throwaway file:
`python3 <skill-dir>/scripts/scout.py --state /tmp/scout-test.json …`.

| # | Do | Expect |
|---|---|---|
| 1 | Fresh start: ask "find me Luma events this week" with no state file | Claude asks once for city, exactly 3 keywords, calendar links and host links |
| 2 | Answer with a city, 3 keywords, one public calendar link and one `luma.com/user/<name>` link | Probe search confirms the city; `state.json` has 1 calendar and 1 host; a profile is built; the run continues straight to results |
| 3 | Look at `~/.config/luma-event-scout/state.json` | No addresses, coordinates of events, guest names or registrations; file mode is `600` |
| 4 | Ask again ("what's on?") | No setup questions; the first line is the one-line summary; the list is sorted by date with links |
| 5 | Check the list | Calendar and host events you're not registered for all appear; events you're registered for don't; a clash shows "⚠ clashes with …"; sold-out events say so |
| 6 | Register for 5 events on Luma that have already ended (or use a test state with 5 IDs removed from `seen_event_ids`), then run again | The run reports a profile refresh; `last_profiled_at` moves forward; the 2 generated keywords may change |
| 7 | With fewer than 5 new events, run again | No refresh; the profile is unchanged |
| 8 | Add a calendar with a wrong ID: `scout.py calendars add --url https://luma.com/x --cal-id cal-doesnotexist --name X --slug x`, then run | The run still finishes; the "Skipped:" line names `calendar:x` |
| 9 | Ask "search Berlin this time" | Results are for Berlin; `state.json` still says your own city |
| 10 | Say "change" and replace your keywords | `user_keywords` updates; profile, calendars and hosts are kept |
| 11 | Say "change" and try a keyword equal to a generated one | Claude regenerates the generated keywords and then saves yours |
| 12 | Revoke the Luma connection (`/mcp`) and run | Claude says to sign in again and stops; nothing is written |
| 13 | Corrupt the state file (add a stray character) and run | Claude shows the error, doesn't overwrite the file, and offers to set up again |
