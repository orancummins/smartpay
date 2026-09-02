"""SmartPay reading Alex's profile from BankSym over FDX.

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


def test_seeded_accounts_and_transactions_all_arrive(live, fixture_profile):
    """Every seeded account and transaction must come back over FDX.

    Asserted as a superset, not an exact count: BankSym is a test bank and accounts
    can legitimately be added to Alex through its console. Extra empty accounts do
    not change any recommendation, so failing the suite over them would be noise --
    but a *missing* seeded account is a real defect, and that is what this catches.
    """
    profile = live.get_profile("alex")

    seeded = {a.mask for a in fixture_profile.accounts}
    live_masks = {a.mask for a in profile.accounts}
    assert seeded <= live_masks, f"seeded accounts missing over FDX: {seeded - live_masks}"

    # BankSym is a real double-entry-per-account ledger, so a card payment needs
    # two legs to net out correctly: the checking debit (present in the fixture
    # too) and a credit on the card account itself (which the fixture's ledger
    # model has no need for -- SmartPay excludes card payments from spend by type,
    # not by balancing them). BankSym therefore carries exactly one extra row per
    # card_payment in the fixture. Spend, the number that actually matters, must
    # still match exactly.
    from app.models.financial import TransactionType
    fixture_payments = sum(
        1 for t in fixture_profile.transactions
        if t.transaction_type is TransactionType.CARD_PAYMENT
    )
    assert len(profile.transactions) == len(fixture_profile.transactions) + fixture_payments
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

    fixture_counts = counts(fixture_profile)
    live_counts = counts(profile)
    # Every type matches exactly except CARD_PAYMENT, which is doubled by design:
    # BankSym needs a credit leg on the card account to net its balance, on top of
    # the checking debit the fixture already models. See
    # test_seeded_accounts_and_transactions_all_arrive for the full explanation.
    for txn_type, fixture_count in fixture_counts.items():
        if txn_type is TransactionType.CARD_PAYMENT:
            assert live_counts[txn_type] == fixture_count * 2
        else:
            assert live_counts[txn_type] == fixture_count, txn_type

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
    assert service.optimise_itinerary()["data"]["incremental_guaranteed"] == "542.90"


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
    assert classify("LATE PAYMENT FEE", "chase", Decimal("40.00")) is TransactionType.FEE
    assert classify("Returned Payment Fee", "citi", Decimal("40.00")) is TransactionType.FEE


# --- FDX wire format --------------------------------------------------------


def test_fdx_direction_is_decoded_from_debit_credit_memo():
    """The subtlest part of the FDX mapping, unit-tested without needing BankSym.

    FDX always reports a positive amount and says which way it went in
    debitCreditMemo. SmartPay signs money-out positive. Reading the amount alone
    would make every payroll deposit look like spending and invert the whole
    profile.
    """
    from decimal import Decimal

    to_txn = banksym.BankSymProvider._to_transaction

    spend = to_txn("acc_1", {
        "transactionId": "t1", "postedTimestamp": "2025-11-04T00:00:00Z",
        "description": "PUBLIX", "payee": "publix", "category": "supermarket",
        "debitCreditMemo": "DEBIT", "amount": 85.20,
    })
    assert spend.amount == Decimal("85.20"), "a debit is money out, positive to SmartPay"

    income = to_txn("acc_2", {
        "transactionId": "t2", "postedTimestamp": "2025-11-01T00:00:00Z",
        "description": "NORTHWIND HEALTH PAYROLL", "payee": "employer",
        "debitCreditMemo": "CREDIT", "amount": 4180.00,
    })
    assert income.amount == Decimal("-4180.00"), "a credit is money in, negative to SmartPay"
    assert not income.is_consumer_spend


def test_fdx_polymorphic_accounts_are_both_read(live):
    """FDX splits deposits and cards into different envelopes; both must arrive."""
    from app.models.financial import AccountType

    profile = live.get_profile("alex")
    types = {a.account_type for a in profile.accounts}
    assert AccountType.CHECKING in types, "depositAccount entries were dropped"
    assert AccountType.CREDIT_CARD in types, "locAccount entries were dropped"
    assert sum(1 for a in profile.accounts if a.account_type is AccountType.CREDIT_CARD) == 5


def test_card_liability_balances_are_read_as_positive_amounts_owed(live):
    """Amounts owed are never negative, but can be exactly zero.

    Citi/AAdvantage genuinely has no new purchases in Alex's final billing cycle,
    so a correctly netted ledger reports $0 owed on it -- that is the fix working,
    not a defect. The invariant to hold is "never negative", and separately that
    the cards Alex actually used still show a real balance.
    """
    from app.models.financial import AccountType

    profile = live.get_profile("alex")
    cards = [a for a in profile.accounts if a.account_type is AccountType.CREDIT_CARD]
    assert cards
    assert all(a.current_balance >= 0 for a in cards), "a card balance went negative"
    assert any(a.current_balance > 0 for a in cards), "no card shows any balance owed"


def test_card_payments_actually_reduce_the_card_balance(live, fixture_profile):
    """Regression test for a real bug: importing only the checking-side debit of a
    card_payment left every card accumulating a full year of purchases with no
    repayment ever applied, reporting balances several times the true amount owed
    (Chase Freedom Unlimited showed $24,772.75 -- its entire year of spend).

    The correct outstanding balance is independently computable from the fixture's
    own ledger: total purchases in the account's final billing cycle, since every
    earlier month is fully reconciled by the following month's payment.
    """
    from decimal import Decimal

    from app.models.financial import TransactionType

    from app.models.financial import AccountType

    card_account_ids = {
        a.account_id for a in fixture_profile.accounts
        if a.account_type is AccountType.CREDIT_CARD
    }

    fixture_totals: dict[str, Decimal] = {}
    fixture_paid: dict[str, Decimal] = {}
    for t in fixture_profile.transactions:
        # Utilities and subscriptions post PURCHASE rows straight to checking too,
        # so this must be scoped to card accounts specifically -- otherwise a
        # checking account's whole year of direct-debit purchases gets treated as
        # an "outstanding card balance" with no payment ever netting it. FEE is
        # included alongside PURCHASE: a late payment fee genuinely adds to what
        # is owed on the card it was assessed against.
        if (
            t.transaction_type in (TransactionType.PURCHASE, TransactionType.FEE)
            and t.account_id in card_account_ids
        ):
            fixture_totals[t.account_id] = fixture_totals.get(t.account_id, Decimal(0)) + t.amount
        if t.transaction_type is TransactionType.CARD_PAYMENT and t.counterparty_account_id:
            fixture_paid[t.counterparty_account_id] = (
                fixture_paid.get(t.counterparty_account_id, Decimal(0)) + t.amount
            )

    expected_outstanding = {
        acc: fixture_totals.get(acc, Decimal(0)) - fixture_paid.get(acc, Decimal(0))
        for acc in fixture_totals
    }

    profile = live.get_profile("alex")
    fixture_by_id = {a.account_id: a for a in fixture_profile.accounts}
    live_by_mask = {a.mask: a for a in profile.accounts}

    checked = 0
    for account_id, expected in expected_outstanding.items():
        mask = fixture_by_id[account_id].mask
        live_account = live_by_mask.get(mask)
        if live_account is None:
            continue
        assert live_account.current_balance == expected, (
            f"{live_account.display_name}: expected ${expected} outstanding, "
            f"got ${live_account.current_balance} -- a missing payment leg would "
            f"show something close to the full annual total instead"
        )
        checked += 1
    assert checked == 5, "expected to check all five cards"


def test_credit_limits_agree_between_fixture_and_banksym(live, fixture_profile):
    """Both are "retrieved or inferred through Open Banking": the fixture path
    assigns a limit per product (app.providers.open_finance.CREDIT_LIMITS) and the
    BankSym path reconstructs it from FDX's availableCredit + currentBalance. They
    must describe the same cardholder the same way regardless of source.
    """
    fixture_limits = {
        i.instrument_id: i.card.credit_limit
        for i in fixture_profile.instruments if i.is_card
    }
    live_limits = {
        i.instrument_id: i.card.credit_limit
        for i in live.get_profile("alex").instruments if i.is_card
    }
    assert fixture_limits.keys() == live_limits.keys()
    for instrument_id, expected in fixture_limits.items():
        assert live_limits[instrument_id] == expected, instrument_id


def test_late_fee_is_read_back_as_a_fee_not_an_ordinary_purchase(live, fixture_profile):
    """Regression test for a real gap: classify() had no case for FEE at all, so
    a late payment fee read back through FDX was silently relabelled PURCHASE. It
    would then earn rewards in the accumulated-savings comparison -- real issuers
    never pay rewards on a fee -- and be invisible to the risk engine's late-fee
    disclosure, which depends on finding it.
    """
    from app.models.financial import TransactionType

    fixture_fees = [
        t for t in fixture_profile.transactions if t.transaction_type is TransactionType.FEE
    ]
    assert fixture_fees, "the fixture must actually contain a fee to test this"

    profile = live.get_profile("alex")
    live_fees = [t for t in profile.transactions if t.transaction_type is TransactionType.FEE]
    assert len(live_fees) == len(fixture_fees)
    assert live_fees[0].amount == fixture_fees[0].amount
    assert live_fees[0].description.upper() == fixture_fees[0].description.upper()
