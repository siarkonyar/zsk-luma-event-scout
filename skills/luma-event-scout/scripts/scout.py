#!/usr/bin/env python3
"""Entry point for the luma-event-scout skill: python3 scout.py <command> [options]."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scout_lib.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
