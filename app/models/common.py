"""Shared enums and the Evidence model that every recommendation hangs off."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from app.money import ZERO, quantize


class Category(StrEnum):
    """Canonical spend taxonomy. ChatGPT free text is mapped onto this."""

    AIRFARE = "airfare"
    HOTEL = "hotel"
    ATTRACTION = "attraction"
    CAR_RENTAL = "car_rental"
    RESTAURANT = "restaurant"
    SUPERMARKET = "supermarket"
    GROCERY_ONLINE = "grocery_online"
    GAS = "gas"
    RIDESHARE = "rideshare"
    TRANSPORT = "transport"
    ENTERTAINMENT = "entertainment"
    STREAMING = "streaming"
    DRUGSTORE = "drugstore"
    SHOPPING = "shopping"
    UTILITIES = "utilities"
    HOUSING = "housing"
    GOLF = "golf"
    OTHER = "other"


#: Friendly words for the spend taxonomy, used when summarising a card's earn.
_CATEGORY_WORDS: dict[Category, str] = {
    Category.RESTAURANT: "dining",
    Category.SUPERMARKET: "groceries",
    Category.GROCERY_ONLINE: "groceries",
    Category.GAS: "gas",
    Category.RIDESHARE: "rideshare",
    Category.TRANSPORT: "transport",
    Category.ENTERTAINMENT: "entertainment",
    Category.STREAMING: "streaming",
    Category.DRUGSTORE: "drugstore",
    Category.SHOPPING: "shopping",
    Category.UTILITIES: "utilities",
    Category.GOLF: "golf",
    Category.OTHER: "everyday spend",
}
_TRAVEL_CATEGORIES = {
    Category.AIRFARE, Category.HOTEL, Category.ATTRACTION, Category.CAR_RENTAL,
}


def summarise_categories(categories: list[Category]) -> str:
    """A short human phrase for a set of spend categories, e.g. "travel", "dining".

    The four travel categories collapse to a single "travel" so a card's earn reads
    as a headline rather than a list of MCC-style buckets.
    """
    words: list[str] = []
    remaining = list(categories)
    if _TRAVEL_CATEGORIES & set(remaining):
        words.append("travel")
        remaining = [c for c in remaining if c not in _TRAVEL_CATEGORIES]
    for category in remaining:
        word = _CATEGORY_WORDS.get(category, category.value.replace("_", " "))
        if word not in words:
            words.append(word)
    return ", ".join(words)


class PurchaseChannel(StrEnum):
    """How a purchase is booked.

    PLAN.MD section 15: reward rules may depend on booking channel, and the engine
    must never award portal-specific rewards to a direct merchant purchase. The
    issuer portals are distinct values because a card can only earn the bonus
    through its *own* issuer's portal.
    """

    MERCHANT_DIRECT = "merchant_direct"
    CITI_TRAVEL = "citi_travel"
    CHASE_TRAVEL = "chase_travel"
    ONLINE = "online"
    IN_STORE = "in_store"


#: Categories that an issuer travel portal can actually book. Restaurants and
#: incidentals cannot be, so the optimiser must not offer a portal option for them.
PORTAL_BOOKABLE: frozenset[Category] = frozenset(
    {Category.HOTEL, Category.CAR_RENTAL, Category.ATTRACTION, Category.AIRFARE}
)

#: Which issuer owns which portal.
PORTAL_BY_ISSUER: dict[str, PurchaseChannel] = {
    "citi": PurchaseChannel.CITI_TRAVEL,
    "chase": PurchaseChannel.CHASE_TRAVEL,
}


class RewardCurrency(StrEnum):
    CITI_THANKYOU = "citi_thankyou"
    CHASE_ULTIMATE_REWARDS = "chase_ultimate_rewards"
    AA_MILES = "american_airlines_miles"
    USD_CASHBACK = "usd_cashback"
    #: Generic issuer loyalty points, used by sourced issuer rewards programs whose
    #: specific currency the catalogue does not name.
    LOYALTY_POINTS = "loyalty_points"


class Network(StrEnum):
    MASTERCARD = "mastercard"
    VISA = "visa"
    NONE = "none"


class NetworkTier(StrEnum):
    STANDARD = "standard"
    WORLD = "world"
    WORLD_ELITE = "world_elite"
    NONE = "none"


class Confidence(StrEnum):
    """Honesty about where a rule came from.

    AUTHORITATIVE is reserved for rules read off a live issuer page with a real
    source_url and verified_at. Everything else is DEMO_APPROXIMATION. We never
    fabricate a verification date.
    """

    AUTHORITATIVE = "authoritative"
    DEMO_APPROXIMATION = "demo_approximation"
    SYNTHETIC_DEMO = "synthetic_demo"
    #: A real record copied verbatim from a sourced dataset (the Mastercard Offers
    #: platform export). Not scraped live, so never AUTHORITATIVE, but not fabricated
    #: either -- the offer terms are genuine.
    SOURCED_DATASET = "sourced_dataset"


class EvidenceType(StrEnum):
    ISSUER_REWARD_RULE = "issuer_reward_rule"
    NETWORK_BENEFIT = "mastercard_network_benefit"
    SYNTHETIC_OFFER = "synthetic_demo_offer"
    MASTERCARD_OFFER = "mastercard_card_linked_offer"
    MASTERCARD_REWARD = "mastercard_issuer_reward_program"
    FLIPPER_CAMPAIGN = "flipper_campaign"
    PRICELESS = "priceless_experience"
    TRANSACTION_HISTORY = "open_finance_transaction_history"
    FORECAST = "commercegpt_prediction"
    CALCULATION = "smartpay_deterministic_calculation"


class Evidence(BaseModel):
    """PLAN.MD section 25. Every number SmartPay reports must trace back to one."""

    evidence_type: EvidenceType
    source_name: str
    source_url: str | None = None
    verified_at: date | None = None
    confidence: Confidence
    note: str | None = None

    def describe(self) -> str:
        bits = [self.source_name]
        if self.verified_at:
            bits.append(f"verified {self.verified_at.isoformat()}")
        if self.confidence is not Confidence.AUTHORITATIVE:
            bits.append(self.confidence.value.replace("_", " "))
        return f"{self.note or self.evidence_type.value} ({', '.join(bits)})"


class Provenance(BaseModel):
    """Attached to synthetic demo artefacts so they can never be mistaken for real."""

    status: Confidence = Confidence.SYNTHETIC_DEMO
    modelled_on: str | None = None
    label: str = "Simulated Mastercard card-linked offer"


class ValueBreakdown(BaseModel):
    """PLAN.MD section 16: keep value types separate, never collapse into one number.

    Guaranteed dollars, estimated reward value and unquantified benefits are
    reported side by side so we do not manufacture fake precision. Decimal
    throughout; pydantic serialises these to JSON strings, which is what we want
    crossing the MCP boundary -- a float would reintroduce the rounding error.
    """

    hard_savings: Decimal = ZERO
    statement_credits: Decimal = ZERO
    fees_avoided: Decimal = ZERO
    points_earned: int = 0
    points_currency: RewardCurrency | None = None
    estimated_reward_value: Decimal = ZERO
    soft_benefits: list[str] = Field(default_factory=list)

    @property
    def guaranteed_value(self) -> Decimal:
        """Dollars the consumer is certain to keep. Never includes point estimates."""
        return quantize(self.hard_savings + self.statement_credits + self.fees_avoided)

    @property
    def total_value(self) -> Decimal:
        """Guaranteed plus estimated. Always presented alongside the split, never alone."""
        return quantize(self.guaranteed_value + self.estimated_reward_value)
