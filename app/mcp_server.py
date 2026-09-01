"""SmartPay MCP server.

Six read-only tools (PLAN.MD sections 29 and 39). SmartPay never moves money,
applies for anything, or changes state -- it reads, analyses and explains.

Response contract for every tool (PLAN.MD section 27 -- the LLM explains, it does
not calculate):

    {
      "display_markdown": "<table rendered deterministically in Python>",
      "data": {...},                 # machine-readable, same numbers
      "disclaimers": ["..."],        # must be surfaced, never dropped
    }
"""

from __future__ import annotations

import contextlib

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from typing import Any

from app import config, runtime, widget
from app.services.smartpay import SmartPayService

smartpay = SmartPayService()

INSTRUCTIONS = """
SmartPay is a deterministic payment-intelligence service. It reads the connected
consumer's bank and card data, infers how they normally pay, and computes the
optimal way to pay for a purchase or an itinerary.

WHOSE DATA: the consumer is already identified by the connection itself. There is
no customer parameter and you must never ask who the user means, or ask them to
name anyone before calling a tool.

WHO THE CONSUMER IS: Alex, a US-based consumer living in the Boston area, holding
US-issued cards and banking with two US institutions. Alex is a demo persona and
is NOT the person operating this chat. Plan US domestic travel departing from the
US, and price everything in USD. Do NOT localise the itinerary to the operator's
own country, city or currency, and do not use their location as the origin --
their location is irrelevant to Alex's finances. Refer to the consumer as Alex.

This matters to the numbers, not just the wording: several card benefits are
limited to domestic US itineraries, so an international origin genuinely removes
value that SmartPay would otherwise find.

CRITICAL PRESENTATION RULE: every tool returns a `display_markdown` field that has
already been formatted. Present that field to the user verbatim. Do not recompute,
re-round, re-total or restate any monetary figure, and never omit any entry in
`disclaimers`. All arithmetic is performed in Python; your role is narration only.
""".strip()

mcp = MCPServer(
    name="SmartPay",
    title="SmartPay Payment Intelligence",
    instructions=INSTRUCTIONS,
    version="0.1.0",
)

PRESENT_VERBATIM = " Present the `display_markdown` field verbatim."

#: Binds a tool to the UI component. `ui.resourceUri` is the MCP Apps standard;
#: `openai/outputTemplate` is the alias ChatGPT also honours, so both are sent.
WIDGET_META: dict[str, Any] = {
    "ui.resourceUri": widget.WIDGET_URI,
    "openai/outputTemplate": widget.WIDGET_URI,
    "openai/toolInvocation/invoking": "Working out how to pay",
    "openai/toolInvocation/invoked": "Payment plan ready",
}


@mcp.resource(
    widget.WIDGET_URI,
    name="SmartPay payment plan",
    title="SmartPay payment plan",
    description="Baseline versus recommended payment for each item of a trip.",
    mime_type="text/html",
    meta={
        "ui.prefersBorder": True,
        "openai/widgetDescription": (
            "Shows how the consumer would normally pay for each item against how "
            "SmartPay recommends they pay, with the guaranteed value of the change."
        ),
        # Everything is inlined as a data URI, so the component needs no network at
        # all. Declaring empty lists says so explicitly rather than by omission.
        "ui.csp": {"connectDomains": [], "resourceDomains": []},
    },
)
def payment_plan_widget() -> str:
    return widget.widget_html()


@mcp.tool(
    title="Get financial profile",
    description=(
        "Read the connected consumer's bank and card data: accounts, 12 months of "
        "transactions, spend by category, and which card they habitually use for "
        "each category." + PRESENT_VERBATIM
    ),
)
def get_financial_profile() -> dict[str, Any]:
    return smartpay.get_financial_profile(config.DEMO_CUSTOMER_ID)


@mcp.tool(
    title="Get wallet",
    description=(
        "List the payment cards the connected consumer holds, with network, annual fee and "
        "headline earn rate." + PRESENT_VERBATIM
    ),
)
def get_wallet() -> dict[str, Any]:
    return smartpay.get_wallet(config.DEMO_CUSTOMER_ID)


