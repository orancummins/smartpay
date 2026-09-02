"""Loads the curated card / benefit / offer knowledge base from YAML.

PLAN.MD section 9: no live scraping at demo time. Everything is read from disk
once, validated through pydantic, and cached.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from app import config
from app.models.common import Category, Confidence, Evidence, EvidenceType, NetworkTier
from app.models.financial import CardProduct
from app.models.rules import BenefitRule, Offer, PricelessExperience

_CARDS = TypeAdapter(CardProduct)
_BENEFITS = TypeAdapter(list[BenefitRule])
_OFFERS = TypeAdapter(list[Offer])

#: The catalogue's own category taxonomy doesn't match our spend taxonomy --
#: it describes what the EXPERIENCE is, ours describes what the CONSUMER
#: spends on. This is what turns "you spend on dining" into "here's a
#: culinary experience," not a 1:1 rename.
_CATALOGUE_AFFINITY: dict[str, Category] = {
    "CULINARY": Category.RESTAURANT,
    "SPORTS_GOLF": Category.GOLF,
    "ENTERTAINMENT": Category.ENTERTAINMENT,
    "ARTS_CULTURE": Category.ENTERTAINMENT,
    "SPORTS_RUNNING": Category.ENTERTAINMENT,
    "SPORTS_BASEBALL": Category.ENTERTAINMENT,
    "SPORTS_FOOTBALL": Category.ENTERTAINMENT,
    "SHOPPING_FASHION": Category.SHOPPING,
    "HEALTH_WELLNESS": Category.OTHER,
    "TRAVEL": Category.HOTEL,
}

#: "MASTERCARD"/"MASTERCARD_CREDIT" in the catalogue mean "any real Mastercard
#: tier", not literally our STANDARD tier -- Alex's actual cards only ever
#: carry WORLD or WORLD_ELITE (see data/cards/*.yaml), so restricting to
#: WORLD_ELITE alone would silently drop every Double Cash-eligible offer.
_CATALOGUE_TIER: dict[str, list[NetworkTier]] = {
    "WORLD_ELITE": [NetworkTier.WORLD_ELITE],
    "MASTERCARD": [NetworkTier.WORLD, NetworkTier.WORLD_ELITE],
    "MASTERCARD_CREDIT": [NetworkTier.WORLD, NetworkTier.WORLD_ELITE],
}


def _parse_catalogue_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _priceless_from_catalogue(entry: dict) -> PricelessExperience:
    """One row of data/priceless_catalogue_smartpay -> a PricelessExperience.

    Never AUTHORITATIVE: the catalogue was assembled by a public search index,
    not read by us off a live page -- several source_url values are
    demonstrably stale or point at a generic collection page rather than this
    specific offer, which is also why the image comes from a separately
    resolved, verified subject (app.priceless_images) rather than whatever
    this row's own source_url happens to point at.
    """
    from app import priceless_images  # avoids every knowledge.py caller needing httpx

    catalogue_category = entry.get("category") or ""
    notes = entry.get("notes")
    catalogue_confidence = entry.get("confidence") or "MEDIUM"
    note = (
        f"Surfaced by the Mastercard Priceless catalogue's public search index "
        f"(catalogue confidence: {catalogue_confidence}). "
        + (notes or "Not independently re-verified by SmartPay.")
    )
    evidence = Evidence(
        evidence_type=EvidenceType.PRICELESS,
        source_name="Mastercard Priceless catalogue",
        source_url=entry.get("source_url") or entry.get("visual_page_url"),
        verified_at=_parse_catalogue_date(entry.get("last_verified_at")),
        confidence=Confidence.DEMO_APPROXIMATION,
        note=note,
    )
    price = entry.get("price_amount")
    subject, _is_specific = priceless_images.subject_for(entry["offer_id"], catalogue_category)
    image_record = priceless_images.get_cached(subject) if subject else None
    return PricelessExperience(
        experience_id=entry["offer_id"],
        title=entry["title"],
        city=entry.get("city"),
        affinity_categories=(
            [_CATALOGUE_AFFINITY[catalogue_category]]
            if catalogue_category in _CATALOGUE_AFFINITY else []
        ),
        network_tiers=_CATALOGUE_TIER.get(entry.get("eligibility_tier") or "", []),
        available_from=_parse_catalogue_date(entry.get("valid_from")),
        available_to=_parse_catalogue_date(entry.get("valid_to")),
        description=entry.get("eligibility_text") or "",
        evidence=evidence,
        catalogue_category=catalogue_category,
        catalogue_confidence=catalogue_confidence,
        offer_type=entry.get("offer_type") or "",
        price_amount=Decimal(str(price)) if price is not None else None,
        currency=entry.get("currency") or "USD",
        tags=list(entry.get("tags") or []),
        source_url=entry.get("source_url"),
        image_relative_path=image_record.get("relative_path") if image_record else None,
        widget_image_relative_path=(
            image_record.get("widget_relative_path") if image_record else None
        ),
        image_attribution=image_record.get("attribution") if image_record else None,
    )


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


@lru_cache(maxsize=1)
def card_products() -> dict[str, CardProduct]:
    products: dict[str, CardProduct] = {}
    for path in sorted((config.DATA / "cards").glob("*.yaml")):
        product = _CARDS.validate_python(_load_yaml(path))
        products[product.product_id] = product
    return products


@lru_cache(maxsize=1)
def benefits() -> list[BenefitRule]:
    """Network benefits and issuer credits, in one list.

    They are separate files because they are separate kinds of claim, but the
    engine evaluates them uniformly.
    """
    out: list[BenefitRule] = []
    for folder in ("mastercard", "benefits"):
        for path in sorted((config.DATA / folder).glob("*.yaml")):
            doc = _load_yaml(path)
            if "benefits" in doc:
                out.extend(_BENEFITS.validate_python(doc["benefits"]))
    return out


@lru_cache(maxsize=1)
def offers() -> list[Offer]:
    path = config.DATA / "mastercard" / "offers.yaml"
    return _OFFERS.validate_python(_load_yaml(path).get("offers", []))


@lru_cache(maxsize=1)
def priceless() -> list[PricelessExperience]:
    """The real Priceless catalogue -- data/priceless_catalogue_smartpay,
    already curated for this consumer (every row carries an "alex" tag).
    Supersedes the two hand-written demo records the codebase started with;
    those covered exactly the same ground (Orlando golf, Orlando dining) with
    fabricated evidence, which real catalogue rows now do honestly instead.
    """
    path = config.DATA / "priceless_catalogue_smartpay" / "priceless_catalogue.json"
    entries = json.loads(path.read_text())
    return [_priceless_from_catalogue(e) for e in entries]


def reset_cache() -> None:
    for fn in (card_products, benefits, offers, priceless):
        fn.cache_clear()
