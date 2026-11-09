from __future__ import annotations

import copy
import json
import stat

import pytest

from scout_lib import state as st
from scout_lib.state import StateError

NOW = "2026-11-09T00:00:00Z"


@pytest.fixture
def base(location, keywords):
    return st.new_state(location, keywords)


def test_new_state_has_version_keywords_and_empty_lists(base):
    assert base["version"] == 1
    assert base["user_keywords"] == ["ai", "founders", "hackathon"]
    assert base["followed_calendars"] == []
    assert base["followed_hosts"] == []
    assert base["profile"] is None
    assert base["seen_event_ids"] == []


@pytest.mark.parametrize("kws", [["a", "b"], ["a", "b", "c", "d"]])
def test_new_state_rejects_wrong_keyword_count(location, kws):
    with pytest.raises(StateError):
        st.new_state(location, kws)


def test_new_state_rejects_duplicate_keywords(location):
    with pytest.raises(StateError):
        st.new_state(location, ["AI", " ai ", "x"])


def test_new_state_rejects_location_without_bounds(location, keywords):
    bad = {k: v for k, v in location.items() if k != "bounds"}
    with pytest.raises(StateError):
        st.new_state(bad, keywords)


def test_save_then_load_round_trips(tmp_path, base):
    path = tmp_path / "cfg" / "state.json"
    st.save_state(path, base)
    assert st.load_state(path) == base


def test_save_is_atomic_and_private(tmp_path, base):
    path = tmp_path / "state.json"
    st.save_state(path, base)
    st.save_state(path, base)
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_load_missing_returns_none(tmp_path):
    assert st.load_state(tmp_path / "nope.json") is None


def test_load_corrupt_raises_and_keeps_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"version": 1, "user_keyw')
    before = path.read_bytes()
    with pytest.raises(StateError):
        st.load_state(path)
    assert path.read_bytes() == before


def test_load_newer_version_raises(tmp_path, base):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({**base, "version": 2}))
    with pytest.raises(StateError):
        st.load_state(path)


def test_with_calendar_does_not_mutate_input(base, calendar):
    snapshot = copy.deepcopy(base)
    updated = st.with_calendar(base, calendar)
    assert base == snapshot
    assert updated["followed_calendars"] == [calendar]


def test_with_calendar_replaces_same_cal_id(base, calendar):
    once = st.with_calendar(base, calendar)
    twice = st.with_calendar(once, {**calendar, "name": "Renamed"})
    assert [c["name"] for c in twice["followed_calendars"]] == ["Renamed"]


def test_without_calendar_unknown_slug_raises(base):
    with pytest.raises(StateError):
        st.without_calendar(base, "missing")


def test_without_calendar_removes(base, calendar):
    removed = st.without_calendar(st.with_calendar(base, calendar), "test-cal")
    assert removed["followed_calendars"] == []


def test_with_host_does_not_mutate_input(base, host):
    snapshot = copy.deepcopy(base)
    updated = st.with_host(base, host)
    assert base == snapshot
    assert updated["followed_hosts"] == [host]


def test_with_host_replaces_same_user_id(base, host):
    once = st.with_host(base, host)
    twice = st.with_host(once, {**host, "name": "Renamed"})
    assert [h["name"] for h in twice["followed_hosts"]] == ["Renamed"]


def test_without_host_unknown_username_raises(base):
    with pytest.raises(StateError):
        st.without_host(base, "missing")


def test_without_host_removes(base, host):
    removed = st.without_host(st.with_host(base, host), "test_hosts")
    assert removed["followed_hosts"] == []


def test_new_event_ids_dedupes_and_skips_seen(base, profile):
    seen = st.with_profile(base, profile, ["evt-a"], NOW)
    assert st.new_event_ids(seen, ["evt-a", "evt-b", "evt-b", "evt-c"]) == ["evt-b", "evt-c"]


def test_with_profile_sets_seen_and_timestamp(base, profile):
    snapshot = copy.deepcopy(base)
    updated = st.with_profile(base, profile, ["evt-a", "evt-b"], NOW)
    assert base == snapshot
    assert updated["profile"]["last_profiled_at"] == NOW
    assert updated["profile"]["generated_keywords"] == ["tech", "startups"]
    assert updated["seen_event_ids"] == ["evt-a", "evt-b"]


def test_with_profile_merges_seen_ids_without_duplicates(base, profile):
    once = st.with_profile(base, profile, ["evt-a"], NOW)
    twice = st.with_profile(once, profile, ["evt-a", "evt-b"], NOW)
    assert twice["seen_event_ids"] == ["evt-a", "evt-b"]


