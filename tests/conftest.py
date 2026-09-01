"""Shared test setup.

The query history is a real file shared by the dashboard and MCP processes. Without
this, running the suite writes test itineraries into it -- "A trip ChatGPT invented"
turning up at the top of a live demo's history, and the user's own questions pushed
down. Every test gets its own throwaway store.
"""

import pytest

from app import history


@pytest.fixture(autouse=True)
def isolated_query_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "queries.json")
