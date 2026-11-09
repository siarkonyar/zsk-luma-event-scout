from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from fakes import RecordingSleep, RoutingOpener, fixture_text
from scout_lib.cli import main
from scout_lib.http import Fetcher

NOW = "2026-11-09T12:00:00Z"
ROOT = Path(__file__).resolve().parent.parent
INIT = [
    "init", "--location-query", "Testville, TL", "--location-name", "Testville",
    "--timezone", "Europe/London", "--bounds", "51.7", "51.3", "0.2", "-0.5",
    "--keywords", "ai", "founders", "hackathon",
]


def host_pages(request):
    query = parse_qs(urlparse(request.full_url).query)
    name = "host_events_page2.json" if "pagination_cursor" in query else "host_events_page1.json"
    return json.loads(fixture_text(name))


def fake_fetcher():
    routes = {
        "https://api.lu.ma/ics/get": fixture_text("calendar.ics"),
        "https://api.luma.com/user/profile/events-hosting": host_pages,
        "https://api.luma.com/user/profile": json.loads(fixture_text("host_profile.json")),
    }
    return Fetcher(opener=RoutingOpener(routes), sleep=RecordingSleep())


class Cli:
    def __init__(self, tmp_path, capsys):
        self.state = tmp_path / "config" / "state.json"
        self.run_dir = tmp_path / "run"
        self.tmp = tmp_path
        self.capsys = capsys

    def __call__(self, *args):
        argv = ["--state", str(self.state), "--run-dir", str(self.run_dir), "--now", NOW, *args]
        code = main(argv, fetcher=fake_fetcher())
        out, err = self.capsys.readouterr()
        return code, (json.loads(out) if out.strip() else None), err

    def write(self, name, data):
        path = self.tmp / name
        path.write_text(json.dumps(data))
        return str(path)


@pytest.fixture
def cli(tmp_path, capsys):
    return Cli(tmp_path, capsys)


def history(ids, period="past"):
    events = [{"api_id": i, "name": i, "start_at": "2026-10-01T18:00:00Z", "end_at": None,
               "calendar": "C", "hosts": [], "location_type": "offline",
               "approval_status": "approved"} for i in ids]
    return {"period": period, "events": events}


PROFILE = {
    "summary": "Likes builder meetups.",
    "interests": [{"tag": "agents", "weight": 0.9, "evidence_count": 4}],
    "generated_keywords": ["tech", "startups"],
    "built_from_events": 5,
}


def test_show_without_state_exits_3(cli):
    code, out, err = cli("show")
    assert code == 3 and out is None
    assert "no state" in err


def test_init_then_show(cli):
    assert cli(*INIT)[0] == 0
    code, out, _ = cli("show")
    assert code == 0
    assert out["summary"] == 'Testville · 3 keywords + 0 generated · 0 calendars · 0 hosts. Say "change" to edit.'
    assert out["keywords"] == ["ai", "founders", "hackathon"]
    assert out["has_profile"] is False and out["last_profiled_at"] is None


def test_init_refuses_overwrite_without_force(cli):
    cli(*INIT)
    code, _, err = cli(*INIT)
    assert code == 1 and "--force" in err
    assert cli(*INIT, "--force")[0] == 0


def test_init_rejects_bad_timezone(cli):
    bad = [a if a != "Europe/London" else "Mars/Olympus" for a in INIT]
    code, _, err = cli(*bad)
    assert code == 1 and "timezone" in err
    assert not cli.state.exists()


def test_bad_arguments_exit_2(cli):
    assert cli("init", "--keywords", "only-one")[0] == 2


def with_profile(cli):
    cli(*INIT)
    cli("calendars", "add", "--url", "https://luma.com/test-cal", "--cal-id", "cal-T1",
        "--name", "Test Calendar", "--slug", "test-cal")
    return cli("save-profile", cli.write("profile.json", PROFILE),
               "--history", cli.write("h.json", history(["evt-1"])))


def test_show_includes_stored_profile(cli):
    with_profile(cli)
    out = cli("show")[1]
    assert out["profile"]["summary"] == "Likes builder meetups."
    assert out["profile"]["interests"] == PROFILE["interests"]
    assert out["profile"]["built_from_events"] == 5


def test_show_profile_is_null_before_setup_finishes(cli):
    cli(*INIT)
    assert cli("show")[1]["profile"] is None


