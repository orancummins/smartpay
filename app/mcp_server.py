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

from app import config
from app.services.smartpay import SmartPayService

smartpay = SmartPayService()

INSTRUCTIONS = """
SmartPay is a deterministic payment-intelligence service. It reads a consumer's
connected bank and card data, infers how they normally pay, and computes the
optimal way to pay for a purchase or an itinerary.

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


@mcp.tool(
    title="Get financial profile",
    description=(
        "Read the consumer's connected bank and card data: accounts, 12 months of "
        "transactions, spend by category, and which card they habitually use for "
        "each category." + PRESENT_VERBATIM
    ),
)
def get_financial_profile(customer_id: str = config.DEMO_CUSTOMER_ID) -> dict:
    return smartpay.get_financial_profile(customer_id)


@mcp.tool(
    title="Get wallet",
    description=(
        "List the payment cards the consumer holds, with network, annual fee and "
        "headline earn rate." + PRESENT_VERBATIM
    ),
)
def get_wallet(customer_id: str = config.DEMO_CUSTOMER_ID) -> dict:
    return smartpay.get_wallet(customer_id)


@mcp.tool(
    title="Optimise a single purchase",
    description=(
        "Work out the best way to pay for one purchase. Pass `purchase` with "
        "merchant, category, amount, and optionally purchase_date, "
        "purchase_channel and metadata (travellers, checked_bags, segments). "
        "Returns the consumer's likely habitual choice, the recommended card and "
        "booking channel, guaranteed savings and estimated reward value."
        + PRESENT_VERBATIM
    ),
)
def optimise_purchase(
    customer_id: str = config.DEMO_CUSTOMER_ID, purchase: dict | None = None
) -> dict:
    return smartpay.optimise_purchase(customer_id, purchase)


@mcp.tool(
    title="Optimise an itinerary",
    description=(
        "Work out the best way to pay for a whole trip. Pass `itinerary` as "
        "{title, start_date, items:[{label, merchant, category, amount, metadata}]}. "
        "Categories: airfare, hotel, attraction, car_rental, restaurant, rideshare, "
        "shopping, other. For flights include metadata {travellers, checked_bags, "
        "segments} so baggage benefits can be valued. Omit `itinerary` to use the "
        "frozen demo itinerary. Returns per-item baseline versus recommendation, "
        "guaranteed savings, estimated reward value and evidence." + PRESENT_VERBATIM
    ),
)
def optimise_itinerary(
    customer_id: str = config.DEMO_CUSTOMER_ID,
    itinerary: dict | None = None,
    scenario_id: str | None = None,
) -> dict:
    return smartpay.optimise_itinerary(customer_id, itinerary, scenario_id)


@mcp.tool(
    title="Optimise the wallet",
    description=(
        "Forecast the consumer's next 12 months of spend and evaluate whether their "
        "current set of cards is the right one, net of annual fees. Returns a "
        "recommended change, the net annual incremental value, and the drivers."
        + PRESENT_VERBATIM
    ),
)
def optimise_wallet(customer_id: str = config.DEMO_CUSTOMER_ID) -> dict:
    return smartpay.optimise_wallet(customer_id)


@mcp.tool(
    title="Explain a recommendation",
    description=(
        "Show the evidence behind one recommendation. Pass the recommendation_id "
        "from a previous optimise_itinerary call, formatted '<itinerary_id>:<item_id>' "
        "(for example 'disney_october_2026:flights'). Returns the issuer or network "
        "sources, their confidence, and when they were verified." + PRESENT_VERBATIM
    ),
)
def get_recommendation_evidence(recommendation_id: str) -> dict:
    return smartpay.get_recommendation_evidence(recommendation_id)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "smartpay", "version": "0.1.0"})


@mcp.custom_route("/demo/alex", methods=["GET"])
async def demo_alex(_: Request) -> JSONResponse:
    """Debugging shortcut. PLAN.MD section 30."""
    return JSONResponse(smartpay.get_financial_profile(config.DEMO_CUSTOMER_ID)["data"])


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
    if config.PUBLIC_HOST:
        allowed_hosts.append(config.PUBLIC_HOST)

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
        uvicorn.run(build_app(), host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
