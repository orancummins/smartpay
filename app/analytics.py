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
from app.money import ZERO, fmt, quantize

#: Never pruned, unlike history.HISTORY_PATH's capped recent-activity list. This is
#: the one number in the header that must only ever grow.
LEDGER_PATH = config.ROOT / ".runtime" / "identified_ledger.json"


#: Manual cache keyed by customer_id rather than @lru_cache on the function: a
#: FinancialProfile holds list fields and is not hashable, and passing it as any
#: lru_cache argument -- even alongside a hashable key -- fails the same way, since
#: every argument is hashed to build the cache key.
_CACHE: dict[str, dict] = {}

#: The scored pass behind both accumulated_savings and retrospective_history.
#: Cached separately from _CACHE (which holds the reduced summary) so the two
#: views are built from literally the same numbers and can never disagree.
_RECORDS_CACHE: dict[str, list[dict]] = {}


def _purchase_records(profile: FinancialProfile) -> list[dict]:
    """Score every real past purchase on the card actually used and on the best
    card available, once. Both accumulated_savings and retrospective_history
    reduce this same list rather than re-running the optimiser, which is what
    keeps the header figure and the "what could you have saved" panel honest
    about being two views of one computation, not two computations that happen
    to agree.

    Offers are deliberately excluded -- they carry itinerary-level redemption
    caps (one $75 credit across a whole trip) that do not map onto scoring
    arbitrary daily transactions in isolation, and folding them in without that
    reconciliation would overstate the total.
    """
    if profile.customer_id in _RECORDS_CACHE:
        return _RECORDS_CACHE[profile.customer_id]

    optimizer = PurchaseOptimizer(profile)
    instruments = {i.account_id: i for i in profile.instruments if i.is_card}

    # Fees are excluded from the comparison: a late payment fee is assessed on
    # whatever card was already in use, not a decision a different card choice
    # could have changed, and real issuers do not pay rewards on fee assessments.
    purchases = [
        t for t in profile.spend_transactions if t.transaction_type is TransactionType.PURCHASE
    ]

    records: list[dict] = []
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

        records.append({
            "date": txn.posted_at,
            "month": txn.posted_at.strftime("%Y-%m"),
            "merchant": txn.merchant,
            "description": txn.description,
            "category": txn.category.value,
            "amount": txn.amount,
            "actual_card": actual_instrument.display_name,
            "actual_is_mastercard": actual_instrument.is_mastercard,
            "best_card": best.instrument_name,
            "best_instrument_id": best.instrument_id,
            # A guaranteed gap can come from the channel alone -- the same card
            # booked through its own issuer portal instead of direct earns Alex a
            # bonus it never paid out on the historical merchant-direct purchase.
            # Recording both channels lets the habit-change summary say "book via
            # Citi Travel" rather than falsely claiming a card switch happened.
            "actual_channel": txn.channel.value,
            "best_channel": best.channel.value,
            "guaranteed_delta": best.value.guaranteed_value - actual.value.guaranteed_value,
            "estimated_delta": best.value.estimated_reward_value - actual.value.estimated_reward_value,
            # What actually fired on the card Alex actually used -- shown so a
            # transaction that was ALREADY on its best card doesn't read as
            # "nothing happened here" when a real Mastercard benefit or sourced
            # reward program did apply. Offers are included for display only:
            # excluded from every dollar total above per this function's own
            # redemption-cap rationale, but naming one that fired on a single
            # real transaction is not the aggregate-overstatement risk that is.
            "actual_benefits": [
                {"label": b.display_name, "value": str(b.value)}
                for b in actual.benefits if b.value > 0
            ],
            "actual_reward_programs": [
                {
                    "label": rp.label, "issuer": rp.issuer_name,
                    "program": rp.display_name, "points": rp.points,
                    "value": str(rp.estimated_value),
                }
                for rp in actual.reward_programs
            ],
            "actual_offers": [
                {"label": o.label, "merchant": o.merchant_name, "value": str(o.value)}
                for o in actual.offers
            ],
        })

    _RECORDS_CACHE[profile.customer_id] = records
    return records


def accumulated_savings(profile: FinancialProfile) -> dict:
    """Guaranteed value SmartPay's rules find across Alex's real 12-month ledger.

    For every past spend transaction: score it on the card that was actually used,
    score it on the best card available, and take the guaranteed difference.
    """
    if profile.customer_id in _CACHE:
        return _CACHE[profile.customer_id]

    guaranteed = ZERO
    estimated = ZERO
    by_card: dict[str, Decimal] = {}
    for r in _purchase_records(profile):
        if r["guaranteed_delta"] > ZERO:
            guaranteed += r["guaranteed_delta"]
            by_card[r["best_card"]] = by_card.get(r["best_card"], ZERO) + r["guaranteed_delta"]
        estimated += r["estimated_delta"]

    # transaction_count deliberately counts every purchase, including the ones
    # paid from checking that _purchase_records has no card comparison for --
    # this is "how many transactions were considered," not "how many scored".
    purchase_count = sum(
        1 for t in profile.spend_transactions if t.transaction_type is TransactionType.PURCHASE
    )

    result = {
        "guaranteed": quantize(guaranteed),
        "estimated": quantize(estimated),
        "top_driver": max(by_card.items(), key=lambda kv: kv[1])[0] if by_card else None,
        "transaction_count": purchase_count,
    }
    _CACHE[profile.customer_id] = result
    return result


