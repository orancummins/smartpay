"""Clipped coupons: a Mastercard tiebreak discount turned into a real,
time-boxed offer -- not just a note buried in a recommendation table.

The trigger is narrow and specific: SmartPay only ever proposes a percentage
discount "to flip to Mastercard from a competitor brand" in exactly one place
-- app.engines.optimizer's network tiebreak, which funds a real statement
credit when a Mastercard option is recommended over a non-Mastercard rival
that scored exactly the same. Every coupon here traces back to one of those
recommendations: a real, identified merchant, the purchase's own amount, and
a short redemption window from the day SmartPay proposed it.

Shared with the dashboard the way app/history.py is: a small JSON file under
.runtime/, since the MCP server and the dashboard are separate processes.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from app import config

#: Runtime state, not project data -- gitignored, and safe to delete.
COUPONS_PATH = config.ROOT / ".runtime" / "coupons.json"

#: "A few days" -- explicit so the window can be challenged, the same way every
#: other policy constant in this codebase is (PAYOFF_UTILISATION_THRESHOLD,
#: TIEBREAK_BONUS_RATE, and so on).
VALID_FOR_DAYS = 3


def _load() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(COUPONS_PATH.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(coupons: dict[str, dict[str, Any]]) -> None:
    try:
        COUPONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=COUPONS_PATH.parent, delete=False, encoding="utf-8"
        ) as handle:
            json.dump(coupons, handle, indent=2)
            temp = Path(handle.name)
        os.replace(temp, COUPONS_PATH)
    except OSError:
        pass  # a demo must not fall over because it could not persist a coupon


def record_from_recommendation(
    coupon_id: str,
    merchant: str,
    item_label: str,
    approx_amount: Decimal,
    card_name: str,
    discount_percent: Decimal,
    issued_on: date,
) -> None:
    """Turn one Mastercard-tiebreak recommendation into a clipped coupon.

    Keyed on coupon_id (the same recommendation_id the rest of the app already
    uses) so re-asking the same question refreshes the coupon -- a new expiry,
    the same identity -- rather than piling up duplicates. Clip state survives
    a refresh either way, since that is the one thing a real user chose.
    """
    coupons = _load()
    existing = coupons.get(coupon_id, {})
    coupons[coupon_id] = {
        "coupon_id": coupon_id,
        "merchant": merchant,
        "item_label": item_label,
        "approx_amount": str(approx_amount),
        "card": card_name,
        "discount_percent": str(discount_percent),
        "issued_on": issued_on.isoformat(),
        "expires_on": (issued_on + timedelta(days=VALID_FOR_DAYS)).isoformat(),
        "clipped": existing.get("clipped", False),
    }
    _save(coupons)


def load_active(today: date) -> list[dict[str, Any]]:
    """Unexpired coupons, most recently issued first."""
    coupons = [
        c for c in _load().values()
        if date.fromisoformat(c["expires_on"]) >= today
    ]
    return sorted(coupons, key=lambda c: c["issued_on"], reverse=True)


def set_clipped(coupon_id: str, clipped: bool) -> bool:
    """Returns False if the coupon does not exist (e.g. it already expired and
    was pruned), so the caller can tell the difference from a real toggle."""
    coupons = _load()
    if coupon_id not in coupons:
        return False
    coupons[coupon_id]["clipped"] = clipped
    _save(coupons)
    return True


def clear() -> None:
    with contextlib.suppress(OSError):
        COUPONS_PATH.unlink()
