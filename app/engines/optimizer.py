"""The optimiser. PLAN.MD section 16, with the section 34 totals.

TWO PASSES, deliberately.

PLAN.MD section 16 scores each purchase independently. That is wrong at itinerary
level and would inflate the headline number on stage. A $75 offer with a $750
minimum would pay out on every Disney line; a $5-per-month Lyft credit would pay
out on every ride. So:

  Pass 1  score every (instrument, channel) pair for every item, independently.
  Pass 2  reconcile plan-wide: each limited artefact -- one-time offers, monthly
          capped credits -- is granted on ONE item only, the one where it is worth
          most. Items that lose a claim are re-scored and re-ranked, and the loop
          repeats to a fixed point.

The baseline plan is reconciled the same way, so the comparison stays honest.
"""

from __future__ import annotations

import collections
from datetime import date
from decimal import Decimal

from app.engines.benefits import BenefitsEngine
from app.engines.categorizer import categorise
from app.engines.counterfactual import CounterfactualEngine
from app.engines.offers import OffersEngine
from app.engines.rewards import RewardsEngine, available_channels
from app.engines import risk
from app.knowledge import benefits as all_benefits
from app.models.common import Evidence, PurchaseChannel, ValueBreakdown
from app.models.financial import FinancialProfile, PaymentInstrument
from app.models.planning import (
    Itinerary,
    ItineraryItem,
    PaymentOption,
    PaymentPlan,
    PaymentRecommendation,
    PurchaseIntent,
)
from app.money import ZERO, quantize

MAX_RECONCILE_PASSES = 6


def _monthly_capped_benefit_ids() -> set[str]:
    return {b.benefit_id for b in all_benefits() if b.monthly_cap is not None}


class PurchaseOptimizer:
    def __init__(self, profile: FinancialProfile) -> None:
        self.profile = profile
        self.rewards = RewardsEngine()
        self.offers = OffersEngine()
        self.benefits = BenefitsEngine()
        self.counterfactual = CounterfactualEngine(profile)

    def build_option(
        self,
        purchase: PurchaseIntent,
        instrument: PaymentInstrument,
        channel: PurchaseChannel,
        merchant_key: str,
        blocked: frozenset[str] = frozenset(),
        on: date | None = None,
    ) -> PaymentOption:
        """Score one (instrument, channel) pair. `blocked` removes artefacts already
        claimed elsewhere in the plan."""
        reward = self.rewards.evaluate(purchase, instrument, channel, merchant_key)
        offers = [
            o for o in self.offers.evaluate(purchase, instrument, merchant_key, on)
            if o.offer_id not in blocked
        ]
        benefits = [
            b for b in self.benefits.evaluate_purchase(purchase, instrument, channel, merchant_key, on)
            if b.benefit_id not in blocked
        ]

        credits = sum((o.value for o in offers), ZERO)
        hard = ZERO
        fees = ZERO
        soft: list[str] = []
        for b in benefits:
            if b.unpriced:
                soft.append(b.display_name)
            elif b.benefit_id.endswith("CHECKED_BAG") or "fee" in b.display_name.lower():
                fees += b.value
            elif b.display_name.startswith("10%") or "% off" in b.explanation:
                hard += b.value
            else:
                credits += b.value

        product = instrument.product
        if product:
            soft.extend(product.soft_benefits)

        value = ValueBreakdown(
            hard_savings=quantize(hard),
            statement_credits=quantize(credits),
            fees_avoided=quantize(fees),
            points_earned=reward.points,
            points_currency=reward.currency,
            estimated_reward_value=reward.estimated_value,
            soft_benefits=soft,
        )

        evidence: list[Evidence] = list(reward.evidence)
        for o in offers:
            evidence.extend(o.evidence)
        for b in benefits:
            evidence.extend(b.evidence)

        return PaymentOption(
            instrument_id=instrument.instrument_id,
            instrument_name=instrument.display_name,
            channel=channel,
            is_mastercard=instrument.is_mastercard,
            value=value,
            reward=reward,
            offers=offers,
            benefits=benefits,
            evidence=evidence,
            late_fee_warning=risk.late_fee_warning(instrument, self.profile),
            payoff_recommendation=risk.payoff_recommendation(
                instrument, self.profile, purchase.amount
            ),
        )

    def options_for(
        self,
        purchase: PurchaseIntent,
        merchant_key: str,
        blocked: frozenset[str] = frozenset(),
        on: date | None = None,
    ) -> list[PaymentOption]:
        out: list[PaymentOption] = []
        for instrument in self.profile.instruments:
            if not instrument.is_card:
                continue  # demo scope: card-only comparison
            # A hard constraint, not a preference: a card cannot actually be
            # charged more than its available credit. Excluded before scoring
            # rather than ranked down, so an unaffordable card can never win no
            # matter how good its rewards look on paper.
            if not risk.can_afford(instrument, self.profile, purchase.amount):
                continue
            for channel in available_channels(purchase.category, instrument):
                out.append(
                    self.build_option(purchase, instrument, channel, merchant_key, blocked, on)
                )
        # Deterministic ordering:
        #   1. value
        #   2. prefer booking DIRECT -- never tell someone to change how they book
        #      unless it actually earns them something
        #   3. prefer Mastercard, but ONLY on an exact tie, and only with disclosure
        #   4. stable tiebreak on name so runs cannot reorder
        out.sort(
            key=lambda o: (
                -o.score,
                o.channel is not PurchaseChannel.MERCHANT_DIRECT,
                not o.is_mastercard,
                o.instrument_name,
                o.channel.value,
            )
        )
        self._disclose_tiebreak(out)
        return out

    @staticmethod
    def _disclose_tiebreak(options: list[PaymentOption]) -> None:
        """Flag the winner when a non-Mastercard option was worth exactly the same.

        The preference is legitimate only because it never changes a number and is
        always stated. If it ever fired on options that were NOT exactly equal it
        would be overstating the Mastercard, so the equality test is strict.
        """
        if not options:
            return
        winner = options[0]
        if not winner.is_mastercard:
            return
        rivals = [
            o for o in options[1:]
            if o.score == winner.score
            and o.channel is winner.channel
            and not o.is_mastercard
        ]
        if not rivals:
            return
        names = ", ".join(sorted({o.instrument_name for o in rivals}))
        winner.tiebreak_note = (
            f"Exact tie on value with {names}. SmartPay prefers the Mastercard when "
            f"options are worth precisely the same; no figure above is affected."
        )


