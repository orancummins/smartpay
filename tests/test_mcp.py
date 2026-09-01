"""MCP surface tests. PLAN.MD section 37 integration list.

These drive the real MCP protocol in-process, so tool schemas and serialisation
are exercised exactly as ChatGPT will exercise them -- no running server needed.
"""

import json

import anyio
import pytest
from mcp.client.client import Client

from app.dashboard_server import admin_dashboard, demo_alex, demo_alex_json
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
    assert payload["data"]["incremental_guaranteed"] == "600.50"
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


def test_demo_alex_renders_the_dashboard():
    """Assert what the page must SAY, not how it is styled.

    The previous version of this test pinned hex codes, `conic-gradient` and
    `backdrop-filter:blur(6px)` -- styling minutiae that a redesign breaks and a bad
    design still passes. These check the page carries the right numbers, the right
    disclosures and a usable structure.
    """
    response = anyio.run(demo_alex, None)
    html = response.body.decode()

    assert response.media_type == "text/html"
    assert html.startswith("<!doctype html>")

    # The figures on screen must be the engine's, to the cent.
    assert "$600.50" in html, "headline guaranteed value missing"
    assert "$359.70" in html
    assert "35,620" in html

    # The story: baseline, recommendation and the rule behind it.
    assert "Chase Sapphire Preferred" in html
    assert "Citi / AAdvantage Platinum Select World Elite Mastercard" in html
    assert "via Citi Travel" in html
    assert "First checked bag free on American Airlines" in html

    # All five cards, each with its art.
    assert html.count('class="wallet-card art-') == 5
    for art in ("citi_strata_premier.webp", "chase_sapphire_preferred.png"):
        assert art in html

    # Disclosures are not optional, whatever the design does.
    assert "synthetic demo consumer" in html
    assert "Simulated Mastercard card-linked offer" in html
    assert "tie · +5% Mastercard credit" in html, "the network tiebreak must stay visible"

    # Provenance, with a real verification date.
    assert "2026-09-01" in html
    assert "financialdataexchange" in html or "citi.com" in html or "chase.com" in html

    # The six sections the user asked for, in order, plus the closing beat.
    # Headings are no longer numbered in the UI -- the numbers were a build-time
    # ordering aid, not something a reader needed on screen.
    headings = [
        "Potential savings over last year",
        "Potential future savings identified",
        "Financial institutions &amp; accounts connected",
        "Recent activity",
        "Here's all the information you've shared",
        "Card benefits, rewards, offers &amp; terms",
        "And one more thing…",
    ]
    positions = [html.index(h) for h in headings]
    assert positions == sorted(positions), "the six sections are out of the requested order"

    # Potential savings over last year is computed from real transaction history, never asserted.
    assert "Alex Morgan" in html
    assert "based on payments Mastercard has already seen" in html or (
        "payments Mastercard has already seen" in html
    )

    # Section 3: bank logos are present and prominent (not the small topbar mark).
    assert 'class="inst-logo"' in html
    assert "/static/logos/citi.svg" in html
    assert "/static/logos/chase.svg" in html

    # Section 4/5: real transaction activity, not just SmartPay enquiries.
    assert 'class="activity-row"' in html
    assert 'class="data-table"' in html
    assert "Every transaction shared" in html
    # Section 5 shows the full raw ledger now, not just consumer spend -- a card
    # payment or ATM withdrawal is real shared information too.
    assert "Card payment" in html
    assert "ATM withdrawal" in html

    # The retrospective savings slider: expandable, right under the header, and
    # built from the same guaranteed figure as the hero stat.
    retro_pos = html.index("What could you have saved?")
    assert positions[0] < retro_pos < positions[1], (
        "the retrospective panel must sit just under the header, before section 2"
    )
    assert 'id="retro-slider"' in html
    assert 'id="retro-data"' in html

    # "And one more thing..." must be the LAST panel, right before the disclaimers.
    assert html.index("And one more thing…") > max(
        p for h, p in zip(headings[:-1], positions[:-1])
    )
    assert html.index("And one more thing…") < html.index("synthetic demo consumer")


