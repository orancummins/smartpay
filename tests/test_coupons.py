"""Clipped coupons: a Mastercard tiebreak discount turned into a real,
time-boxed offer tied to an identified merchant, an approximate amount, and a
short redemption window.
"""

from datetime import date, timedelta
from decimal import Decimal

from app import coupons
from app.services.smartpay import SmartPayService


def test_record_and_load_active_round_trips():
    coupons.record_from_recommendation(
        coupon_id="trip:dining", merchant="local_bistro", item_label="Dinner",
        approx_amount=Decimal("120.00"), card_name="Citi Strata Premier Card",
        discount_percent=Decimal("5.00"), issued_on=date.today(),
    )
    active = coupons.load_active(date.today())
    assert len(active) == 1
    assert active[0]["coupon_id"] == "trip:dining"
    assert active[0]["merchant"] == "local_bistro"


def test_new_coupons_start_already_clipped():
    """SmartPay found the discount and is handing it over -- the consumer
    should not have to perform a "clip" action to receive something that is
    already theirs."""
    coupons.record_from_recommendation(
        coupon_id="trip:dining", merchant="local_bistro", item_label="Dinner",
        approx_amount=Decimal("120.00"), card_name="Citi Strata Premier Card",
        discount_percent=Decimal("5.00"), issued_on=date.today(),
    )
    assert coupons.load_active(date.today())[0]["clipped"] is True


def test_a_real_unclip_survives_reissuing_the_same_recommendation():
    coupons.record_from_recommendation(
        coupon_id="trip:dining", merchant="local_bistro", item_label="Dinner",
        approx_amount=Decimal("120.00"), card_name="Citi Strata Premier Card",
        discount_percent=Decimal("5.00"), issued_on=date.today(),
    )
    coupons.set_clipped("trip:dining", False)

    coupons.record_from_recommendation(
        coupon_id="trip:dining", merchant="local_bistro", item_label="Dinner",
        approx_amount=Decimal("120.00"), card_name="Citi Strata Premier Card",
        discount_percent=Decimal("5.00"), issued_on=date.today(),
    )
    assert coupons.load_active(date.today())[0]["clipped"] is False, (
        "re-asking the same question must not silently re-clip a coupon the user unclipped"
    )


def test_expired_coupons_are_excluded_from_load_active():
    issued = date.today() - timedelta(days=30)
    coupons.record_from_recommendation(
        coupon_id="old:coupon", merchant="marriott", item_label="Hotel",
        approx_amount=Decimal("500.00"), card_name="Citi Strata Premier Card",
        discount_percent=Decimal("5.00"), issued_on=issued,
    )
    assert coupons.load_active(date.today()) == []


def test_reissuing_the_same_recommendation_refreshes_expiry_not_clip_state():
    coupons.record_from_recommendation(
        coupon_id="trip:dining", merchant="local_bistro", item_label="Dinner",
        approx_amount=Decimal("120.00"), card_name="Citi Strata Premier Card",
        discount_percent=Decimal("5.00"), issued_on=date.today(),
    )
    coupons.set_clipped("trip:dining", True)

    coupons.record_from_recommendation(
        coupon_id="trip:dining", merchant="local_bistro", item_label="Dinner",
        approx_amount=Decimal("120.00"), card_name="Citi Strata Premier Card",
        discount_percent=Decimal("5.00"), issued_on=date.today(),
    )
    active = coupons.load_active(date.today())
    assert len(active) == 1
    assert active[0]["clipped"] is True, "re-asking the same question must not un-clip it"


def test_set_clipped_on_an_unknown_coupon_returns_false():
    assert coupons.set_clipped("does-not-exist", True) is False


def test_optimise_itinerary_creates_a_coupon_for_the_known_disney_tie():
    """The frozen Disney scenario has exactly one Mastercard tiebreak (dining).
    That, and only that, must produce a coupon.
    """
    service = SmartPayService()
    service.optimise_itinerary()

    active = coupons.load_active(date.today())
    assert len(active) == 1
    coupon = active[0]
    assert coupon["coupon_id"] == "disney_october_2026:dining"
    assert coupon["merchant"]
    assert coupon["approx_amount"] == "950.00"
    assert coupon["card"] == "Citi Strata Premier Card"
    assert coupon["discount_percent"] == "5.00"
    assert date.fromisoformat(coupon["expires_on"]) == date.today() + timedelta(
        days=coupons.VALID_FOR_DAYS
    )


def test_optimise_purchase_without_a_tie_creates_no_coupon():
    from decimal import Decimal as D

    from app.models.common import Category

    service = SmartPayService()
    service.optimise_purchase(
        purchase={"merchant": "cvs", "category": Category.DRUGSTORE.value, "amount": "400"}
    )
    assert coupons.load_active(date.today()) == []


def test_rendering_the_page_does_not_record_a_coupon():
    """Same principle as history and the ledger: rendering is not a question."""
    from app.dashboard import render_alex_dashboard
    from app.providers.open_finance import SyntheticAlexProvider

    render_alex_dashboard(SyntheticAlexProvider().get_profile("alex"))
    assert coupons.load_active(date.today()) == []


def test_dashboard_renders_an_active_coupon_as_a_clip_card():
    from app.dashboard import render_alex_dashboard
    from app.providers.open_finance import SyntheticAlexProvider

    coupons.record_from_recommendation(
        coupon_id="trip:dining", merchant="local_bistro", item_label="Dinner",
        approx_amount=Decimal("120.00"), card_name="Citi Strata Premier Card",
        discount_percent=Decimal("5.00"), issued_on=date.today(),
    )
    html = render_alex_dashboard(SyntheticAlexProvider().get_profile("alex"))
    assert "Mastercard offers for you" in html
    assert "Local Bistro" in html
    assert "5.00%" in html or "5%" in html
    assert 'data-coupon-id="trip:dining"' in html
    # Auto-clipped: the card renders already in its clipped state, not
    # waiting on the consumer to press a button for something already theirs.
    assert 'class="coupon clipped"' in html
    assert '<span>Clipped</span>' in html


def test_dashboard_omits_the_coupons_panel_when_there_are_none():
    from app.dashboard import render_alex_dashboard
    from app.providers.open_finance import SyntheticAlexProvider

    html = render_alex_dashboard(SyntheticAlexProvider().get_profile("alex"))
    assert "Mastercard offers for you" not in html


def test_clip_endpoint_persists_the_clip_state():
    from starlette.testclient import TestClient

    from app.dashboard_server import app

    coupons.record_from_recommendation(
        coupon_id="trip:dining", merchant="local_bistro", item_label="Dinner",
        approx_amount=Decimal("120.00"), card_name="Citi Strata Premier Card",
        discount_percent=Decimal("5.00"), issued_on=date.today(),
    )
    client = TestClient(app)
    response = client.post("/coupons/clip", json={"coupon_id": "trip:dining", "clipped": True})
    assert response.status_code == 200
    assert response.json() == {"coupon_id": "trip:dining", "clipped": True}
    assert coupons.load_active(date.today())[0]["clipped"] is True


def test_clip_endpoint_404s_on_an_unknown_coupon():
    from starlette.testclient import TestClient

    from app.dashboard_server import app

    client = TestClient(app)
    response = client.post("/coupons/clip", json={"coupon_id": "no-such-id", "clipped": True})
    assert response.status_code == 404
