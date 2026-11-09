from __future__ import annotations

from scout_lib.merge import find_clashes, merge_candidates


def rec(api_id, start, end, source="discovery:ai", name=None, registered=None, sold_out=None):
    return {
        "api_id": api_id, "name": name or api_id, "start_at": start, "end_at": end,
        "url": f"https://luma.com/{api_id}", "calendar": "C", "source": source,
        "online": None, "sold_out": sold_out, "registered": registered, "clash_with": [],
    }


def reg(api_id, start, end, status="approved", name=None):
    return {"api_id": api_id, "name": name or api_id, "start_at": start, "end_at": end,
            "approval_status": status}


def disc(events, keyword="ai", failed=()):
    return {"keyword": keyword, "events": events, "failed_days": list(failed)}


NO_FEEDS = {"events": [], "failures": [], "skipped_external": 0}


def test_dedupe_prefers_followed_source():
    d = disc([rec("evt-1", "2026-11-10T18:00:00Z", None, sold_out=True)])
    feeds = {**NO_FEEDS, "events": [rec("evt-1", "2026-11-10T18:00:00Z", None, source="calendar:c")]}
    result = merge_candidates([d], feeds, [])
    assert [c["source"] for c in result["candidates"]] == ["calendar:c"]
    assert result["candidates"][0]["sold_out"] is True
    assert result["counts"]["duplicates"] == 1


def test_dedupe_across_discovery_keywords():
    a = disc([rec("evt-1", "2026-11-10T18:00:00Z", None)], keyword="ai")
    b = disc([rec("evt-1", "2026-11-10T18:00:00Z", None, source="discovery:tech")], keyword="tech")
    result = merge_candidates([a, b], NO_FEEDS, [])
    assert [c["source"] for c in result["candidates"]] == ["discovery:ai"]


def test_drops_registered_keeps_invited():
    d = disc([
        rec("evt-2", "2026-11-10T10:00:00Z", None),
        rec("evt-3", "2026-11-10T11:00:00Z", None),
        rec("evt-4", "2026-11-10T12:00:00Z", None, registered="waitlist"),
        rec("evt-5", "2026-11-10T13:00:00Z", None),
    ])
    registered = [
        reg("evt-2", "2026-11-10T10:00:00Z", None),
        reg("evt-3", "2026-11-10T11:00:00Z", None, status="invited"),
    ]
    result = merge_candidates([d], NO_FEEDS, registered)
    by_id = {c["api_id"]: c for c in result["candidates"]}
    assert set(by_id) == {"evt-3", "evt-5"}
    assert by_id["evt-3"]["registered"] == "invited"
    assert result["counts"]["dropped_registered"] == 2


def test_hosted_events_count_as_registered():
    d = disc([rec("evt-6", "2026-11-10T10:00:00Z", None)])
    result = merge_candidates([d], NO_FEEDS, [reg("evt-6", "2026-11-10T10:00:00Z", None, "host")])
    assert result["candidates"] == []


def test_clash_detected_and_named():
    candidate = rec("evt-c", "2026-11-10T18:00:00Z", "2026-11-10T21:00:00Z")
    registered = [reg("evt-r", "2026-11-10T19:00:00Z", "2026-11-10T20:00:00Z", name="Other")]
    assert find_clashes(candidate, registered) == [{"api_id": "evt-r", "name": "Other"}]


def test_invited_event_is_not_a_clash():
    candidate = rec("evt-c", "2026-11-10T18:00:00Z", "2026-11-10T21:00:00Z")
    registered = [reg("evt-r", "2026-11-10T19:00:00Z", "2026-11-10T20:00:00Z", status="invited")]
    assert find_clashes(candidate, registered) == []


def test_clash_with_missing_end_uses_two_hours():
    registered = [reg("evt-r", "2026-11-10T18:00:00Z", None)]
    inside = rec("evt-a", "2026-11-10T19:30:00Z", "2026-11-10T20:00:00Z")
    after = rec("evt-b", "2026-11-10T20:00:00Z", "2026-11-10T21:00:00Z")
    assert find_clashes(inside, registered) == [{"api_id": "evt-r", "name": "evt-r"}]
    assert find_clashes(after, registered) == []


