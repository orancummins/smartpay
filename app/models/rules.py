"""Network benefits, card-linked offers and Priceless experiences.

Kept separate from issuer reward rules (PLAN.MD section 10): a Mastercard network
benefit is not the same kind of thing as a Citi earn rate, and collapsing them
would make the provenance story incoherent.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.common import (
    Category,
    Confidence,
    Evidence,
    NetworkTier,
    Provenance,
    PurchaseChannel,
)
from app.money import ZERO


class BenefitType(StrEnum):
    STATEMENT_CREDIT = "statement_credit"
    DISCOUNT_PCT = "discount_pct"
    FEE_WAIVER = "fee_waiver"
    INSURANCE = "insurance"
    ACCESS = "access"


class BenefitRule(BaseModel):
    """A Mastercard network benefit. PLAN.MD section 19.

    Some of these cannot be judged from a single transaction -- the Lyft credit
    needs three rides in a calendar month -- so qualification may consult history.
    """

    benefit_id: str
    display_name: str
    network_tiers: list[NetworkTier] = Field(default_factory=list)
    #: Issuer credits (e.g. the Citi Travel hotel benefit) are card-specific rather
    #: than network-wide, so they scope by product instead of by tier.
    eligible_products: list[str] = Field(default_factory=list)
    #: Credits that only apply when booked through a specific channel. Same section 15
    #: mechanic as reward rules: a portal credit must not apply to a direct booking.
    required_channels: list[PurchaseChannel] = Field(default_factory=list)
    #: Minimum single-transaction amount, e.g. the $500 hotel stay threshold.
    min_transaction_amount: Decimal = ZERO
    #: Benefits limited to domestic itineraries. The AAdvantage checked-bag waiver
    #: says "domestic American Airlines itineraries", so paying it out on a
    #: transatlantic trip would overstate the card by $360.
    domestic_only: bool = False
    merchants: list[str] = Field(default_factory=list)
    categories: list[Category] = Field(default_factory=list)
    benefit_type: BenefitType
    #: For STATEMENT_CREDIT: dollars. For DISCOUNT_PCT: percent, e.g. 10 == 10%.
    value: Decimal = ZERO
    #: Behavioural qualification, evaluated against transaction history.
    min_transactions_per_month: int = 0
    #: Cap on how much this benefit can pay out per month.
    monthly_cap: Decimal | None = None
    #: Per-item cap for percentage discounts.
    max_discount: Decimal | None = None
    #: For benefits priced per unit rather than per transaction -- the free checked
    #: bag is worth (bags x directions x fee), which only the itinerary metadata knows.
    value_per_unit: Decimal = ZERO
    unit_source: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    #: True when the benefit is a soft perk we name but refuse to price.
    unpriced: bool = False
    description: str = ""
    evidence: Evidence

    def is_active(self, on: date) -> bool:
        if self.valid_from and on < self.valid_from:
            return False
        if self.valid_to and on > self.valid_to:
            return False
        return True

    def tier_qualifies(self, tier: NetworkTier) -> bool:
        return not self.network_tiers or tier in self.network_tiers

    def product_qualifies(self, product_id: str) -> bool:
        return not self.eligible_products or product_id in self.eligible_products

    def channel_qualifies(self, channel: PurchaseChannel) -> bool:
        return not self.required_channels or channel in self.required_channels


class Offer(BaseModel):
    """A card-linked offer. PLAN.MD section 11.

    Demo offers are synthetic and must be labelled as such everywhere they surface.
    """

    offer_id: str
    merchant_name: str
    merchants: list[str] = Field(default_factory=list)
    categories: list[Category] = Field(default_factory=list)
    eligible_products: list[str] = Field(default_factory=list)
    minimum_spend: Decimal = ZERO
    benefit_type: BenefitType = BenefitType.STATEMENT_CREDIT
    value: Decimal = ZERO
    #: How many times this offer can pay out across the whole plan. One-time offers
    #: are the main double-counting hazard at itinerary level.
    max_redemptions: int = 1
    valid_from: date | None = None
    valid_to: date | None = None
    description: str = ""
    provenance: Provenance = Provenance()
    evidence: Evidence

    def is_active(self, on: date) -> bool:
        if self.valid_from and on < self.valid_from:
            return False
        if self.valid_to and on > self.valid_to:
            return False
        return True

    @property
    def is_synthetic(self) -> bool:
        return self.provenance.status is Confidence.SYNTHETIC_DEMO


class PricelessExperience(BaseModel):
    """PLAN.MD section 12. Never counted as hard savings -- experience value only."""

    experience_id: str
    title: str
    city: str
    #: Spend categories in the consumer's history that make this relevant. This is
    #: what turns "you like golf" from an assertion into an inference.
    affinity_categories: list[Category] = Field(default_factory=list)
    network_tiers: list[NetworkTier] = Field(default_factory=list)
    available_from: date | None = None
    available_to: date | None = None
    description: str = ""
    evidence: Evidence

    def is_available(self, on: date) -> bool:
        if self.available_from and on < self.available_from:
            return False
        if self.available_to and on > self.available_to:
            return False
        return True
