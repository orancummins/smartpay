"""Ledger integrity. PLAN.MD section 7 and Phase 2 acceptance criteria.

These are the tests that stop the demo quoting a savings figure built on
double-counted money.
"""

import collections
from datetime import date
from decimal import Decimal

from app.models.financial import TransactionType
from app.providers.open_finance import SyntheticAlexProvider

PROFILE = SyntheticAlexProvider().get_profile("alex")
TXNS = PROFILE.transactions


def test_no_duplicate_transaction_ids():
    ids = [t.transaction_id for t in TXNS]
    assert len(ids) == len(set(ids))


def test_card_payment_is_not_consumer_spend():
    """The single most important integrity rule.

    Paying off a card moves money that was ALREADY counted when the purchase posted.
    Counting it twice would inflate every spend total the demo reports.
    """
    payments = [t for t in TXNS if t.transaction_type is TransactionType.CARD_PAYMENT]
    assert payments, "expected card payments in the ledger"
    for p in payments:
        assert not p.is_consumer_spend
    assert not any(p in PROFILE.spend_transactions for p in payments)


def test_every_card_payment_reconciles_to_a_real_card_account():
    card_accounts = {a.account_id for a in PROFILE.accounts if a.account_type.value == "credit_card"}
    checking = {a.account_id for a in PROFILE.accounts if a.account_type.value == "checking"}
    for p in (t for t in TXNS if t.transaction_type is TransactionType.CARD_PAYMENT):
        assert p.counterparty_account_id in card_accounts, "payment to an unknown card"
        assert p.account_id in checking, "card payment must leave a checking account"


def test_card_payments_match_the_balance_they_settle():
    """Each month's card purchases must equal the payment that settles them."""
    purchases: dict[tuple[str, str], Decimal] = collections.defaultdict(Decimal)
    for t in TXNS:
        if t.transaction_type is TransactionType.PURCHASE:
            purchases[(t.account_id, t.posted_at.strftime("%Y-%m"))] += t.amount

    for p in (t for t in TXNS if t.transaction_type is TransactionType.CARD_PAYMENT):
        # Settles the month before the payment posts.
        y, m = p.posted_at.year, p.posted_at.month
        prev = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
        assert purchases[(p.counterparty_account_id, prev)] == p.amount, (
            f"payment {p.transaction_id} does not match the {prev} balance it settles"
        )


def test_atm_withdrawal_classification():
    """PLAN.MD section 7: cash out is visible, but never becomes merchant spend."""
    atms = [t for t in TXNS if t.transaction_type is TransactionType.ATM_WITHDRAWAL]
    assert atms
    for t in atms:
        assert not t.is_consumer_spend


def test_income_is_not_spend_and_is_negative():
    income = [t for t in TXNS if t.transaction_type is TransactionType.INCOME]
    assert income
    for t in income:
        assert t.amount < 0, "income must be an inflow"
        assert not t.is_consumer_spend


def test_all_dates_within_the_declared_period():
    for t in TXNS:
        assert date(2025, 9, 1) <= t.posted_at <= date(2026, 9, 30)


def test_monthly_volumes_are_plausible():
    per_month = collections.Counter(t.posted_at.strftime("%Y-%m") for t in PROFILE.spend_transactions)
    assert len(per_month) >= 12
    for month, n in per_month.items():
        assert 20 <= n <= 90, f"{month} has an implausible {n} consumer transactions"


def test_consumer_payment_event_count_in_target_range():
    """PLAN.MD section 5: ~550-600 consumer payment events."""
    assert 550 <= len(PROFILE.spend_transactions) <= 600


def test_planted_signals_exist_for_every_inference_the_demo_makes():
    """If SmartPay claims Alex plays golf, there must be golf in the ledger.

    Each assertion here backs a specific claim made on stage.
    """
    merchants = collections.Counter(t.merchant for t in PROFILE.spend_transactions)
    assert merchants["instacart"] >= 10, "Instacart benefit needs a subscription history"
    assert merchants["peacock"] >= 10, "Peacock credit needs a subscription history"

    golf = [t for t in PROFILE.spend_transactions if t.category.value == "golf"]
    assert len(golf) >= 10, "the Priceless golf suggestion must be inferable, not asserted"

    lyft_by_month = collections.Counter(
        t.posted_at.strftime("%Y-%m")
        for t in PROFILE.spend_transactions
        if t.merchant == "lyft"
    )
    qualifying = [m for m, n in lyft_by_month.items() if n >= 3]
    assert len(qualifying) >= 9, (
        "the Mastercard 'take 3 rides, get $5' benefit must qualify in most months"
    )


def test_baseline_categories_have_enough_support():
    """Categories the demo narrates must not rest on one or two transactions."""
    counts = collections.Counter(t.category.value for t in PROFILE.spend_transactions)
    for category in ("restaurant", "supermarket", "gas", "rideshare", "airfare", "hotel"):
        assert counts[category] >= 5, f"{category} has only {counts[category]} samples"
