"""The categorizer's real job: absorbing whatever prose ChatGPT sends.

Every phrasing here is one a model plausibly emits when planning a Disney trip.
"""

import pytest

from app.engines.categorizer import categorise
from app.models.common import Category

CASES = [
    # (input, expected category, expected merchant_key or None)
    ("American Airlines", Category.AIRFARE, "american_airlines"),
    ("American Airlines BOS-MCO", Category.AIRFARE, "american_airlines"),
    ("Round-trip flights for 4", Category.AIRFARE, None),
    ("Delta Air Lines", Category.AIRFARE, "delta"),
    ("JetBlue Airways flight", Category.AIRFARE, "jetblue"),
    ("Disney's Art of Animation Resort", Category.HOTEL, "disney_resort"),
    ("Disney's Pop Century Resort, 5 nights", Category.HOTEL, "disney_resort"),
    ("Caribbean Beach Resort", Category.HOTEL, "disney_resort"),
    ("Hotel accommodation", Category.HOTEL, None),
    ("Marriott Bonvoy", Category.HOTEL, "marriott"),
    ("Walt Disney World", Category.ATTRACTION, "walt_disney_world"),
    ("Walt Disney World park tickets", Category.ATTRACTION, "walt_disney_world"),
    ("Disney World 5-day park tickets", Category.ATTRACTION, "walt_disney_world"),
    ("Magic Kingdom admission", Category.ATTRACTION, "walt_disney_world"),
    ("Epcot", Category.ATTRACTION, "walt_disney_world"),
    ("Universal Studios", Category.ATTRACTION, "universal_orlando"),
    ("Theme park tickets", Category.ATTRACTION, None),
    ("Lyft", Category.RIDESHARE, "lyft"),
    ("Uber to MCO airport", Category.RIDESHARE, "uber"),
    ("Airport transport", Category.RIDESHARE, None),
    ("Airport transfer", Category.RIDESHARE, None),
    ("Rental car", Category.CAR_RENTAL, None),
    ("Hertz Rent A Car", Category.CAR_RENTAL, "hertz"),
    ("Restaurants and dining", Category.RESTAURANT, None),
    ("Dinner reservations", Category.RESTAURANT, None),
    ("Character breakfast", Category.RESTAURANT, None),
    ("Groceries", Category.SUPERMARKET, None),
    ("Instacart", Category.GROCERY_ONLINE, "instacart"),
    ("Souvenirs and gifts", Category.SHOPPING, None),
    ("Gas / fuel", Category.GAS, None),
]


@pytest.mark.parametrize("text,expected_category,expected_merchant", CASES)
def test_chatgpt_phrasings(text, expected_category, expected_merchant):
    result = categorise(text)
    assert result.category is expected_category, f"{text!r} -> {result.category}"
    if expected_merchant:
        assert result.merchant_key == expected_merchant, f"{text!r} -> {result.merchant_key}"


def test_explicit_category_from_caller_wins():
    """If ChatGPT tells us the category, believe it over our own guess."""
    result = categorise("Some Obscure Vendor", explicit_category=Category.HOTEL)
    assert result.category is Category.HOTEL
    assert result.confident


def test_unknown_merchant_is_flagged_not_guessed():
    """An unrecognised merchant must earn base rate only, and say why.

    Silently guessing a category here would invent reward value out of nothing.
    """
    result = categorise("Blorptron Incorporated")
    assert result.category is Category.OTHER
    assert not result.confident
    assert "base rate only" in result.explanation


def test_fuzzy_handles_a_typo():
    assert categorise("Amercan Airlines").merchant_key == "american_airlines"
