import pytest
from decimal import Decimal
from app.money import usd, quantize, points_to_usd, fmt


def test_decimal_money_rejects_float():
    """PLAN.MD section 27: no floats for money, enforced rather than documented."""
    with pytest.raises(TypeError):
        usd(19.99)


def test_decimal_money_is_exact():
    total = usd("0.10") + usd("0.20")
    assert total == usd("0.30")
    assert str(total) == "0.30"


def test_quantize_half_up():
    assert quantize(Decimal("1.005")) == Decimal("1.01")
    assert quantize(Decimal("2.344")) == Decimal("2.34")


def test_points_to_usd_at_one_cent():
    assert points_to_usd(18420, Decimal("0.01")) == Decimal("184.20")


def test_fmt():
    assert fmt(usd("1234.5")) == "$1,234.50"
    assert fmt(usd("-12")) == "-$12.00"
