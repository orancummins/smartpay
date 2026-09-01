"""A short, shared record of what SmartPay has been asked.

The dashboard and the MCP server are separate processes, so the history cannot live
in memory: ChatGPT calls the MCP server on one port and the dashboard renders on
another. A small JSON file is the shared surface between them.

Writes are atomic (temp file, then rename) because both processes touch the same
path, and a half-written file read mid-flight would break the dashboard rather than
just showing stale data. Reads never raise: a missing or corrupt file means "no
history yet", which the dashboard handles by falling back to the frozen scenario.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import config

#: Runtime state, not project data -- gitignored, and safe to delete.
HISTORY_PATH = config.ROOT / ".runtime" / "queries.json"

#: Enough to show what was asked recently without the page becoming a log viewer.
MAX_ENTRIES = 12


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load(path: Path | None = None) -> list[dict[str, Any]]:
    """Most recent first. Any failure reads as an empty history."""
    path = path or HISTORY_PATH
    try:
        entries = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)]


def record(entry: dict[str, Any], path: Path | None = None) -> list[dict[str, Any]]:
    """Prepend an entry, de-duplicating by scenario, and persist.

    Re-asking the same itinerary should move it to the top rather than fill the list
    with copies of itself -- during a demo the same scenario gets run repeatedly.
    """
    path = path or HISTORY_PATH
    entry = {**entry, "asked_at": entry.get("asked_at") or _now()}

    kept = [e for e in load(path) if e.get("key") != entry.get("key")]
    entries = [entry, *kept][:MAX_ENTRIES]

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, delete=False, encoding="utf-8"
        ) as handle:
            json.dump(entries, handle, indent=2)
            temp = Path(handle.name)
        os.replace(temp, path)
    except OSError:
        # A demo must not fall over because it could not write its own history.
        return entries
    return entries


def clear(path: Path | None = None) -> None:
    with contextlib.suppress(OSError):
        (path or HISTORY_PATH).unlink()
