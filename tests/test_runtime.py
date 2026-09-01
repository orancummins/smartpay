"""Staleness reporting.

A server that started before your last edit keeps answering correctly and silently
lacks the new behaviour. That is what happened: the MCP server ran for four hours
without the query-history code, so ChatGPT's answers were right and the dashboard
just never updated. /health now makes it visible.
"""

import time

from app import runtime


def test_status_reports_when_the_process_predates_its_source(monkeypatch):
    monkeypatch.setattr(runtime, "STARTED_AT", time.time() - 3600)
    monkeypatch.setattr(runtime, "newest_source_mtime", lambda: time.time())
    status = runtime.status()
    assert status["stale"] is True
    assert "restart" in status["hint"]


def test_status_is_clean_for_a_freshly_started_process(monkeypatch):
    monkeypatch.setattr(runtime, "STARTED_AT", time.time())
    monkeypatch.setattr(runtime, "newest_source_mtime", lambda: time.time() - 60)
    status = runtime.status()
    assert status["stale"] is False
    assert status["hint"] is None


def test_status_survives_an_unreadable_tree(monkeypatch):
    monkeypatch.setattr(runtime, "newest_source_mtime", lambda: 0.0)
    assert runtime.status()["source_modified_at"] is None


def test_both_servers_expose_health_with_staleness():
    import anyio
    from app.dashboard_server import health as dashboard_health

    payload = anyio.run(dashboard_health, None)
    body = payload.body.decode()
    for field in ("started_at", "stale", "smartpay-dashboard"):
        assert field in body


def test_reload_watches_only_app(monkeypatch):
    """reload_dirs must exclude .runtime: queries.json changes on every question,
    and watching it would restart the server in a loop mid-demo."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "app" / "mcp_server.py").read_text()
    assert 'reload_dirs=["app"]' in source
    assert "reload_dirs=[\".\"]" not in source
