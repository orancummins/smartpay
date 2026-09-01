"""MCP surface tests. PLAN.MD section 37 integration list.

These drive the real MCP protocol in-process, so tool schemas and serialisation
are exercised exactly as ChatGPT will exercise them -- no running server needed.
"""

import json

import anyio
import pytest
from mcp.client.client import Client

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
    ("get_financial_profile", {"customer_id": "alex"}),
    ("get_wallet", {"customer_id": "alex"}),
    ("optimise_itinerary", {"customer_id": "alex"}),
    ("optimise_wallet", {"customer_id": "alex"}),
])
def test_every_tool_returns_the_response_contract(name, args):
    payload = call(name, args)
    assert set(payload) == {"display_markdown", "data", "disclaimers"}
    assert payload["display_markdown"].strip()
    assert isinstance(payload["disclaimers"], list)


def test_mcp_get_wallet():
    payload = call("get_wallet", {"customer_id": "alex"})
    names = [c["display_name"] for c in payload["data"]["cards"]]
    assert "Citi Strata Premier Card" in names
    assert "Chase Sapphire Preferred" in names


def test_mcp_optimise_itinerary():
    payload = call("optimise_itinerary", {"customer_id": "alex"})
    assert payload["data"]["incremental_guaranteed"] == "553.00"
    assert len(payload["data"]["recommendations"]) == 6


def test_mcp_optimise_purchase_values_the_baggage_benefit():
    payload = call("optimise_purchase", {
        "customer_id": "alex",
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
    call("optimise_itinerary", {"customer_id": "alex"})
    payload = call("get_recommendation_evidence",
                   {"recommendation_id": "disney_october_2026:hotel"})
    assert "Citi Travel" in payload["display_markdown"]


def test_money_crosses_the_boundary_as_strings_not_floats():
    """Decimal must survive JSON. A float here would reintroduce rounding error."""
    payload = call("optimise_itinerary", {"customer_id": "alex"})
    assert isinstance(payload["data"]["incremental_guaranteed"], str)
    for r in payload["data"]["recommendations"]:
        assert isinstance(r["guaranteed_savings"], str)


def test_disclaimers_are_never_empty_on_an_optimisation():
    payload = call("optimise_itinerary", {"customer_id": "alex"})
    assert len(payload["disclaimers"]) >= 3
