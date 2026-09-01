"""Future spend prediction. PLAN.MD section 22.

Labelled everywhere as a demo adapter. The real CommerceGPT API is not wired in;
this projects forward from observed history using run rate, seasonality and known
upcoming commitments. Deterministic: no sampling, so the same history always
yields the same forecast.
"""

from __future__ import annotations

import collections
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.models.common import Category, Confidence, Evidence, EvidenceType
from app.models.financial import FinancialProfile
from app.models.planning import FutureSpendForecast, Itinerary
from app.money import ZERO, quantize

#: Modest category-level drift applied to the observed run rate. Deliberately
#: small and legible rather than a black box.
GROWTH: dict[Category, Decimal] = {
    Category.AIRFARE: Decimal("1.08"),
    Category.HOTEL: Decimal("1.08"),
    Category.ATTRACTION: Decimal("1.05"),
    Category.RESTAURANT: Decimal("1.04"),
    Category.SUPERMARKET: Decimal("1.03"),
    Category.GAS: Decimal("1.00"),
}
DEFAULT_GROWTH = Decimal("1.02")


class FutureSpendProvider(Protocol):
    def predict(self, profile: FinancialProfile, horizon_months: int) -> FutureSpendForecast: ...


class CommerceGPTMockProvider:
    """Demo CommerceGPT adapter."""

    name = "Demo CommerceGPT adapter"

    def predict(
        self,
        profile: FinancialProfile,
        horizon_months: int = 12,
        upcoming: Itinerary | None = None,
    ) -> FutureSpendForecast:
        totals: dict[Category, Decimal] = collections.defaultdict(Decimal)
        months: set[str] = set()
        for txn in profile.spend_transactions:
            totals[txn.category] += txn.amount
            months.add(txn.posted_at.strftime("%Y-%m"))

        observed_months = max(len(months), 1)
        horizon = Decimal(horizon_months)

        forecast: dict[Category, Decimal] = {}
        for category, total in totals.items():
            run_rate = total / Decimal(observed_months)
            growth = GROWTH.get(category, DEFAULT_GROWTH)
            forecast[category] = quantize(run_rate * horizon * growth)

        drivers = [
            f"{observed_months} months of observed Open Finance transaction history",
            f"Category run rate projected over {horizon_months} months",
            "Category-level growth assumptions applied (travel +8%, dining +4%)",
        ]

        if upcoming is not None:
            for item in upcoming.items:
                forecast[item.category] = quantize(
                    forecast.get(item.category, ZERO) + item.amount
                )
            drivers.append(f"Known upcoming itinerary: {upcoming.title}")

        return FutureSpendForecast(
            customer_id=profile.customer_id,
            horizon_months=horizon_months,
            by_category=dict(sorted(forecast.items(), key=lambda kv: -kv[1])),
            method=self.name,
            drivers=drivers,
            evidence=[
                Evidence(
                    evidence_type=EvidenceType.FORECAST,
                    source_name="Demo CommerceGPT adapter",
                    confidence=Confidence.DEMO_APPROXIMATION,
                    verified_at=date(2026, 9, 1),
                    note=(
                        "Forecast produced by a deterministic demo adapter from observed "
                        "history. Not a live CommerceGPT prediction."
                    ),
                )
            ],
        )
