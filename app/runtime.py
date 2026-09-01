"""Whether a running server is still serving the code on disk.

A server started before an edit keeps answering correctly while silently missing the
new behaviour, which is very hard to spot from the outside: the MCP server ran for
four hours without the query-history code, so ChatGPT's answers were right and the
dashboard simply never updated. /health now says so.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from app import config

STARTED_AT = time.time()


def newest_source_mtime() -> float:
    """Most recent modification across the application source."""
    newest = 0.0
    for path in (config.ROOT / "app").rglob("*.py"):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def status() -> dict:
    """Health payload, including whether this process predates its own source."""
    newest = newest_source_mtime()
    stale = newest > STARTED_AT
    return {
        "started_at": datetime.fromtimestamp(STARTED_AT, UTC).isoformat(timespec="seconds"),
        "source_modified_at": (
            datetime.fromtimestamp(newest, UTC).isoformat(timespec="seconds")
            if newest else None
        ),
        "stale": stale,
        "hint": (
            "Source has changed since this process started — restart it, or run with "
            "SMARTPAY_RELOAD=1"
        ) if stale else None,
    }
