"""Shared test setup.

The query history and the identified-savings ledger are real files shared by the
dashboard and MCP processes. Without this, running the suite writes test
itineraries into them -- "A trip ChatGPT invented" turning up in a live demo's
history and ledger, real entries pushed down or double-counted. Every test gets
its own throwaway store for both, and the ledger's in-process cache is reset so
one test's monkeypatched profile cannot leak into the next.
"""

import pytest

from app import analytics, coupons, history


@pytest.fixture(autouse=True)
def isolated_query_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "queries.json")
    monkeypatch.setattr(analytics, "LEDGER_PATH", tmp_path / "identified_ledger.json")
    monkeypatch.setattr(coupons, "COUPONS_PATH", tmp_path / "coupons.json")
    analytics._CACHE.clear()
    analytics._RECORDS_CACHE.clear()
    yield
    analytics._CACHE.clear()
    analytics._RECORDS_CACHE.clear()
