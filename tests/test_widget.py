"""The component ChatGPT embeds.

ChatGPT fetches one HTML resource and runs it in a sandboxed iframe, hydrating it
from window.openai.toolOutput. These tests cover the parts that make or break that
contract: discovery, self-containment, and the data the component reads.
"""

import json

import anyio
import pytest
from mcp.client.client import Client

from app import widget
from app.mcp_server import mcp

PLAN_TOOLS = {"optimise_itinerary", "optimise_purchase"}


def _client_call(fn):
    async def run():
        async with Client(mcp, raise_exceptions=True) as c:
            return await fn(c)

    return anyio.run(run)


def test_the_component_is_registered_as_a_ui_resource():
    """The ui:// scheme is required and the mimetype tells ChatGPT to render it."""
    resources = _client_call(lambda c: c.list_resources())
    uris = {str(r.uri): r for r in resources.resources}
    assert widget.WIDGET_URI in uris
    # Not plain "text/html": a generic HTML resource is not recognised as a
    # component. The exact value is switchable because the docs disagree with each
    # other, so assert the shape rather than one string.
    mime = uris[widget.WIDGET_URI].mime_type
    assert mime.startswith("text/html")
    assert mime != "text/html", "a bare text/html resource does not render as UI"


def test_plan_tools_point_at_the_component():
    """A tool is bound to its UI by _meta; a mismatch means it never renders."""
    tools = _client_call(lambda c: c.list_tools())
    for tool in tools.tools:
        meta = tool.meta or {}
        if tool.name in PLAN_TOOLS:
            # Both the MCP Apps standard key and ChatGPT's alias are sent.
            assert meta.get("ui.resourceUri") == widget.WIDGET_URI, tool.name
            assert meta.get("openai/outputTemplate") == widget.WIDGET_URI, tool.name
        else:
            assert "openai/outputTemplate" not in meta, tool.name


def test_tools_return_structured_content_for_the_component_to_read():
    """window.openai.toolOutput IS the structured content.

    A bare `dict` return annotation produces none at all, which leaves the component
    with nothing to render.
    """
    result = _client_call(lambda c: c.call_tool("optimise_itinerary", {}))
    assert result.structured_content, "no structured content for the widget"
    assert set(result.structured_content) == {"display_markdown", "data", "disclaimers"}
    assert result.structured_content["data"]["recommendations"]


def test_the_component_fetches_nothing():
    """The iframe cannot reach the dashboard server, so every asset is inlined.

    Any remote reference would be blocked and leave a broken image on screen.
    """
    html = widget.widget_html()
    for remote in ("http://", "https://", "//cdn", "googleapis", "/static/"):
        assert remote not in html, f"component would try to fetch {remote}"
    assert "data:image/" in html


def test_the_component_reads_the_host_api_defensively():
    html = widget.widget_html()
    # Hydration, sizing, and the two host actions the UI offers.
    for api in ("toolOutput", "notifyIntrinsicHeight", "requestDisplayMode",
                "sendFollowUpMessage", "openai:set_globals"):
        assert api in html, f"missing {api}"
    # It must not assume the host exists: the same file is previewable standalone.
    assert "window.openai" in html
    assert "const oai = () =>" in html


def test_disclaimers_survive_into_the_component():
    """The disclaimers sit beside `data` on the envelope, not inside it.

    Reading only `data` silently dropped them, which is the one thing that must
    never go missing from anything SmartPay shows.
    """
    html = widget.widget_html()
    assert "out.disclaimers" in html
    result = _client_call(lambda c: c.call_tool("optimise_itinerary", {}))
    assert result.structured_content["disclaimers"]


def test_bar_marks_are_block_level():
    """A span is inline, so width and height are ignored and every bar renders
    empty -- which is exactly what happened before this was pinned."""
    html = widget.widget_html()
    assert ".bar .fill{display:block" in html
    assert ".bar .track{display:block" in html


def test_inline_stays_compact_and_detail_is_behind_fullscreen():
    html = widget.widget_html()
    assert '.detail{display:none' in html
    assert ':root[data-mode="fullscreen"] .detail{display:block}' in html


def test_the_resource_is_a_complete_document():
    html = _client_call(
        lambda c: c.read_resource(widget.WIDGET_URI)
    ).contents[0].text
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    # Large, because the card art is inlined; guard against it ballooning further.
    assert len(html) < 600_000


def test_asset_inlining_is_missing_file_tolerant():
    assert widget.data_uri("logos/citi.svg").startswith("data:image/svg+xml;base64,")
    assert widget.data_uri("nope/missing.png") == ""
