"""Sourced issuer rewards programs. PLAN.MD section 17.

A companion to the earn engine: real Mastercard issuer rewards programs (see
scripts/import_mastercard_rewards.py) applied as an ADDITIVE, issuer-matched
category bonus. A program only ever augments a card whose issuer actually runs it,
and is never restated as that card's own published base rate -- so it cannot
inflate a card the issuer does not back.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.knowledge import rewards_programs as all_programs
from app.models.common import RewardCurrency
from app.models.financial import PaymentInstrument
from app.models.planning import PurchaseIntent, RewardProgramBonus
from app.models.rules import RewardProgram
from app.money import points_to_usd, quantize
from app import config


class RewardsProgramsEngine:
    def evaluate(
        self,
        purchase: PurchaseIntent,
        instrument: PaymentInstrument,
        on: date | None = None,
    ) -> list[RewardProgramBonus]:
        product = instrument.product
        if product is None:
            return []

        on = on or purchase.purchase_date or date.today()
        candidates: list[tuple[RewardProgram, int, Decimal]] = []
        for program in all_programs():
            if not program.is_active(on):
                continue
            if not program.applies_to(instrument.issuer, purchase.category):
                continue
            points, value = self._bonus(program, purchase.amount)
            if value <= 0 and points <= 0:
                continue
            candidates.append((program, points, value))

        if not candidates:
            return []

        # One issuer bonus per purchase: the catalogue carries near-duplicate rows
        # for the same program, so keep the single most valuable rather than
        # stacking them into a fictitious combined bonus.
        program, points, value = max(candidates, key=lambda c: c[2])
        return [
            RewardProgramBonus(
                program_id=program.program_id,
                issuer_name=program.issuer_name,
                display_name=program.reward_summary,
                points=points,
                estimated_value=value,
                label=program.provenance.label,
                explanation=(
                    f"{program.issuer_name}: {program.reward_summary} "
                    f"(sourced issuer rewards program)"
                ),
                evidence=[program.evidence],
            )
        ]

    @staticmethod
    def _bonus(program: RewardProgram, amount: Decimal) -> tuple[int, Decimal]:
        """The (points, estimated USD value) an issuer program adds on `amount`.

        A cashback program pays a percentage of spend; a points program accrues its
        rate in points per dollar, valued at the configured points valuation.
        """
        if program.reward_currency is RewardCurrency.USD_CASHBACK:
            return 0, quantize(amount * program.rate / 100)
        points = int(amount * program.rate)
        valuation = config.REWARD_VALUATIONS.get(
            program.reward_currency.value, config.REWARD_VALUATIONS["loyalty_points"]
        )
        return points, points_to_usd(points, valuation)
