"""Engine unit tests. PLAN.MD section 37."""

from datetime import date
from decimal import Decimal

import pytest

from app.engines.baseline import MIN_SUPPORT, BaselineEngine
from app.engines.benefits import BenefitsEngine
from app.engines.offers import OffersEngine
from app.engines.rewards import RewardsEngine, available_channels
from app.models.common import Category, PurchaseChannel
from app.models.planning import PurchaseIntent
from app.providers.open_finance import SyntheticAlexProvider

PROFILE = SyntheticAlexProvider().get_profile("alex")
INST = {i.instrument_id: i for i in PROFILE.instruments}
REWARDS = RewardsEngine()
OFFERS = OffersEngine()
BENEFITS = BenefitsEngine()
OCT = date(2026, 10, 12)


def buy(merchant, category, amount, **meta):
    return PurchaseIntent(
        merchant=merchant, category=category, amount=Decimal(amount),
        purchase_date=OCT, metadata=meta,
    )


def test_reward_base_earn():
    """A category with no bonus rule falls back to the card's base rate."""
    p = buy("some_shop", Category.SHOPPING, "100")
    r = REWARDS.evaluate(p, INST["citi_strata_premier"])
    assert r.multiplier == Decimal("1")
    assert r.points == 100


def test_reward_category_multiplier():
    p = buy("publix", Category.SUPERMARKET, "200")
    r = REWARDS.evaluate(p, INST["citi_strata_premier"])
    assert r.multiplier == Decimal("3")
    assert r.points == 600


def test_cashback_multiplier_is_percent_not_points():
    """2% must be $2 on $100, not 200 points. A factor-of-100 error is available here."""
    p = buy("some_shop", Category.SHOPPING, "100")
    r = REWARDS.evaluate(p, INST["citi_double_cash"])
    assert r.points == 0
    assert r.estimated_value == Decimal("2.00")


def test_portal_only_rule_applies_through_the_portal():
    p = buy("disney_resort", Category.HOTEL, "1000")
    r = REWARDS.evaluate(p, INST["citi_strata_premier"], PurchaseChannel.CITI_TRAVEL)
    assert r.multiplier == Decimal("10")
    assert r.rule_id == "STRATA_PORTAL_10X"


def test_direct_booking_does_not_receive_portal_bonus():
    """PLAN.MD section 15. The single most damaging error the engine could make."""
    p = buy("disney_resort", Category.HOTEL, "1000")
    r = REWARDS.evaluate(p, INST["citi_strata_premier"], PurchaseChannel.MERCHANT_DIRECT)
    assert r.multiplier == Decimal("3")
    assert "STRATA_PORTAL_10X" in r.channel_blocked_rule_ids


def test_a_card_cannot_earn_through_a_rival_portal():
    p = buy("disney_resort", Category.HOTEL, "1000")
    r = REWARDS.evaluate(p, INST["chase_sapphire_preferred"], PurchaseChannel.CITI_TRAVEL)
    assert r.multiplier == Decimal("2"), "Chase card must not earn on Citi Travel"


def test_only_travel_categories_offer_a_portal_channel():
    """Nobody books a restaurant meal through a travel portal."""
    assert available_channels(Category.RESTAURANT, INST["citi_strata_premier"]) == [
        PurchaseChannel.MERCHANT_DIRECT
    ]
    assert PurchaseChannel.CITI_TRAVEL in available_channels(
        Category.HOTEL, INST["citi_strata_premier"]
    )


def test_offer_minimum_spend():
    small = buy("walt_disney_world", Category.ATTRACTION, "500")
    big = buy("walt_disney_world", Category.ATTRACTION, "1780")
    assert OFFERS.evaluate(small, INST["citi_strata_premier"]) == []
    assert len(OFFERS.evaluate(big, INST["citi_strata_premier"])) == 1


def test_offer_date_window_excludes_expired():
    p = buy("walt_disney_world", Category.ATTRACTION, "1780")
    p.purchase_date = date(2026, 12, 25)
    assert OFFERS.evaluate(p, INST["citi_strata_premier"]) == []


def test_offer_is_restricted_to_eligible_card():
    p = buy("walt_disney_world", Category.ATTRACTION, "1780")
    assert OFFERS.evaluate(p, INST["chase_sapphire_preferred"]) == []


def test_offer_does_not_leak_to_an_unrelated_merchant():
    """A Walt Disney World offer must not pay out on a Marriott stay."""
    p = buy("marriott", Category.HOTEL, "2000")
    assert OFFERS.evaluate(p, INST["citi_strata_premier"]) == []


def test_world_elite_benefit():
    p = buy("lyft", Category.RIDESHARE, "180", airport=True)
    we = BENEFITS.evaluate_purchase(p, INST["citi_aa_platinum_select"])
    assert any(b.benefit_id == "MC_WE_LYFT_AIRPORT_10PCT" and b.value == Decimal("18.00")
               for b in we)


def test_world_tier_does_not_get_a_world_elite_benefit():
    """Double Cash is World, not World Elite. Verified against mastercard.com."""
    p = buy("lyft", Category.RIDESHARE, "180", airport=True)
    ids = {b.benefit_id for b in BENEFITS.evaluate_purchase(p, INST["citi_double_cash"])}
    assert "MC_WE_LYFT_AIRPORT_10PCT" not in ids


