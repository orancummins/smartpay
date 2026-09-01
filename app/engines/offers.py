"""Card-linked offers. PLAN.MD section 18.

Per-item qualification only. Whether an offer can actually be REDEEMED across a
whole itinerary is decided in the optimiser's second pass, because a one-time
$75 offer must not pay out once per matching line item.
"""

from __future__ import annotations

from datetime import date

from app.knowledge import offers as all_offers
from app.models.financial import PaymentInstrument
from app.models.planning import OfferEvaluation, PurchaseIntent


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

        merchant_key = merchant_key or purchase.merchant
        on = on or purchase.purchase_date or date.today()
        results: list[OfferEvaluation] = []

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

            results.append(
                OfferEvaluation(
                    offer_id=offer.offer_id,
                    merchant_name=offer.merchant_name,
                    value=offer.value,
                    is_synthetic=offer.is_synthetic,
                    label=offer.provenance.label,
                    explanation=(
                        f"{offer.description} (minimum spend "
                        f"${offer.minimum_spend:,.0f} met)"
                    ),
                    evidence=[offer.evidence],
                )
            )
        return results
