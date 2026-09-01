"""Reward earn. PLAN.MD section 17.

Two rules govern this engine:

1. A rule that requires a channel NEVER fires for another channel. This is the
   section 15 requirement, and getting it wrong would silently hand a 10x portal
   rate to a direct booking -- the most damaging error available to us.

2. Reward earn is reported as ESTIMATED value, never guaranteed, because it
   depends on a points valuation we chose. Only credits, discounts and waived fees
   -- money the consumer verifiably does not pay -- count as guaranteed.
"""

from __future__ import annotations

from decimal import Decimal

from app import config
from app.models.common import Category, PurchaseChannel, RewardCurrency
from app.models.financial import CardProduct, PaymentInstrument, RewardRule
from app.models.planning import PurchaseIntent, RewardEvaluation
from app.money import ZERO, points_to_usd, quantize


def _valuation(currency: RewardCurrency) -> Decimal:
    return config.REWARD_VALUATIONS.get(currency.value, Decimal("0.01"))


def _rule_value(amount: Decimal, multiplier: Decimal, currency: RewardCurrency) -> tuple[int, Decimal]:
    """Return (points earned, estimated USD value).

    Cashback multipliers are percentages (2 == 2%); points multipliers are points
    per dollar (10 == 10x). Conflating the two would be a factor-of-100 error.
    """
    if currency is RewardCurrency.USD_CASHBACK:
        return 0, quantize(amount * multiplier / Decimal("100"))
    points = int(amount * multiplier)
    return points, points_to_usd(points, _valuation(currency))


class RewardsEngine:
    def evaluate(
        self,
        purchase: PurchaseIntent,
        instrument: PaymentInstrument,
        channel: PurchaseChannel | None = None,
        merchant_key: str | None = None,
    ) -> RewardEvaluation:
        channel = channel or purchase.purchase_channel
        merchant_key = merchant_key or purchase.merchant

        product = instrument.product
        if product is None:
            # Debit and bank rails earn nothing. Stated explicitly rather than
            # left as an implicit zero.
            return RewardEvaluation(
                multiplier=ZERO,
                explanation="Debit and bank transfers earn no card rewards.",
            )

        best: RewardRule | None = None
        blocked: list[str] = []

        for rule in product.reward_rules:
            if not self._in_window(rule, purchase):
                continue
            category_or_merchant_hit = (
                (rule.merchants and merchant_key in rule.merchants)
                or (rule.categories and purchase.category in rule.categories)
            )
            if not category_or_merchant_hit:
                continue
            if not rule.channel_qualifies(channel):
                # Matched on what was bought, rejected on how it was booked. Worth
                # surfacing: it is exactly the "book it through the portal" advice.
                blocked.append(rule.rule_id)
                continue
            if best is None or rule.multiplier > best.multiplier:
                best = rule

        if best is None:
            points, value = _rule_value(
                purchase.amount, product.base_multiplier, product.base_currency
            )
            return RewardEvaluation(
                multiplier=product.base_multiplier,
                points=points,
                currency=product.base_currency,
                estimated_value=value,
                channel_blocked_rule_ids=blocked,
                evidence=[product.evidence],
                explanation=self._describe(product, product.base_multiplier,
                                           product.base_currency, "base rate"),
            )

        points, value = _rule_value(purchase.amount, best.multiplier, best.reward_currency)
        return RewardEvaluation(
            multiplier=best.multiplier,
            points=points,
            currency=best.reward_currency,
            estimated_value=value,
            rule_id=best.rule_id,
            channel_blocked_rule_ids=blocked,
            evidence=[best.evidence],
            explanation=self._describe(product, best.multiplier, best.reward_currency,
                                       best.description or best.rule_id),
        )

    @staticmethod
    def _in_window(rule: RewardRule, purchase: PurchaseIntent) -> bool:
        on = purchase.purchase_date
        if on is None:
            return True
        if rule.valid_from and on < rule.valid_from:
            return False
        if rule.valid_to and on > rule.valid_to:
            return False
        return True

    @staticmethod
    def _describe(
        product: CardProduct, multiplier: Decimal, currency: RewardCurrency, label: str
    ) -> str:
        unit = "%" if currency is RewardCurrency.USD_CASHBACK else "x"
        rate = multiplier.normalize()
        return f"{product.display_name}: {rate}{unit} — {label}"


def available_channels(category: Category, instrument: PaymentInstrument) -> list[PurchaseChannel]:
    """Channels this instrument could realistically use for this category.

    A card can only earn through its OWN issuer's travel portal, and only travel
    categories are portal-bookable at all. This is what stops the optimiser
    proposing "book your restaurant meal through Citi Travel".
    """
    from app.models.common import PORTAL_BOOKABLE, PORTAL_BY_ISSUER

    channels = [PurchaseChannel.MERCHANT_DIRECT]
    if category in PORTAL_BOOKABLE and instrument.is_card:
        portal = PORTAL_BY_ISSUER.get(instrument.issuer)
        if portal:
            channels.append(portal)
    return channels
