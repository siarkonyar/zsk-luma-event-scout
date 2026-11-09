"""Every tunable value of the scout script, in one place."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

STATE_VERSION = 1
STATE_PATH = Path.home() / ".config" / "luma-event-scout" / "state.json"
RUN_DIR = Path.home() / ".cache" / "luma-event-scout" / "run"

USER_KEYWORD_COUNT = 3
GENERATED_KEYWORD_COUNT = 2
REFRESH_THRESHOLD = 5
WINDOW_DAYS = 14

DEFAULT_EVENT_DURATION = timedelta(hours=2)
REGISTERED_STATUSES = frozenset({"approved", "pending_approval", "waitlist", "host"})

ICS_URL = "https://api.lu.ma/ics/get?entity=calendar&id={cal_id}"
HOST_PROFILE_URL = "https://api.luma.com/user/profile"
HOST_EVENTS_URL = "https://api.luma.com/user/profile/events-hosting"
HOST_PAGE_LIMIT = 50
HOST_MAX_PAGES = 10

HTTP_TIMEOUT_S = 20
HTTP_RETRIES = 2
REQUEST_DELAY_S = 0.5
USER_AGENT = "luma-event-scout/0.1"

ONLINE_LOCATION_TYPES = frozenset({"zoom", "meet", "youtube", "discord", "twitch", "twitter"})

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_NO_STATE = 0, 1, 2, 3
