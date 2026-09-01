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
