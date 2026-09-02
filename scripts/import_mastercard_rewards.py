"""Import real US Mastercard issuer rewards programs into the SmartPay knowledge base.

The source is the Mastercard Rewards platform export (loyalty/rewards promotions).
Each row is an issuer-run loyalty program: the issuing bank, the market, a program
name and a prose description of how it accrues ("earn an additional 1 point per
USD for eligible travel merchant categories", "2 points per $1 spent").

Only US, consumer-facing *category-bonus* earn programs are imported (PLAN.MD
section 17). Internal accrual/scoring configuration, deactivated promos, return
handling and base-rate-only rows are dropped, because a category bonus is the only
shape that can feed the rewards engine as an additive, issuer-matched bonus without
restating a card's own base earn rate.

Run with an interpreter that has openpyxl, e.g. the campaign repo venv:

    python scripts/import_mastercard_rewards.py \
        --source "../campaign/data/Rewards - July2026.xlsx"
"""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT.parent / "campaign" / "data" / "Rewards - July2026.xlsx"
OUTPUT = REPO_ROOT / "data" / "mastercard" / "rewards_catalog.json"
SHEET = "Loaylty-Rewards-Promos"

#: END_DATE values at/after this year are the source's "no end / ongoing" sentinel
#: (Oracle 4712 infinity), so they become an open-ended validity window.
ONGOING_YEAR = 2100

#: Issuing-bank name -> the issuer key SmartPay keys cards on. Only issuers whose
#: key matches a card in Alex's wallet (citi, chase) can ever apply to him; the
#: rest are carried so the mechanism is faithful and future wallets work.
_ISSUER_KEYS: dict[str, str] = {
    "citibank n.a.": "citi",
    "citibank na commercial": "citi",
    "citi gold debit": "citi",
    "capital one bank": "capital_one",
    "first hawaiian bank": "first_hawaiian",
    "bank of america": "bank_of_america",
    "usaa federal savings bank": "usaa",
    "keybank national association": "keybank",
    "wells fargo bank": "wells_fargo",
    "us bank": "us_bank",
    "bmo harris bank": "bmo_harris",
    "truist bank": "truist",
    "synchrony financial": "synchrony",
}

#: Rows that are internal configuration rather than a consumer-facing program.
_INTERNAL = re.compile(
    r"scoring|accrual rule|deactivat|\breturn\b|conversion|\bcv\b|data rate|\bIRD\b"
    r"|non-qualif|large ticket|\bcharity\b|snapcommerce|truaxis|sessionm|belk|apple merchant",
    re.IGNORECASE,
)

_POINTS = re.compile(
    r"(\d*\.?\d+)\s*(?:pt|pts|point|points)\s*(?:per|/)\s*(?:\$?\s*1\b|usd|dollar)",
    re.IGNORECASE,
)
_CASHBACK = re.compile(r"(\d*\.?\d+)\s*%", re.IGNORECASE)

#: Description keyword -> the spend categories a bonus applies to. Union across hits.
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "dining": ["restaurant"],
    "restaurant": ["restaurant"],
    "travel": ["airfare", "hotel", "attraction", "car_rental"],
    "airline": ["airfare"],
    "hotel": ["hotel"],
    "fuel": ["gas"],
    "gas": ["gas"],
    "service station": ["gas"],
    "grocery": ["supermarket"],
    "supermarket": ["supermarket"],
    "telco": ["utilities"],
    "utilities": ["utilities"],
    "entertainment": ["entertainment"],
    "streaming": ["streaming"],
    "office supply": ["other"],
}


def _issuer_key(name: str) -> str:
    lowered = name.strip().lower()
    if lowered in _ISSUER_KEYS:
        return _ISSUER_KEYS[lowered]
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_") or "unknown_issuer"


def _categories(text: str) -> list[str]:
    hits: list[str] = []
    lowered = text.lower()
    for keyword, cats in _CATEGORY_KEYWORDS.items():
        if keyword in lowered:
            for c in cats:
                if c not in hits:
                    hits.append(c)
    return hits


def _parse_rate(text: str) -> tuple[str, Decimal] | None:
    """Return (reward_currency, rate) or None.

    Points programs accrue points per dollar; cashback programs a percentage. A
    bonus that says "additional 0.5 points per USD (0.005 per dollar)" is a points
    program, so points are matched before the percentage fallback.
    """
    m = _POINTS.search(text)
    if m:
        return "loyalty_points", Decimal(m.group(1))
    m = _CASHBACK.search(text)
    if m:
        return "usd_cashback", Decimal(m.group(1))
    return None


def _iso(value) -> str | None:
    if value is None:
        return None
    try:
        if value.year >= ONGOING_YEAR:
            return None
    except AttributeError:
        return None
    return str(value)[:10]


def build(source: Path) -> list[dict]:
    wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    ws = wb[SHEET]
    rows = ws.iter_rows(values_only=True)
    next(rows)  # header

    seen: set[tuple] = set()
    programs: list[dict] = []
    for issuer_name, _pid, region, promo, desc, begin, end in rows:
        if region != "UNITED STATES" or not promo:
            continue
        text = f"{promo} {desc or ''}"
        if _INTERNAL.search(text):
            continue
        categories = _categories(text)
        if not categories:
            # Only targeted category bonuses feed the engine; a base "1pt per $1"
            # would double-count a card's own base rate.
            continue
        parsed = _parse_rate(text)
        if parsed is None:
            continue
        currency, rate = parsed
        if rate <= 0:
            continue
        issuer_key = _issuer_key(str(issuer_name))

        dedupe = (issuer_key, str(promo).strip(), tuple(categories), currency, str(rate))
        if dedupe in seen:
            continue
        seen.add(dedupe)

        programs.append(
            {
                "program_id": f"{issuer_key}:{re.sub(r'[^a-z0-9]+', '_', str(promo).lower()).strip('_')}",
                "issuer_key": issuer_key,
                "issuer_name": str(issuer_name).strip(),
                "display_name": str(promo).strip(),
                "description": str(desc or promo).strip(),
                "categories": categories,
                "reward_currency": currency,
                "rate": f"{rate.normalize():f}",
                "valid_from": _iso(begin),
                "valid_to": _iso(end),
            }
        )

    programs.sort(key=lambda p: (p["issuer_name"].lower(), p["display_name"].lower()))
    return programs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    programs = build(args.source)
    payload = {
        "provenance": {
            "source_name": "Mastercard Rewards platform (US loyalty programs)",
            "market": "US",
            "note": (
                "Real Mastercard issuer rewards programs. Curated to US consumer-facing "
                "category-bonus earn programs. Applied only to a card whose issuer runs "
                "the program -- never restated as the card's own published base rate."
            ),
        },
        "programs": programs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    issuers = sorted({p["issuer_key"] for p in programs})
    print(f"Wrote {len(programs)} US reward programs -> {args.output}")
    print(f"Issuers: {issuers}")


if __name__ == "__main__":
    main()
