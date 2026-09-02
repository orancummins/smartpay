"""Purchase intents, itineraries, and everything the optimiser produces."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.common import (
    Category,
    Evidence,
    PurchaseChannel,
    RewardCurrency,
    ValueBreakdown,
)
from app.money import ZERO

#: Airports ChatGPT plausibly names for a non-US origin. Not exhaustive -- it does
#: not need to be, because `location` already gates the common case; this catches
#: the realistic failure where a model plans from the operator's own city.
NON_US_AIRPORTS: frozenset[str] = frozenset({
    "DUB", "ORK", "SNN", "BFS", "LHR", "LGW", "STN", "LTN", "MAN", "EDI", "GLA",
    "CDG", "ORY", "AMS", "FRA", "MUC", "BER", "ZRH", "GVA", "VIE", "BRU", "CPH",
    "ARN", "OSL", "HEL", "MAD", "BCN", "LIS", "OPO", "FCO", "MXP", "VCE", "ATH",
    "PRG", "WAW", "BUD", "IST", "KEF", "YYZ", "YVR", "YUL", "YYC", "MEX", "CUN",
    "GRU", "GIG", "EZE", "SCL", "BOG", "LIM", "NRT", "HND", "KIX", "ICN", "PVG",
    "PEK", "CAN", "HKG", "TPE", "SIN", "BKK", "KUL", "CGK", "DEL", "BOM", "SYD",
    "MEL", "BNE", "AKL", "CHC", "DXB", "AUH", "DOH", "TLV", "JNB", "CPT", "CAI",
    "NBO", "LOS",
})


class PurchaseIntent(BaseModel):
    """PLAN.MD section 14. What the consumer intends to buy."""

    merchant: str
    category: Category = Category.OTHER
    amount: Decimal
    currency: str = "USD"
    purchase_date: date | None = None
    location: str = "US"
    #: How the consumer currently plans to buy it. The optimiser may propose a
    #: different channel, which is where the portal upgrade comes from.
    purchase_channel: PurchaseChannel = PurchaseChannel.MERCHANT_DIRECT
    label: str | None = None
    metadata: dict = Field(default_factory=dict)

    @property
    def display_label(self) -> str:
        return self.label or self.merchant

    @property
    def is_domestic_us(self) -> bool:
        """Whether this is a US-domestic purchase.

        Deliberately conservative: any recognised non-US endpoint, or any location
        other than US, makes it international. Benefits scoped to domestic travel
        must not pay out just because we failed to recognise an airport code.
        """
        if (self.location or "US").upper() not in {"US", "USA", "UNITED STATES"}:
            return False
        meta = self.metadata or {}
        if meta.get("international") is True:
            return False
        endpoints = {
            str(meta.get(k, "")).strip().upper()
            for k in ("origin", "destination", "from", "to")
        }
        return not (endpoints & NON_US_AIRPORTS)


class ItineraryItem(PurchaseIntent):
    item_id: str


class Itinerary(BaseModel):
    itinerary_id: str
    title: str
    items: list[ItineraryItem]
    start_date: date | None = None
    end_date: date | None = None

    @property
    def total(self) -> Decimal:
        return sum((i.amount for i in self.items), ZERO)


class RewardEvaluation(BaseModel):
    """Result of RewardsEngine.evaluate for one instrument/channel pair."""

    multiplier: Decimal = Decimal("1")
    points: int = 0
    currency: RewardCurrency = RewardCurrency.USD_CASHBACK
    estimated_value: Decimal = ZERO
    rule_id: str | None = None
    #: Rules that matched the category but were rejected on channel. Surfacing these
    #: is what lets SmartPay say "book it through the portal instead".
    channel_blocked_rule_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    explanation: str = ""


class OfferEvaluation(BaseModel):
    offer_id: str
    merchant_name: str
    value: Decimal = ZERO
    is_synthetic: bool = True
    label: str = ""
    explanation: str = ""
    evidence: list[Evidence] = Field(default_factory=list)


class BenefitEvaluation(BaseModel):
    benefit_id: str
    display_name: str
    value: Decimal = ZERO
    unpriced: bool = False
    explanation: str = ""
    evidence: list[Evidence] = Field(default_factory=list)


class RewardProgramBonus(BaseModel):
    """An additive, issuer-matched bonus from a sourced issuer rewards program."""

    program_id: str
    issuer_name: str = ""
    display_name: str
    points: int = 0
    estimated_value: Decimal = ZERO
    label: str = ""
    explanation: str = ""
    evidence: list[Evidence] = Field(default_factory=list)


class PaymentOption(BaseModel):
    """One way to pay for one item: an instrument used through a channel."""

    instrument_id: str
    instrument_name: str
    channel: PurchaseChannel
    is_mastercard: bool = False
    value: ValueBreakdown = ValueBreakdown()
    reward: RewardEvaluation = RewardEvaluation()
    offers: list[OfferEvaluation] = Field(default_factory=list)
    benefits: list[BenefitEvaluation] = Field(default_factory=list)
    #: Additive bonuses from sourced issuer rewards programs, matched to this
    #: option's card by issuer. Their points/value are already folded into `value`.
    reward_programs: list[RewardProgramBonus] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    #: Set when this option only won because of the network tiebreak. Disclosed in
    #: the output rather than applied silently.
    tiebreak_note: str | None = None
    #: The simulated Mastercard-funded statement credit granted when a tie is
    #: broken in its favour -- already folded into `value.statement_credits`
    #: above, and repeated here so a caller can show "+$X for choosing
    #: Mastercard" without having to re-derive it from a rival's score.
    tiebreak_bonus: Decimal = ZERO
    #: Disclosed riders from app.engines.risk -- informational, never folded into
    #: `value` or `score`. Available credit is enforced as a hard filter before an
    #: option is ever built (see PurchaseOptimizer.options_for); these two are
    #: advisory and ride alongside whichever option is chosen.
    late_fee_warning: str | None = None
    payoff_recommendation: str | None = None

    @property
    def score(self) -> Decimal:
        """Ranking objective: guaranteed dollars plus estimated reward value.

        Explicit and configurable rather than an ad-hoc tie-break, so a judge can
        challenge the objective directly.
        """
        return self.value.total_value

    @property
    def channel_label(self) -> str:
        return {
            PurchaseChannel.CITI_TRAVEL: "via Citi Travel",
            PurchaseChannel.CHASE_TRAVEL: "via Chase Travel",
            PurchaseChannel.MERCHANT_DIRECT: "booked direct",
        }.get(self.channel, self.channel.value)


class PaymentRecommendation(BaseModel):
    """Baseline versus optimal for a single item. PLAN.MD section 21."""

    item_id: str
    item_label: str
    merchant: str
    category: Category
    amount: Decimal
    baseline: PaymentOption
    baseline_probability: Decimal = ZERO
    baseline_rationale: str = ""
    recommended: PaymentOption
    #: recommended.score - baseline.score, split by value type.
    incremental_guaranteed: Decimal = ZERO
    incremental_estimated: Decimal = ZERO
    incremental_points: int = 0
    rationale: str = ""
    evidence: list[Evidence] = Field(default_factory=list)


class PaymentPlan(BaseModel):
    """The full itinerary result. PLAN.MD section 34."""

    customer_id: str
    itinerary_id: str
    itinerary_title: str
    itinerary_total: Decimal
    recommendations: list[PaymentRecommendation]
    baseline_value: ValueBreakdown = ValueBreakdown()
    smartpay_value: ValueBreakdown = ValueBreakdown()
    incremental_guaranteed: Decimal = ZERO
    incremental_estimated: Decimal = ZERO
    incremental_points: int = 0
    priceless: list[dict] = Field(default_factory=list)
    disclaimers: list[str] = Field(default_factory=list)


class FutureSpendForecast(BaseModel):
    """PLAN.MD section 22. Clearly labelled as a demo adapter."""

    customer_id: str
    horizon_months: int
    by_category: dict[Category, Decimal]
    method: str = "Demo CommerceGPT adapter"
    drivers: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum(self.by_category.values(), ZERO)


class WalletCandidate(BaseModel):
    product_id: str
    display_name: str
    annual_fee: Decimal
    projected_reward_value: Decimal
    credits_likely_used: Decimal = ZERO
    net_annual_value: Decimal = ZERO


class WalletRecommendation(BaseModel):
    """PLAN.MD section 23."""

    customer_id: str
    action: str                       # "drop" | "add" | "keep" | "shift_spend"
    headline: str
    current_wallet_value: Decimal = ZERO
    recommended_wallet_value: Decimal = ZERO
    net_annual_incremental_value: Decimal = ZERO
    candidates: list[WalletCandidate] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    disclaimers: list[str] = Field(default_factory=list)
