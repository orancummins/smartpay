"""Import real US Mastercard card-linked offers into the SmartPay knowledge base.

The source is the Mastercard Offers platform export (Q3 2026 catalogue). Each row
carries a campaign id, the merchant, the offer window and a `campaign_name` that
encodes the offer mechanics in prose ("5% Cash Back+ 1x", "$30 Back on $300+ 1x",
"SpendUSD200get5%MaxUSD25_x1"). This script parses those mechanics into the
`Offer` schema and writes a compact catalogue that `app.knowledge.offers()` loads.

Only the US market is imported (the SmartPay persona, Alex, is US-based). The
offer terms are copied verbatim from the source; only the validity window is
extended to cover the rehearsed demo trip in October 2026 -- see PLAN.MD section
11 and the provenance note attached at load time.

Run with an interpreter that has openpyxl available, e.g. the campaign repo venv:

    python scripts/import_mastercard_offers.py \
        --source "../campaign/data/Offers - July2026-2.xlsx"
"""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT.parent / "campaign" / "data" / "Offers - July2026-2.xlsx"
OUTPUT = REPO_ROOT / "data" / "mastercard" / "offers_catalog.json"

#: The rehearsed demo trip is in October 2026; the source offers are a Q3
#: catalogue that expires 2026-09-30. The offer TERMS are real, but the window is
#: extended to the demo period so the sourced offers apply to the demo itinerary.
DEMO_VALID_TO = "2026-11-30"

#: Redemptions marked "Unlimited" have no practical per-plan cap.
UNLIMITED = 999

_US = re.compile(r"MTR[\s\-_]*(?:USA|US)\b", re.IGNORECASE)

# Mechanics parsing. Applied in order against the campaign_name; first hit wins.
_SPEND_GET = re.compile(
    r"spend\s*(?:usd|us\$|\$)?\s*([\d,]+)\s*get\s*(?:usd|us\$|\$)?\s*([\d,]+)\s*(%)?",
    re.IGNORECASE,
)
_AMOUNT_BACK_ON = re.compile(
    r"(?:usd|us\$|\$)\s*([\d,]+)\s*back\s*on\s*(?:usd|us\$|\$)?\s*([\d,]+)",
    re.IGNORECASE,
)
_PCT_ON = re.compile(
    r"([\d.]+)\s*%[^%]*?\bon\b\s*(?:usd|us\$|\$)?\s*([\d,]+)",
    re.IGNORECASE,
)
_PCT_ANY = re.compile(r"([\d.]+)\s*%", re.IGNORECASE)
_MAX = re.compile(r"max\s*(?:usd|us\$|\$)?\s*([\d,]+)", re.IGNORECASE)
_TIMES = re.compile(r"(?:_x|\bx)\s*(\d+)\b|\b(\d+)\s*x\b", re.IGNORECASE)