def test_checked_bag_benefit_is_priced_per_bag_and_direction():
    p = buy("american_airlines", Category.AIRFARE, "1420",
            travellers=4, checked_bags=4, segments=2)
    b = next(x for x in BENEFITS.evaluate_purchase(p, INST["citi_aa_platinum_select"])
             if x.benefit_id == "AA_FREE_CHECKED_BAG")
    assert b.value == Decimal("360.00")  # 4 bags x 2 directions x $45


def test_checked_bag_benefit_caps_at_five_people():
    """Cardholder plus up to four companions. A party of ten does not get ten bags."""
    p = buy("american_airlines", Category.AIRFARE, "5000",
            travellers=10, checked_bags=10, segments=2)
    b = next(x for x in BENEFITS.evaluate_purchase(p, INST["citi_aa_platinum_select"])
             if x.benefit_id == "AA_FREE_CHECKED_BAG")
    assert b.value == Decimal("450.00")  # 5 bags x 2 directions x $45


def test_hotel_credit_requires_the_issuer_portal():
    p = buy("disney_resort", Category.HOTEL, "2450")
    direct = {b.benefit_id for b in BENEFITS.evaluate_purchase(
        p, INST["citi_strata_premier"], PurchaseChannel.MERCHANT_DIRECT)}
    portal = {b.benefit_id for b in BENEFITS.evaluate_purchase(
        p, INST["citi_strata_premier"], PurchaseChannel.CITI_TRAVEL)}
    assert "STRATA_HOTEL_100" not in direct
    assert "STRATA_HOTEL_100" in portal


def test_hotel_credit_respects_minimum_stay_value():
    p = buy("disney_resort", Category.HOTEL, "400")
    ids = {b.benefit_id for b in BENEFITS.evaluate_purchase(
        p, INST["citi_strata_premier"], PurchaseChannel.CITI_TRAVEL)}
    assert "STRATA_HOTEL_100" not in ids


def test_debit_earns_nothing_and_says_so():
    p = buy("publix", Category.SUPERMARKET, "200")
    r = REWARDS.evaluate(p, INST["debit_chase"])
    assert r.estimated_value == Decimal("0.00")
    assert "no card rewards" in r.explanation


# --- baseline ---------------------------------------------------------------

BASELINE = BaselineEngine(PROFILE)


def test_baseline_probability_reflects_history():
    d = BASELINE.distribution(Category.RESTAURANT, "local_bistro")
    assert d.most_likely == "chase_sapphire_preferred"
    assert Decimal("0.4") < d.probability("chase_sapphire_preferred") < Decimal("0.9")


def test_baseline_never_claims_certainty_from_thin_evidence():
    """Laplace smoothing: no distribution may reach probability 1.0."""
    for category in Category:
        d = BASELINE.distribution(category, "a_merchant_never_seen_before")
        for p in d.probabilities.values():
            assert p < Decimal("1.0")


def test_baseline_falls_back_when_support_is_thin():
    """Attractions are too rare on their own, so the travel group carries them."""
    d = BASELINE.distribution(Category.ATTRACTION, "walt_disney_world")
    assert d.level in {"category group", "global"}
    assert d.support >= MIN_SUPPORT


def test_baseline_probabilities_sum_to_one():
    d = BASELINE.distribution(Category.RESTAURANT, "local_bistro")
    assert sum(d.probabilities.values()) == pytest.approx(Decimal("1"), abs=Decimal("0.0001"))


# --- domestic-only benefits -------------------------------------------------


def test_checked_bag_benefit_is_domestic_only():
    """Citi's wording is "domestic American Airlines itineraries".

    The operator running this demo may be outside the US, so ChatGPT can plausibly
    plan a transatlantic trip. Paying the waiver out on one would overstate the
    card by $360 -- the single largest figure in the demo.
    """
    domestic = buy("american_airlines", Category.AIRFARE, "2400",
                   travellers=4, checked_bags=4, segments=2,
                   origin="BOS", destination="MCO")
    assert any(b.benefit_id == "AA_FREE_CHECKED_BAG"
               for b in BENEFITS.evaluate_purchase(domestic, INST["citi_aa_platinum_select"]))

    for origin in ("DUB", "LHR", "CDG", "SYD"):
        international = buy("american_airlines", Category.AIRFARE, "2400",
                            travellers=4, checked_bags=4, segments=2,
                            origin=origin, destination="MCO")
        ids = {b.benefit_id
               for b in BENEFITS.evaluate_purchase(international, INST["citi_aa_platinum_select"])}
        assert "AA_FREE_CHECKED_BAG" not in ids, f"{origin} wrongly earned the waiver"


def test_non_us_location_also_blocks_a_domestic_benefit():
    p = buy("american_airlines", Category.AIRFARE, "2400",
            travellers=4, checked_bags=4, segments=2)
    p.location = "IE"
    ids = {b.benefit_id for b in BENEFITS.evaluate_purchase(p, INST["citi_aa_platinum_select"])}
    assert "AA_FREE_CHECKED_BAG" not in ids


def test_explicit_international_flag_blocks_a_domestic_benefit():
    p = buy("american_airlines", Category.AIRFARE, "2400",
            travellers=4, checked_bags=4, segments=2, international=True)
    ids = {b.benefit_id for b in BENEFITS.evaluate_purchase(p, INST["citi_aa_platinum_select"])}
    assert "AA_FREE_CHECKED_BAG" not in ids
