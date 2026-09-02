"""End-to-end tests, including the golden file for the rehearsed demo.

PLAN.MD section 38: demo reliability matters more than breadth. The golden test
is the safety net -- it fails the moment any number said on stage changes.
"""

import json
from pathlib import Path

import pytest

from app.services.smartpay import SmartPayService

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "golden_disney_plan.json").read_text())


@pytest.fixture(scope="module")
def service():
    return SmartPayService()


def test_alex_profile_builds(service):
    result = service.get_financial_profile("alex")
    assert result["display_markdown"].startswith("## Financial profile")
    assert result["data"]["account_count"] == 8
    assert "Chase, Citi" in result["data"]["institutions"]
    assert result["disclaimers"], "synthetic data must always be disclosed"


def test_wallet_lists_six_cards(service):
    cards = service.get_wallet("alex")["data"]["cards"]
    assert len(cards) == 6
    assert sum(1 for c in cards if "Mastercard" in c["network"]) == 4


def test_disney_itinerary_matches_golden_totals(service):
    """The headline numbers must not drift. This is the number said on stage."""
    data = service.optimise_itinerary()["data"]
    assert data["itinerary_total"] == GOLDEN["itinerary_total"]
    assert data["incremental_guaranteed"] == GOLDEN["incremental_guaranteed"]
    assert data["incremental_estimated"] == GOLDEN["incremental_estimated"]
    assert data["incremental_points"] == GOLDEN["incremental_points"]


def test_disney_itinerary_matches_golden_line_by_line(service):
    actual = service.optimise_itinerary()["data"]["recommendations"]
    assert len(actual) == len(GOLDEN["recommendations"])
    for got, want in zip(actual, GOLDEN["recommendations"]):
        for key, value in want.items():
            assert got[key] == value, f"{want['recommendation_id']}.{key} drifted"


def test_optimisation_is_deterministic(service):
    """Two runs must be byte-identical, or the rehearsal is worthless."""
    first = service.optimise_itinerary()["display_markdown"]
    second = SmartPayService().optimise_itinerary()["display_markdown"]
    assert first == second


def test_portal_upgrade_is_actually_recommended(service):
    """The section 15 channel mechanic must visibly earn its place in the demo."""
    recs = service.optimise_itinerary()["data"]["recommendations"]
    portal = [r for r in recs if r["recommended_channel"] != "booked direct"]
    assert portal, "no line item benefits from the travel portal"
    assert all("Citi Travel" in r["recommended_channel"] for r in portal)


def test_baseline_differs_from_recommendation(service):
    """If SmartPay only ever confirmed existing habits there would be no story."""
    recs = service.optimise_itinerary()["data"]["recommendations"]
    changed = [r for r in recs if r["baseline_payment"] != r["recommended_payment"]]
    assert len(changed) >= 4


def test_offers_are_real_and_labelled(service):
    """Sourced Mastercard card-linked offers must reach the user labelled as real."""
    result = service.optimise_itinerary()
    assert any("real Mastercard card-linked offers" in d for d in result["disclaimers"])
    offers = [o for r in result["data"]["recommendations"] for o in r["offers"]]
    assert offers
    for o in offers:
        assert o["label"] == "Mastercard card-linked offer"


def test_sourced_reward_programs_stay_off_alex_without_an_issuer_match(service):
    """Alex banks with Citi and Chase; neither runs an earn program in the sourced US
    rewards catalogue. The issuer-matched layer must therefore leave his plan
    untouched -- it must never attach another issuer's program to his cards."""
    data = service.optimise_itinerary()["data"]
    programs = [rp for r in data["recommendations"] for rp in r["reward_programs"]]
    assert programs == []


def test_guaranteed_and_estimated_are_never_merged(service):
    """PLAN.MD section 16: no fake precision."""
    md = service.optimise_itinerary()["display_markdown"]
    assert "**Guaranteed savings:" in md
    assert "Estimated additional reward value:" in md


def test_priceless_is_inferred_from_history_not_asserted(service):
    """Every match traces to something real: either Alex's own spend history,
    or the itinerary's own destination -- never asserted with no reason."""
    priceless = service.optimise_itinerary()["data"]["priceless"]
    assert priceless
    for p in priceless:
        assert "inferred from" in p["why"] or "relevant to this trip's destination" in p["why"]
    md = service.optimise_itinerary()["display_markdown"]
    assert "excluded from the savings figures" in md


def test_priceless_leads_with_the_itinerary_destination(service):
    """The known Disney scenario flies into Orlando; the real catalogue has a
    real Orlando golf offer, so it must be the top Priceless match -- not
    buried under Alex's unrelated historic-spend affinities.
    """
    priceless = service.optimise_itinerary()["data"]["priceless"]
    assert priceless[0]["city"] == "Orlando"
    assert "this trip's destination" in priceless[0]["why"]


