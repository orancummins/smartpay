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

from app import config
from app.models.financial import (
    Account,
    CardInstance,
    FinancialProfile,
    PaymentInstrument,
    Transaction,
)
from app.knowledge import card_products

_ACCOUNTS = TypeAdapter(list[Account])
_TRANSACTIONS = TypeAdapter(list[Transaction])


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
        return _ACCOUNTS.validate_python(_raw()["accounts"])

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


def default_provider() -> OpenFinanceProvider:
    return SyntheticAlexProvider()