def test_set_generated_keeps_profile(cli):
    with_profile(cli)
    code, out, _ = cli("set-generated", "culture", "science")
    assert code == 0
    assert out["keywords"] == ["ai", "founders", "hackathon", "culture", "science"]
    assert out["profile"]["summary"] == "Likes builder meetups."


def test_set_generated_rejects_user_keyword(cli):
    with_profile(cli)
    code, _, err = cli("set-generated", "AI", "science")
    assert code == 1 and "repeat" in err


def test_set_keywords_keeps_profile_and_calendars(cli):
    with_profile(cli)
    code, out, _ = cli("set-keywords", "design", "music", "climate")
    assert code == 0
    assert out["keywords"] == ["design", "music", "climate", "tech", "startups"]
    assert len(out["calendars"]) == 1 and out["has_profile"] is True


def test_set_keywords_rejects_collision_with_generated(cli):
    with_profile(cli)
    code, _, err = cli("set-keywords", "tech", "music", "climate")
    assert code == 1 and "generated" in err


def test_set_location_keeps_profile(cli):
    with_profile(cli)
    code, out, _ = cli("set-location", "--location-query", "Otherville, OT", "--location-name",
                       "Otherville", "--timezone", "Europe/Berlin", "--bounds", "53", "52", "14", "13")
    assert code == 0
    assert out["location"]["name"] == "Otherville" and out["has_profile"] is True


def test_calendars_add_list_rm(cli):
    cli(*INIT)
    code, out, _ = cli("calendars", "add", "--url", "https://luma.com/test-cal", "--cal-id",
                       "cal-T1", "--name", "Test Calendar", "--slug", "test-cal")
    assert code == 0
    assert out["calendars"][0]["ics"].endswith("id=cal-T1")
    assert out["calendars"][0]["added_at"] == "2026-11-09"
    assert [c["slug"] for c in cli("calendars", "list")[1]] == ["test-cal"]
    assert cli("calendars", "rm", "test-cal")[1]["calendars"] == []
    assert cli("calendars", "rm", "test-cal")[0] == 1


def test_hosts_add_uses_resolver(cli):
    cli(*INIT)
    code, out, _ = cli("hosts", "add", "https://luma.com/user/test_hosts")
    assert code == 0
    assert out["hosts"][0]["user_id"] == "usr-HOST1"
    assert [h["username"] for h in cli("hosts", "list")[1]] == ["test_hosts"]
    assert cli("hosts", "rm", "test_hosts")[1]["hosts"] == []
    assert cli("hosts", "add", "https://luma.com/not-a-profile")[0] == 1


def test_windows_outputs_14_days(cli):
    cli(*INIT)
    code, out, _ = cli("windows")
    assert code == 0 and out["timezone"] == "Europe/London"
    assert len(out["windows"]) == 14
    assert out["windows"][0] == {"date": "2026-11-09", "after": "2026-11-09T00:00:00Z",
                                 "before": "2026-11-10T00:00:00Z"}
    tokyo = cli("windows", "--days", "2", "--timezone", "Asia/Tokyo")[1]
    assert tokyo["windows"][0]["after"] == "2026-11-08T15:00:00Z"


def test_new_events_and_refresh_flag(cli):
    with_profile(cli)
    five = cli("new-events", "--history", cli.write("h5.json", history(["evt-1", *[f"evt-n{i}" for i in range(5)]])))[1]
    assert five == {"count": 5, "new_ids": [f"evt-n{i}" for i in range(5)], "threshold": 5, "refresh": True}
    four = cli("new-events", "--history", cli.write("h4.json", history([f"evt-n{i}" for i in range(4)])))[1]
    assert four["count"] == 4 and four["refresh"] is False


def test_save_profile_then_show_has_5_keywords(cli):
    code, out, _ = with_profile(cli)
    assert code == 0
    assert out["keywords"] == ["ai", "founders", "hackathon", "tech", "startups"]
    assert out["last_profiled_at"] == NOW


def test_prepare_run_clears_json(cli):
    cli.run_dir.mkdir(parents=True)
    (cli.run_dir / "old.json").write_text("{}")
    (cli.run_dir / "keep.txt").write_text("x")
    code, out, _ = cli("prepare-run")
    assert code == 0 and out == {"run_dir": str(cli.run_dir)}
    assert sorted(p.name for p in cli.run_dir.iterdir()) == ["keep.txt"]


