from __future__ import annotations

import pytest


@pytest.fixture
def location() -> dict:
    return {
        "query": "Testville, TL",
        "name": "Testville",
        "timezone": "Europe/London",
        "bounds": {"north": 51.7, "south": 51.3, "east": 0.2, "west": -0.5},
    }


@pytest.fixture
def keywords() -> list:
    return ["ai", "founders", "hackathon"]


@pytest.fixture
def calendar() -> dict:
    return {
        "url": "https://luma.com/test-cal",
        "cal_id": "cal-T1",
        "name": "Test Calendar",
        "slug": "test-cal",
        "ics": "https://api.lu.ma/ics/get?entity=calendar&id=cal-T1",
        "added_at": "2026-11-09",
    }


@pytest.fixture
def host() -> dict:
    return {
        "url": "https://luma.com/user/test_hosts",
        "username": "test_hosts",
        "user_id": "usr-HOST1",
        "name": "Test Hosts",
        "added_at": "2026-11-09",
    }


@pytest.fixture
def profile() -> dict:
    return {
        "summary": "Likes technical meetups.",
        "interests": [{"tag": "agents", "weight": 0.8, "evidence_count": 6}],
        "generated_keywords": ["tech", "startups"],
        "built_from_events": 58,
    }
