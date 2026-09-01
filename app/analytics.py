"""Retrospective and cumulative money figures for the dashboard header.

Two numbers, two different sources, deliberately kept apart:

* **Accumulated savings** looks backward. It re-evaluates every one of Alex's real
  past transactions against every card in the wallet and sums the guaranteed value
  gap between the card actually used and the best one available -- literally "the
  payments Mastercard has already seen, run through what SmartPay would have
  suggested." It is a pure function of the frozen dataset, so it is cached and
  never changes across a session.

* **Potential future savings** looks forward: the wallet's recurring annual
  switch-value, plus a running ledger of every distinct itinerary or purchase
  question SmartPay has been asked. Unlike the capped "recent activity" list, this
  ledger never evicts an entry, so the total only grows.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path

from app import config
from app.engines.optimizer import PurchaseOptimizer
from app.models.financial import FinancialProfile, TransactionType
from app.models.planning import PurchaseIntent
from app.money import ZERO, quantize

#: Never pruned, unlike history.HISTORY_PATH's capped recent-activity list. This is
#: the one number in the header that must only ever grow.
LEDGER_PATH = config.ROOT / ".runtime" / "identified_ledger.json"


#: Manual cache keyed by customer_id rather than @lru_cache on the function: a
#: FinancialProfile holds list fields and is not hashable, and passing it as any
#: lru_cache argument -- even alongside a hashable key -- fails the same way, since
#: every argument is hashed to build the cache key.
_CACHE: dict[str, dict] = {}


def accumulated_savings(profile: FinancialProfile) -> dict:
    """Guaranteed value SmartPay's rules find across Alex's real 12-month ledger.

    For every past spend transaction: score it on the card that was actually used,
    score it on the best card available, and take the guaranteed difference. Offers
    are deliberately excluded -- they carry itinerary-level redemption caps (one
    $75 credit across a whole trip) that do not map onto scoring arbitrary daily
    transactions in isolation, and folding them in without that reconciliation
    would overstate the total.
    """
    if profile.customer_id in _CACHE:
        return _CACHE[profile.customer_id]

    optimizer = PurchaseOptimizer(profile)
    instruments = {i.account_id: i for i in profile.instruments if i.is_card}

    guaranteed = ZERO
    estimated = ZERO
    by_card: dict[str, Decimal] = {}

    # Fees are excluded from the comparison: a late payment fee is assessed on
    # whatever card was already in use, not a decision a different card choice
    # could have changed, and real issuers do not pay rewards on fee assessments.
    purchases = [
        t for t in profile.spend_transactions if t.transaction_type is TransactionType.PURCHASE
    ]

    for txn in purchases:
        actual_instrument = instruments.get(txn.account_id)
        if actual_instrument is None:
            continue  # paid from checking; no card comparison is possible

        purchase = PurchaseIntent(
            merchant=txn.merchant, category=txn.category, amount=txn.amount,
            purchase_date=txn.posted_at, purchase_channel=txn.channel,
        )
        actual = optimizer.build_option(
            purchase, actual_instrument, txn.channel, txn.merchant, on=txn.posted_at
        )
        best = optimizer.options_for(purchase, txn.merchant, on=txn.posted_at)[0]

        delta = best.value.guaranteed_value - actual.value.guaranteed_value
        if delta > ZERO:
            guaranteed += delta
            by_card[best.instrument_name] = by_card.get(best.instrument_name, ZERO) + delta
        estimated += best.value.estimated_reward_value - actual.value.estimated_reward_value

    result = {
        "guaranteed": quantize(guaranteed),
        "estimated": quantize(estimated),
        "top_driver": max(by_card.items(), key=lambda kv: kv[1])[0] if by_card else None,
        "transaction_count": len(purchases),
    }
    _CACHE[profile.customer_id] = result
    return result


def _load_ledger() -> dict[str, dict]:
    try:
        data = json.loads(LEDGER_PATH.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_identified(key: str, title: str, guaranteed: Decimal, estimated: Decimal) -> None:
    """Add or update one distinct enquiry's contribution to the running total.

    Keyed the same way as the recent-activity history, so re-asking the same trip
    updates its entry rather than double-counting it -- but this ledger is never
    pruned, so a total built up over many questions survives the recent list
    capping older entries for display.
    """
    ledger = _load_ledger()
    ledger[key] = {"title": title, "guaranteed": str(guaranteed), "estimated": str(estimated)}
    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=LEDGER_PATH.parent, delete=False, encoding="utf-8"
        ) as handle:
            json.dump(ledger, handle, indent=2)
            temp = Path(handle.name)
        os.replace(temp, LEDGER_PATH)
    except OSError:
        pass  # a demo must not fall over because it could not persist its ledger


def potential_future_savings(wallet_annual_value: Decimal) -> dict:
    """The forward-looking total: the wallet's recurring opportunity, plus every
    distinct question SmartPay has been asked, added once each."""
    ledger = _load_ledger()
    enquiries_guaranteed = sum((Decimal(e["guaranteed"]) for e in ledger.values()), ZERO)
    enquiries_estimated = sum((Decimal(e["estimated"]) for e in ledger.values()), ZERO)
    return {
        "wallet_annual": quantize(wallet_annual_value),
        "enquiries_guaranteed": quantize(enquiries_guaranteed),
        "enquiries_estimated": quantize(enquiries_estimated),
        "enquiry_count": len(ledger),
        "total": quantize(wallet_annual_value + enquiries_guaranteed + enquiries_estimated),
    }


def clear_ledger() -> None:
    with contextlib.suppress(OSError):
        LEDGER_PATH.unlink()
