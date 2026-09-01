"""Network and issuer benefits. PLAN.MD section 19.

Benefits are not transaction multipliers. Some are channel-gated credits, some are
percentage discounts, some are fee waivers priced per unit, and some cannot be
judged from a single transaction at all -- the Mastercard Lyft credit needs three
rides in a calendar month, which only the transaction history can answer.
"""

from __future__ import annotations

import collections
from datetime import date
from decimal import Decimal

from app.knowledge import benefits as all_benefits
from app.models.common import NetworkTier, PurchaseChannel
from app.models.financial import FinancialProfile, PaymentInstrument
from app.models.planning import BenefitEvaluation, PurchaseIntent
from app.models.rules import BenefitRule, BenefitType
from app.money import ZERO, quantize


class BenefitsEngine:
    def evaluate_purchase(
        self,
        purchase: PurchaseIntent,
        instrument: PaymentInstrument,
        channel: PurchaseChannel | None = None,
        merchant_key: str | None = None,
        on: date | None = None,
    ) -> list[BenefitEvaluation]:
        product = instrument.product
        if product is None:
            return []

        channel = channel or purchase.purchase_channel
        merchant_key = merchant_key or purchase.merchant
        on = on or purchase.purchase_date or date.today()
        out: list[BenefitEvaluation] = []

        for rule in all_benefits():
            if not self._applies(rule, product.product_id, product.network_tier, on):
                continue
            if not rule.channel_qualifies(channel):
                continue
            if rule.min_transaction_amount and purchase.amount < rule.min_transaction_amount:
                continue
            matches = (
                (rule.merchants and merchant_key in rule.merchants)
                or (rule.categories and purchase.category in rule.categories)
            )
            if not matches:
                continue
            # Behavioural benefits are handled by evaluate_monthly_behaviour, which
            # can see the history this single purchase cannot.
            if rule.min_transactions_per_month:
                continue

            value = self._value_for(rule, purchase)
            if value <= ZERO and not rule.unpriced:
                continue

            out.append(
                BenefitEvaluation(
                    benefit_id=rule.benefit_id,
                    display_name=rule.display_name,
                    value=value,
                    unpriced=rule.unpriced,
                    explanation=self._explain(rule, purchase, value),
                    evidence=[rule.evidence],
                )
            )
        return out

    def evaluate_monthly_behaviour(
        self,
        profile: FinancialProfile,
        instrument: PaymentInstrument,
        on: date | None = None,
    ) -> list[BenefitEvaluation]:
        """Benefits that depend on how the consumer behaves over a month.

        Uses observed history to decide whether Alex actually qualifies, rather
        than assuming the benefit always pays out.
        """
        product = instrument.product
        if product is None:
            return []
        on = on or date.today()

        by_merchant_month: dict[str, collections.Counter] = collections.defaultdict(
            collections.Counter
        )
        for txn in profile.spend_transactions:
            by_merchant_month[txn.merchant][txn.posted_at.strftime("%Y-%m")] += 1

        out: list[BenefitEvaluation] = []
        for rule in all_benefits():
            if not rule.min_transactions_per_month:
                continue
            if not self._applies(rule, product.product_id, product.network_tier, on):
                continue

            months = collections.Counter()
            for merchant in rule.merchants:
                months.update(by_merchant_month.get(merchant, {}))
            qualifying = [m for m, n in months.items() if n >= rule.min_transactions_per_month]
            if not qualifying:
                continue

            share = Decimal(len(qualifying)) / Decimal(max(len(months), 1))
            out.append(
                BenefitEvaluation(
                    benefit_id=rule.benefit_id,
                    display_name=rule.display_name,
                    value=rule.value,
                    explanation=(
                        f"{rule.description}. Alex met the threshold in "
                        f"{len(qualifying)} of {len(months)} observed months "
                        f"({share:.0%}), so this credit is expected to apply."
                    ),
                    evidence=[rule.evidence],
                )
            )
        return out

    @staticmethod
    def _applies(rule: BenefitRule, product_id: str, tier: NetworkTier, on: date) -> bool:
        if not rule.is_active(on):
            return False
        if not rule.product_qualifies(product_id):
            return False
        # Network benefits scope by tier; issuer credits scope by product and carry
        # no tier list, so an empty tier list must not be read as "any card".
        if rule.network_tiers and not rule.tier_qualifies(tier):
            return False
        if not rule.network_tiers and not rule.eligible_products:
            return False
        return True

    @staticmethod
    def _value_for(rule: BenefitRule, purchase: PurchaseIntent) -> Decimal:
        if rule.benefit_type is BenefitType.DISCOUNT_PCT:
            value = quantize(purchase.amount * rule.value / Decimal("100"))
            if rule.max_discount:
                value = min(value, rule.max_discount)
            return value

        if rule.benefit_type is BenefitType.FEE_WAIVER and rule.unit_source:
            units = BenefitsEngine._units(rule.unit_source, purchase)
            return quantize(Decimal(units) * rule.value_per_unit)

        return rule.value

    @staticmethod
    def _units(unit_source: str, purchase: PurchaseIntent) -> int:
        """Derive benefit units from itinerary metadata.

        The free checked bag covers the cardholder plus up to four companions, so
        at most five bags per direction no matter how large the party is.
        """
        if unit_source != "free_checked_bags":
            return 0
        meta = purchase.metadata or {}
        travellers = int(meta.get("travellers", 1) or 1)
        bags = int(meta.get("checked_bags", travellers) or travellers)
        segments = int(meta.get("segments", 2) or 2)
        covered = min(bags, travellers, 5)
        return max(covered, 0) * max(segments, 0)

    @staticmethod
    def _explain(rule: BenefitRule, purchase: PurchaseIntent, value: Decimal) -> str:
        if rule.benefit_type is BenefitType.FEE_WAIVER and rule.unit_source:
            units = BenefitsEngine._units(rule.unit_source, purchase)
            return (
                f"{rule.display_name}: {units} checked bags waived at "
                f"${rule.value_per_unit} each."
            )
        if rule.benefit_type is BenefitType.DISCOUNT_PCT:
            return f"{rule.display_name}: {rule.value}% off this purchase."
        return rule.description or rule.display_name
