"""Public-host parsing.

Getting this wrong is uniquely nasty: /health keeps returning 200 while /mcp
returns 421, so the server looks healthy while every ChatGPT tool call fails.
"""

import importlib

import pytest

from app import config


@pytest.mark.parametrize("raw,expected", [
    ("", []),
    ("abc.ngrok-free.dev", ["abc.ngrok-free.dev"]),
    ("https://abc.ngrok-free.dev", ["abc.ngrok-free.dev"]),
    ("http://abc.ngrok-free.dev", ["abc.ngrok-free.dev"]),
    # Pasting the full connector URL, trailing path and all, must work.
    ("https://abc.ngrok-free.dev/mcp", ["abc.ngrok-free.dev"]),
    ("  https://abc.trycloudflare.com/mcp  ", ["abc.trycloudflare.com"]),
    # Several tunnels at once.
    ("a.example.com, https://b.example.com/mcp",
     ["a.example.com", "b.example.com"]),
    (",,   ,", []),
])
def test_public_host_parsing(raw, expected):
    assert config._hosts(raw) == expected


def test_localhost_is_always_allowed(monkeypatch):
    """The server must still build with no tunnel configured."""
    monkeypatch.setenv("SMARTPAY_PUBLIC_HOST", "")
    importlib.reload(config)
    try:
        from app import mcp_server

        assert mcp_server.build_app() is not None
    finally:
        # reload() mutates module state for every later test in the run, so put
        # the real environment back rather than leaving order-dependent tests.
        monkeypatch.undo()
        importlib.reload(config)