def savings_by_card(profile: FinancialProfile) -> dict[str, Decimal]:
    """Guaranteed dollars attributable to each card being the best choice,
    across Alex's real 12-month ledger -- keyed by instrument_id rather than
    display name so a caller can join it straight back to a card product
    (and from there, to that product's real application page).

    This is the evidence behind "this card would have earned you $X based on
    your historic spend": the same reduction accumulated_savings performs,
    just not collapsed down to a single top_driver.
    """
    totals: dict[str, Decimal] = {}
    for r in _purchase_records(profile):
        if r["guaranteed_delta"] > ZERO:
            totals[r["best_instrument_id"]] = (
                totals.get(r["best_instrument_id"], ZERO) + r["guaranteed_delta"]
            )
    return {k: quantize(v) for k, v in totals.items()}


#: Human phrasing for a booking channel. Covers every PurchaseChannel value,
#: unlike PaymentOption.channel_label which only names the three that matter for
#: the itinerary table.
_CHANNEL_PHRASE = {
    "merchant_direct": "booking direct",
    "citi_travel": "booking via Citi Travel",
    "chase_travel": "booking via Chase Travel",
    "online": "buying online",
    "in_store": "buying in store",
}


def _habit_change_label(category: str, from_card: str, to_card: str, from_ch: str, to_ch: str) -> str:
    """Describe what actually has to change, honestly.

    A guaranteed gap can come from the channel alone -- the same card earns a
    portal bonus it never got on a merchant-direct purchase. Saying "switch to
    card X" when the card never needed to change would be a claim the ledger
    does not support.
    """
    if to_card != from_card:
        return f"Use {to_card} instead of {from_card}"
    phrase = _CHANNEL_PHRASE.get(to_ch, to_ch.replace("_", " "))
    return f"Keep {to_card}, but try {phrase} instead"


def _fee_records(profile: FinancialProfile) -> list[dict]:
    """Late-fee transactions, annotated for the "what could you have saved" panel.

    Kept separate from _purchase_records on purpose: a fee is not a "which card"
    decision (see accumulated_savings' own rationale for excluding it there), so
    its avoidable value is tracked as its own thing -- never folded into the
    card-driven guaranteed total the header figure reports, only ever shown
    alongside it.
    """
    instruments = {i.account_id: i for i in profile.instruments if i.is_card}
    records: list[dict] = []
    for t in profile.spend_transactions:
        if t.transaction_type is not TransactionType.FEE:
            continue
        instrument = instruments.get(t.account_id)
        records.append({
            "date": t.posted_at,
            "month": t.posted_at.strftime("%Y-%m"),
            "merchant": t.merchant,
            "description": t.description,
            "category": t.category.value,
            "amount": t.amount,
            "card_name": instrument.display_name if instrument else "this card",
        })
    return records


