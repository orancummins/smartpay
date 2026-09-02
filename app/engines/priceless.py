"""Matching real Priceless catalogue offers to Alex's actual behaviour.

Two related but distinct questions, both answered from the same 91-row real
catalogue (data/priceless_catalogue_smartpay) and the same eligibility rules:

* "What could Alex have already used?" -- purely retrospective, driven by the
  last 12 months of real spend. Powers the dashboard's own Priceless panel,
  independent of any specific request.
* "What's relevant to what ChatGPT just asked about?" -- the itinerary or
  purchase in front of SmartPay right now, checked against its destination
  city first, then the same historic-spend signal filling any remaining room.
"""

from __future__ import annotations

import collections
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.knowledge import priceless as all_priceless
from app.models.common import Category, NetworkTier
from app.models.financial import FinancialProfile
from app.models.planning import Itinerary
from app.models.rules import PricelessExperience
from app.money import fmt

#: A spend category needs at least this many real transactions before an
#: experience "inferred from" it is an inference rather than a guess dressed
#: up as one -- the same bar app.services.smartpay._priceless_for always used.
MIN_SUPPORTING_TRANSACTIONS = 8

#: Airport codes that show up in itinerary metadata, mapped to the catalogue's
#: own city names. A small explicit table rather than a geocoding call --
#: this only ever needs to resolve airports SmartPay's own scenarios and a
#: ChatGPT-plausible US trip request would plausibly use.
AIRPORT_TO_CITY: dict[str, str] = {
    "BOS": "Boston", "MCO": "Orlando", "JFK": "New York", "LGA": "New York",
    "EWR": "New York", "LAX": "Los Angeles", "ORD": "Chicago", "MIA": "Miami",
    "SFO": "San Francisco", "AUS": "Austin", "BNA": "Nashville",
    "DCA": "Washington", "IAD": "Washington", "LAS": "Las Vegas",
}

#: How many experiences to surface per spend category / per city match, and
#: overall. The catalogue is dense enough (58 culinary rows alone) that an
#: uncapped match floods the response with the same idea repeated.
PER_GROUP_LIMIT = 2
TOTAL_LIMIT = 8

#: Alex lives here (per the MCP server's own consumer profile) -- an offer
#: Alex can actually walk into is more useful than an equally-ranked one
#: three time zones away, so historic-spend matching (which has no specific
#: destination to prefer) breaks ties toward home turf.
HOME_CITY = "Boston"


def _spend_signal(profile: FinancialProfile) -> tuple[dict, dict]:
    spend: dict[Category, Decimal] = collections.defaultdict(Decimal)
    counts: dict[Category, int] = collections.Counter()
    for txn in profile.spend_transactions:
        spend[txn.category] += txn.amount
        counts[txn.category] += 1
    return spend, counts


def _tiers_held(profile: FinancialProfile) -> set[NetworkTier]:
    return {i.product.network_tier for i in profile.instruments if i.product}


def _eligible(experience: PricelessExperience, tiers: set[NetworkTier], on: date) -> bool:
    if not experience.is_available(on):
        return False
    return not experience.network_tiers or bool(tiers & set(experience.network_tiers))


def _rank_key(experience: PricelessExperience, home_city: str | None = None):
    """Home city first when one is given, then HIGH catalogue confidence,
    then World Elite-exclusive offers (the more exclusive tier reads as the
    more compelling pick), then a stable, deterministic tiebreak -- PLAN.MD
    section 38: never reorder between runs.
    """
    return (
        0 if home_city and experience.city == home_city else 1,
        0 if experience.catalogue_confidence == "HIGH" else 1,
        0 if experience.network_tiers == [NetworkTier.WORLD_ELITE] else 1,
        experience.title,
    )


def _to_dict(experience: PricelessExperience, why: str) -> dict:
    return {
        "experience_id": experience.experience_id,
        "title": experience.title,
        "city": experience.city,
        "category": experience.catalogue_category.replace("_", " ").title(),
        "price_amount": (
            str(experience.price_amount) if experience.price_amount is not None else None
        ),
        "currency": experience.currency,
        "source_url": experience.source_url,
        "image_url": (
            f"/static/{experience.image_relative_path}"
            if experience.image_relative_path else None
        ),
        # Basename only (e.g. "fine-dining-widget.jpg") -- the ChatGPT widget's
        # sandboxed iframe can't fetch image_url, so it looks this up in its
        # own pre-inlined asset map instead. See app.widget._priceless_assets.
        "widget_image_filename": (
            Path(experience.widget_image_relative_path).name
            if experience.widget_image_relative_path else None
        ),
        "image_attribution": experience.image_attribution,
        "why": why,
    }


def historic_matches(
    profile: FinancialProfile,
    on: date | None = None,
    per_group: int = PER_GROUP_LIMIT,
    total: int = TOTAL_LIMIT,
) -> list[dict]:
    """Priceless experiences Alex's real spend history actually supports --
    "what you could already have used," independent of any specific request.
    """
    on = on or date.today()
    spend, counts = _spend_signal(profile)
    tiers = _tiers_held(profile)

    by_category: dict[Category, list[PricelessExperience]] = collections.defaultdict(list)
    for experience in all_priceless():
        if not _eligible(experience, tiers, on):
            continue
        for category in experience.affinity_categories:
            if counts[category] >= MIN_SUPPORTING_TRANSACTIONS:
                by_category[category].append(experience)

    out: list[dict] = []
    for category, experiences in sorted(by_category.items(), key=lambda kv: -counts[kv[0]]):
        experiences.sort(key=lambda e: _rank_key(e, HOME_CITY))
        why = (
            f"inferred from {counts[category]} {category.value} transactions "
            f"totalling {fmt(spend[category])} in Alex's history"
        )
        for experience in experiences[:per_group]:
            out.append(_to_dict(experience, why))
            if len(out) >= total:
                return out
    return out


def _itinerary_cities(itinerary: Itinerary) -> set[str]:
    """Where this trip is actually GOING, not where it starts. Alex's home
    airport shows up as "origin" on the flight home too, and offers "relevant
    to this trip's destination, Boston" would be a wrong label for a trip
    that starts, not ends, there.
    """
    cities: set[str] = set()
    for item in itinerary.items:
        code = str((item.metadata or {}).get("destination", "")).upper()
        if code in AIRPORT_TO_CITY:
            cities.add(AIRPORT_TO_CITY[code])
    return cities


def itinerary_matches(
    profile: FinancialProfile,
    itinerary: Itinerary,
    total: int = TOTAL_LIMIT,
) -> list[dict]:
    """Priceless experiences relevant to what ChatGPT just asked about: this
    itinerary's own destination first, then Alex's historic-spend affinities
    filling whatever room is left.
    """
    on = itinerary.start_date or date.today()
    tiers = _tiers_held(profile)
    cities = _itinerary_cities(itinerary)

    out: list[dict] = []
    seen: set[str] = set()
    if cities:
        candidates = [
            e for e in all_priceless() if e.city in cities and _eligible(e, tiers, on)
        ]
        candidates.sort(key=_rank_key)
        for experience in candidates[: min(total, 3)]:
            out.append(
                _to_dict(experience, f"relevant to this trip's destination, {experience.city}")
            )
            seen.add(experience.experience_id)

    if len(out) < total:
        for match in historic_matches(profile, on=on, total=total - len(out)):
            if match["experience_id"] not in seen:
                out.append(match)
                seen.add(match["experience_id"])
    return out[:total]
