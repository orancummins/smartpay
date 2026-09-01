"""SmartPay reading Alex's profile from BankSym over Open Finance.

The point of PLAN.MD section 8's provider abstraction is that swapping the data
source changes nothing downstream. These tests are the evidence: identical
recommendations and identical money, from a live HTTP API instead of a fixture.

Skipped when BankSym is not running, so the suite stays green offline.
"""

import pytest

from app.engines.optimizer import ItineraryOptimizer
from app.providers.open_finance import SyntheticAlexProvider, default_provider
from app.scenarios import load_scenario
from app.services.smartpay import SmartPayService

banksym = pytest.importorskip("app.providers.banksym")


@pytest.fixture(scope="module")
def live():
    """The BankSym-backed provider, or skip if BankSym is not seeded and running."""
    provider = banksym.BankSymProvider()
    try:
        provider.get_profile("alex")
    except Exception as exc:  # noqa: BLE001 - any failure means "not available"
        pytest.skip(f"BankSym unavailable: {exc}")
    return provider


@pytest.fixture(scope="module")
def fixture_profile():
    return SyntheticAlexProvider().get_profile("alex")


def test_same_accounts_and_transaction_counts(live, fixture_profile):
    profile = live.get_profile("alex")
    assert len(profile.accounts) == len(fixture_profile.accounts)
    assert len(profile.transactions) == len(fixture_profile.transactions)
    assert len(profile.spend_transactions) == len(fixture_profile.spend_transactions)


def test_transaction_types_are_reconstructed_from_raw_postings(live, fixture_profile):
    """Open Finance returns money movements, not meaning.

    Nothing in the payload says "this is a card repayment, do not count it as
    spend". If SmartPay's classifier gets that wrong, every spend total inflates.
    """
    from app.models.financial import TransactionType

    profile = live.get_profile("alex")

    def counts(p):
        out = {}
        for t in p.transactions:
            out[t.transaction_type] = out.get(t.transaction_type, 0) + 1
        return out

    assert counts(profile) == counts(fixture_profile)

    payments = [t for t in profile.transactions
                if t.transaction_type is TransactionType.CARD_PAYMENT]
    assert payments
    assert all(not t.is_consumer_spend for t in payments)


def test_spend_totals_match_to_the_cent(live, fixture_profile):
    profile = live.get_profile("alex")

    def by_category(p):
        out = {}
        for t in p.spend_transactions:
            out[t.category] = out.get(t.category, 0) + t.amount
        return out

    assert by_category(profile) == by_category(fixture_profile)


def test_all_five_cards_are_matched_to_their_products(live):
    profile = live.get_profile("alex")
    cards = {i.instrument_id for i in profile.instruments if i.is_card}
    assert cards == {
        "citi_strata_premier", "citi_double_cash", "citi_aa_platinum_select",
        "chase_sapphire_preferred", "chase_freedom_unlimited",
    }


def test_both_institutions_are_aggregated(live):
    """Alex banks with two institutions; Open Finance has to reassemble one picture."""
    profile = live.get_profile("alex")
    assert {a.institution for a in profile.accounts} == {"citi", "chase"}


def test_identical_recommendations_from_a_live_api(live, fixture_profile):
    """The headline claim: same engines, same answer, different source."""
    itinerary = load_scenario("disney_october_2026")
    from_fixture = ItineraryOptimizer(fixture_profile).optimise(itinerary, "alex")
    from_banksym = ItineraryOptimizer(live.get_profile("alex")).optimise(itinerary, "alex")

    assert from_banksym.incremental_guaranteed == from_fixture.incremental_guaranteed
    assert from_banksym.incremental_estimated == from_fixture.incremental_estimated
    assert from_banksym.incremental_points == from_fixture.incremental_points

    for got, want in zip(from_banksym.recommendations, from_fixture.recommendations):
        assert got.recommended.instrument_id == want.recommended.instrument_id
        assert got.recommended.channel is want.recommended.channel
        assert got.baseline.instrument_id == want.baseline.instrument_id
        assert got.incremental_guaranteed == want.incremental_guaranteed


def test_service_honours_the_configured_provider(live, monkeypatch):
    monkeypatch.setenv("SMARTPAY_PROVIDER", "banksym")
    service = SmartPayService(provider=live)
    assert service.optimise_itinerary()["data"]["incremental_guaranteed"] == "553.00"


def test_default_provider_selects_by_name():
    assert isinstance(default_provider("synthetic"), SyntheticAlexProvider)
    assert isinstance(default_provider("banksym"), banksym.BankSymProvider)
    with pytest.raises(ValueError):
        default_provider("nonsense")


def test_classifier_rules():
    """The classification boundary, unit-tested without needing BankSym."""
    from decimal import Decimal

    from app.models.financial import TransactionType

    classify = banksym.classify
    assert classify("AUTOPAY ACCT_CITI_STRATA", "card_payment", Decimal("500")) is (
        TransactionType.CARD_PAYMENT
    )
    assert classify("ATM WITHDRAWAL", "chase_atm", Decimal("100")) is (
        TransactionType.ATM_WITHDRAWAL
    )
    assert classify("NORTHWIND HEALTH PAYROLL", "northwind_health", Decimal("-4180")) is (
        TransactionType.INCOME
    )
    assert classify("PUBLIX", "publix", Decimal("85.20")) is TransactionType.PURCHASE