def retrospective_history(profile: FinancialProfile) -> dict:
    """Per-transaction and per-month detail behind accumulated_savings.

    Powers the dashboard's "what could you have saved" panel: a slider over
    trailing months, an annotated transaction list, and the specific habit
    changes (grouped by category, from-card/channel, to-card/channel) that
    would produce whatever total the slider lands on. Late fees are annotated
    the same way but kept in a separate `fee_avoidable` bucket -- see
    _fee_records for why they never add into the main guaranteed total.

    Every value here is JSON-safe (Decimals and dates as strings) since this is
    embedded directly into the rendered page for client-side slider math --
    there is no server round-trip as the user drags.
    """
    records = _purchase_records(profile)
    fees = _fee_records(profile)
    months = sorted({r["month"] for r in records} | {f["month"] for f in fees})

    transactions: list[dict] = []
    habit_totals: dict[tuple[str, str, str, str, str], dict] = {}
    for r in records:
        guaranteed_delta = r["guaranteed_delta"]
        estimated_delta = r["estimated_delta"]
        improved = guaranteed_delta > ZERO
        # habit_label is computed once here and carried on the transaction so the
        # dashboard's slider can regroup habit changes for an arbitrary trailing
        # window purely by grouping on this string -- the "same card, different
        # channel" honesty check in _habit_change_label lives in exactly one
        # place, not duplicated in client-side JS. It also doubles as the
        # per-row "what would change here" line in the annotated list.
        habit_label = (
            _habit_change_label(
                r["category"], r["actual_card"], r["best_card"],
                r["actual_channel"], r["best_channel"],
            )
            if improved else None
        )
        transactions.append({
            "kind": "card",
            "date": r["date"].isoformat(),
            "month": r["month"],
            "merchant": r["merchant"],
            "description": r["description"],
            "category": r["category"],
            "amount": str(quantize(r["amount"])),
            "actual_card": r["actual_card"],
            "actual_is_mastercard": r["actual_is_mastercard"],
            "best_card": r["best_card"],
            "guaranteed_delta": str(quantize(guaranteed_delta if improved else ZERO)),
            "estimated_delta": str(quantize(estimated_delta)),
            "improved": improved,
            "habit_label": habit_label,
            "actual_benefits": r["actual_benefits"],
            "actual_reward_programs": r["actual_reward_programs"],
            "actual_offers": r["actual_offers"],
        })
        if improved:
            key = (
                r["category"], r["actual_card"], r["best_card"],
                r["actual_channel"], r["best_channel"],
            )
            bucket = habit_totals.setdefault(
                key, {"count": 0, "guaranteed": ZERO, "estimated": ZERO}
            )
            bucket["count"] += 1
            bucket["guaranteed"] += guaranteed_delta
            bucket["estimated"] += estimated_delta

    habit_changes = sorted(
        (
            {
                "category": category,
                "label": _habit_change_label(category, from_card, to_card, from_ch, to_ch),
                "count": v["count"],
                "guaranteed": str(quantize(v["guaranteed"])),
                "estimated": str(quantize(v["estimated"])),
            }
            for (category, from_card, to_card, from_ch, to_ch), v in habit_totals.items()
        ),
        key=lambda h: -Decimal(h["guaranteed"]),
    )

    fee_avoidable: list[dict] = []
    for f in fees:
        habit_label = (
            f"Set up autopay on {f['card_name']} -- this {fmt(f['amount'])} late fee "
            f"would not have happened"
        )
        transactions.append({
            "kind": "fee",
            "date": f["date"].isoformat(),
            "month": f["month"],
            "merchant": f["merchant"],
            "description": f["description"],
            "category": f["category"],
            "amount": str(quantize(f["amount"])),
            "actual_card": f["card_name"],
            "best_card": None,
            # Deliberately zero here -- this must never add into the card-driven
            # guaranteed total the header figure reports. Its own avoidable value
            # travels separately, as avoidable_amount.
            "guaranteed_delta": "0.00",
            "estimated_delta": "0.00",
            "improved": False,
            "habit_label": habit_label,
            "avoidable_amount": str(quantize(f["amount"])),
        })
        fee_avoidable.append({
            "card_name": f["card_name"],
            "label": habit_label,
            "amount": str(quantize(f["amount"])),
            "month": f["month"],
        })

    return {
        "months": months,
        "transactions": transactions,
        "habit_changes": habit_changes,
        "fee_avoidable": fee_avoidable,
    }


def projected_history(profile: FinancialProfile) -> dict:
    """Mocked Mastercard CommerceGPT forward projection.

    Replays the last 12 months of real spend into the next 12 (same merchants and
    cadence), grown by the same modest category assumptions the demo CommerceGPT
    adapter uses, and scores the identical "what if you paid smarter" uplift
    retrospective_history finds looking back. A deterministic simulation, never a
    live prediction -- labelled as such everywhere it surfaces.
    """
    from datetime import timedelta

    from app.models.common import Category
    from app.providers.future_spend import DEFAULT_GROWTH, GROWTH

    records = _purchase_records(profile)
    shift = timedelta(days=364)  # ~1 year, preserving weekday/cadence alignment

    transactions: list[dict] = []
    total_guaranteed = ZERO
    total_estimated = ZERO
    projected_spend = ZERO
    for r in records:
        growth = GROWTH.get(Category(r["category"]), DEFAULT_GROWTH)
        future_date = r["date"] + shift
        amount = quantize(r["amount"] * growth)
        guaranteed = quantize(r["guaranteed_delta"] * growth) if r["guaranteed_delta"] > ZERO else ZERO
        estimated = quantize(r["estimated_delta"] * growth)
        improved = guaranteed > ZERO
        projected_spend += amount
        total_guaranteed += guaranteed
        total_estimated += estimated
        transactions.append({
            "kind": "projected",
            "date": future_date.isoformat(),
            "month": future_date.strftime("%Y-%m"),
            "merchant": r["merchant"],
            "description": r["description"],
            "category": r["category"],
            "amount": str(amount),
            "actual_card": r["actual_card"],
            "actual_is_mastercard": r["actual_is_mastercard"],
            "best_card": r["best_card"],
            "guaranteed_delta": str(guaranteed),
            "estimated_delta": str(estimated),
            "improved": improved,
            "habit_label": _habit_change_label(
                r["category"], r["actual_card"], r["best_card"],
                r["actual_channel"], r["best_channel"],
            ) if improved else None,
        })

    months = sorted({t["month"] for t in transactions})
    return {
        "months": months,
        "transactions": transactions,
        "total_guaranteed": str(quantize(total_guaranteed)),
        "total_estimated": str(quantize(total_estimated)),
        "projected_spend": str(quantize(projected_spend)),
    }


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