def test_priceless_never_pads_a_known_destination_with_other_cities(service):
    """A trip with a resolvable destination must only ever show offers in that
    city -- topping up an empty-looking list with Alex's Boston/LA/NYC
    historic-spend picks under a "for this trip" heading would misrepresent
    them as relevant to a Disney/Orlando trip when they are not."""
    priceless = service.optimise_itinerary()["data"]["priceless"]
    assert priceless
    assert all(p["city"] == "Orlando" for p in priceless)


def test_wallet_optimisation_matches_golden(service):
    rec = service.optimise_wallet()["data"]["recommendation"]
    assert rec["action"] == GOLDEN["wallet_action"]
    assert rec["net_annual_incremental_value"] == GOLDEN["wallet_net_incremental"]
    assert rec["current_wallet_value"] == GOLDEN["wallet_current_value"]


def test_wallet_recommendation_keeps_the_card_that_earns_its_fee(service):
    """The AAdvantage card's $99 fee is repaid many times by the baggage waiver.

    An earlier version dropped it, because the wallet model priced reward rates but
    not benefits. Recommending someone ditch the card that just saved them $360
    would not survive a judge's first question.
    """
    rec = service.optimise_wallet()["data"]["recommendation"]
    assert "AAdvantage" not in rec["headline"]


def test_wallet_forecast_is_labelled_as_a_demo_adapter(service):
    result = service.optimise_wallet()
    assert any("CommerceGPT" in d for d in result["disclaimers"])
    assert result["data"]["forecast"]["method"] == "Demo CommerceGPT adapter"


def test_evidence_is_available_for_every_recommendation(service):
    service.optimise_itinerary()
    for item in ("flights", "hotel", "tickets", "transport"):
        result = service.get_recommendation_evidence(f"disney_october_2026:{item}")
        md = result["display_markdown"]
        assert md.startswith("## Why SmartPay recommended this")
        assert "| Source |" in md


def test_evidence_survives_a_cold_start():
    """A fresh process must still answer 'why?' without a prior optimise call."""
    cold = SmartPayService()
    result = cold.get_recommendation_evidence("disney_october_2026:flights")
    assert "Why SmartPay recommended this" in result["display_markdown"]


def test_evidence_cites_a_real_verified_source(service):
    service.optimise_itinerary()
    md = service.get_recommendation_evidence("disney_october_2026:flights")["display_markdown"]
    assert "authoritative" in md
    assert "2026-09-01" in md
    assert "http" in md


def test_engine_handles_a_chatgpt_authored_itinerary(service):
    """ChatGPT will send prose and its own amounts. Nothing may blow up."""
    result = service.optimise_itinerary(
        "alex",
        {
            "title": "A trip ChatGPT invented",
            "start_date": "2026-10-12",
            "items": [
                {"label": "Flights to Orlando", "merchant": "American Airlines",
                 "amount": "1600", "metadata": {"travellers": 4, "checked_bags": 4,
                                                "segments": 2}},
                {"label": "Disney's Pop Century Resort", "merchant": "Disney's Pop Century Resort",
                 "amount": "1900"},
                {"label": "Park tickets", "merchant": "Walt Disney World", "amount": "1800"},
                {"label": "Dinner somewhere", "merchant": "Some Restaurant", "amount": "400"},
                {"label": "A thing we cannot classify", "merchant": "Blorptron", "amount": "100"},
            ],
        },
    )
    data = result["data"]
    assert len(data["recommendations"]) == 5
    assert float(data["incremental_guaranteed"]) > 0
    # The unclassifiable line must still be handled, just with no invented value.
    unknown = data["recommendations"][-1]
    assert unknown["guaranteed_savings"] == "0.00"


def test_service_never_exposes_a_money_moving_tool():
    """PLAN.MD section 39: read-only and advisory."""
    forbidden = {"apply_for_card", "make_payment", "purchase", "move_money",
                 "switch_card", "open_account"}
    assert not forbidden & set(dir(SmartPayService))


# --- disclosed network tiebreak ---------------------------------------------


def test_network_tiebreak_only_fires_on_an_exact_tie(service):
    """The Mastercard preference is legitimate only if it is only ever applied to a
    genuine tie.

    The tie test must run on the PRE-bonus score: a rival must have scored EXACTLY
    the same as the Mastercard winner once its tiebreak bonus is subtracted back
    out, or SmartPay would be manufacturing a win rather than breaking a real one.
    """
    from app.engines.optimizer import PurchaseOptimizer
    from app.engines.categorizer import categorise
    from app.providers.open_finance import SyntheticAlexProvider
    from app.scenarios import load_scenario

    profile = SyntheticAlexProvider().get_profile("alex")
    optimizer = PurchaseOptimizer(profile)

    for item in load_scenario("disney_october_2026").items:
        key = categorise(item.merchant, item.label, item.category).merchant_key
        options = optimizer.options_for(item, key)
        winner = options[0]
        if winner.tiebreak_note is None:
            continue
        rivals = [o for o in options[1:] if not o.is_mastercard and o.channel is winner.channel]
        assert rivals, "tiebreak fired with no rival to break against"
        assert rivals[0].score == winner.score - winner.tiebreak_bonus, (
            "tiebreak fired on a non-tie"
        )


