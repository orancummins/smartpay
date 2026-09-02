"""The two headline money figures on the dashboard: accumulated (retrospective)
and potential future (prospective, cumulative) savings.
"""

from decimal import Decimal

from app import analytics
from app.providers.open_finance import SyntheticAlexProvider


def test_accumulated_savings_is_computed_not_asserted():
    """The whole point: a real number from real rules over real transactions, not
    a figure typed into the UI."""
    profile = SyntheticAlexProvider().get_profile("alex")
    result = analytics.accumulated_savings(profile)
    assert result["guaranteed"] > Decimal("0")
    assert result["top_driver"]


def test_accumulated_savings_excludes_fees_from_the_transaction_count():
    """spend_transactions includes fees (PLAN.MD section 7 counts a fee as
    consumer spend); this comparison must not, since a late fee is assessed on
    whatever card was already in use -- it is not a "which card should I use"
    decision a different choice could have changed.
    """
    from app.models.financial import TransactionType

    profile = SyntheticAlexProvider().get_profile("alex")
    result = analytics.accumulated_savings(profile)
    purchases_only = sum(
        1 for t in profile.spend_transactions
        if t.transaction_type is TransactionType.PURCHASE
    )
    assert result["transaction_count"] == purchases_only
    assert result["transaction_count"] < len(profile.spend_transactions)


def test_accumulated_savings_is_deterministic():
    profile = SyntheticAlexProvider().get_profile("alex")
    first = analytics.accumulated_savings(profile)
    second = analytics.accumulated_savings(profile)
    assert first == second


def test_accumulated_savings_never_goes_negative():
    """Only transactions where a better card existed contribute; a transaction
    already on the optimal card contributes zero, never a negative adjustment."""
    profile = SyntheticAlexProvider().get_profile("alex")
    result = analytics.accumulated_savings(profile)
    assert result["guaranteed"] >= Decimal("0")


def test_detect_subscriptions_finds_recurring_charges_not_variable_spend():
    """Near-constant monthly merchants are surfaced (Minna-style); variable spend
    and rent are not."""
    profile = SyntheticAlexProvider().get_profile("alex")
    data = analytics.detect_subscriptions(profile)
    names = {i["merchant"] for i in data["items"]}
    assert {"netflix", "spotify", "peacock"} <= names   # streaming subscriptions
    assert "verizon" in names                            # a recurring utility bill
    assert "beacon_property" not in names                # rent is not a subscription
    assert "starbucks" not in names                      # variable spend is not
    assert data["streaming_count"] == 3
    assert Decimal(data["monthly_total"]) > Decimal("0")
    assert Decimal(data["annual_total"]) == Decimal(data["monthly_total"]) * 12
    for item in data["items"]:
        assert item["type"] in ("subscription", "bill")
        assert Decimal(item["amount"]) > Decimal("0")
        assert item["next_renewal"]


def test_potential_future_savings_starts_at_the_wallet_baseline():
    result = analytics.potential_future_savings(Decimal("90.00"))
    assert result["enquiry_count"] == 0
    assert result["total"] == Decimal("90.00")


def test_reasking_the_same_trip_updates_rather_than_doubles():
    analytics.record_identified("disney", "Disney", Decimal("553.00"), Decimal("359.70"))
    analytics.record_identified("disney", "Disney", Decimal("553.00"), Decimal("359.70"))
    result = analytics.potential_future_savings(Decimal("0"))
    assert result["enquiry_count"] == 1
    assert result["enquiries_guaranteed"] == Decimal("553.00")


def test_distinct_enquiries_each_add_to_the_running_total():
    analytics.record_identified("disney", "Disney", Decimal("553.00"), Decimal("359.70"))
    analytics.record_identified("ireland", "Ireland", Decimal("100.00"), Decimal("188.60"))
    result = analytics.potential_future_savings(Decimal("10.00"))
    assert result["enquiry_count"] == 2
    assert result["enquiries_guaranteed"] == Decimal("653.00")
    assert result["enquiries_estimated"] == Decimal("548.30")
    # total = wallet base + every distinct enquiry's guaranteed AND estimated value.
    assert result["total"] == Decimal("1211.30")


def test_ledger_survives_being_asked_about_repeatedly_with_updated_numbers():
    """Re-running the same trip with a different result (e.g. after an engine fix)
    must replace its contribution, not add to it."""
    analytics.record_identified("disney", "Disney", Decimal("500.00"), Decimal("300.00"))
    analytics.record_identified("disney", "Disney", Decimal("553.00"), Decimal("359.70"))
    result = analytics.potential_future_savings(Decimal("0"))
    assert result["enquiries_guaranteed"] == Decimal("553.00")


def test_missing_ledger_file_reads_as_no_enquiries_yet():
    result = analytics.potential_future_savings(Decimal("42.00"))
    assert result["enquiry_count"] == 0
    assert result["total"] == Decimal("42.00")


