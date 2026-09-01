"""Central demo configuration. No magic numbers scattered through the engines."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Deterministic everything. PLAN.MD section 38.
RANDOM_SEED = 20261001

DEMO_CUSTOMER_ID = "alex"
DEMO_SCENARIO_ID = "disney_october_2026"

HOST = os.environ.get("SMARTPAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("SMARTPAY_PORT", "9021"))

# The ngrok dev domain, e.g. "abc123.ngrok-free.dev". The MCP SDK's DNS-rebinding
# protection rejects any Host header it has not been told about, and it does not
# support subdomain wildcards, so the public hostname must be named explicitly.
PUBLIC_HOST = os.environ.get("SMARTPAY_PUBLIC_HOST", "").strip()

# Escape hatch for debugging a tunnel. Data is entirely synthetic, so this is not
# a meaningful exposure, but it stays opt-in rather than the default.
ALLOW_ANY_HOST = os.environ.get("SMARTPAY_ALLOW_ANY_HOST", "") == "1"

# PLAN.MD section 24: point valuations are configurable, never hardcoded into the
# engines, so a judge can challenge the assumption and we can change it in one place.
REWARD_VALUATIONS: dict[str, Decimal] = {
    "citi_thankyou": Decimal("0.01"),
    "chase_ultimate_rewards": Decimal("0.01"),
    "american_airlines_miles": Decimal("0.01"),
    "usd_cashback": Decimal("1.00"),
}

VALUATION_NOTE = (
    "Points valued at 1.0 cent each. This is a deliberately conservative, "
    "non-controversial assumption and is configurable."
)