@mcp.tool(
    title="Optimise a single purchase",
    description=(
        "Work out the best way for the connected consumer to pay for one purchase. Pass `purchase` with "
        "merchant, category, amount, and optionally purchase_date, "
        "purchase_channel and metadata (travellers, checked_bags, segments). "
        "Returns the consumer's likely habitual choice, the recommended card and "
        "booking channel, guaranteed savings and estimated reward value."
        + PRESENT_VERBATIM
    ),
    meta=WIDGET_META,
)
def optimise_purchase(purchase: dict | None = None) -> dict[str, Any]:
    return smartpay.optimise_purchase(config.DEMO_CUSTOMER_ID, purchase)


@mcp.tool(
    title="Optimise an itinerary",
    description=(
        "Work out the best way for Alex to pay for a whole trip. Alex is US-based, "
        "so itineraries should be US domestic and priced in USD. Pass `itinerary` as "
        "{title, start_date, items:[{label, merchant, category, amount, metadata}]}. "
        "Categories: airfare, hotel, attraction, car_rental, restaurant, rideshare, "
        "shopping, other. For flights include metadata {travellers, checked_bags, "
        "segments} so baggage benefits can be valued. Omit `itinerary` to use the "
        "frozen demo itinerary. Returns per-item baseline versus recommendation, "
        "guaranteed savings, estimated reward value and evidence." + PRESENT_VERBATIM
    ),
    meta=WIDGET_META,
)
def optimise_itinerary(
    itinerary: dict | None = None,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    return smartpay.optimise_itinerary(config.DEMO_CUSTOMER_ID, itinerary, scenario_id)


@mcp.tool(
    title="Optimise the wallet",
    description=(
        "Forecast the connected consumer's next 12 months of spend and evaluate whether their "
        "current set of cards is the right one, net of annual fees. Returns a "
        "recommended change, the net annual incremental value, and the drivers."
        + PRESENT_VERBATIM
    ),
)
def optimise_wallet() -> dict[str, Any]:
    return smartpay.optimise_wallet(config.DEMO_CUSTOMER_ID)


@mcp.tool(
    title="Explain a recommendation",
    description=(
        "Show the evidence behind one recommendation. Pass the recommendation_id "
        "from a previous optimise_itinerary call, formatted '<itinerary_id>:<item_id>' "
        "(for example 'disney_october_2026:flights'). Returns the issuer or network "
        "sources, their confidence, and when they were verified." + PRESENT_VERBATIM
    ),
)
def get_recommendation_evidence(recommendation_id: str) -> dict[str, Any]:
    return smartpay.get_recommendation_evidence(recommendation_id)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {"status": "ok", "service": "smartpay", "version": "0.1.0", **runtime.status()}
    )


@mcp.custom_route("/", methods=["GET"])
async def root(_: Request) -> PlainTextResponse:
    return PlainTextResponse("SmartPay MCP server. Endpoint: /mcp   Health: /health\n")


def build_app():
    """Starlette app exposing MCP over streamable HTTP at /mcp."""
    allowed_hosts = [
        f"localhost:{config.PORT}",
        f"127.0.0.1:{config.PORT}",
        "localhost",
        "127.0.0.1",
    ]
    allowed_hosts.extend(config.PUBLIC_HOSTS)

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=not config.ALLOW_ANY_HOST,
        allowed_hosts=allowed_hosts,
        allowed_origins=["*"] if config.ALLOW_ANY_HOST else [],
    )

    # stateless_http keeps every request self-contained, so a tunnel reconnect or a
    # retry from ChatGPT cannot land on a missing session.
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        if config.RELOAD:
            # reload_dirs is restricted to app/: the default watches the whole tree,
            # and .runtime/queries.json changes on every query, which would restart
            # the server in a loop.
            uvicorn.run(
                "app.mcp_server:build_app", factory=True, host=config.HOST,
                port=config.PORT, log_level="info", reload=True, reload_dirs=["app"],
            )
        else:
            uvicorn.run(build_app(), host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