def test_feeds_and_merge_end_to_end(cli):
    cli(*INIT)
    cli("calendars", "add", "--url", "https://luma.com/test-cal", "--cal-id", "cal-T1",
        "--name", "Test Calendar", "--slug", "test-cal")
    cli("hosts", "add", "test_hosts")
    feeds_out = str(cli.tmp / "feeds.json")
    code, summary, _ = cli("feeds", "--out", feeds_out)
    assert code == 0
    assert summary == {"events": 7, "failures": [], "skipped_external": 1}
    discovery = cli.write("d1.json", {"keyword": "ai", "failed_days": [], "events": [{
        "api_id": "evt-X", "name": "Discovered", "start_at": "2026-11-10T18:00:00Z",
        "end_at": "2026-11-10T20:00:00Z", "url": "https://luma.com/x", "calendar": "Other",
        "source": "discovery:ai", "online": False, "sold_out": False, "registered": None,
        "clash_with": []}]})
    registered = cli.write("reg.json", history(["evt-A1"], period="future"))
    out_path = str(cli.tmp / "candidates.json")
    code, merged, _ = cli("merge", "--discovery", discovery, "--feeds", feeds_out,
                          "--registered", registered, "--out", out_path)
    assert code == 0
    assert merged["counts"] == {"candidates": 7, "dropped_registered": 1, "duplicates": 0}
    candidates = json.loads(Path(out_path).read_text())["candidates"]
    assert "evt-A1" not in {c["api_id"] for c in candidates}
    starts = [c["start_at"] for c in candidates]
    assert starts == sorted(starts)


def test_merge_tolerates_missing_and_bad_files(cli):
    discovery = cli.write("d1.json", {"keyword": "ai", "failed_days": [], "events": [{
        "api_id": "evt-X", "name": "Discovered", "start_at": "2026-11-10T18:00:00Z",
        "end_at": None, "url": "https://luma.com/x", "calendar": "Other", "source": "discovery:ai",
        "online": False, "sold_out": False, "registered": None, "clash_with": []}]})
    bad_feeds = cli.tmp / "feeds.json"
    bad_feeds.write_text("{not json")
    out_path = cli.tmp / "candidates.json"
    code, merged, _ = cli("merge", "--discovery", discovery, str(cli.tmp / "discovery-2.json"),
                          "--feeds", str(bad_feeds), "--registered", str(cli.tmp / "missing.json"),
                          "--out", str(out_path))
    assert code == 0
    assert merged["counts"]["candidates"] == 1
    failures = " | ".join(merged["failures"])
    assert "discovery file discovery-2.json: missing" in failures
    assert "feeds:" in failures
    assert "registered events (clash check skipped): missing" in failures
    assert json.loads(out_path.read_text())["failures"] == merged["failures"]


def test_feeds_city_override_does_not_change_state(cli):
    cli(*INIT)
    cli("hosts", "add", "test_hosts")
    before = cli.state.read_bytes()
    code, summary, _ = cli("feeds", "--location-name", "Otherville", "--bounds", "10", "9", "10", "9",
                           "--timezone", "Asia/Tokyo", "--out", str(cli.tmp / "f.json"))
    assert code == 0
    assert summary["events"] == 2  # the online event and the one with no place info
    assert cli.state.read_bytes() == before


def test_corrupt_state_fails_and_is_untouched(cli):
    cli.state.parent.mkdir(parents=True)
    cli.state.write_text('{"version": 1, "loca')
    before = cli.state.read_bytes()
    commands = [
        ["show"], ["set-keywords", "a", "b", "c"], ["calendars", "list"], ["hosts", "list"],
        ["windows"], ["new-events", "--history", cli.write("h.json", history([]))],
        ["feeds", "--out", str(cli.tmp / "f.json")], INIT,
    ]
    for command in commands:
        code, _, err = cli(*command)
        assert code == 1, command
        assert err.startswith("error:")
    assert cli.state.read_bytes() == before


def test_script_entry_runs(tmp_path):
    script = ROOT / "skills" / "luma-event-scout" / "scripts" / "scout.py"
    result = subprocess.run(
        [sys.executable, str(script), "--state", str(tmp_path / "s.json"), "show"],
        capture_output=True, text=True,
    )
    assert result.returncode == 3
    assert "no state" in result.stderr
