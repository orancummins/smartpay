"""MCP surface tests. PLAN.MD section 37 integration list.

These drive the real MCP protocol in-process, so tool schemas and serialisation
are exercised exactly as ChatGPT will exercise them -- no running server needed.
"""

import json

import anyio
import pytest
from mcp.client.client import Client

from app.dashboard_server import demo_alex, demo_alex_json
from app.mcp_server import mcp

EXPECTED_TOOLS = {
    "get_financial_profile", "get_wallet", "optimise_purchase",
    "optimise_itinerary", "optimise_wallet", "get_recommendation_evidence",
}


def call(name: str, args: dict) -> dict:
    async def run():
        async with Client(mcp, raise_exceptions=True) as c:
            result = await c.call_tool(name, args)
            assert not result.is_error, f"{name} returned an error"
            return json.loads(result.content[0].text)

    return anyio.run(run)


def test_exactly_the_six_planned_tools_are_exposed():
    async def run():
        async with Client(mcp, raise_exceptions=True) as c:
            return {t.name for t in (await c.list_tools()).tools}

    assert anyio.run(run) == EXPECTED_TOOLS


def test_no_state_changing_tool_is_exposed():
    """PLAN.MD section 39. SmartPay is read-only and advisory."""
    async def run():
        async with Client(mcp, raise_exceptions=True) as c:
            return {t.name for t in (await c.list_tools()).tools}

    names = anyio.run(run)
    for banned in ("apply", "pay", "purchase", "transfer", "move", "open", "switch"):
        assert not any(banned in n and n not in EXPECTED_TOOLS for n in names)


def test_server_instructs_the_model_not_to_do_the_arithmetic():
    """The presentation rule is the only thing stopping ChatGPT restating numbers."""
    async def run():
        async with Client(mcp, raise_exceptions=True) as c:
            return c.instructions or ""

    text = anyio.run(run)
    assert "verbatim" in text
    assert "Do not recompute" in text


@pytest.mark.parametrize("name,args", [
    ("get_financial_profile", {}),
    ("get_wallet", {}),
    ("optimise_itinerary", {}),
    ("optimise_wallet", {}),
])
def test_every_tool_returns_the_response_contract(name, args):
    payload = call(name, args)
    assert set(payload) == {"display_markdown", "data", "disclaimers"}
    assert payload["display_markdown"].strip()
    assert isinstance(payload["disclaimers"], list)


def test_mcp_get_wallet():
    payload = call("get_wallet", {})
    names = [c["display_name"] for c in payload["data"]["cards"]]
    assert "Citi Strata Premier Card" in names
    assert "Chase Sapphire Preferred" in names


def test_mcp_optimise_itinerary():
    payload = call("optimise_itinerary", {})
    assert payload["data"]["incremental_guaranteed"] == "553.00"
    assert len(payload["data"]["recommendations"]) == 6


def test_mcp_optimise_purchase_values_the_baggage_benefit():
    payload = call("optimise_purchase", {
        "purchase": {
            "merchant": "American Airlines", "category": "airfare", "amount": "1650",
            "purchase_date": "2026-10-12",
            "metadata": {"travellers": 4, "checked_bags": 4, "segments": 2},
        },
    })
    rec = payload["data"]["recommendations"][0]
    assert rec["is_mastercard"]
    assert rec["guaranteed_savings"] == "360.00"


def test_mcp_evidence_round_trip():
    call("optimise_itinerary", {})
    payload = call("get_recommendation_evidence",
                   {"recommendation_id": "disney_october_2026:hotel"})
    assert "Citi Travel" in payload["display_markdown"]


def test_money_crosses_the_boundary_as_strings_not_floats():
    """Decimal must survive JSON. A float here would reintroduce rounding error."""
    payload = call("optimise_itinerary", {})
    assert isinstance(payload["data"]["incremental_guaranteed"], str)
    for r in payload["data"]["recommendations"]:
        assert isinstance(r["guaranteed_savings"], str)