class ItineraryOptimizer:
    def __init__(self, profile: FinancialProfile) -> None:
        self.profile = profile
        self.purchase = PurchaseOptimizer(profile)
        self.counterfactual = self.purchase.counterfactual
        self._limited = self._limited_artefacts()

    def _limited_artefacts(self) -> dict[str, int]:
        """Artefacts that may only be claimed a bounded number of times per plan."""
        from app.knowledge import offers as all_offers

        limits = {o.offer_id: o.max_redemptions for o in all_offers()}
        for benefit_id in _monthly_capped_benefit_ids():
            limits[benefit_id] = 1  # one itinerary sits inside one statement month
        return limits

    def _reconcile(
        self,
        items: list[ItineraryItem],
        keys: list[str],
        chooser,
        on: date | None,
    ) -> list[PaymentOption]:
        """Fixed-point loop: pick, detect over-claims, block the weaker ones, repeat."""
        blocked_by_item: dict[str, frozenset[str]] = {i.item_id: frozenset() for i in items}

        for _ in range(MAX_RECONCILE_PASSES):
            chosen: dict[str, PaymentOption] = {}
            for item, key in zip(items, keys):
                options = self.purchase.options_for(item, key, blocked_by_item[item.item_id], on)
                chosen[item.item_id] = chooser(item, key, options)

            claims: dict[str, list[tuple[Decimal, str]]] = collections.defaultdict(list)
            for item in items:
                option = chosen[item.item_id]
                for o in option.offers:
                    claims[o.offer_id].append((o.value, item.item_id))
                for b in option.benefits:
                    if b.benefit_id in self._limited:
                        claims[b.benefit_id].append((b.value, item.item_id))

            changed = False
            for artefact_id, entries in claims.items():
                limit = self._limited.get(artefact_id)
                if limit is None or len(entries) <= limit:
                    continue
                # Keep the claim where it is worth most. On equal value, apply it to
                # the LARGEST qualifying purchase -- alphabetical order would park a
                # $75 Disney offer on the dining line instead of the park tickets.
                amounts = {i.item_id: i.amount for i in items}
                entries.sort(key=lambda e: (-e[0], -amounts.get(e[1], Decimal(0)), e[1]))
                for _value, item_id in entries[limit:]:
                    blocked_by_item[item_id] = blocked_by_item[item_id] | {artefact_id}
                    changed = True

            if not changed:
                return [chosen[i.item_id] for i in items]

        return [chosen[i.item_id] for i in items]

    def optimise(self, itinerary: Itinerary, customer_id: str) -> PaymentPlan:
        items = itinerary.items
        on = itinerary.start_date
        cats = [categorise(i.merchant, i.label, i.category) for i in items]
        keys = [c.merchant_key for c in cats]

        # Resolve each item's category through the categorizer, so free text from
        # ChatGPT is normalised before any rule is applied.
        for item, cat in zip(items, cats):
            item.category = cat.category

        baseline_ids: list[str | None] = []
        baseline_dists = []
        for item, key in zip(items, keys):
            instrument_id, _channel, dist = self.counterfactual.estimate_baseline(item, key)
            baseline_ids.append(instrument_id)
            baseline_dists.append(dist)

        def pick_recommended(_item, _key, options):
            return options[0]

        def pick_baseline(item, _key, options):
            wanted = baseline_ids[items.index(item)]
            for option in options:
                if option.instrument_id == wanted and option.channel is PurchaseChannel.MERCHANT_DIRECT:
                    return option
            return options[0]

        recommended = self._reconcile(items, keys, pick_recommended, on)
        baseline = self._reconcile(items, keys, pick_baseline, on)

        recommendations: list[PaymentRecommendation] = []
        for item, base, best, dist in zip(items, baseline, recommended, baseline_dists):
            recommendations.append(
                PaymentRecommendation(
                    item_id=item.item_id,
                    item_label=item.display_label,
                    merchant=item.merchant,
                    category=item.category,
                    amount=item.amount,
                    baseline=base,
                    baseline_probability=dist.probability(base.instrument_id),
                    baseline_rationale=self.counterfactual.rationale(dist, base.instrument_name),
                    recommended=best,
                    incremental_guaranteed=quantize(
                        best.value.guaranteed_value - base.value.guaranteed_value
                    ),
                    incremental_estimated=quantize(
                        best.value.estimated_reward_value - base.value.estimated_reward_value
                    ),
                    incremental_points=best.value.points_earned - base.value.points_earned,
                    rationale=self._rationale(best, base),
                    evidence=best.evidence,
                )
            )

        return PaymentPlan(
            customer_id=customer_id,
            itinerary_id=itinerary.itinerary_id,
            itinerary_title=itinerary.title,
            itinerary_total=itinerary.total,
            recommendations=recommendations,
            baseline_value=self._sum(baseline),
            smartpay_value=self._sum(recommended),
            incremental_guaranteed=quantize(
                self._sum(recommended).guaranteed_value - self._sum(baseline).guaranteed_value
            ),
            incremental_estimated=quantize(
                self._sum(recommended).estimated_reward_value
                - self._sum(baseline).estimated_reward_value
            ),
            incremental_points=(
                self._sum(recommended).points_earned - self._sum(baseline).points_earned
            ),
        )

    @staticmethod
    def _sum(options: list[PaymentOption]) -> ValueBreakdown:
        total = ValueBreakdown()
        soft: list[str] = []
        for o in options:
            total.hard_savings += o.value.hard_savings
            total.statement_credits += o.value.statement_credits
            total.fees_avoided += o.value.fees_avoided
            total.estimated_reward_value += o.value.estimated_reward_value
            total.points_earned += o.value.points_earned
            soft.extend(o.value.soft_benefits)
        total.soft_benefits = sorted(set(soft))
        return total

    @staticmethod
    def _rationale(best: PaymentOption, base: PaymentOption) -> str:
        bits = [best.reward.explanation]
        if best.channel is not PurchaseChannel.MERCHANT_DIRECT:
            bits.append(f"Booked {best.channel_label} to qualify for the higher rate.")
        for o in best.offers:
            bits.append(f"{o.label}: {o.explanation}")
        for b in best.benefits:
            bits.append(b.explanation)
        if best.tiebreak_note:
            bits.append(best.tiebreak_note)
        if best.instrument_id == base.instrument_id and best.channel is base.channel:
            bits.append("This already matches Alex's usual choice.")
        return " ".join(bits)
