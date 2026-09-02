"""The application service. PLAN.MD section 28.

MCP and any future REST layer both call this and nothing else, so SmartPay's core
stays channel-independent. Every method returns the same envelope:

    {"display_markdown": ..., "data": ..., "disclaimers": [...]}
"""

from __future__ import annotations

import collections
import re
from datetime import date
from decimal import Decimal

from app import analytics, config, coupons, history, render
from app.engines.baseline import BaselineEngine
from app.engines.optimizer import ItineraryOptimizer, PurchaseOptimizer
from app.engines.categorizer import categorise
from app.engines.wallet_optimizer import WalletOptimizer
from app.engines import priceless as priceless_engine
from app.knowledge import card_products
from app.models.common import Category, RewardCurrency
from app.models.planning import Itinerary, ItineraryItem, PaymentPlan, PurchaseIntent
from app.money import ZERO, fmt, quantize
from app.providers.future_spend import CommerceGPTMockProvider
from app.providers.open_finance import OpenFinanceProvider, default_provider
from app.scenarios import load_scenario

SYNTHETIC_DATA_NOTE = (
    "Alex is a synthetic demo consumer. Transaction history is generated, not real."
)
NETWORK_TIEBREAK_NOTE = (
    "Where two payment options were worth exactly the same before this, SmartPay "
    "recommends the Mastercard: it funds an extra 5% of that purchase back as a "
    "statement credit for choosing it, which is what breaks the tie. This is a "
    "simulated Mastercard tiebreak incentive modelled on real card-linked offer "
    "mechanics, not a live Mastercard offer, and it only ever applies to an exact "
    "tie."
)
MASTERCARD_OFFER_NOTE = (
    "Offers marked 'Mastercard card-linked offer' are real Mastercard card-linked "
    "offers sourced from the Mastercard Offers platform (2026 Q3 US catalogue). The "
    "offer terms are genuine; their validity window has been extended to the demo "
    "period."
)
FORECAST_NOTE = (
    "Future spend is produced by a demo CommerceGPT adapter from observed history, "
    "not a live CommerceGPT prediction."
)