def test_candidate_without_end_uses_two_hours():
    registered = [reg("evt-r", "2026-11-10T19:59:00Z", "2026-11-10T21:00:00Z")]
    assert find_clashes(rec("evt-a", "2026-11-10T18:00:00Z", None), registered) != []


def test_clash_across_midnight():
    candidate = rec("evt-c", "2026-11-10T23:00:00Z", "2026-11-11T01:00:00Z")
    registered = [reg("evt-r", "2026-11-11T00:30:00Z", "2026-11-11T02:00:00Z")]
    assert find_clashes(candidate, registered) == [{"api_id": "evt-r", "name": "evt-r"}]


def test_merge_fills_clashes_on_candidates():
    d = disc([rec("evt-c", "2026-11-10T18:00:00Z", "2026-11-10T21:00:00Z")])
    registered = [reg("evt-r", "2026-11-10T19:00:00Z", "2026-11-10T20:00:00Z", name="Other")]
    result = merge_candidates([d], NO_FEEDS, registered)
    assert result["candidates"][0]["clash_with"] == [{"api_id": "evt-r", "name": "Other"}]


def test_sorted_and_failures_listed():
    d = disc(
        [rec("evt-late", "2026-11-12T18:00:00Z", None), rec("evt-early", "2026-11-10T08:00:00Z", None)],
        failed=["2026-11-10"],
    )
    feeds = {"events": [rec("evt-mid", "2026-11-11T09:00:00Z", None, source="calendar:c")],
             "failures": [{"source": "calendar:c", "error": "boom"}], "skipped_external": 0}
    result = merge_candidates([d], feeds, [])
    assert [c["api_id"] for c in result["candidates"]] == ["evt-early", "evt-mid", "evt-late"]
    assert result["failures"] == ["calendar:c: boom", "discovery:ai 2026-11-10"]
    assert result["counts"]["candidates"] == 3


def test_merge_skips_malformed_records_and_files():
    good = rec("evt-1", "2026-11-10T18:00:00Z", None)
    nameless = {**rec("evt-2", "2026-11-10T18:00:00Z", None), "name": None}
    no_start = {k: v for k, v in rec("evt-3", "x", None).items() if k != "start_at"}
    bad_time = rec("evt-4", "not-a-time", None)
    no_source = {k: v for k, v in rec("evt-5", "2026-11-10T19:00:00Z", None).items() if k != "source"}
    files = [disc([good, nameless, no_start, bad_time, "junk", no_source]), ["not", "a", "result"]]
    registered = ["junk", {"api_id": "evt-r"}, reg("evt-ok", "2026-11-10T18:30:00Z", None)]
    result = merge_candidates(files, NO_FEEDS, registered)
    assert [c["api_id"] for c in result["candidates"]] == ["evt-2", "evt-1", "evt-5"]
    by_id = {c["api_id"]: c for c in result["candidates"]}
    assert by_id["evt-2"]["name"] == ""
    assert by_id["evt-5"]["source"] == "discovery:ai"
    assert by_id["evt-1"]["clash_with"] == [{"api_id": "evt-ok", "name": "evt-ok"}]
    assert "discovery:ai: skipped 3 malformed records" in result["failures"]
    assert "discovery result 2: not a discovery result" in result["failures"]


def test_merge_ignores_malformed_feeds():
    feeds = {"events": ["junk", rec("evt-f", "2026-11-10T10:00:00Z", None, source="calendar:c")],
             "failures": ["junk"]}
    result = merge_candidates([], feeds, [])
    assert [c["api_id"] for c in result["candidates"]] == ["evt-f"]
    assert "feeds: skipped 1 malformed record" in result["failures"]


def test_inputs_are_not_mutated():
    event = rec("evt-c", "2026-11-10T18:00:00Z", "2026-11-10T21:00:00Z")
    d = disc([event])
    merge_candidates([d], NO_FEEDS, [reg("evt-r", "2026-11-10T19:00:00Z", None)])
    assert event["clash_with"] == []
