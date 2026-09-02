"""Open Finance provider backed by BankSym, speaking FDX.

Reads over **FDX** (Financial Data Exchange), the US open banking standard, which
is what the Citi and Chase tenants expose.

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
    "4028": "first_hawaiian_priority_destinations",
    "6671": "chase_marriott_bonvoy_boundless",
}

#: FDX accountType -> SmartPay account type.
_ACCOUNT_TYPE = {
    "CHECKING": AccountType.CHECKING,
    "SAVINGS": AccountType.CHECKING,
    "CREDITCARD": AccountType.CREDIT_CARD,
}

FDX_VERSION = "v6"


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
    # Real issuer statements label a penalty charge exactly this way, so matching
    # the phrase is a real-world signal, not an arbitrary string. Without this a
    # late fee is read back as an ordinary purchase: it would earn rewards in the
    # accumulated-savings comparison (real issuers never pay rewards on fees) and
    # be invisible to the risk engine's late-fee disclosure.
    if "LATE PAYMENT FEE" in text or "RETURNED PAYMENT FEE" in text:
        return TransactionType.FEE
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
                    base = f"/fdx/{bank_id}/{FDX_VERSION}"

                    response = client.get(
                        f"{base}/accounts", params={"customerId": customer_id}
                    )
                    response.raise_for_status()

                    for entry in response.json()["accounts"]:
                        # FDX is polymorphic: exactly one typed account is populated,
                        # and a credit card arrives as a line of credit rather than a
                        # deposit account.
                        raw = entry.get("depositAccount") or entry.get("locAccount")
                        if raw is None:
                            continue
                        is_card = entry.get("locAccount") is not None

                        account_id = raw["accountId"]
                        mask = (raw.get("accountNumberDisplay") or "")[-4:]
                        account_type = _ACCOUNT_TYPE.get(
                            raw.get("accountType", ""), AccountType.CHECKING
                        )
                        balance = Decimal(str(raw.get("currentBalance") or 0))
                        accounts.append(
                            Account(
                                account_id=account_id,
                                institution=institution,
                                display_name=raw.get("productName")
                                or raw.get("nickname")
                                or account_id,
                                account_type=account_type,
                                mask=mask,
                                current_balance=balance,
                            )
                        )

                        if is_card:
                            product_id = MASK_TO_PRODUCT.get(mask)
                            if product_id and product_id in products:
                                product = products[product_id]
                                # A credit limit is retrieved through Open Banking
                                # here, not assumed: FDX exposes availableCredit
                                # directly, so the limit is reconstructed as
                                # available + owed rather than invented separately
                                # from the fixture path's own assignment.
                                credit_limit = None
                                available = raw.get("availableCredit")
                                if available is not None:
                                    credit_limit = Decimal(str(available)) + balance
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
                                            credit_limit=credit_limit,
                                        ),
                                        account_id=account_id,
                                    )
                                )
                        else:
                            instruments.append(
                                PaymentInstrument(
                                    instrument_id=f"debit_{institution}",
                                    display_name=f"{raw.get('productName') or account_id} (debit)",
                                    issuer=institution,
                                    is_card=False,
                                    account_id=account_id,
                                )
                            )

                        txn_response = client.get(f"{base}/accounts/{account_id}/transactions")
                        txn_response.raise_for_status()
                        for row in txn_response.json()["transactions"]:
                            raw_txn = row.get("depositTransaction") or row.get("locTransaction")
                            if raw_txn:
                                transactions.append(
                                    self._to_transaction(account_id, raw_txn)
                                )
        except httpx.HTTPError as exc:
            raise BankSymUnavailable(
                f"Could not read from BankSym at {handles['base_url']}: {exc}"
            ) from exc

        transactions.sort(key=lambda t: (t.posted_at, t.transaction_id))
        return accounts, transactions, instruments

    @staticmethod
    def _to_transaction(account_id: str, row: dict) -> Transaction:
        # FDX always reports a positive amount and carries direction separately in
        # debitCreditMemo. SmartPay signs money-out positive, so DEBIT keeps its
        # sign and CREDIT flips -- reading the amount alone would make every
        # payroll deposit look like spending.
        magnitude = Decimal(str(row.get("amount") or 0))
        amount = magnitude if row.get("debitCreditMemo") == "DEBIT" else -magnitude

        merchant = row.get("payee") or ""
        description = row.get("description") or ""
        category = row.get("category") or Category.OTHER.value
        posted = str(row["postedTimestamp"])[:10]
        return Transaction(
            transaction_id=row["transactionId"],
            account_id=account_id,
            posted_at=date.fromisoformat(posted),
            merchant=merchant,
            description=description,
            amount=amount,
            category=(
                Category(category)
                if category in Category._value2member_map_
                else Category.OTHER
            ),
            transaction_type=classify(description, merchant, amount),
            channel=PurchaseChannel.MERCHANT_DIRECT,
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
