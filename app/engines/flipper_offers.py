"""Flipper campaigns: a large, general Mastercard-funded cash back incentive
tied to reaching a spend threshold on one specific card.

Unlike app.engines.offers (a card-linked offer that fires on one matching
transaction) this never scores an individual purchase -- it counts every
purchase on the campaign's own card across a rolling window, so the answer
is always "how close is this consumer to the threshold right now," computed
fresh from real transaction history rather than tied to any one recommendation.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.knowledge import flipper_offers as all_flipper_offers
from app.models.financial import FinancialProfile
from app.models.rules import FlipperOffer
from app.money import fmt, quantize


def _progress(profile: FinancialProfile, offer: FlipperOffer, on: date) -> dict | None:
    instrument = next(
        (i for i in profile.instruments if i.instrument_id == offer.card_product_id), None
    )
    if instrument is None:
        return None  # Alex does not hold the card this campaign targets

    cutoff = on - timedelta(days=offer.window_days)
    txns = [
        t for t in profile.spend_transactions
        if t.account_id == instrument.account_id and cutoff <= t.posted_at <= on
    ]
    count = len(txns)
    spend = quantize(sum((t.amount for t in txns), Decimal(0)))
    complete = count >= offer.required_transaction_count and spend >= offer.required_spend_amount

    if complete:
        why = (
            f"Already qualifies: {count} purchases totalling {fmt(spend)} on "
            f"{instrument.display_name} in the last {offer.window_days} days, "
            f"past the {offer.required_transaction_count}-purchase, "
            f"{fmt(offer.required_spend_amount)} threshold."
        )
    else:
        remaining_count = max(offer.required_transaction_count - count, 0)
        remaining_spend = max(offer.required_spend_amount - spend, Decimal(0))
        why = (
            f"{count} of {offer.required_transaction_count} purchases and "
            f"{fmt(spend)} of {fmt(offer.required_spend_amount)} spent on "
            f"{instrument.display_name} in the last {offer.window_days} days -- "
            f"{remaining_count} more purchase{'s' if remaining_count != 1 else ''} "
            f"and {fmt(remaining_spend)} more spend to unlock."
        )

    return {
        "offer_id": offer.offer_id,
        "display_name": offer.display_name,
        "headline": offer.headline,
        "card": instrument.display_name,
        "card_product_id": offer.card_product_id,
        "cashback_value": str(offer.cashback_value),
        "required_transaction_count": offer.required_transaction_count,
        "required_spend_amount": str(offer.required_spend_amount),
        "window_days": offer.window_days,
        "progress_transaction_count": count,
        "progress_spend_amount": str(spend),
        "complete": complete,
        "why": why,
        "provenance_label": offer.provenance.label,
        "evidence_note": offer.evidence.note,
    }


def evaluate(profile: FinancialProfile, on: date | None = None) -> list[dict]:
    """Every Flipper campaign whose target card Alex actually holds, with his
    real progress toward it -- never hung off any one transaction.

    Defaults `on` to the frozen dataset's own last transaction date, not
    date.today(): the rolling window this counts against must stay stable no
    matter which real calendar day the demo runs on, or progress would quietly
    decay as the actual date slides past data that stops on 2026-08-31.
    """
    on = on or max((t.posted_at for t in profile.transactions), default=date.today())
    out: list[dict] = []
    for offer in all_flipper_offers():
        if not offer.is_active(on):
            continue
        progress = _progress(profile, offer, on)
        if progress is not None:
            out.append(progress)
    return out
