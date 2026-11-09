from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "mcp__plugin_luma-event-scout_luma__"
ALLOWED_LUMA_TOOLS = {"list_events", "get_event", "search_events", "lookup_entity", "get_self"}
TOOL_PATTERN = re.compile(re.escape(PREFIX) + r"(\w+)")


def frontmatter(path: Path) -> tuple:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    head, body = text[4:].split("\n---\n", 1)
    fields = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body


def agent_files() -> list:
    return sorted((ROOT / "agents").glob("*.md"))


def test_plugin_manifest():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "luma-event-scout"
    assert manifest["version"] and manifest["description"]


def test_marketplace_lists_plugin():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert market["name"] and market["owner"]["name"]
    assert [(p["name"], p["source"]) for p in market["plugins"]] == [("luma-event-scout", "./")]


def test_mcp_declares_luma_http():
    config = json.loads((ROOT / ".mcp.json").read_text())
    assert config["mcpServers"]["luma"] == {"type": "http", "url": "https://mcp.luma.com"}


def test_agents_use_haiku_and_allowed_tools_only():
    names = set()
    for path in agent_files():
        fields, body = frontmatter(path)
        names.add(fields["name"])
        assert fields["model"] == "haiku", path
        assert fields["description"], path
        tools = [t.strip() for t in fields["tools"].split(",")]
        luma = [t for t in tools if t.startswith(PREFIX)]
        others = [t for t in tools if not t.startswith(PREFIX)]
        assert others == ["Write"], path
        assert len(luma) == 1 and luma[0][len(PREFIX):] in ALLOWED_LUMA_TOOLS, path
        assert "output_path" in body, path
    assert names == {"luma-day-searcher", "luma-history-reader"}


def test_no_forbidden_luma_tool_named_anywhere():
    files = [*agent_files(), *ROOT.glob("skills/**/SKILL.md")]
    assert files
    for path in files:
        for tool in TOOL_PATTERN.findall(path.read_text(encoding="utf-8")):
            assert tool in ALLOWED_LUMA_TOOLS, f"{path} names forbidden tool {tool}"