def test_disclaimers_are_never_empty_on_an_optimisation():
    payload = call("optimise_itinerary", {})
    assert len(payload["disclaimers"]) >= 3


def test_no_tool_asks_who_the_user_is():
    """The consumer is implicit in the connection.

    If any tool advertises a customer parameter, ChatGPT will try to fill it and
    the user ends up having to name the persona out loud mid-demo.
    """
    async def run():
        async with Client(mcp, raise_exceptions=True) as c:
            return (await c.list_tools()).tools

    # get_recommendation_evidence genuinely needs an id; it names a recommendation,
    # not a person. Every other tool must be callable with no arguments at all.
    callable_bare = {
        "get_financial_profile", "get_wallet", "optimise_purchase",
        "optimise_itinerary", "optimise_wallet",
    }
    for tool in anyio.run(run):
        params = set((tool.input_schema or {}).get("properties", {}))
        assert not {"customer_id", "customer", "user_id", "user"} & params, (
            f"{tool.name} exposes an identity parameter"
        )
        if tool.name in callable_bare:
            assert not (tool.input_schema or {}).get("required"), (
                f"{tool.name} has required parameters, so it cannot be called bare"
            )


def test_stale_clients_sending_customer_id_still_work():
    """A connector that cached the old schema must not break mid-demo."""
    payload = call("get_wallet", {"customer_id": "alex"})
    assert payload["data"]["cards"]


def test_instructions_tell_the_model_not_to_ask_who():
    async def run():
        async with Client(mcp, raise_exceptions=True) as c:
            return c.instructions or ""

    text = anyio.run(run)
    assert "never ask who the user means" in text


def test_instructions_pin_the_consumer_to_the_us():
    """The operator may be outside the US; Alex is not.

    Without this, a model localises the itinerary to whoever is chatting, and the
    domestic-only baggage benefit silently drops out of the demo.
    """
    async def run():
        async with Client(mcp, raise_exceptions=True) as c:
            return c.instructions or ""

    text = anyio.run(run)
    assert "US-based consumer" in text
    assert "NOT the person operating this chat" in text
    assert "Do NOT localise" in text


def test_demo_alex_renders_the_open_finance_dashboard():
    response = anyio.run(demo_alex, None)
    html = response.body.decode()

    assert response.media_type == "text/html"
    assert "Alex Morgan" in html
    assert html.count('class="wallet-card art-') == 5
    assert 'class="wallet-carousel"' in html
    assert 'data-carousel-next' in html
    assert 'data-carousel-prev' in html
    assert 'class="carousel-dots"' in html
    assert html.count('/static/cards/') == 10
    assert "citi_strata_premier.webp" in html
    assert "chase_sapphire_preferred.png" in html
    assert '/static/logos/citi.svg' in html
    assert '/static/logos/chase.svg' in html
    assert '<link rel="icon" href="/static/logos/mastercard.svg" type="image/svg+xml">' in html
    assert "Powered by Mastercard" not in html
    assert "#EB001B" in html
    assert "#FF5F00" in html
    assert "#F79E1B" in html
    assert "conic-gradient" in html
    assert "Where Alex spends" in html
    assert "spend-track" in html
    assert "Monthly average" in html
    assert 'class="spend-summary"' in html
    assert "backdrop-filter:blur(6px)" in html
    assert "art-chase_freedom_unlimited .art-cleanup" in html
    assert html.count('class="account-name"') == 7
    assert "Connected accounts" in html
    assert "Citi Strata Premier Card" in html
    assert "Recent activity" in html
    assert 'id="page-previous"' in html
    assert 'id="page-next"' in html
    assert "const pageSize = 25" in html
    assert "@media(min-width:1100px)" in html
    assert "h1{font-size:44px}" in html


def test_demo_alex_json_remains_available_for_debugging():
    response = anyio.run(demo_alex_json, None)
    payload = json.loads(response.body)

    assert payload["customer_id"] == "alex"
    assert len(payload["accounts"]) == 7