def test_network_tiebreak_is_always_disclosed(service):
    """It must never be applied silently."""
    result = service.optimise_itinerary()
    tied = [r for r in result["data"]["recommendations"] if r["tiebreak_note"]]
    if not tied:
        pytest.skip("no tie in the current dataset")

    assert any("simulated Mastercard tiebreak incentive" in d for d in result["disclaimers"])
    md = result["display_markdown"]
    assert "worth **exactly** the same" in md
    assert "funds an extra 5%" in md
    for r in tied:
        assert "Exact tie on value with" in r["tiebreak_note"]
        assert "funds an extra 5%" in r["tiebreak_note"]


def test_tiebreak_funds_a_real_5_percent_statement_credit(service):
    """Breaking a tie in Mastercard's favour now genuinely funds the difference --
    it is a real statement credit, not just a stated preference with no dollars
    behind it. The headline number must move by exactly the bonus, no more."""
    from decimal import Decimal

    from app.money import quantize

    result = service.optimise_itinerary()
    tied = [r for r in result["data"]["recommendations"] if r["tiebreak_note"]]
    assert tied, "expected the known Disney dining tie in the frozen scenario"
    for r in tied:
        assert Decimal(r["guaranteed_savings"]) == quantize(Decimal(r["amount"]) * Decimal("0.05"))
    assert result["data"]["incremental_guaranteed"] == "542.90"


# --- apply-for-a-Mastercard CTA, evidence-backed -----------------------------


def test_apply_offer_is_only_attached_on_a_genuine_switch_to_a_mastercard(service):
    """No offer on a line that already matches the baseline, and never on a
    line that recommends a Visa -- an "apply" pitch has to follow a real
    switch, not decorate every row."""
    result = service.optimise_itinerary()
    for r in result["data"]["recommendations"]:
        if r["apply_offer"] is not None:
            assert r["is_mastercard"]
            assert r["baseline_payment"] != r["recommended_payment"]


def test_apply_offer_links_to_the_products_own_verified_evidence(service):
    from app.knowledge import card_products

    result = service.optimise_itinerary()
    offers = [r["apply_offer"] for r in result["data"]["recommendations"] if r["apply_offer"]]
    assert offers, "expected at least one apply offer in the known Disney scenario"
    products_by_name = {p.display_name: p for p in card_products().values()}
    for offer in offers:
        product = products_by_name[offer["card"]]
        assert offer["url"] == product.evidence.source_url
        assert offer["url"].startswith("https://")


def test_apply_offer_savings_figure_matches_savings_by_card(service):
    from decimal import Decimal

    from app import analytics
    from app.knowledge import card_products
    from app.providers.open_finance import SyntheticAlexProvider

    result = service.optimise_itinerary()
    profile = SyntheticAlexProvider().get_profile("alex")
    by_card = analytics.savings_by_card(profile)
    products = card_products()
    ids_by_name = {p.display_name: pid for pid, p in products.items()}

    for r in result["data"]["recommendations"]:
        offer = r["apply_offer"]
        if not offer:
            continue
        instrument_id = ids_by_name[offer["card"]]
        assert Decimal(offer["historic_savings"]) == by_card[instrument_id]


def test_markdown_highlights_the_funded_discount_before_the_table(service):
    result = service.optimise_itinerary()
    md = result["display_markdown"]
    assert "Mastercard-funded discount on this response" in md
    assert md.index("Mastercard-funded discount") < md.index("| Item |")


def test_markdown_names_the_same_apply_card_only_once(service):
    """The same card can win several lines in one itinerary; the apply pitch
    must appear once, not once per line, or it reads as spam."""
    result = service.optimise_itinerary()
    md = result["display_markdown"]
    for r in result["data"]["recommendations"]:
        offer = r["apply_offer"]
        if offer:
            assert md.count(f"[Apply for {offer['card']}]") == 1


def test_tiebreak_never_overrides_a_better_non_mastercard_option():
    """A Visa that genuinely wins must still win. Constructed so Chase leads outright."""
    from app.engines.optimizer import PurchaseOptimizer
    from app.models.common import Category
    from app.models.planning import PurchaseIntent
    from app.providers.open_finance import SyntheticAlexProvider
    from decimal import Decimal

    profile = SyntheticAlexProvider().get_profile("alex")
    # Drugstore: Freedom Unlimited earns 3%, no Mastercard in the wallet matches it.
    purchase = PurchaseIntent(
        merchant="cvs", category=Category.DRUGSTORE, amount=Decimal("400")
    )
    winner = PurchaseOptimizer(profile).options_for(purchase, "cvs")[0]
    assert winner.instrument_id == "chase_freedom_unlimited"
    assert not winner.is_mastercard
    assert winner.tiebreak_note is None
