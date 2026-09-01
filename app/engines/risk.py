"""Affordability and payment-risk factors.

Two different kinds of "other factor" the optimiser must account for, kept
deliberately separate because they behave differently:

* **Available credit is a hard constraint.** A card cannot be charged more than
  its available credit -- that is not a preference to weigh, it is what actually
  happens at checkout. ``affordable_instruments`` removes a candidate from
  consideration entirely rather than scoring it down.

* **Late-fee history and payoff timing are disclosed riders on the winning
  recommendation, never a silent score adjustment.** The user's own framing was
  "ensuring we pick a certain card but should flag that we should pay it off" --
  the pick stands; a warning and an actionable payoff suggestion ride alongside
  it. Folding these into the dollar score would blur the guaranteed-vs-estimated
  distinction this whole engine is built to keep clean.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.financial import (
    Account,
    FinancialProfile,
    PaymentInstrument,
    TransactionType,
)
from app.money import ZERO, fmt, quantize

#: Utilisation above which a payoff is worth flagging. A policy choice for this
#: demo, not an issuer rule -- stated explicitly so it can be challenged, the same
#: way the ranking objective in PaymentOption.score documents itself.
PAYOFF_UTILISATION_THRESHOLD = Decimal("0.5")


def account_for(instrument: PaymentInstrument, profile: FinancialProfile) -> Account | None:
    if not instrument.account_id:
        return None
    return next((a for a in profile.accounts if a.account_id == instrument.account_id), None)


def available_credit(instrument: PaymentInstrument, profile: FinancialProfile) -> Decimal | None:
    """The credit line left on this card, or None if it is not a card or the
    limit is unknown.

    None is deliberately not treated as "unlimited" by callers: it means the data
    was not available (retrieved or inferred through Open Banking), not that the
    check passed.
    """
    if not instrument.is_card or instrument.card is None:
        return None
    limit = instrument.card.credit_limit
    if limit is None:
        return None
    account = account_for(instrument, profile)
    owed = account.current_balance if account else ZERO
    return quantize(limit - owed)


def can_afford(instrument: PaymentInstrument, profile: FinancialProfile, amount: Decimal) -> bool:
    """Whether this instrument could actually be charged this amount.

    A missing credit limit does not fail the check -- it means we cannot verify
    the constraint, not that the constraint is violated, so an instrument with
    unknown available credit is treated as affordable rather than silently
    excluded from every recommendation.
    """
    if not instrument.is_card:
        return True
    remaining = available_credit(instrument, profile)
    if remaining is None:
        return True
    return amount <= remaining


def late_fee_history(instrument: PaymentInstrument, profile: FinancialProfile) -> list:
    """Fee transactions actually posted to this specific card's account.

    Scoped to the account, not the product: a late fee on one card says nothing
    about a different card from the same issuer.
    """
    if not instrument.account_id:
        return []
    return [
        t for t in profile.transactions
        if t.account_id == instrument.account_id and t.transaction_type is TransactionType.FEE
    ]


def _linked_checking(instrument: PaymentInstrument, profile: FinancialProfile) -> Account | None:
    """The checking account Alex would plausibly pay this card down from.

    Same institution: that is how autopay is actually wired in this dataset (see
    generate_alex.py's _card_payments), so it is the honest assumption here too.
    """
    if not instrument.issuer:
        return None
    return next(
        (
            a for a in profile.accounts
            if a.institution == instrument.issuer and a.account_type.value == "checking"
        ),
        None,
    )


def payoff_recommendation(
    instrument: PaymentInstrument, profile: FinancialProfile, purchase_amount: Decimal
) -> str | None:
    """A disclosed suggestion to pay the card down, when three things are true:
    the resulting balance is a large share of the credit line, a linked checking
    account exists, and it holds enough to cover the payoff.

    Never returned as a dollar figure added to the recommendation's value -- it is
    advice about cash-flow timing, not a saving. Whether Alex actually has that
    much sitting in checking is exactly the kind of fact Open Banking makes
    checkable instead of assumed.
    """
    if not instrument.is_card or instrument.card is None or instrument.card.credit_limit is None:
        return None
    account = account_for(instrument, profile)
    if account is None:
        return None

    resulting_balance = account.current_balance + purchase_amount
    utilisation = resulting_balance / instrument.card.credit_limit
    if utilisation < PAYOFF_UTILISATION_THRESHOLD:
        return None

    checking = _linked_checking(instrument, profile)
    if checking is None or checking.current_balance < resulting_balance:
        # The risk is real even without checking headroom, but recommending a
        # specific payoff Alex cannot actually make would be worse than saying
        # nothing -- silence here, not a false reassurance.
        return None

    return (
        f"After this purchase, {instrument.display_name} would sit at "
        f"{utilisation:.0%} of its credit limit. {checking.display_name} has enough "
        f"to pay it down -- consider paying {fmt(resulting_balance)} from there."
    )


def late_fee_warning(instrument: PaymentInstrument, profile: FinancialProfile) -> str | None:
    """A disclosed warning when the recommended card has a real fee on record.

    Quantifies the actual historical amount rather than a generic caution, so the
    claim is exactly as concrete as every other figure this engine reports.
    """
    fees = late_fee_history(instrument, profile)
    if not fees:
        return None
    most_recent = max(fees, key=lambda t: t.posted_at)
    return (
        f"{instrument.display_name} has a {fmt(most_recent.amount)} late payment "
        f"fee on record from {most_recent.posted_at.strftime('%B %Y')} -- consider "
        f"autopay to avoid another one."
    )