def test_with_profile_rejects_generated_equal_to_user_keyword(base, profile):
    with pytest.raises(StateError):
        st.with_profile(base, {**profile, "generated_keywords": ["AI", "tech"]}, [], NOW)


def test_with_profile_rejects_wrong_generated_count(base, profile):
    with pytest.raises(StateError):
        st.with_profile(base, {**profile, "generated_keywords": ["tech"]}, [], NOW)


def test_with_profile_rejects_weight_out_of_range(base, profile):
    bad = {**profile, "interests": [{"tag": "x", "weight": 1.5, "evidence_count": 1}]}
    with pytest.raises(StateError):
        st.with_profile(base, bad, [], NOW)


def test_with_profile_rejects_missing_summary(base, profile):
    with pytest.raises(StateError):
        st.with_profile(base, {**profile, "summary": "  "}, [], NOW)


def test_all_keywords_user_then_generated(base, profile):
    assert st.all_keywords(base) == ["ai", "founders", "hackathon"]
    full = st.with_profile(base, profile, [], NOW)
    assert st.all_keywords(full) == ["ai", "founders", "hackathon", "tech", "startups"]


def test_summary_line(base, calendar, host, profile):
    empty = 'Testville · 3 keywords + 0 generated · 0 calendars · 0 hosts. Say "change" to edit.'
    assert st.summary_line(base) == empty
    second = {**calendar, "cal_id": "cal-T2", "slug": "other"}
    full = st.with_profile(base, profile, [], NOW)
    full = st.with_host(st.with_calendar(st.with_calendar(full, calendar), second), host)
    expected = 'Testville · 3 keywords + 2 generated · 2 calendars · 1 host. Say "change" to edit.'
    assert st.summary_line(full) == expected


def test_with_user_keywords_replaces_and_keeps_the_rest(base, calendar, profile):
    full = st.with_profile(st.with_calendar(base, calendar), profile, ["evt-a"], NOW)
    snapshot = copy.deepcopy(full)
    updated = st.with_user_keywords(full, ["design", "music", "climate"])
    assert full == snapshot
    assert updated["user_keywords"] == ["design", "music", "climate"]
    assert updated["profile"] == full["profile"]
    assert updated["followed_calendars"] == full["followed_calendars"]


def test_with_user_keywords_rejects_generated_collision(base, profile):
    full = st.with_profile(base, profile, [], NOW)
    with pytest.raises(StateError, match="generated"):
        st.with_user_keywords(full, ["Tech", "music", "climate"])


def test_with_user_keywords_rejects_wrong_count(base):
    with pytest.raises(StateError):
        st.with_user_keywords(base, ["one", "two"])


def test_with_location_validates_and_keeps_the_rest(base, location):
    moved = st.with_location(base, {**location, "name": "Otherville"})
    assert moved["location"]["name"] == "Otherville"
    assert moved["user_keywords"] == base["user_keywords"]
    with pytest.raises(StateError):
        st.with_location(base, {**location, "timezone": ""})


def test_with_profile_keeps_only_known_fields(base, profile):
    noisy = {
        **profile,
        "top_hosts": ["A Person"],
        "home_address": "1 Road",
        "interests": [{"tag": "agents", "weight": 0.8, "evidence_count": 6, "host": "Someone"}],
    }
    stored = st.with_profile(base, noisy, [], NOW)["profile"]
    assert set(stored) == {"summary", "interests", "generated_keywords", "built_from_events", "last_profiled_at"}
    assert stored["interests"] == [{"tag": "agents", "weight": 0.8, "evidence_count": 6}]


def test_with_generated_keywords_replaces_only_them(base, profile):
    full = st.with_profile(base, profile, ["evt-a"], NOW)
    updated = st.with_generated_keywords(full, ["culture", "science"])
    assert updated["profile"]["generated_keywords"] == ["culture", "science"]
    assert updated["profile"]["summary"] == full["profile"]["summary"]
    assert updated["profile"]["last_profiled_at"] == NOW
    assert updated["seen_event_ids"] == ["evt-a"]
    assert full["profile"]["generated_keywords"] == ["tech", "startups"]


def test_with_generated_keywords_needs_profile_and_distinct_words(base, profile):
    with pytest.raises(StateError, match="profile"):
        st.with_generated_keywords(base, ["culture", "science"])
    full = st.with_profile(base, profile, [], NOW)
    with pytest.raises(StateError):
        st.with_generated_keywords(full, ["AI", "science"])


def test_normalize_keyword():
    assert st.normalize_keyword("  Machine   LEARNING ") == "machine learning"
