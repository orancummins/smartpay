"""Card-linked offers. PLAN.MD section 18.

Per-item qualification only. Whether an offer can actually be REDEEMED across a
whole itinerary is decided in the optimiser's second pass, because a one-time
$75 offer must not pay out once per matching line item.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.knowledge import offers as all_offers
from app.models.financial import PaymentInstrument
from app.models.planning import OfferEvaluation, PurchaseIntent
from app.models.rules import BenefitType, Offer
from app.money import quantize


class OffersEngine:
    def evaluate(
        self,
        purchase: PurchaseIntent,
        instrument: PaymentInstrument,
        merchant_key: str | None = None,
        on: date | None = None,
    ) -> list[OfferEvaluation]:
        product = instrument.product
        if product is None:
            return []
        # A Mastercard card-linked offer can only ever be redeemed by paying with
        # a Mastercard-network card -- without this, a Visa baseline option
        # silently claims the same credit as the Mastercard recommendation, and
        # the two cancel out in the incremental total instead of showing up as
        # real Mastercard-exclusive value.
        if not instrument.is_mastercard:
            return []

        merchant_key = merchant_key or purchase.merchant
        on = on or purchase.purchase_date or date.today()
        candidates: list[tuple[Offer, Decimal]] = []

        for offer in all_offers():
            if offer.eligible_products and product.product_id not in offer.eligible_products:
                continue
            if not offer.is_active(on):
                continue
            # A merchant-scoped offer REQUIRES that merchant. OR-ing merchant and
            # category would let a Walt Disney World offer pay out on any hotel
            # stay anywhere, which is not how card-linked offers work.
            if offer.merchants and merchant_key not in offer.merchants:
                continue
            if offer.categories and purchase.category not in offer.categories:
                continue
            if not offer.merchants and not offer.categories:
                continue
            if purchase.amount < offer.minimum_spend:
                continue

            candidates.append((offer, self._credit(offer, purchase.amount)))

        if not candidates:
            return []

        # A consumer redeems at most one card-linked offer per merchant per
        # purchase. The catalogue carries near-duplicate campaigns for the same
        # merchant (e.g. an activation vs a standing offer), so keep only the most
        # valuable rather than stacking them into a fictitious combined credit.
        offer, credit = max(candidates, key=lambda c: c[1])
        return [
            OfferEvaluation(
                offer_id=offer.offer_id,
                merchant_name=offer.merchant_name,
                value=credit,
                is_synthetic=offer.is_synthetic,
                label=offer.provenance.label,
                explanation=(
                    f"{offer.description} (minimum spend "
                    f"${offer.minimum_spend:,.0f} met)"
                ),
                evidence=[offer.evidence],
            )
        ]

    @staticmethod
    def _credit(offer: Offer, amount: Decimal) -> Decimal:
        """The dollar credit this offer pays on a purchase of `amount`.

        A statement-credit offer pays its flat value; a percentage offer pays that
        percentage of the spend, capped by max_discount when the catalogue sets one.
        """
        if offer.benefit_type is BenefitType.DISCOUNT_PCT:
            credit = amount * offer.value / 100
            if offer.max_discount is not None:
                credit = min(credit, offer.max_discount)
            return quantize(credit)
        return quantize(offer.value)
