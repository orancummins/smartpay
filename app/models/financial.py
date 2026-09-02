"""Accounts, cards, transactions and the assembled financial profile."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.common import (
    Category,
    Evidence,
    Network,
    NetworkTier,
    PurchaseChannel,
    RewardCurrency,
    summarise_categories,
)
from app.money import ZERO


class AccountType(StrEnum):
    CHECKING = "checking"
    CREDIT_CARD = "credit_card"


class TransactionType(StrEnum):
    """PLAN.MD section 7: the ledger must distinguish real consumer spend from
    money merely moving between Alex's own accounts."""

    PURCHASE = "purchase"
    INCOME = "income"
    CARD_PAYMENT = "card_payment"       # checking -> credit card. NOT consumer spend.
    TRANSFER = "transfer"               # internal. NOT consumer spend.
    ATM_WITHDRAWAL = "atm_withdrawal"   # cash out. Not merchant-level spend.
    FEE = "fee"
    REFUND = "refund"


#: Transaction types that count as consumer spend for behavioural inference.
#: Everything else is excluded, which is what stops double counting.
SPEND_TYPES: frozenset[TransactionType] = frozenset(
    {TransactionType.PURCHASE, TransactionType.FEE}
)


class Account(BaseModel):
    account_id: str
    institution: str                # "citi" | "chase"
    display_name: str
    account_type: AccountType
    mask: str
    current_balance: Decimal = ZERO


class Transaction(BaseModel):
    transaction_id: str
    account_id: str
    posted_at: date
    merchant: str
    description: str
    amount: Decimal                 # positive = money out, negative = money in
    category: Category
    transaction_type: TransactionType = TransactionType.PURCHASE
    channel: PurchaseChannel = PurchaseChannel.MERCHANT_DIRECT
    #: For CARD_PAYMENT rows, the credit-card account being paid. Lets the validator
    #: prove every payment reconciles to a real card.
    counterparty_account_id: str | None = None

    @property
    def is_consumer_spend(self) -> bool:
        return self.transaction_type in SPEND_TYPES


class RewardRule(BaseModel):
    """A single earn rule on a card product. PLAN.MD section 17."""

    rule_id: str
    categories: list[Category] = Field(default_factory=list)
    merchants: list[str] = Field(default_factory=list)
    multiplier: Decimal = Decimal("1")
    reward_currency: RewardCurrency = RewardCurrency.USD_CASHBACK
    #: When set, the rule only fires for these channels. This is the section 15
    #: mechanic: a 10x portal rate must never apply to a direct merchant booking.
    required_channels: list[PurchaseChannel] = Field(default_factory=list)
    #: Annual spend cap on the bonus rate, in dollars. None = uncapped.
    annual_cap: Decimal | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    description: str = ""
    evidence: Evidence

    def channel_qualifies(self, channel: PurchaseChannel) -> bool:
        return not self.required_channels or channel in self.required_channels

    @property
    def category_summary(self) -> str:
        """A short phrase for what this rule rewards, e.g. "travel", "dining".

        Merchant-scoped rules with no category fall back to naming select merchants.
        """
        return summarise_categories(self.categories) or (
            "select merchants" if self.merchants else "everyday spend"
        )

    def matches(self, category: Category, merchant_key: str, channel: PurchaseChannel) -> bool:
        if not self.channel_qualifies(channel):
            return False
        if self.merchants and merchant_key in self.merchants:
            return True
        if self.categories and category in self.categories:
            return True
        return False


class CardProduct(BaseModel):
    """Product-level economics, loaded from data/cards/*.yaml."""

    product_id: str
    display_name: str
    issuer: str
    network: Network
    network_tier: NetworkTier = NetworkTier.NONE
    annual_fee: Decimal = ZERO
    annual_fee_waived_first_year: bool = False
    foreign_transaction_fee_pct: Decimal = ZERO
    base_currency: RewardCurrency = RewardCurrency.USD_CASHBACK
    base_multiplier: Decimal = Decimal("1")
    reward_rules: list[RewardRule] = Field(default_factory=list)
    #: Free-text perks we can name but deliberately do not price.
    soft_benefits: list[str] = Field(default_factory=list)
    #: Published penalty fee for a missed minimum payment. Evidence-backed like
    #: every other rule here -- verified against a live issuer pricing disclosure,
    #: not assumed. Used to make the cost of a late payment concrete rather than a
    #: vague warning, and to size the guaranteed value of actually avoiding one.
    #: Its own Evidence, separate from the product's, because the two claims come
    #: from different pages (a product page states the rewards; the penalty fee
    #: comes from the issuer's pricing/terms disclosure).
    late_payment_fee: Decimal = ZERO
    late_payment_fee_evidence: Evidence | None = None
    evidence: Evidence

    @property
    def is_mastercard(self) -> bool:
        return self.network is Network.MASTERCARD


class CardInstance(BaseModel):
    """A specific card in Alex's wallet."""

    instrument_id: str
    product: CardProduct
    account_id: str
    mask: str
    opened_at: date
    #: The cardholder's credit line. Unlike reward rates or fees, a credit limit is
    #: an underwriting outcome for this specific account, not a published product
    #: term -- so it carries no issuer evidence and lives on the instance, sourced
    #: from Open Finance (retrieved from BankSym/FDX, or inferred from the ledger
    #: for the frozen fixture) rather than the curated knowledge base.
    credit_limit: Decimal | None = None

    @property
    def display_name(self) -> str:
        return self.product.display_name


class PaymentInstrument(BaseModel):
    """The optimiser's unit of choice: a card, or a debit account.

    PLAN.MD section 13 lists only CardInstance, but section 16 evaluates debit and
    bank rails alongside cards, so they need one shared shape to be ranked together.
    """

    instrument_id: str
    display_name: str
    issuer: str
    is_card: bool
    card: CardInstance | None = None
    account_id: str | None = None

    @property
    def product(self) -> CardProduct | None:
        return self.card.product if self.card else None

    @property
    def is_mastercard(self) -> bool:
        return bool(self.card and self.card.product.is_mastercard)


class FinancialProfile(BaseModel):
    """Everything SmartPay knows about the consumer, from Open Finance."""

    customer_id: str
    accounts: list[Account]
    transactions: list[Transaction]
    instruments: list[PaymentInstrument]

    @property
    def spend_transactions(self) -> list[Transaction]:
        return [t for t in self.transactions if t.is_consumer_spend]

    def instrument(self, instrument_id: str) -> PaymentInstrument | None:
        return next((i for i in self.instruments if i.instrument_id == instrument_id), None)
