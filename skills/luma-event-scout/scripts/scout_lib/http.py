"""A small, polite HTTP client: one delay between calls, retries on transient errors."""
from __future__ import annotations

import json as _json
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

from .constants import HTTP_RETRIES, HTTP_TIMEOUT_S, REQUEST_DELAY_S, USER_AGENT

_ACCEPT = "application/json, text/calendar;q=0.9, */*;q=0.5"


class FetchError(Exception):
    """A request failed for good (after any retries)."""


def _is_retryable(status: int) -> bool:
    return status == 429 or status >= 500


class Fetcher:
    def __init__(
        self,
        opener=urllib.request.urlopen,
        sleep=time.sleep,
        delay_s: float = REQUEST_DELAY_S,
        retries: int = HTTP_RETRIES,
        timeout_s: float = HTTP_TIMEOUT_S,
    ):
        self._opener = opener
        self._sleep = sleep
        self._delay_s = delay_s
        self._retries = retries
        self._timeout_s = timeout_s
        self._calls = 0

    def _pause_between_calls(self) -> None:
        if self._calls:
            self._sleep(self._delay_s)
        self._calls += 1

    def _request(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": _ACCEPT})
        with self._opener(request, timeout=self._timeout_s) as response:
            return response.read().decode("utf-8", errors="replace")

    def text(self, url: str, params: dict = None) -> str:
        full_url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}" if params else url
        self._pause_between_calls()
        last_error = "no response"
        for attempt in range(self._retries + 1):
            try:
                return self._request(full_url)
            except urllib.error.HTTPError as exc:
                if not _is_retryable(exc.code):
                    raise FetchError(f"{exc.code} for {url}") from exc
                last_error = str(exc.code)
            except OSError as exc:
                last_error = f"network error ({getattr(exc, 'reason', exc)})"
            if attempt < self._retries:
                self._sleep(2 ** attempt)
        raise FetchError(f"{last_error} for {url}")

    def json(self, url: str, params: dict = None) -> dict:
        body = self.text(url, params)
        try:
            data = _json.loads(body)
        except ValueError as exc:
            raise FetchError(f"invalid JSON from {url}") from exc
        if not isinstance(data, dict):
            raise FetchError(f"unexpected JSON shape from {url}")
        return data
