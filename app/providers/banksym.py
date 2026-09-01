"""Open Finance provider backed by BankSym.

PLAN.MD section 8 asks that the optimisation engine be insulated from where the
data comes from. This is the proof: the same engines, reading Alex's profile from
two live BankSym bank tenants over an Open Finance API, must produce the same
recommendations as the frozen fixture. A test asserts exactly that.

Two things a real aggregation integration has to do, and this does too:

* **Aggregate across institutions.** Alex banks with Citi and Chase. They are
  separate tenants with separate customer ids, and reassembling one financial
  picture from both is the whole point of Open Finance.

* **Classify raw postings.** An aggregator returns money movements, not meaning.
  Nothing in the payload says "this is a credit card payment, do not count it as
  spend" -- that distinction is SmartPay's to derive, and getting it wrong would
  double-count every dollar Alex repays.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import httpx

from app import config
from app.knowledge import card_products
from app.models.common import Category, PurchaseChannel
from app.models.financial import (
    Account,
    AccountType,
    CardInstance,
    FinancialProfile,
    PaymentInstrument,
    Transaction,
    TransactionType,
)

HANDLES_PATH = config.DATA / "alex" / "banksym_handles.json"

#: Card last-four -> product. In a real linking flow the consumer picks their card
#: product, or the aggregator returns a product identifier; the mask is the stable
#: join key available to us here.
MASK_TO_PRODUCT = {
    "9021": "citi_strata_premier",
    "7745": "citi_double_cash",
    "3160": "citi_aa_platinum_select",
    "5518": "chase_sapphire_preferred",
    "2094": "chase_freedom_unlimited",
}

_ACCOUNT_TYPE = {"checking": AccountType.CHECKING, "creditCard": AccountType.CREDIT_CARD}


class BankSymUnavailable(RuntimeError):
    """Raised when BankSym is not reachable or has not been seeded."""


def classify(description: str, merchant: str, amount: Decimal) -> TransactionType:
    """Derive a transaction type from what an aggregator actually returns.

    Open Finance gives money movements; the meaning is ours to infer. This is the
    integrity boundary from PLAN.MD section 7: a card repayment is money leaving
    checking for money already counted when the purchase posted, so counting it as
    spend would inflate every total SmartPay reports.
    """
    text = (description or "").upper()
    if text.startswith("AUTOPAY"):
        return TransactionType.CARD_PAYMENT
    if "ATM WITHDRAWAL" in text:
        return TransactionType.ATM_WITHDRAWAL
    if amount < 0:
        return TransactionType.INCOME
    if merchant == "card_payment":
        return TransactionType.CARD_PAYMENT
    return TransactionType.PURCHASE


class BankSymProvider:
    """Reads Alex's profile from BankSym over its Open Finance API."""

    def __init__(
        self,
        handles_path: Path | None = None,
        token: str = "smartpay-demo-token",
        timeout: float = 30.0,
    ) -> None:
        self.handles_path = handles_path or HANDLES_PATH
        self.token = token
        self.timeout = timeout

    # -- plumbing ------------------------------------------------------------

    @property
    def handles(self) -> dict:
        if not self.handles_path.exists():
            raise BankSymUnavailable(
                f"{self.handles_path} missing. Start BankSym and run: "
                "python scripts/seed_banksym.py"
            )
        return json.loads(self.handles_path.read_text())

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.handles["base_url"],
            timeout=self.timeout,
            headers={"Authorization": f"Bearer {self.token}"},
        )

    @lru_cache(maxsize=1)  # noqa: B019 - provider is a per-process singleton
    def _fetch(self) -> tuple[list[Account], list[Transaction], list[PaymentInstrument]]:
        handles = self.handles
        products = card_products()
        accounts: list[Account] = []
        transactions: list[Transaction] = []
        instruments: list[PaymentInstrument] = []

        try:
            with self._client() as client:
                for institution, inst in handles["institutions"].items():
                    bank_id, customer_id = inst["bank_id"], inst["customer_id"]
                    base = f"/openfinance/{bank_id}/v1"

                    response = client.get(f"{base}/customers/{customer_id}/accounts")
                    response.raise_for_status()

                    for raw in response.json()["accounts"]:
                        account_id = raw["accountId"]
                        mask = raw["accountNumberMask"]
                        account_type = _ACCOUNT_TYPE.get(
                            raw["accountType"], AccountType.CHECKING
                        )
                        accounts.append(
                            Account(
                                account_id=account_id,
                                institution=institution,
                                display_name=raw["name"],
                                account_type=account_type,
                                mask=mask,
                                current_balance=Decimal(raw["balances"][0]["amount"]),
                            )
                        )

                        if account_type is AccountType.CREDIT_CARD:
                            product_id = MASK_TO_PRODUCT.get(mask)
                            if product_id and product_id in products:
                                product = products[product_id]
                                instruments.append(
                                    PaymentInstrument(
                                        instrument_id=product_id,
                                        display_name=product.display_name,
                                        issuer=product.issuer,
                                        is_card=True,
                                        card=CardInstance(
                                            instrument_id=product_id,
                                            product=product,
                                            account_id=account_id,
                                            mask=mask,
                                            opened_at=date(2022, 1, 1),
                                        ),
                                        account_id=account_id,
                                    )
                                )
                        else:
                            instruments.append(
                                PaymentInstrument(
                                    instrument_id=f"debit_{institution}",
                                    display_name=f"{raw['name']} (debit)",
                                    issuer=institution,
                                    is_card=False,
                                    account_id=account_id,
                                )
                            )

                        txn_response = client.get(f"{base}/accounts/{account_id}/transactions")
                        txn_response.raise_for_status()
                        for row in txn_response.json()["transactions"]:
                            transactions.append(self._to_transaction(account_id, row))
        except httpx.HTTPError as exc:
            raise BankSymUnavailable(
                f"Could not read from BankSym at {handles['base_url']}: {exc}"
            ) from exc

        transactions.sort(key=lambda t: (t.posted_at, t.transaction_id))
        return accounts, transactions, instruments

    @staticmethod
    def _to_transaction(account_id: str, row: dict) -> Transaction:
        # BankSym signs money-out negative; SmartPay signs money-out positive.
        amount = -Decimal(row["amount"])
        merchant = row.get("merchantName") or ""
        description = row.get("description") or ""
        category = row.get("category") or Category.OTHER.value
        channel = row.get("channel") or PurchaseChannel.MERCHANT_DIRECT.value
        return Transaction(
            transaction_id=row["transactionId"],
            account_id=account_id,
            posted_at=date.fromisoformat(row["postedDate"]),
            merchant=merchant,
            description=description,
            amount=amount,
            category=Category(category) if category in Category._value2member_map_ else Category.OTHER,
            transaction_type=classify(description, merchant, amount),
            channel=(
                PurchaseChannel(channel)
                if channel in PurchaseChannel._value2member_map_
                else PurchaseChannel.MERCHANT_DIRECT
            ),
        )

    # -- OpenFinanceProvider -------------------------------------------------

    def get_accounts(self, customer_id: str) -> list[Account]:
        return self._fetch()[0]

    def get_transactions(self, customer_id: str) -> list[Transaction]:
        return self._fetch()[1]

    def get_instruments(self, customer_id: str) -> list[PaymentInstrument]:
        return self._fetch()[2]

    def get_profile(self, customer_id: str) -> FinancialProfile:
        accounts, transactions, instruments = self._fetch()
        return FinancialProfile(
            customer_id=customer_id,
            accounts=accounts,
            transactions=transactions,
            instruments=instruments,
        )
