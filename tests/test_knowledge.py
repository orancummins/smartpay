"""Rule-validator tests. PLAN.MD Phase 3 acceptance criteria."""

from datetime import date

import pytest

from app.knowledge import benefits, card_products, offers, priceless, rewards_programs
from app.models.common import Confidence, Network, PurchaseChannel


def test_every_rule_carries_evidence():
    """PLAN.MD section 25: no unattributed claims anywhere in the knowledge base."""
    for product in card_products().values():
        assert product.evidence.source_name
        for rule in product.reward_rules:
            assert rule.evidence.source_name, f"{rule.rule_id} has no source"
    for b in benefits():
        assert b.evidence.source_name, f"{b.benefit_id} has no source"
    for o in offers():
        assert o.evidence.source_name
    for p in priceless():
        assert p.evidence.source_name


def test_authoritative_rules_have_url_and_date():
    """Authoritative means we actually read a live page. Never assert it otherwise."""
    for product in card_products().values():
        for rule in product.reward_rules:
            if rule.evidence.confidence is Confidence.AUTHORITATIVE:
                assert rule.evidence.source_url, f"{rule.rule_id} claims authoritative with no URL"
                assert rule.evidence.verified_at, f"{rule.rule_id} claims authoritative with no date"


def test_offers_are_sourced_not_fabricated_or_authoritative():
    """Catalogue offers are real Mastercard card-linked records: never AUTHORITATIVE
    (not read off a live page with a verification date), never SYNTHETIC_DEMO (not
    fabricated), and labelled as card-linked offers."""
    for o in offers():
        assert o.evidence.confidence is Confidence.SOURCED_DATASET
        assert not o.is_synthetic
        assert o.provenance.label == "Mastercard card-linked offer"
    for p in priceless():
        assert p.evidence.confidence is not Confidence.AUTHORITATIVE


def test_wallet_has_both_networks():
    """Chase stays in the wallet as the baseline Alex actually uses."""
    networks = {p.network for p in card_products().values()}
    assert Network.MASTERCARD in networks
    assert Network.VISA in networks


def test_portal_rules_are_channel_gated():
    """PLAN.MD section 15: every 5x/10x portal rate must name its channel.

    Without this, a direct merchant booking would silently collect the portal bonus,
    which is the single most damaging error the engine could make.
    """
    for product in card_products().values():
        for rule in product.reward_rules:
            if rule.multiplier >= 5:
                assert rule.required_channels, (
                    f"{rule.rule_id} pays {rule.multiplier}x with no channel requirement"
                )


def test_a_card_cannot_use_a_rival_issuer_portal():
    expected = {"citi": PurchaseChannel.CITI_TRAVEL, "chase": PurchaseChannel.CHASE_TRAVEL}
    for product in card_products().values():
        for rule in product.reward_rules:
            for channel in rule.required_channels:
                assert channel == expected[product.issuer], (
                    f"{rule.rule_id} on a {product.issuer} card requires {channel}"
                )


def test_offer_date_window():
    offer = offers()[0]
    assert offer.is_active(date(2026, 10, 12))
    assert not offer.is_active(date(2026, 12, 25))


def test_reward_programs_are_sourced_and_targeted():
    """Sourced issuer rewards programs are real records (never AUTHORITATIVE, never
    SYNTHETIC_DEMO), labelled as issuer programs, and carry a targeted category so
    they can never silently restate a card's base rate."""
    programs = rewards_programs()
    assert programs
    for p in programs:
        assert p.evidence.confidence is Confidence.SOURCED_DATASET
        assert p.evidence.source_name
        assert p.provenance.label == "Mastercard issuer rewards program"
        assert p.categories
        assert p.rate > 0


def test_benefit_date_window_and_tier():
    from app.models.common import NetworkTier

    peacock = next(b for b in benefits() if b.benefit_id == "MC_WE_PEACOCK_3")
    assert peacock.is_active(date(2026, 10, 1))
    assert not peacock.is_active(date(2028, 1, 1))
    # Verified against mastercard.com: Peacock is World Elite, not World.
    assert peacock.tier_qualifies(NetworkTier.WORLD_ELITE)
    assert not peacock.tier_qualifies(NetworkTier.WORLD)


def test_sapphire_preferred_does_not_earn_3x_on_physical_supermarkets():
    """The distinction the whole wallet recommendation rests on.

    Chase's 3x grocery is online grocery only. If this ever silently becomes 3x on
    supermarkets, the wallet conclusion becomes wrong and must not be presented.
    """
    from app.models.common import Category

    csp = card_products()["chase_sapphire_preferred"]
    for rule in csp.reward_rules:
        if Category.SUPERMARKET in rule.categories:
            pytest.fail(f"{rule.rule_id} grants CSP a supermarket rate")


def test_every_card_discloses_a_late_payment_fee_with_authoritative_evidence():
    """Verified against a live issuer pricing/terms disclosure, same discipline as
    every reward rate in this file -- never a guessed or rounded figure."""
    for product in card_products().values():
        assert product.late_payment_fee > 0, f"{product.product_id} has no late fee"
        assert product.late_payment_fee_evidence is not None
        assert product.late_payment_fee_evidence.confidence is Confidence.AUTHORITATIVE
        assert product.late_payment_fee_evidence.source_url
        assert product.late_payment_fee_evidence.verified_at