def test_dashboard_is_accessible_and_self_contained():
    html = anyio.run(demo_alex, None).body.decode()

    assert '<html lang="en">' in html
    assert 'name="viewport"' in html
    # Charts are images to a screen reader and must say what they show.
    assert html.count("role=\"img\"") >= 3
    assert html.count("aria-label=") >= 5
    assert "aria-labelledby=" in html

    # Nothing may be fetched from a third party: the demo has to work offline.
    for remote in ("http://cdn", "https://cdn", "googleapis", "unpkg", "jsdelivr"):
        assert remote not in html, f"external dependency: {remote}"

    # Dark mode is selected, under both the OS setting and the explicit toggle.
    assert "prefers-color-scheme:dark" in html
    assert '[data-theme="dark"]' in html
    assert "prefers-reduced-motion" in html


def test_dashboard_never_shows_a_bare_series_colour_as_text():
    """The validated palette has three light slots under 3:1 on the surface.

    That is legal only with direct labels, so every bar must carry its own value.

    Only one bar chart remains on the page (section 5's "where your money
    goes," capped at 9 categories) since the per-enquiry breakdown chart was
    removed in favour of the plain per-item table.
    """
    html = anyio.run(demo_alex, None).body.decode()
    assert html.count('class="bar-value') == html.count('class="bar-label"')
    assert html.count('class="bar-label"') >= 9


def test_demo_alex_json_remains_available_for_debugging():
    response = anyio.run(demo_alex_json, None)
    payload = json.loads(response.body)

    assert payload["customer_id"] == "alex"
    assert len(payload["accounts"]) == 7


def test_smartpay_admin_renders_analytics_and_flipper_campaigns():
    response = anyio.run(admin_dashboard, None)
    html = response.body.decode()

    assert response.media_type == "text/html"
    assert "SmartPay Admin" in html
    assert "Portfolio performance" in html
    assert "12.8M" in html
    assert "ChatGPT" in html
    assert "Gemini" in html
    assert "Grok" in html
    assert "Flipper" in html
    assert "Campaign studio" in html
    assert "Competitor card portfolio" in html
    assert "Contactless" in html
    assert "E-commerce" in html
    assert "In-store" in html
    assert 'id="campaign-form"' in html


def test_card_art_carries_no_placeholder_cardholder_name():
    """Citi's product shots ship embossed with their placeholder, "LINDA WALKER".

    On a dashboard about Alex Morgan that reads as a bug, so the art is rewritten by
    scripts/restyle_card_art.py. This guards the originals never creep back in.
    """
    from pathlib import Path

    cards = Path(__file__).resolve().parent.parent / "app" / "static" / "cards"
    shipped = [p for p in cards.glob("*") if p.suffix in {".png", ".webp"}]
    assert len(shipped) == 5

    originals = cards / "_original"
    assert originals.is_dir(), "originals must be kept so the edit stays reversible"
    for edited in shipped:
        backup = originals / edited.name
        if backup.exists():
            assert edited.read_bytes() != backup.read_bytes(), (
                f"{edited.name} still matches the untouched original"
            )


def test_network_chip_never_collides_with_the_fee_pill():
    """`.mc` was both the topbar logo (width:30px) and the chip's network modifier.

    The logo rule won, collapsing every network chip to 30px so its text spilled over
    the annual-fee pill beside it. Two guards: the logo no longer uses a name generic
    enough to collide, and chips do not wrap their own text.
    """
    html = anyio.run(demo_alex, None).body.decode()

    assert 'class="brand-mark"' in html
    assert ".mc{width:30px" not in html, "the bare .mc width rule is back"
    assert "white-space:nowrap" in html

    # The chip says the tier, not the full "Mastercard World Elite", which is too
    # long for the card column.
    assert '<span class="chip mc">World Elite</span>' in html
    assert "Mastercard World Elite</span>" not in html