def test_retrospective_history_agrees_with_accumulated_savings():
    """The dashboard slider and the header figure must be two views of the exact
    same scored pass, not two separately-computed numbers that happen to match.
    """
    profile = SyntheticAlexProvider().get_profile("alex")
    accumulated = analytics.accumulated_savings(profile)
    history = analytics.retrospective_history(profile)

    total = sum(
        (Decimal(t["guaranteed_delta"]) for t in history["transactions"]), Decimal(0)
    )
    assert total == accumulated["guaranteed"]
    assert len(history["months"]) == 12
    assert history["months"] == sorted(history["months"])


def test_mastercard_transactions_surface_what_actually_applied():
    """A transaction already on its best card must not read as "nothing
    happened here" just because no card switch is needed -- if it was paid on
    a Mastercard and a real benefit, offer or issuer rewards program fired,
    the annotated history must say so."""
    profile = SyntheticAlexProvider().get_profile("alex")
    history = analytics.retrospective_history(profile)

    card_txns = [t for t in history["transactions"] if t["kind"] == "card"]
    lit = [
        t for t in card_txns
        if t["actual_is_mastercard"]
        and (t["actual_benefits"] or t["actual_offers"] or t["actual_reward_programs"])
    ]
    assert lit, "expected at least one real Mastercard benefit/offer to surface"
    # A card-linked offer or benefit must never attach to a purchase made on a
    # non-Mastercard card -- these mechanics are Mastercard-network only.
    for t in card_txns:
        if not t["actual_is_mastercard"]:
            assert not t["actual_offers"], "an offer attached to a non-Mastercard transaction"


def test_habit_changes_never_claim_a_card_switch_that_did_not_happen():
    """A guaranteed gap can come from the booking channel alone (the same card,
    booked through its own issuer portal instead of direct). The label must say
    so honestly rather than claiming a card switch that never happened.
    """
    profile = SyntheticAlexProvider().get_profile("alex")
    history = analytics.retrospective_history(profile)
    assert history["habit_changes"], "expected at least one real habit change"
    for h in history["habit_changes"]:
        assert Decimal(h["guaranteed"]) > Decimal("0")
        assert h["count"] > 0
        assert "instead" in h["label"]

    # Sorted by guaranteed value, most impactful first.
    values = [Decimal(h["guaranteed"]) for h in history["habit_changes"]]
    assert values == sorted(values, reverse=True)


def test_habit_change_channel_only_switch_is_labelled_as_a_channel_change():
    """A specific, known instance in the frozen dataset: two Marriott stays booked
    merchant-direct that would have earned a portal bonus on the exact same card.
    """
    profile = SyntheticAlexProvider().get_profile("alex")
    history = analytics.retrospective_history(profile)
    channel_only = [
        h for h in history["habit_changes"]
        if h["label"].startswith("Keep ") and "booking via" in h["label"]
    ]
    assert channel_only, "expected a same-card, channel-only habit change"


def test_late_fee_is_annotated_as_its_own_avoidable_amount_never_added_to_guaranteed():
    """A late fee is not a "which card" decision (accumulated_savings excludes it
    for the same reason), so its avoidable value must show up as its own line --
    never silently inflate the card-driven guaranteed total.
    """
    profile = SyntheticAlexProvider().get_profile("alex")
    accumulated = analytics.accumulated_savings(profile)
    history = analytics.retrospective_history(profile)

    assert history["fee_avoidable"], "expected the planted late fee in the fixture"
    fee = history["fee_avoidable"][0]
    assert fee["amount"] == "40.00"
    assert "autopay" in fee["label"]
    assert "40.00" in fee["label"]

    fee_txns = [t for t in history["transactions"] if t["kind"] == "fee"]
    assert len(fee_txns) == 1
    assert fee_txns[0]["guaranteed_delta"] == "0.00", (
        "a fee's avoidable value must never count toward the card-driven guaranteed total"
    )
    assert fee_txns[0]["avoidable_amount"] == "40.00"

    total = sum(
        (Decimal(t["guaranteed_delta"]) for t in history["transactions"]), Decimal(0)
    )
    assert total == accumulated["guaranteed"], (
        "adding the fee annotation must not change the card-driven guaranteed total"
    )


def test_savings_by_card_sums_to_the_same_guaranteed_total():
    """savings_by_card is the same reduction accumulated_savings performs, just
    not collapsed down to a single top_driver -- the two must never disagree.
    """
    profile = SyntheticAlexProvider().get_profile("alex")
    accumulated = analytics.accumulated_savings(profile)
    by_card = analytics.savings_by_card(profile)

    assert by_card, "expected at least one card to have won something historically"
    assert sum(by_card.values(), Decimal(0)) == accumulated["guaranteed"]
    assert all(v > Decimal("0") for v in by_card.values())


def test_savings_by_card_is_keyed_by_instrument_id_not_display_name():
    profile = SyntheticAlexProvider().get_profile("alex")
    by_card = analytics.savings_by_card(profile)
    known_ids = {i.instrument_id for i in profile.instruments if i.is_card}
    assert set(by_card) <= known_ids
