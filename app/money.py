"""Money handling. PLAN.MD section 27: Decimal only, never float.

Every monetary value in SmartPay flows through here. The engines are forbidden
from constructing Decimals from floats, because Decimal(0.1) is not 0.1 and a
judge who adds up our column by hand must get our total exactly.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def usd(value: str | int | Decimal) -> Decimal:
    """Build a USD amount, quantized to cents.

    Floats are rejected outright rather than silently coerced -- that is the whole
    point of the rule.
    """
    if isinstance(value, float):
        raise TypeError(
            f"Refusing to build money from float {value!r}. "
            "Pass a str, int or Decimal (PLAN.MD section 27)."
        )
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def quantize(value: Decimal) -> Decimal:
    """Round an already-computed Decimal to cents, half-up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def points_to_usd(points: int, cents_per_point: Decimal) -> Decimal:
    """Convert a reward-currency balance to USD at a configured valuation.

    `cents_per_point` is expressed in dollars per point (0.01 == 1 cent per point),
    matching config.REWARD_VALUATIONS.
    """
    return quantize(Decimal(points) * cents_per_point)


def fmt(value: Decimal) -> str:
    """Render money for display: $1,234.56, negatives as -$12.00."""
    q = quantize(value)
    sign = "-" if q < 0 else ""
    return f"{sign}${abs(q):,.2f}"


def fmt_points(points: int) -> str:
    return f"{points:,}"
