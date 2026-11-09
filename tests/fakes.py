"""Test doubles for the HTTP layer: a scripted opener and a recording sleep."""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class _Response(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status


class FakeOpener:
    """Returns queued responses in order; an int queues an HTTP error with that status."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.requests: list = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if not self._responses:
            raise AssertionError(f"unexpected request: {request.full_url}")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, int):
            raise urllib.error.HTTPError(request.full_url, item, "error", {}, None)
        body = item if isinstance(item, bytes) else str(item).encode("utf-8")
        return _Response(body)

    @property
    def urls(self) -> list:
        return [r.full_url for r in self.requests]


class RoutingOpener:
    """Answers by URL prefix, so tests don't depend on request order."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.requests: list = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        for prefix, item in self.routes.items():
            if request.full_url.startswith(prefix):
                if isinstance(item, int):
                    raise urllib.error.HTTPError(request.full_url, item, "error", {}, None)
                if callable(item):
                    item = item(request)
                body = json.dumps(item) if isinstance(item, (dict, list)) else item
                return _Response(body.encode("utf-8"))
        raise AssertionError(f"no route for {request.full_url}")


class RecordingSleep:
    def __init__(self):
        self.calls: list = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
