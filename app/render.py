"""Deterministic markdown rendering.

PLAN.MD section 27 says the LLM may explain results but must not calculate them.
That rule only has teeth if the presentation layer is ours: these functions build
the exact table ChatGPT is told to reproduce verbatim, so the figures on screen
are the figures Python computed.
"""

from __future__ import annotations

from app.models.planning import PaymentPlan, WalletRecommendation
from app.money import fmt, fmt_points

VALUATION_FOOTNOTE = (
    "Points and cash back are valued at 1.0 cent per point. Guaranteed value is "
    "money you verifiably do not pay: statement credits, discounts and waived "
    "fees. Reward value is an estimate and is reported separately, never merged "
    "into the guaranteed figure."
)


def _channel_note(option) -> str:
    return "" if option.channel.value == "merchant_direct" else f" ({option.channel_label})"


def payment_plan_markdown(plan: PaymentPlan) -> str:
    lines: list[str] = [
        f"## SmartPay payment plan — {plan.itinerary_title}",
        "",
        f"**Itinerary total:** {fmt(plan.itinerary_total)}",
        "",
        "| Item | Amount | You would normally pay with | SmartPay recommends | Guaranteed | Est. rewards |",
        "|---|---:|---|---|---:|---:|",
    ]

    tied = False
    for r in plan.recommendations:
        marker = ""
        if r.recommended.tiebreak_note:
            marker, tied = " \\*", True
        lines.append(
            f"| {r.item_label} | {fmt(r.amount)} | {r.baseline.instrument_name} "
            f"({r.baseline_probability:.0%} of the time) | "
            f"{r.recommended.instrument_name}{_channel_note(r.recommended)}{marker} | "
            f"{fmt(r.incremental_guaranteed)} | {fmt(r.incremental_estimated)} |"
        )

    if tied:
        lines += [
            "",
            "\\* On this line the options were worth **exactly** the same. SmartPay "
            "prefers the Mastercard when value is identical; no figure in this table "
            "is changed by that preference.",
        ]

    lines += [
        "",
        "### SmartPay incremental value",
        "",
        f"- **Guaranteed savings: {fmt(plan.incremental_guaranteed)}**",
        f"- Estimated additional reward value: {fmt(plan.incremental_estimated)}",
        f"- Additional points earned: {fmt_points(plan.incremental_points)}",
        "",
        "### Where the guaranteed value comes from",
        "",
    ]

    for r in plan.recommendations:
        details: list[str] = []
        for b in r.recommended.benefits:
            if b.value > 0:
                details.append(f"{b.display_name} — {fmt(b.value)}")
        for o in r.recommended.offers:
            details.append(f"{o.label}: {o.merchant_name} — {fmt(o.value)}")
        if details:
            lines.append(f"- **{r.item_label}** — " + "; ".join(details))

    if plan.priceless:
        lines += ["", "### Additional experience value", ""]
        for experience in plan.priceless:
            lines.append(f"- {experience['title']} — {experience['why']}")
        lines.append("")
        lines.append(
            "_Experience value is listed separately and is deliberately excluded "
            "from the savings figures above._"
        )

    if plan.disclaimers:
        lines += ["", "---", ""]
        lines += [f"_{d}_" for d in plan.disclaimers]

    return "\n".join(lines)


def wallet_markdown(rec: WalletRecommendation) -> str:
    lines = [
        "## SmartPay wallet review",
        "",
        f"**{rec.headline}**",
        "",
        f"- Current wallet, projected annual value: {fmt(rec.current_wallet_value)}",
        f"- Recommended wallet, projected annual value: {fmt(rec.recommended_wallet_value)}",
        f"- **Net annual incremental value: {fmt(rec.net_annual_incremental_value)}**",
        "",
        "### What is driving this",
        "",
    ]
    lines += [f"- {d}" for d in rec.drivers]
    lines += [
        "",
        "### Every option considered",
        "",
        "| Change | Projected annual wallet value |",
        "|---|---:|",
    ]
    for c in rec.candidates:
        lines.append(f"| {c.display_name} | {fmt(c.net_annual_value)} |")

    if rec.disclaimers:
        lines += ["", "---", ""]
        lines += [f"_{d}_" for d in rec.disclaimers]
    return "\n".join(lines)


def profile_markdown(customer_id: str, summary: dict) -> str:
    lines = [
        "## Your financial profile",
        "",
        f"- Connected institutions: {summary['institutions']}",
        f"- Accounts: {summary['account_count']}",
        f"- Transactions analysed: {summary['transaction_count']} "
        f"({summary['spend_count']} consumer payments)",
        f"- Period: {summary['period_start']} to {summary['period_end']}",
        "",
        "### Annual spend by category",
        "",
        "| Category | Observed 12-month spend |",
        "|---|---:|",
    ]
    for category, amount in summary["by_category"]:
        lines.append(f"| {category} | {amount} |")
    lines += [
        "",
        "### How you currently pay",
        "",
        "| Category | Most-used card | Share |",
        "|---|---|---:|",
    ]
    for category, card, share in summary["habits"]:
        lines.append(f"| {category} | {card} | {share} |")
    return "\n".join(lines)


def wallet_list_markdown(customer_id: str, cards: list[dict]) -> str:
    lines = [
        "## Your wallet",
        "",
        "| Card | Network | Annual fee | Headline earn |",
        "|---|---|---:|---|",
    ]
    for c in cards:
        lines.append(
            f"| {c['display_name']} | {c['network']} | {c['annual_fee']} | {c['headline']} |"
        )
    return "\n".join(lines)
