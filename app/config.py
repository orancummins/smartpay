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

# Which Open Finance source to read from.
#   "synthetic"  frozen committed fixture -- the default, and what the rehearsed
#                demo numbers are pinned to
#   "banksym"    live BankSym tenants over its Open Finance API
# The engines are identical either way; that is the point of PLAN.MD section 8.
PROVIDER = os.environ.get("SMARTPAY_PROVIDER", "synthetic").strip().lower()
DEMO_SCENARIO_ID = "disney_october_2026"

HOST = os.environ.get("SMARTPAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("SMARTPAY_PORT", "9022"))
DASHBOARD_PORT = int(os.environ.get("SMARTPAY_DASHBOARD_PORT", "9023"))

# Public hostname(s) the server is reached on, comma separated. The MCP SDK's
# DNS-rebinding protection rejects any Host header it has not been told about, and
# it does not support subdomain wildcards, so each public hostname must be named
# explicitly. Accepts a full URL or a bare host, so pasting a tunnel URL works:
#
#   SMARTPAY_PUBLIC_HOST=https://abc.ngrok-free.dev
#   SMARTPAY_PUBLIC_HOST=abc.ngrok-free.dev,xyz.trycloudflare.com
#
# Get this wrong and /health returns 200 while /mcp returns 421 -- it looks healthy
# and is not.
def _hosts(raw: str) -> list[str]:
    out = []
    for part in raw.split(","):
        host = part.strip().removeprefix("https://").removeprefix("http://")
        host = host.split("/")[0].strip()
        if host:
            out.append(host)
    return out


PUBLIC_HOSTS = _hosts(os.environ.get("SMARTPAY_PUBLIC_HOST", ""))

# Mimetype for the embedded UI resource. The docs are inconsistent here: the field
# reference says "text/html", the current code example uses "text/html;profile=mcp-app",
# and hosts in the wild have long expected "text/html+skybridge". A plain "text/html"
# resource is not recognised as a component by ChatGPT, so this is switchable rather
# than guessed -- try the alternatives if the component does not render.
WIDGET_MIME = os.environ.get("SMARTPAY_WIDGET_MIME", "text/html+skybridge")

# Watch app/ and restart on change. A long-running server quietly serving code from
# before your last edit is hard to spot -- the tool answers correctly and only the
# new behaviour is missing.
RELOAD = os.environ.get("SMARTPAY_RELOAD", "") == "1"

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
    "loyalty_points": Decimal("0.01"),
}

VALUATION_NOTE = (
    "Points valued at 1.0 cent each. This is a deliberately conservative, "
    "non-controversial assumption and is configurable."
)
