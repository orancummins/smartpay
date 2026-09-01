"""What Alex would have done. PLAN.MD section 21.

The counterfactual is only credible if the baseline is valued through exactly the
same machinery as the recommendation. If the baseline were scored more crudely,
the delta would measure our own inconsistency rather than a better payment choice.
So: same rewards engine, same offers, same benefits -- only the instrument and the
booking channel differ.

Alex's baseline channel is always MERCHANT_DIRECT, because that is what the
history shows: not one portal booking in twelve months.
"""

from __future__ import annotations

from app.engines.baseline import BaselineDistribution, BaselineEngine
from app.models.common import PurchaseChannel
from app.models.financial import FinancialProfile
from app.models.planning import PurchaseIntent


class CounterfactualEngine:
    def __init__(self, profile: FinancialProfile) -> None:
        self.profile = profile
        self.baseline = BaselineEngine(profile)

    def estimate_baseline(
        self, purchase: PurchaseIntent, merchant_key: str
    ) -> tuple[str | None, PurchaseChannel, BaselineDistribution]:
        dist = self.baseline.distribution(purchase.category, merchant_key)
        return dist.most_likely, PurchaseChannel.MERCHANT_DIRECT, dist

    def rationale(self, dist: BaselineDistribution, instrument_name: str) -> str:
        if not dist.probabilities:
            return "No comparable history; assumed the most-used card."
        return dist.rationale.replace("{instrument}", instrument_name)
