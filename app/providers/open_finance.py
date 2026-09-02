"""Mastercard Open Finance abstraction. PLAN.MD section 8.

The optimisation engine only ever sees this Protocol, so a real Open Finance Test
Drive provider can be dropped in later without the engines noticing.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from typing import Protocol

from pydantic import TypeAdapter

from decimal import Decimal

from app import config
from app.models.financial import (
    Account,
    CardInstance,
    FinancialProfile,
    PaymentInstrument,
    Transaction,
    TransactionType,
)
from app.knowledge import card_products
from app.money import ZERO, quantize

#: Credit limits are an underwriting outcome for this specific cardholder, not a
#: published product term, so they carry no issuer evidence -- see CardInstance.
#: These are a plausible, one-time assignment for the demo persona, not tuned to
#: produce any particular recommendation.
CREDIT_LIMITS: dict[str, Decimal] = {
    "citi_strata_premier": Decimal("14000"),
    "citi_double_cash": Decimal("9000"),
    "citi_aa_platinum_select": Decimal("10000"),
    "chase_sapphire_preferred": Decimal("16000"),
    "chase_freedom_unlimited": Decimal("11000"),
    "first_hawaiian_priority_destinations": Decimal("12000"),
}

_ACCOUNTS = TypeAdapter(list[Account])
_TRANSACTIONS = TypeAdapter(list[Transaction])


def _derive_balances(
    accounts: list[Account], transactions: list[Transaction], card_account_ids: set[str]
) -> dict[str, Decimal]:
    """Compute each account's current balance from the ledger.

    The frozen fixture stores no balance field at all -- it must be *inferred* from
    the transaction history, which is exactly what a real Open Finance balance
    inference does when an issuer does not expose one directly. A checking account
    nets every posting to it (SmartPay signs money-out positive, so balance is the
    negative of that sum). A card account cannot be netted the same way: a
    card_payment row lives only on the CHECKING side of the ledger (see PLAN.MD
    section 7), so a card's outstanding balance is its own purchases and fees minus
    whatever has been paid against it via counterparty_account_id.
    """
    net: dict[str, Decimal] = {a.account_id: ZERO for a in accounts}
    paid_against: dict[str, Decimal] = {}

    for t in transactions:
        if t.account_id in net:
            net[t.account_id] -= t.amount
        if t.transaction_type is TransactionType.CARD_PAYMENT and t.counterparty_account_id:
            paid_against[t.counterparty_account_id] = (
                paid_against.get(t.counterparty_account_id, ZERO) + t.amount
            )

    balances: dict[str, Decimal] = {}
    for account_id in net:
        if account_id in card_account_ids:
            purchases = sum(
                (t.amount for t in transactions
                 if t.account_id == account_id
                 and t.transaction_type in (TransactionType.PURCHASE, TransactionType.FEE)),
                ZERO,
            )
            balances[account_id] = quantize(purchases - paid_against.get(account_id, ZERO))
        else:
            balances[account_id] = quantize(net[account_id])
    return balances


class OpenFinanceProvider(Protocol):
    def get_accounts(self, customer_id: str) -> list[Account]: ...
    def get_transactions(self, customer_id: str) -> list[Transaction]: ...
    def get_profile(self, customer_id: str) -> FinancialProfile: ...


@lru_cache(maxsize=1)
def _raw() -> dict:
    path = config.DATA / "alex" / "transactions.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing. Run: python scripts/generate_alex.py"
        )
    return json.loads(path.read_text())


class SyntheticAlexProvider:
    """Reads the frozen, committed dataset. No generation at request time."""

    def get_accounts(self, customer_id: str) -> list[Account]:
        accounts = _ACCOUNTS.validate_python(_raw()["accounts"])
        card_account_ids = set(_raw()["card_accounts"])
        transactions = self.get_transactions(customer_id)
        balances = _derive_balances(accounts, transactions, card_account_ids)
        return [
            a.model_copy(update={"current_balance": balances.get(a.account_id, ZERO)})
            for a in accounts
        ]

    def get_transactions(self, customer_id: str) -> list[Transaction]:
        return _TRANSACTIONS.validate_python(_raw()["transactions"])

    def get_instruments(self, customer_id: str) -> list[PaymentInstrument]:
        raw = _raw()
        products = card_products()
        accounts = {a.account_id: a for a in self.get_accounts(customer_id)}
        instruments: list[PaymentInstrument] = []

        for account_id, product_id in raw["card_accounts"].items():
            account = accounts[account_id]
            product = products[product_id]
            card = CardInstance(
                instrument_id=product_id,
                product=product,
                account_id=account_id,
                mask=account.mask,
                opened_at=date(2022, 1, 1),
                credit_limit=CREDIT_LIMITS.get(product_id),
            )
            instruments.append(
                PaymentInstrument(
                    instrument_id=product_id,
                    display_name=product.display_name,
                    issuer=product.issuer,
                    is_card=True,
                    card=card,
                    account_id=account_id,
                )
            )

        for account in accounts.values():
            if account.account_type.value == "checking":
                instruments.append(
                    PaymentInstrument(
                        instrument_id=f"debit_{account.institution}",
                        display_name=f"{account.display_name} (debit)",
                        issuer=account.institution,
                        is_card=False,
                        account_id=account.account_id,
                    )
                )
        return instruments

    def get_profile(self, customer_id: str) -> FinancialProfile:
        return FinancialProfile(
            customer_id=customer_id,
            accounts=self.get_accounts(customer_id),
            transactions=self.get_transactions(customer_id),
            instruments=self.get_instruments(customer_id),
        )


def default_provider(name: str | None = None) -> OpenFinanceProvider:
    """Resolve the configured Open Finance source.

    PLAN.MD section 8 asks that a different provider be pluggable without touching
    the optimisation engine. That only means anything if something actually selects
    one, so this is what the service calls -- switching source is configuration,
    not a code change.
    """
    choice = (name or config.PROVIDER).strip().lower()
    if choice in {"synthetic", "alex", "fixture"}:
        return SyntheticAlexProvider()
    if choice == "banksym":
        from app.providers.banksym import BankSymProvider

        return BankSymProvider()
    raise ValueError(
        f"Unknown SMARTPAY_PROVIDER {choice!r}. Expected 'synthetic' or 'banksym'."
    )
