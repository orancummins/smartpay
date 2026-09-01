"""Loads the curated card / benefit / offer knowledge base from YAML.

PLAN.MD section 9: no live scraping at demo time. Everything is read from disk
once, validated through pydantic, and cached.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from app import config
from app.models.financial import CardProduct
from app.models.rules import BenefitRule, Offer, PricelessExperience

_CARDS = TypeAdapter(CardProduct)
_BENEFITS = TypeAdapter(list[BenefitRule])
_OFFERS = TypeAdapter(list[Offer])
_PRICELESS = TypeAdapter(list[PricelessExperience])


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
    path = config.DATA / "mastercard" / "priceless.yaml"
    return _PRICELESS.validate_python(_load_yaml(path).get("experiences", []))


def reset_cache() -> None:
    for fn in (card_products, benefits, offers, priceless):
        fn.cache_clear()