def _num(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


def _merchant_key(name: str) -> str:
    """Stable slug used to match an offer to a purchase's merchant."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "unknown_merchant"


#: One merchant's export field is corrupted -- UTF-8 bytes mis-decoded as
#: Latin-1 upstream, before this script ever saw it -- so the generic mojibake
#: fix below can't recover it. Fixed by hand since it's a single row.
_MERCHANT_NAME_OVERRIDES = {
    "Peppermint CAFÃ‰&POOL BAR": "Peppermint Café & Pool Bar",
}


def _clean_merchant_name(name: str) -> str:
    """Display-only cleanup of the source export's merchant field.

    Some rows are mojibake (UTF-8 text mis-decoded as Latin-1 somewhere
    upstream) and some are SHOUTED IN ALL CAPS -- neither is how the offer
    terms actually read, so this never touches merchant_key (the matching
    slug, derived from the raw name before this runs).
    """
    if name in _MERCHANT_NAME_OVERRIDES:
        return _MERCHANT_NAME_OVERRIDES[name]
    try:
        name = name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return name.title() if name.isupper() else name


def _redemptions(text: str) -> int:
    if re.search(r"unlimited", text, re.IGNORECASE):
        return UNLIMITED
    m = _TIMES.search(text)
    if m:
        return int(m.group(1) or m.group(2))
    return 1


def _parse_mechanics(name: str) -> dict | None:
    """Extract (benefit_type, value, minimum_spend, max_discount) from prose.

    Returns None when no value can be established -- a card-linked offer with no
    quantifiable benefit is not worth carrying.
    """
    cap_match = _MAX.search(name)
    max_discount = _num(cap_match.group(1)) if cap_match else None

    spend = _SPEND_GET.search(name)
    if spend:
        minimum, reward, is_pct = spend.group(1), spend.group(2), spend.group(3)
        if is_pct:
            return {
                "benefit_type": "discount_pct",
                "value": _num(reward),
                "minimum_spend": _num(minimum),
                "max_discount": max_discount,
            }
        return {
            "benefit_type": "statement_credit",
            "value": _num(reward),
            "minimum_spend": _num(minimum),
            "max_discount": None,
        }

    amount_back = _AMOUNT_BACK_ON.search(name)
    if amount_back:
        return {
            "benefit_type": "statement_credit",
            "value": _num(amount_back.group(1)),
            "minimum_spend": _num(amount_back.group(2)),
            "max_discount": None,
        }

    pct_on = _PCT_ON.search(name)
    if pct_on:
        return {
            "benefit_type": "discount_pct",
            "value": _num(pct_on.group(1)),
            "minimum_spend": _num(pct_on.group(2)),
            "max_discount": max_discount,
        }

    pct_any = _PCT_ANY.search(name)
    if pct_any:
        return {
            "benefit_type": "discount_pct",
            "value": _num(pct_any.group(1)),
            "minimum_spend": Decimal("0"),
            "max_discount": max_discount,
        }

    return None


def _describe(merchant: str, mech: dict, redemptions: int) -> str:
    minimum = mech["minimum_spend"]
    times = "unlimited times" if redemptions >= UNLIMITED else (
        "once" if redemptions == 1 else f"up to {redemptions} times"
    )
    if mech["benefit_type"] == "discount_pct":
        body = f"{mech['value']:g}% back at {merchant}"
        if mech["max_discount"] is not None:
            body += f" (up to ${mech['max_discount']:,.0f})"
    else:
        body = f"${mech['value']:,.0f} back at {merchant}"
    if minimum > 0:
        body += f" on spend of ${minimum:,.0f} or more"
    return f"{body}, redeemable {times}."


def _iso(value) -> str | None:
    if value is None:
        return None
    return str(value)[:10]


def build(source: Path) -> list[dict]:
    wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    next(rows)  # header

    # A single campaign is distributed to many publishers, so the same offer id
    # recurs across rows. De-duplicate on the campaign id: one offer, once.
    offers: dict[str, dict] = {}
    for campaign_id, campaign_name, _publisher, merchant, start, end in rows:
        if not campaign_name or not merchant or not campaign_id:
            continue
        offer_id = str(campaign_id)
        if offer_id in offers:
            continue
        name = str(campaign_name)
        if not _US.search(name):
            continue
        mech = _parse_mechanics(name)
        if mech is None:
            continue
        merchant = str(merchant).strip()
        merchant_key = _merchant_key(merchant)
        merchant = _clean_merchant_name(merchant)
        redemptions = _redemptions(name)
        offers[offer_id] = {
            "offer_id": offer_id,
            "merchant_name": merchant,
            "merchants": [merchant_key],
            "minimum_spend": f"{mech['minimum_spend']:.2f}",
            "benefit_type": mech["benefit_type"],
            "value": f"{mech['value']:.2f}",
            "max_discount": (
                f"{mech['max_discount']:.2f}" if mech["max_discount"] is not None else None
            ),
            "max_redemptions": redemptions,
            "valid_from": _iso(start),
            "valid_to": DEMO_VALID_TO,
            "source_valid_to": _iso(end),
            "description": _describe(merchant, mech, redemptions),
        }

    return sorted(offers.values(), key=lambda o: (o["merchant_name"].lower(), o["offer_id"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    offers = build(args.source)
    payload = {
        "provenance": {
            "source_name": "Mastercard Offers platform (2026 Q3 US catalogue)",
            "market": "US",
            "note": (
                "Real Mastercard card-linked offer records. Offer terms are copied "
                "from the source export; the validity window is extended to the demo "
                "period so sourced offers apply to the rehearsed October 2026 trip."
            ),
        },
        "offers": offers,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {len(offers)} US offers -> {args.output}")


if __name__ == "__main__":
    main()
