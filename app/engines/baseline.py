"""How Alex actually pays. PLAN.MD section 20.

No ML framework: observed frequencies with Laplace smoothing and a fallback
ladder. The ladder matters more than it looks. Raw frequencies give P = 1.0 from a
single observation, so a lone Lyft ride would let SmartPay claim certainty about a
habit it has seen once. Each rung is used only if it has enough support:

    merchant + category  ->  merchant  ->  category  ->  category group  ->  global

The category-group rung is what rescues travel. Alex books flights six times a
year, not sixty, so per-category evidence is thin while the pooled travel
behaviour is clear.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from decimal import Decimal

from app.models.common import Category
from app.models.financial import FinancialProfile

#: Minimum observations before a rung is trusted on its own.
MIN_SUPPORT = 5
#: Laplace smoothing constant. Stops any single observation implying certainty.
ALPHA = Decimal("1")

CATEGORY_GROUPS: dict[str, set[Category]] = {
    "travel": {Category.AIRFARE, Category.HOTEL, Category.ATTRACTION, Category.CAR_RENTAL},
    "daily": {Category.SUPERMARKET, Category.GROCERY_ONLINE, Category.DRUGSTORE},
    "going_out": {Category.RESTAURANT, Category.ENTERTAINMENT, Category.GOLF},
    "getting_around": {Category.RIDESHARE, Category.TRANSPORT, Category.GAS},
    "retail": {Category.SHOPPING, Category.OTHER},
}


def group_for(category: Category) -> str | None:
    for name, members in CATEGORY_GROUPS.items():
        if category in members:
            return name
    return None


@dataclass
class BaselineDistribution:
    """A probability distribution over payment instruments, plus how we got it."""

    probabilities: dict[str, Decimal]
    level: str
    support: int
    rationale: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def most_likely(self) -> str | None:
        if not self.probabilities:
            return None
        return max(self.probabilities.items(), key=lambda kv: (kv[1], kv[0]))[0]

    def probability(self, instrument_id: str) -> Decimal:
        return self.probabilities.get(instrument_id, Decimal("0"))


class BaselineEngine:
    def __init__(self, profile: FinancialProfile) -> None:
        self.profile = profile
        self._account_to_instrument = {
            i.account_id: i.instrument_id for i in profile.instruments if i.is_card
        }
        self._build()

    def _build(self) -> None:
        self.by_merchant_category: dict[tuple[str, Category], collections.Counter] = (
            collections.defaultdict(collections.Counter)
        )
        self.by_merchant: dict[str, collections.Counter] = collections.defaultdict(
            collections.Counter
        )
        self.by_category: dict[Category, collections.Counter] = collections.defaultdict(
            collections.Counter
        )
        self.by_group: dict[str, collections.Counter] = collections.defaultdict(
            collections.Counter
        )
        self.global_counts: collections.Counter = collections.Counter()

        for txn in self.profile.spend_transactions:
            instrument_id = self._account_to_instrument.get(txn.account_id)
            if instrument_id is None:
                continue  # paid from checking; not a card habit
            self.by_merchant_category[(txn.merchant, txn.category)][instrument_id] += 1
            self.by_merchant[txn.merchant][instrument_id] += 1
            self.by_category[txn.category][instrument_id] += 1
            group = group_for(txn.category)
            if group:
                self.by_group[group][instrument_id] += 1
            self.global_counts[instrument_id] += 1

    def _smooth(self, counts: collections.Counter) -> dict[str, Decimal]:
        instruments = [i.instrument_id for i in self.profile.instruments if i.is_card]
        total = Decimal(sum(counts.values())) + ALPHA * Decimal(len(instruments))
        return {
            i: ((Decimal(counts.get(i, 0)) + ALPHA) / total)
            for i in instruments
        }

    def distribution(self, category: Category, merchant_key: str) -> BaselineDistribution:
        group = group_for(category)
        ladder = [
            (self.by_merchant_category.get((merchant_key, category)),
             f"{merchant_key} purchases in {category.value}", "merchant+category"),
            (self.by_merchant.get(merchant_key), f"{merchant_key} purchases", "merchant"),
            (self.by_category.get(category), f"{category.value} purchases", "category"),
            (self.by_group.get(group) if group else None,
             f"{group} purchases" if group else "", "category group"),
            (self.global_counts, "all card purchases", "global"),
        ]

        for counts, label, level in ladder:
            if not counts:
                continue
            support = sum(counts.values())
            if support < MIN_SUPPORT and level != "global":
                continue
            probs = self._smooth(counts)
            top = max(probs.items(), key=lambda kv: (kv[1], kv[0]))
            return BaselineDistribution(
                probabilities=probs,
                level=level,
                support=support,
                counts=dict(counts),
                rationale=(
                    f"Based on {support} historical {label}, Alex used "
                    f"{{instrument}} {top[1]:.0%} of the time."
                ),
                )

        return BaselineDistribution({}, "none", 0, "No usable history.")
