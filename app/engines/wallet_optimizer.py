"""Wallet optimisation. PLAN.MD section 23.

    Net annual incremental value
      = incremental reward value
      + credits likely to be used
      + fees avoided
      - incremental annual fee

Two things PLAN.MD section 23 leaves out and this implementation fixes:

1. The formula only subtracts the INCREMENTAL annual fee, but the fees Alex
   already pays belong in the current wallet's value too. Otherwise dropping a
   $95 card looks free rather than profitable.

2. "Credits likely to be used" must be grounded in observed behaviour. We only
   count the Lyft credit because Alex demonstrably takes three rides most months.
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.rewards import RewardsEngine, available_channels
from app.engines.rewards_programs import RewardsProgramsEngine
from app.knowledge import benefits as all_benefits, card_products
from app.models.common import (
    Category,
    Confidence,
    Evidence,
    EvidenceType,
    NetworkTier,
    PurchaseChannel,
)
from app.models.financial import FinancialProfile, PaymentInstrument
from app.models.planning import (
    FutureSpendForecast,
    PurchaseIntent,
    WalletCandidate,
    WalletRecommendation,
)
from app.money import ZERO, quantize

#: Categories that never touch a card, so they must not inflate any wallet's value.
NON_CARD_CATEGORIES = {Category.HOUSING, Category.UTILITIES}


class WalletOptimizer:
    def __init__(self, profile: FinancialProfile) -> None:
        self.profile = profile
        self.rewards = RewardsEngine()
        self.reward_programs = RewardsProgramsEngine()

    def _reward_value(
        self, wallet: list[PaymentInstrument], forecast: FutureSpendForecast
    ) -> Decimal:
        """Best achievable annual reward value from this wallet.

        Assumes SmartPay's own advice is followed -- each category goes on the best
        card in the wallet, through the best channel that card can use.
        """
        total = ZERO
        for category, spend in forecast.by_category.items():
            if category in NON_CARD_CATEGORIES or spend <= ZERO:
                continue
            best = ZERO
            for instrument in wallet:
                purchase = PurchaseIntent(
                    merchant=category.value, category=category, amount=spend
                )
                # A sourced issuer rewards program (see app.engines.rewards_programs)
                # is additive on top of the card's own published earn, issuer-matched
                # and channel independent -- omitting it here made a card's real
                # total rate look weaker than it is, which is what silently
                # recommended dropping a card with a genuine, sourced bonus this
                # engine just never counted.
                bonus = sum(
                    (p.estimated_value for p in self.reward_programs.evaluate(purchase, instrument)),
                    ZERO,
                )
                for channel in available_channels(category, instrument):
                    evaluation = self.rewards.evaluate(purchase, instrument, channel)
                    best = max(best, evaluation.estimated_value + bonus)
            total += best
        return quantize(total)

    def _credits(
        self, wallet: list[PaymentInstrument], forecast: FutureSpendForecast
    ) -> tuple[Decimal, list[str]]:
        """Credits this wallet would plausibly actually realise."""
        from app.engines.benefits import BenefitsEngine

        engine = BenefitsEngine()
        product_ids = {i.instrument_id for i in wallet}
        tiers = {i.product.network_tier for i in wallet if i.product}

        total = ZERO
        notes: list[str] = []
        claimed: set[str] = set()

        for instrument in wallet:
            for evaluation in engine.evaluate_monthly_behaviour(self.profile, instrument):
                if evaluation.benefit_id in claimed:
                    continue
                claimed.add(evaluation.benefit_id)
                annual = quantize(evaluation.value * 12)
                total += annual
                notes.append(f"{evaluation.display_name}: ${annual}/yr (observed behaviour)")

        for rule in all_benefits():
            if rule.benefit_id in claimed or rule.min_transactions_per_month:
                continue
            if rule.monthly_cap is None:
                continue
            eligible = (
                (rule.eligible_products and product_ids & set(rule.eligible_products))
                or (rule.network_tiers and tiers & set(rule.network_tiers))
            )
            if not eligible:
                continue
            # Only count a subscription credit if Alex actually subscribes.
            if rule.merchants and not any(
                t.merchant in rule.merchants for t in self.profile.spend_transactions
            ):
                continue
            claimed.add(rule.benefit_id)
            annual = quantize(rule.value * 12)
            total += annual
            notes.append(f"{rule.display_name}: ${annual}/yr")

        hotel_spend = forecast.by_category.get(Category.HOTEL, ZERO)
        for rule in all_benefits():
            if rule.monthly_cap is not None or not rule.required_channels:
                continue
            if not (rule.eligible_products and product_ids & set(rule.eligible_products)):
                continue
            if hotel_spend >= max(rule.min_transaction_amount, Decimal("500")):
                total += rule.value
                notes.append(f"{rule.display_name}: ${rule.value}/yr")
                break  # one hotel credit is realistically used per year

        return quantize(total), notes

    def _annual_fees(self, wallet: list[PaymentInstrument]) -> Decimal:
        return quantize(sum((i.product.annual_fee for i in wallet if i.product), ZERO))

    def _value_of(
        self, wallet: list[PaymentInstrument], forecast: FutureSpendForecast
    ) -> tuple[Decimal, Decimal, Decimal, list[str]]:
        rewards = self._reward_value(wallet, forecast)
        credits, notes = self._credits(wallet, forecast)
        fees = self._annual_fees(wallet)
        return quantize(rewards + credits - fees), rewards, credits, notes

    def _trip_value(self, wallet: list[PaymentInstrument], itinerary) -> Decimal:
        """Guaranteed value this wallet delivers on a known upcoming trip.

        Re-optimising the trip for each candidate wallet is what makes the
        comparison honest. Attributing a benefit to one card in isolation would
        overstate its worth whenever another card in the wallet covers the same
        benefit -- both World Elite Mastercards carry the Lyft airport discount, so
        dropping one loses nothing there. Only the genuinely unique value, such as
        the AAdvantage checked-bag waiver, shows up as a difference.
        """
        if itinerary is None:
            return ZERO
        from app.engines.optimizer import ItineraryOptimizer

        restricted = self.profile.model_copy(update={"instruments": list(wallet)})
        plan = ItineraryOptimizer(restricted).optimise(itinerary, self.profile.customer_id)
        return plan.smartpay_value.guaranteed_value

    def optimise(self, forecast: FutureSpendForecast, itinerary=None) -> WalletRecommendation:
        wallet = [i for i in self.profile.instruments if i.is_card]
        current_net, current_rewards, current_credits, credit_notes = self._value_of(
            wallet, forecast
        )
        current_trip = self._trip_value(wallet, itinerary)
        current_net = quantize(current_net + current_trip)

        candidates: list[WalletCandidate] = []
        best_drop: tuple[Decimal, PaymentInstrument] | None = None

        for instrument in wallet:
            trimmed = [i for i in wallet if i.instrument_id != instrument.instrument_id]
            net, rewards, credits, _ = self._value_of(trimmed, forecast)
            net = quantize(net + self._trip_value(trimmed, itinerary))
            delta = quantize(net - current_net)
            candidates.append(
                WalletCandidate(
                    product_id=instrument.instrument_id,
                    display_name=f"Drop {instrument.display_name}",
                    annual_fee=instrument.product.annual_fee if instrument.product else ZERO,
                    projected_reward_value=rewards,
                    credits_likely_used=credits,
                    net_annual_value=net,
                )
            )
            if delta > ZERO and (best_drop is None or delta > best_drop[0]):
                best_drop = (delta, instrument)

        candidates.sort(key=lambda c: (-c.net_annual_value, c.display_name))

        if current_trip > ZERO:
            credit_notes.append(
                f"${current_trip:,.0f} of guaranteed value on the upcoming trip"
            )

        top_categories = [
            f"${float(v):,.0f} predicted {c.value}"
            for c, v in list(forecast.by_category.items())
            if c not in NON_CARD_CATEGORIES
        ][:4]

        evidence = [
            Evidence(
                evidence_type=EvidenceType.CALCULATION,
                source_name="SmartPay deterministic calculation",
                confidence=Confidence.AUTHORITATIVE,
                note=(
                    "Wallet values computed by applying each card's published earn "
                    "rules to the forecast category mix, net of annual fees."
                ),
            ),
            *forecast.evidence,
        ]

        if best_drop is None:
            return WalletRecommendation(
                customer_id=self.profile.customer_id,
                action="keep",
                headline="Alex's current wallet is already well matched to predicted spend.",
                current_wallet_value=current_net,
                recommended_wallet_value=current_net,
                net_annual_incremental_value=ZERO,
                candidates=candidates,
                drivers=top_categories + credit_notes,
                evidence=evidence,
            )

        delta, drop = best_drop
        product = drop.product
        fee = product.annual_fee if product else ZERO
        return WalletRecommendation(
            customer_id=self.profile.customer_id,
            action="drop",
            headline=(
                f"Drop {drop.display_name}. Its ${fee:,.0f} annual fee is no longer "
                f"earning its keep against Alex's predicted spend."
            ),
            current_wallet_value=current_net,
            recommended_wallet_value=quantize(current_net + delta),
            net_annual_incremental_value=delta,
            candidates=candidates,
            drivers=top_categories + credit_notes,
            evidence=evidence,
        )