def _slug(title: str) -> str:
    """A stable id derived from the itinerary's title.

    Every ChatGPT-authored itinerary used to be filed under "custom", so asking
    about Ireland and then New York left only one of them in the history -- the
    second overwrote the first. Deriving the id from the title keeps distinct trips
    apart while re-asking the same trip still refreshes its entry in place.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")
    return cleaned[:60] or "custom_itinerary"


def _envelope(markdown: str, data: dict, disclaimers: list[str]) -> dict:
    return {"display_markdown": markdown, "data": data, "disclaimers": disclaimers}


class SmartPayService:
    def __init__(self, provider: OpenFinanceProvider | None = None) -> None:
        self.provider = provider or default_provider()
        self.forecaster = CommerceGPTMockProvider()
        self._recommendations: dict[str, dict] = {}

    # -- profile -------------------------------------------------------------

    def get_financial_profile(self, customer_id: str = config.DEMO_CUSTOMER_ID) -> dict:
        profile = self.provider.get_profile(customer_id)
        baseline = BaselineEngine(profile)
        names = {i.instrument_id: i.display_name for i in profile.instruments}

        totals: dict[Category, Decimal] = collections.defaultdict(Decimal)
        for txn in profile.spend_transactions:
            totals[txn.category] += txn.amount

        habits = []
        for category in (Category.RESTAURANT, Category.SUPERMARKET, Category.AIRFARE,
                         Category.HOTEL, Category.GAS, Category.RIDESHARE):
            dist = baseline.distribution(category, "")
            top = dist.most_likely
            if top:
                habits.append((category.value, names.get(top, top), f"{dist.probability(top):.0%}"))

        dates = [t.posted_at for t in profile.transactions]
        summary = {
            "institutions": ", ".join(sorted({a.institution.title() for a in profile.accounts})),
            "account_count": len(profile.accounts),
            "transaction_count": len(profile.transactions),
            "spend_count": len(profile.spend_transactions),
            "period_start": min(dates).isoformat(),
            "period_end": max(dates).isoformat(),
            "by_category": [
                (c.value, fmt(v)) for c, v in sorted(totals.items(), key=lambda kv: -kv[1])
            ],
            "habits": habits,
        }
        return _envelope(
            render.profile_markdown(customer_id, summary), summary, [SYNTHETIC_DATA_NOTE]
        )

    def get_wallet(self, customer_id: str = config.DEMO_CUSTOMER_ID) -> dict:
        profile = self.provider.get_profile(customer_id)
        cards = []
        for instrument in profile.instruments:
            product = instrument.product
            if product is None:
                continue
            best = max(product.reward_rules, key=lambda r: r.multiplier, default=None)
            cards.append({
                "product_id": product.product_id,
                "display_name": product.display_name,
                "network": product.network.value.title()
                + (f" {product.network_tier.value.replace('_', ' ').title()}"
                   if product.network_tier.value != "none" else ""),
                "annual_fee": fmt(product.annual_fee),
                "headline": best.description if best else f"{product.base_multiplier}x base",
            })
        return _envelope(
            render.wallet_list_markdown(customer_id, cards), {"cards": cards},
            [SYNTHETIC_DATA_NOTE],
        )

    # -- optimisation --------------------------------------------------------

    def optimise_purchase(
        self, customer_id: str = config.DEMO_CUSTOMER_ID, purchase: dict | None = None
    ) -> dict:
        intent = PurchaseIntent.model_validate(purchase or {})
        item = ItineraryItem(item_id="purchase", **intent.model_dump())
        itinerary = Itinerary(
            itinerary_id="single_purchase", title=intent.display_label, items=[item],
            start_date=intent.purchase_date,
        )
        return self._optimise(customer_id, itinerary)

    def optimise_itinerary(
        self,
        customer_id: str = config.DEMO_CUSTOMER_ID,
        itinerary: dict | None = None,
        scenario_id: str | None = None,
        record: bool = True,
    ) -> dict:
        """PLAN.MD sections 33 and 38.

        With no items supplied, falls back to the frozen rehearsed scenario so the
        demo is reproducible. With items supplied, optimises exactly those.
        """
        if itinerary and itinerary.get("items"):
            title = itinerary.get("title", "Custom itinerary")
            resolved = Itinerary.model_validate(
                {"itinerary_id": itinerary.get("itinerary_id") or _slug(title),
                 "title": title,
                 "start_date": itinerary.get("start_date"),
                 "end_date": itinerary.get("end_date"),
                 "items": [
                     {"item_id": it.get("item_id") or f"item_{n}", **it}
                     for n, it in enumerate(itinerary["items"], start=1)
                 ]}
            )
        else:
            resolved = load_scenario(scenario_id or config.DEMO_SCENARIO_ID)
        return self._optimise(customer_id, resolved, record=record)

    def _optimise(self, customer_id: str, itinerary: Itinerary, record: bool = True) -> dict:
        profile = self.provider.get_profile(customer_id)
        plan = ItineraryOptimizer(profile).optimise(itinerary, customer_id)
        plan.priceless = self._priceless_for(profile, itinerary)
        plan.disclaimers = [SYNTHETIC_DATA_NOTE, render.VALUATION_FOOTNOTE]
        if any(r.recommended.offers for r in plan.recommendations):
            plan.disclaimers.insert(1, MASTERCARD_OFFER_NOTE)
        if any(r.recommended.tiebreak_note for r in plan.recommendations):
            plan.disclaimers.append(NETWORK_TIEBREAK_NOTE)

        # Where a line genuinely switches to a Mastercard the consumer does not
        # already carry the baseline card for, point at that product's own real
        # application page and quantify it with the same historic-spend evidence
        # accumulated_savings is built from -- never a fabricated "you'd save"
        # figure, and never shown if either the product or the number is missing.
        by_card = analytics.savings_by_card(profile)
        products = card_products()
        apply_offers: dict[str, dict] = {}
        for r in plan.recommendations:
            if not r.recommended.is_mastercard:
                continue
            if r.recommended.instrument_id == r.baseline.instrument_id:
                continue
            product = products.get(r.recommended.instrument_id)
            historic = by_card.get(r.recommended.instrument_id)
            if not product or not product.evidence.source_url or not historic or historic <= ZERO:
                continue
            apply_offers[r.item_id] = {
                "card": product.display_name,
                "url": product.evidence.source_url,
                "historic_savings": str(historic),
            }

        # A compact payload on purpose. The full model dump runs to ~43KB because
        # every option carries its evidence, and that much JSON crowds out the
        # rendered table in ChatGPT's context. Detail stays available on demand
        # through get_recommendation_evidence.
        data = {
            "customer_id": plan.customer_id,
            "itinerary_id": plan.itinerary_id,
            "itinerary_total": str(plan.itinerary_total),
            "baseline_value": {
                "guaranteed": str(plan.baseline_value.guaranteed_value),
                "estimated_reward_value": str(plan.baseline_value.estimated_reward_value),
                "points": plan.baseline_value.points_earned,
            },
            "smartpay_value": {
                "guaranteed": str(plan.smartpay_value.guaranteed_value),
                "estimated_reward_value": str(plan.smartpay_value.estimated_reward_value),
                "points": plan.smartpay_value.points_earned,
            },
            "incremental_guaranteed": str(plan.incremental_guaranteed),
            "incremental_estimated": str(plan.incremental_estimated),
            "incremental_points": plan.incremental_points,
            "recommendations": [
                {
                    "recommendation_id": f"{plan.itinerary_id}:{r.item_id}",
                    "item": r.item_label,
                    "amount": str(r.amount),
                    "baseline_payment": r.baseline.instrument_name,
                    "baseline_probability": f"{r.baseline_probability:.0%}",
                    "recommended_payment": r.recommended.instrument_name,
                    "recommended_channel": r.recommended.channel_label,
                    "tiebreak_note": r.recommended.tiebreak_note,
                    "late_fee_warning": r.recommended.late_fee_warning,
                    "payoff_recommendation": r.recommended.payoff_recommendation,
                    "is_mastercard": r.recommended.is_mastercard,
                    "guaranteed_savings": str(r.incremental_guaranteed),
                    "estimated_reward_value_delta": str(r.incremental_estimated),
                    "points_delta": r.incremental_points,
                    "benefits": [b.display_name for b in r.recommended.benefits],
                    "offers": [
                        {"label": o.label, "merchant": o.merchant_name, "value": str(o.value)}
                        for o in r.recommended.offers
                    ],
                    "apply_offer": apply_offers.get(r.item_id),
                }
                for r in plan.recommendations
            ],
            "priceless": plan.priceless,
        }
        if record:
            history.record(
                {
                    # Keyed on the itinerary so re-running a scenario refreshes its
                    # entry rather than stacking duplicates during a rehearsal.
                    "key": plan.itinerary_id,
                    "title": plan.itinerary_title,
                    "total": str(plan.itinerary_total),
                    "guaranteed": str(plan.incremental_guaranteed),
                    "estimated": str(plan.incremental_estimated),
                    "points": plan.incremental_points,
                    "items": len(plan.recommendations),
                    "plan": data,
                    "priceless": plan.priceless,
                    "disclaimers": plan.disclaimers,
                }
            )
            analytics.record_identified(
                plan.itinerary_id, plan.itinerary_title,
                plan.incremental_guaranteed, plan.incremental_estimated,
            )
            for r in plan.recommendations:
                if r.recommended.tiebreak_bonus > ZERO:
                    discount_percent = quantize(
                        r.recommended.tiebreak_bonus / r.amount * 100
                    )
                    coupons.record_from_recommendation(
                        coupon_id=f"{plan.itinerary_id}:{r.item_id}",
                        merchant=r.merchant,
                        item_label=r.item_label,
                        approx_amount=r.amount,
                        card_name=r.recommended.instrument_name,
                        discount_percent=discount_percent,
                        issued_on=date.today(),
                    )

        for r in plan.recommendations:
            self._recommendations[f"{plan.itinerary_id}:{r.item_id}"] = {
                "item": r.item_label,
                "recommended": r.recommended.instrument_name,
                "channel": r.recommended.channel_label,
                "rationale": r.rationale,
                "baseline_rationale": r.baseline_rationale,
                "evidence": [e.model_dump(mode="json") for e in r.evidence],
            }
        return _envelope(render.payment_plan_markdown(plan, apply_offers), data, plan.disclaimers)

    def optimise_wallet(self, customer_id: str = config.DEMO_CUSTOMER_ID) -> dict:
        profile = self.provider.get_profile(customer_id)
        itinerary = load_scenario(config.DEMO_SCENARIO_ID)
        forecast = self.forecaster.predict(profile, 12, itinerary)
        rec = WalletOptimizer(profile).optimise(forecast, itinerary)
        rec.disclaimers = [SYNTHETIC_DATA_NOTE, FORECAST_NOTE]
        data = {
            "recommendation": rec.model_dump(mode="json"),
            "forecast": forecast.model_dump(mode="json"),
        }
        return _envelope(render.wallet_markdown(rec), data, rec.disclaimers)

    # -- evidence ------------------------------------------------------------

    def get_recommendation_evidence(self, recommendation_id: str) -> dict:
        record = self._recommendations.get(recommendation_id)
        if record is None and ":" in recommendation_id:
            # Evidence must still answer after a server restart, or when ChatGPT
            # asks "why?" before it has asked for the plan.
            scenario = recommendation_id.split(":", 1)[0]
            try:
                self.optimise_itinerary(config.DEMO_CUSTOMER_ID, None, scenario)
            except KeyError:
                pass
            record = self._recommendations.get(recommendation_id)
        if record is None:
            known = sorted(self._recommendations)
            return _envelope(
                "No such recommendation. Run optimise_itinerary first.\n\n"
                + ("Known ids: " + ", ".join(known) if known else ""),
                {"known_ids": known}, [],
            )
        lines = [
            f"## Why SmartPay recommended this — {record['item']}",
            "",
            f"**Recommended:** {record['recommended']} ({record['channel']})",
            "",
            f"**Baseline:** {record['baseline_rationale']}",
            "",
            f"**Reasoning:** {record['rationale']}",
            "",
            "### Evidence",
            "",
            "| Source | Type | Confidence | Verified | Reference |",
            "|---|---|---|---|---|",
        ]
        seen = set()
        for e in record["evidence"]:
            key = (e["source_name"], e["note"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"| {e['source_name']} | {e['evidence_type']} | {e['confidence']} | "
                f"{e.get('verified_at') or '—'} | {e.get('source_url') or '—'} |"
            )
        return _envelope("\n".join(lines), record, [])

    # -- helpers -------------------------------------------------------------

    def _priceless_for(self, profile, itinerary: Itinerary) -> list[dict]:
        """PLAN.MD section 12. Surfaced only when the history actually supports it,
        or when this itinerary's own destination matches a real catalogue offer
        there -- see app.engines.priceless for the matching and ranking rules.
        """
        return priceless_engine.itinerary_matches(profile, itinerary)
