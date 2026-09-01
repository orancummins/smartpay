"""Generate Alex's synthetic two-bank financial history.

PLAN.MD sections 5-7. Deterministic under a fixed seed, ledger-consistent, and
deliberately IMPERFECT: Alex's habits are predictable but suboptimal, which is what
gives the counterfactual something real to beat.

Every signal the demo later claims to infer is planted here on purpose -- golf
spend, three-plus Lyft rides a month, Instacart, Peacock, supermarket-heavy
grocery. If a judge asks "how do you know Alex plays golf?", the answer must be
rows in the ledger, not a hardcoded string.

Run:  python scripts/generate_alex.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.models.common import Category, PurchaseChannel  # noqa: E402
from app.models.financial import AccountType, TransactionType  # noqa: E402
from app.money import usd  # noqa: E402

START = date(2025, 9, 1)
END = date(2026, 8, 31)

CITI_CHECKING = "acct_citi_checking"
CHASE_CHECKING = "acct_chase_checking"

# card account id -> product id
CARD_ACCOUNTS = {
    "acct_citi_strata": "citi_strata_premier",
    "acct_citi_double_cash": "citi_double_cash",
    "acct_citi_aa": "citi_aa_platinum_select",
    "acct_chase_csp": "chase_sapphire_preferred",
    "acct_chase_cfu": "chase_freedom_unlimited",
}

ACCOUNTS = [
    {"account_id": CITI_CHECKING, "institution": "citi", "display_name": "Citi Checking",
     "account_type": AccountType.CHECKING, "mask": "4412"},
    {"account_id": CHASE_CHECKING, "institution": "chase", "display_name": "Chase Total Checking",
     "account_type": AccountType.CHECKING, "mask": "8830"},
    {"account_id": "acct_citi_strata", "institution": "citi", "display_name": "Citi Strata Premier Card",
     "account_type": AccountType.CREDIT_CARD, "mask": "9021"},
    {"account_id": "acct_citi_double_cash", "institution": "citi", "display_name": "Citi Double Cash Card",
     "account_type": AccountType.CREDIT_CARD, "mask": "7745"},
    {"account_id": "acct_citi_aa", "institution": "citi", "display_name": "Citi / AAdvantage Platinum Select",
     "account_type": AccountType.CREDIT_CARD, "mask": "3160"},
    {"account_id": "acct_chase_csp", "institution": "chase", "display_name": "Chase Sapphire Preferred",
     "account_type": AccountType.CREDIT_CARD, "mask": "5518"},
    {"account_id": "acct_chase_cfu", "institution": "chase", "display_name": "Chase Freedom Unlimited",
     "account_type": AccountType.CREDIT_CARD, "mask": "2094"},
]

# Merchant catalogue: (merchant_key, display name, low, high)
MERCHANTS: dict[Category, list[tuple[str, str, int, int]]] = {
    Category.SUPERMARKET: [
        ("publix", "Publix", 60, 215), ("whole_foods", "Whole Foods Market", 70, 245),
        ("trader_joes", "Trader Joe's", 45, 150), ("stop_and_shop", "Stop & Shop", 55, 195),
    ],
    Category.GROCERY_ONLINE: [("instacart", "Instacart", 65, 180)],
    Category.RESTAURANT: [
        ("chipotle", "Chipotle", 18, 62), ("panera", "Panera Bread", 16, 50),
        ("olive_garden", "Olive Garden", 70, 190), ("local_bistro", "Alma Bistro", 95, 280),
        ("shake_shack", "Shake Shack", 24, 72), ("starbucks", "Starbucks", 8, 28),
        ("thai_basil", "Thai Basil", 45, 130), ("sushi_ichiban", "Sushi Ichiban", 85, 240),
    ],
    Category.GAS: [
        ("shell", "Shell", 55, 120), ("mobil", "Mobil", 58, 125), ("costco_gas", "Costco Gas", 60, 130),
    ],
    Category.RIDESHARE: [("lyft", "Lyft", 11, 46)],
    Category.GOLF: [
        ("granite_links", "Granite Links Golf Club", 95, 210),
        ("golf_galaxy", "Golf Galaxy", 60, 320),
    ],
    Category.ENTERTAINMENT: [
        ("amc_theatres", "AMC Theatres", 35, 110), ("ticketmaster", "Ticketmaster", 140, 460),
        ("museum_of_science", "Museum of Science", 40, 130),
    ],
    Category.SHOPPING: [
        ("amazon", "Amazon", 25, 320), ("target", "Target", 40, 220),
        ("rei", "REI", 70, 380), ("apple_store", "Apple Store", 120, 600),
        ("nordstrom", "Nordstrom", 90, 380),
    ],
    Category.DRUGSTORE: [("cvs", "CVS Pharmacy", 12, 65), ("walgreens", "Walgreens", 10, 58)],
    Category.TRANSPORT: [("mbta", "MBTA", 12, 90), ("logan_parking", "Logan Airport Parking", 24, 110)],
    Category.OTHER: [
        ("usps", "USPS", 8, 40), ("home_depot", "The Home Depot", 25, 190),
        ("petco", "Petco", 20, 95), ("dry_cleaners", "Beacon Dry Cleaners", 18, 60),
    ],
}

# Recurring monthly charges: (merchant_key, display, amount, category, instrument)
SUBSCRIPTIONS = [
    ("peacock", "Peacock Premium", "10.99", Category.STREAMING, "acct_chase_cfu"),
    ("netflix", "Netflix", "17.99", Category.STREAMING, "acct_chase_cfu"),
    ("spotify", "Spotify", "11.99", Category.STREAMING, "acct_citi_double_cash"),
    ("verizon", "Verizon Wireless", "142.00", Category.UTILITIES, CHASE_CHECKING),
    ("eversource", "Eversource Energy", "168.00", Category.UTILITIES, CHASE_CHECKING),
    ("comcast", "Comcast Xfinity", "94.00", Category.UTILITIES, CHASE_CHECKING),
    ("city_water", "City of Boston Water", "56.00", Category.UTILITIES, CHASE_CHECKING),
]

# PLAN.MD section 6 -- Alex's imperfect habits, as weighted instrument choices.
HABITS: dict[Category, dict[str, float]] = {
    Category.RESTAURANT: {"acct_chase_csp": 0.70, "acct_chase_cfu": 0.15,
                          "acct_citi_double_cash": 0.10, "acct_citi_strata": 0.05},
    Category.AIRFARE: {"acct_chase_csp": 0.75, "acct_citi_aa": 0.15, "acct_citi_strata": 0.10},
    Category.HOTEL: {"acct_chase_csp": 0.60, "acct_citi_strata": 0.25, "acct_chase_cfu": 0.15},
    Category.ATTRACTION: {"acct_chase_csp": 0.55, "acct_chase_cfu": 0.30,
                          "acct_citi_double_cash": 0.15},
    Category.SUPERMARKET: {"acct_citi_double_cash": 0.50, "acct_chase_cfu": 0.30,
                           "acct_chase_csp": 0.20},
    Category.GROCERY_ONLINE: {"acct_citi_double_cash": 0.60, "acct_chase_cfu": 0.40},
    Category.GAS: {"acct_chase_cfu": 0.55, "acct_citi_double_cash": 0.30, "acct_chase_csp": 0.15},
    Category.RIDESHARE: {"acct_chase_cfu": 0.45, "acct_chase_csp": 0.30,
                         "acct_citi_double_cash": 0.25},
    Category.GOLF: {"acct_chase_cfu": 0.50, "acct_citi_double_cash": 0.30, "acct_chase_csp": 0.20},
    Category.ENTERTAINMENT: {"acct_chase_cfu": 0.55, "acct_chase_csp": 0.25,
                             "acct_citi_double_cash": 0.20},
    Category.SHOPPING: {"acct_chase_cfu": 0.65, "acct_citi_double_cash": 0.25,
                        "acct_chase_csp": 0.10},
    Category.DRUGSTORE: {"acct_chase_cfu": 0.70, "acct_citi_double_cash": 0.30},
    Category.TRANSPORT: {"acct_chase_cfu": 0.50, "acct_chase_csp": 0.30,
                         "acct_citi_double_cash": 0.20},
    Category.OTHER: {"acct_chase_cfu": 0.65, "acct_citi_double_cash": 0.35},
}

# Roughly how many purchases per month per category. Tuned to land the annual
# spend profile in PLAN.MD section 5 and a total in the 550-600 range.
MONTHLY_COUNTS: dict[Category, int] = {
    Category.SUPERMARKET: 7,
    Category.GROCERY_ONLINE: 1,
    Category.RESTAURANT: 10,
    Category.GAS: 5,
    Category.RIDESHARE: 4,     # >= 3 a month: qualifies the Mastercard Lyft benefit
    Category.GOLF: 1,
    Category.ENTERTAINMENT: 2,
    Category.SHOPPING: 3,
    Category.DRUGSTORE: 1,
    Category.TRANSPORT: 1,
    Category.OTHER: 2,
}


def month_starts() -> list[date]:
    out, cur = [], START
    while cur <= END:
        out.append(cur)
        cur = date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)
    return out


class Generator:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.rows: list[dict] = []
        self.n = 0

    def _id(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}_{self.n:05d}"

    def add(self, **kw) -> None:
        kw.setdefault("transaction_type", TransactionType.PURCHASE)
        kw.setdefault("channel", PurchaseChannel.MERCHANT_DIRECT)
        kw.setdefault("counterparty_account_id", None)
        kw["transaction_id"] = self._id("txn")
        kw["amount"] = str(kw["amount"])
        kw["posted_at"] = kw["posted_at"].isoformat()
        kw["category"] = Category(kw["category"]).value
        kw["transaction_type"] = TransactionType(kw["transaction_type"]).value
        kw["channel"] = PurchaseChannel(kw["channel"]).value
        self.rows.append(kw)

    def day_in(self, month: date) -> date:
        nxt = date(month.year + (month.month == 12), (month.month % 12) + 1, 1)
        span = (nxt - month).days
        return month + timedelta(days=self.rng.randrange(span))

    def pick_instrument(self, category: Category) -> str:
        weights = HABITS[category]
        return self.rng.choices(list(weights), weights=list(weights.values()))[0]

    def amount_for(self, low: int, high: int) -> Decimal:
        cents = self.rng.randrange(low * 100, high * 100)
        return usd(Decimal(cents) / 100)

    def generate(self) -> list[dict]:
        months = month_starts()
        for month in months:
            self._income(month)
            self._housing(month)
            self._subscriptions(month)
            self._atm(month)
            self._everyday(month)
        self._travel(months)
        self._late_fee(months)
        self._card_payments(months)
        self.rows.sort(key=lambda r: (r["posted_at"], r["transaction_id"]))
        return self.rows

    def _income(self, month: date) -> None:
        for day in (1, 15):
            self.add(
                account_id=CHASE_CHECKING, posted_at=month.replace(day=day),
                merchant="northwind_health", description="NORTHWIND HEALTH PAYROLL",
                amount=usd("4180.00") * -1, category=Category.OTHER,
                transaction_type=TransactionType.INCOME,
            )

    def _housing(self, month: date) -> None:
        self.add(
            account_id=CHASE_CHECKING, posted_at=month.replace(day=1),
            merchant="beacon_property", description="BEACON PROPERTY MGMT ACH RENT",
            amount=usd("3000.00"), category=Category.HOUSING,
        )

    def _subscriptions(self, month: date) -> None:
        for i, (key, name, amt, cat, account) in enumerate(SUBSCRIPTIONS):
            self.add(
                account_id=account, posted_at=month.replace(day=min(3 + i * 3, 27)),
                merchant=key, description=name.upper(), amount=usd(amt), category=cat,
                channel=PurchaseChannel.ONLINE,
            )

    def _late_fee(self, months: list[date]) -> None:
        """PLAN.MD section 6: Alex has predictable but imperfect habits -- this is
        the concrete imperfection. One missed minimum payment on the everyday,
        lowest-attention card, verified against Chase's own published penalty fee
        (see data/cards/chase_freedom_unlimited.yaml). Plants the signal the risk
        engine's late-fee disclosure and payoff recommendation are meant to act on;
        without a real row here that behaviour would have nothing to point at.
        """
        month = months[6]
        self.add(
            account_id="acct_chase_cfu", posted_at=month.replace(day=22),
            merchant="chase", description="LATE PAYMENT FEE",
            amount=usd("40.00"), category=Category.OTHER,
            transaction_type=TransactionType.FEE,
        )

    def _atm(self, month: date) -> None:
        # PLAN.MD section 7: cash out is visible, but we never fabricate merchant
        # level spending from it.
        if self.rng.random() < 0.85:
            self.add(
                account_id=CHASE_CHECKING, posted_at=self.day_in(month),
                merchant="chase_atm", description="ATM WITHDRAWAL",
                amount=usd(self.rng.choice([60, 80, 100, 120, 200])),
                category=Category.OTHER, transaction_type=TransactionType.ATM_WITHDRAWAL,
            )

    def _everyday(self, month: date) -> None:
        for category, count in MONTHLY_COUNTS.items():
            n = max(1, count + self.rng.choice([-1, 0, 0, 1]))
            for _ in range(n):
                key, name, low, high = self.rng.choice(MERCHANTS[category])
                account = self.pick_instrument(category)
                channel = (
                    PurchaseChannel.ONLINE
                    if category in (Category.GROCERY_ONLINE, Category.RIDESHARE)
                    else PurchaseChannel.IN_STORE
                )
                self.add(
                    account_id=account, posted_at=self.day_in(month), merchant=key,
                    description=name.upper(), amount=self.amount_for(low, high),
                    category=category, channel=channel,
                )

    def _travel(self, months: list[date]) -> None:
        """Three trips across the year, booked the way Alex actually books: direct,
        on the Sapphire Preferred, collecting no portal bonus at all."""
        trips = [
            (months[2], "american_airlines", "AMERICAN AIRLINES", 1340, Category.AIRFARE),
            (months[2], "marriott", "MARRIOTT BONVOY", 1480, Category.HOTEL),
            (months[4], "universal_orlando", "UNIVERSAL ORLANDO", 640, Category.ATTRACTION),
            (months[4], "aquarium", "NEW ENGLAND AQUARIUM", 210, Category.ATTRACTION),
            (months[6], "jetblue", "JETBLUE AIRWAYS", 1180, Category.AIRFARE),
            (months[6], "hilton", "HILTON HOTELS", 1620, Category.HOTEL),
            (months[6], "hertz", "HERTZ RENT A CAR", 445, Category.CAR_RENTAL),
            (months[9], "american_airlines", "AMERICAN AIRLINES", 1510, Category.AIRFARE),
            (months[9], "marriott", "MARRIOTT BONVOY", 1390, Category.HOTEL),
            (months[10], "delta", "DELTA AIR LINES", 890, Category.AIRFARE),
            (months[10], "hyatt", "HYATT HOTELS", 760, Category.HOTEL),
            # Smaller, one-off travel. Four trips a year gives the baseline engine
            # too few samples to say anything honest about how Alex books travel;
            # a household that spends $15k on travel books more often than that.
            (months[1], "jetblue", "JETBLUE AIRWAYS", 520, Category.AIRFARE),
            (months[7], "american_airlines", "AMERICAN AIRLINES", 610, Category.AIRFARE),
            (months[1], "marriott", "MARRIOTT BONVOY", 340, Category.HOTEL),
            (months[11], "hilton", "HILTON HOTELS", 395, Category.HOTEL),
            (months[8], "boston_ballet", "BOSTON BALLET", 180, Category.ATTRACTION),
            (months[3], "zoo_new_england", "ZOO NEW ENGLAND", 120, Category.ATTRACTION),
        ]
        for month, key, name, amount, category in trips:
            habit = HABITS.get(category, HABITS[Category.OTHER])
            account = self.rng.choices(list(habit), weights=list(habit.values()))[0]
            self.add(
                account_id=account, posted_at=self.day_in(month), merchant=key,
                description=name, amount=usd(amount), category=category,
                channel=PurchaseChannel.MERCHANT_DIRECT,
            )

    def _card_payments(self, months: list[date]) -> None:
        """PLAN.MD section 7. Each month's card balance is paid from checking the
        following month. These are CARD_PAYMENT rows: money leaving checking that
        must never be counted a second time as consumer spend."""
        by_card_month: dict[tuple[str, str], Decimal] = {}
        for row in self.rows:
            if row["account_id"] in CARD_ACCOUNTS and row["transaction_type"] == "purchase":
                key = (row["account_id"], row["posted_at"][:7])
                by_card_month[key] = by_card_month.get(key, Decimal("0")) + Decimal(row["amount"])

        index = {m.strftime("%Y-%m"): i for i, m in enumerate(months)}
        for (card_account, ym), total in sorted(by_card_month.items()):
            i = index.get(ym)
            if i is None or i + 1 >= len(months):
                continue  # final month's balance is still outstanding, as in real life
            pay_month = months[i + 1]
            source = CITI_CHECKING if card_account.startswith("acct_citi") else CHASE_CHECKING
            self.add(
                account_id=source, posted_at=pay_month.replace(day=18),
                merchant="card_payment", description=f"AUTOPAY {card_account.upper()}",
                amount=usd(total), category=Category.OTHER,
                transaction_type=TransactionType.CARD_PAYMENT,
                counterparty_account_id=card_account,
            )


def main() -> None:
    gen = Generator(config.RANDOM_SEED)
    rows = gen.generate()
    payload = {
        "customer_id": config.DEMO_CUSTOMER_ID,
        "generated_with_seed": config.RANDOM_SEED,
        "period": {"start": START.isoformat(), "end": END.isoformat()},
        "accounts": [{**a, "account_type": a["account_type"].value} for a in ACCOUNTS],
        "card_accounts": CARD_ACCOUNTS,
        "transactions": rows,
    }
    out = config.DATA / "alex" / "transactions.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    spend = [r for r in rows if r["transaction_type"] in ("purchase", "fee")]
    print(f"wrote {out}")
    print(f"  transactions: {len(rows)}  (consumer spend rows: {len(spend)})")


if __name__ == "__main__":
    main()
