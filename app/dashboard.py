"""Server-rendered SmartPay dashboard.

Organised as a presentation surface, not a data viewer:

  1. Name and headline savings figures (the header).
  2. Recent ChatGPT activity -- the distinct enquiries and their potential savings.
  3. Discounts and Priceless offers, framed as tied to recent ChatGPT research.
  4. "What could you have saved?" -- the retrospective slider.
  5. Everything Open Finance has shared -- institutions, accounts and transactions.
  6. Your card benefits, rewards, offers and terms.
  7. "And one more thing..." -- the wallet recommendation, always last.

Charts are inline SVG with direct labels. Colours come from the validated
categorical palette, which fails the 3:1 contrast check for three light-mode
slots -- hence labels on every bar rather than a legend-only chart.
"""

from __future__ import annotations

import base64
import html
import json
import mimetypes
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache

from app import config
from app.knowledge import benefits
from app.models.common import RewardCurrency
from app.models.financial import Account, FinancialProfile, PaymentInstrument
from app.money import fmt
from app.render import upside_sentence

CARD_ART = {
    "citi_strata_premier": "/static/cards/citi_strata_premier.webp",
    "citi_double_cash": "/static/cards/citi_double_cash.webp",
    "citi_aa_platinum_select": "/static/cards/citi_aa_platinum_select.webp",
    "chase_sapphire_preferred": "/static/cards/chase_sapphire_preferred.png",
    "chase_freedom_unlimited": "/static/cards/chase_freedom_unlimited.png",
    "first_hawaiian_priority_destinations": "/static/cards/first_hawaiian_priority_destinations.webp",
}

#: How a real historical purchase could be optimised, by mechanism -- so the
#: annotated history reads "this was a Benefit" / "this was an Offer" /
#: "this was a Reward" at a glance, not just an unlabelled pill. Colour reuses
#: the existing chart series tokens (already theme-aware) rather than
#: inventing new ones; the icon repeats the same distinction for anyone
#: relying on shape, not colour, to tell them apart.
_OPT_TYPE = {
    "benefit": (
        "Benefit", "series-1",
        '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" aria-hidden="true">'
        '<path d="M8 1.4 13 3.3v4.2c0 3.4-2.2 5.9-5 6.9-2.8-1-5-3.5-5-6.9V3.3L8 1.4Z" '
        'stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>'
        '<path d="M5.6 8.1 7.2 9.7l3.2-3.4" stroke="currentColor" stroke-width="1.3" '
        'stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>',
    ),
    "offer": (
        "Offer", "series-2",
        '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" aria-hidden="true">'
        '<path d="M2 3.6c0-.9.7-1.6 1.6-1.6h4.2c.4 0 .8.2 1.1.5l5 5c.6.6.6 1.6 0 2.2l-4.2 4.2 '
        'c-.6.6-1.6.6-2.2 0l-5-5A1.6 1.6 0 0 1 2 7.8V3.6Z" stroke="currentColor" '
        'stroke-width="1.3" stroke-linejoin="round"/><circle cx="5.3" cy="5.3" r=".9" '
        'fill="currentColor"/></svg>',
    ),
    "reward": (
        "Reward", "series-4",
        '<svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor" aria-hidden="true">'
        '<path d="M8 1.3 9.7 5.5l4.5.4-3.4 2.9 1 4.4L8 11l-3.8 2.2 1-4.4-3.4-2.9 4.5-.4Z"/></svg>',
    ),
}

#: AI assistants SmartPay connects to. A monogram badge, not a sourced logo
#: mark, the same convention app.admin_dashboard already uses for this exact
#: row of names -- avoids the trademark-sourcing question entirely while
#: staying instantly readable. Every real enquiry recorded so far came
#: through ChatGPT (the one live MCP integration this demo has); the other
#: three are shown at the section level as "SmartPay works from here too",
#: never attributed to a specific enquiry that did not happen there.
_AI_PLATFORM = {
    "chatgpt": ("ChatGPT", "C", "#111111"),
    "gemini": ("Gemini", "G", "linear-gradient(135deg,#4285f4,#a142f4)"),
    "grok": ("Grok", "X", "#050505"),
    "claude": ("Claude", "A", "#c96846"),
}


def _ai_badge(platform: str, *, small: bool = False) -> str:
    name, letter, bg = _AI_PLATFORM[platform]
    cls = "ai-chip" + (" small" if small else "")
    return (
        f'<span class="{cls}"><i style="background:{bg}">{_t(letter)}</i>{_t(name)}</span>'
    )


@lru_cache(maxsize=None)
def _card_art_uri(product_id: str) -> str:
    """Card art inlined as a data URI so it renders without a mounted /static route
    (e.g. in a standalone preview), the same way the ChatGPT widget ships its art."""
    rel = CARD_ART.get(product_id, "")
    if not rel:
        return ""
    path = config.ROOT / "app" / "static" / rel.removeprefix("/static/")
    if not path.exists():
        return ""
    mime = mimetypes.guess_type(path.name)[0] or "image/webp"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _rate(value: Decimal) -> str:
    """A multiplier as a plain number: 10, not Decimal's 1E+1; 0.5, not 0.50."""
    return f"{value.normalize():f}"

#: First Hawaiian has no vendored SVG mark; a compact inline monogram stands in so
#: its accounts card carries a logo like Citi and Chase do.
_FHB_LOGO = "data:image/svg+xml;base64," + base64.b64encode(
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 66 40">'
    b'<rect width="66" height="40" rx="7" fill="#0f4c4a"/>'
    b'<text x="33" y="27" font-family="Georgia,serif" font-size="18" font-weight="700"'
    b' fill="#ffffff" text-anchor="middle">FHB</text></svg>'
).decode()

ISSUER_LOGO = {
    "citi": "/static/logos/citi.svg",
    "chase": "/static/logos/chase.svg",
    "first hawaiian": _FHB_LOGO,
}
ISSUER_NAME = {"citi": "Citi", "chase": "Chase", "first hawaiian": "First Hawaiian"}

#: Validated categorical palette (see the dataviz reference). Adjacent-pair safe in
#: both modes; three light slots sit under 3:1, so every bar carries a direct label.
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500",
               "#d55181", "#008300", "#9085e9", "#e66767"]

CATEGORY_LABEL = {
    "restaurant": "Dining", "supermarket": "Groceries", "grocery_online": "Online grocery",
    "airfare": "Flights", "hotel": "Hotels", "attraction": "Attractions",
    "car_rental": "Car rental", "rideshare": "Rideshare", "transport": "Transport",
    "gas": "Fuel", "shopping": "Shopping", "drugstore": "Pharmacy",
    "entertainment": "Entertainment", "streaming": "Streaming", "golf": "Golf",
    "utilities": "Utilities", "housing": "Housing", "other": "Other",
}

ACCOUNT_TYPE_LABEL = {"checking": "Checking", "credit_card": "Credit card"}

TXN_TYPE_LABEL = {
    "purchase": "Purchase", "fee": "Fee", "card_payment": "Card payment",
    "atm_withdrawal": "ATM withdrawal", "income": "Income",
}

#: The Open Finance domain model carries a customer_id, not a human name -- this is
#: presentation-layer knowledge for the one demo persona, matching the name already
#: used in scripts/seed_banksym.py and the page <title>.
DEMO_CUSTOMER_NAME = "Alex Morgan"


def _t(value: object) -> str:
    return html.escape(str(value))


def _label(value: object) -> str:
    key = str(value)
    return _t(CATEGORY_LABEL.get(key, key.replace("_", " ").title()))


def _money(value: Decimal | str) -> str:
    return _t(fmt(Decimal(str(value))))


def _ago(stamp: object) -> str:
    """Coarse relative time. Minutes matter during a demo; seconds are noise."""
    try:
        then = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return "just now"
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    seconds = int((datetime.now(UTC) - then).total_seconds())
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    days = seconds // 86400
    return f"{days} day{'s' if days > 1 else ''} ago"


def _card_benefits(instrument: PaymentInstrument) -> list:
    product = instrument.product
    if product is None:
        return []
    return [
        b for b in benefits()
        if (b.eligible_products and product.product_id in b.eligible_products)
        or (b.network_tiers and product.network_tier in b.network_tiers)
    ]


# ---------------------------------------------------------------------------
# Charts. Inline SVG so the page stays self-contained and works offline.
# ---------------------------------------------------------------------------

def _truncate(text: str, budget: int) -> str:
    """Clip a label to a character budget.

    SVG has no text-overflow, so long labels have to be cut in the renderer or they
    run under the bars -- which is exactly what they did before this existed.
    """
    text = str(text)
    return text if len(text) <= budget else text[: budget - 1].rstrip() + "…"


def _bar_chart(
    rows: list[tuple[str, Decimal]], *, label_w: int = 150, budget: int = 22
) -> str:
    """Horizontal bars, sorted by magnitude, one direct label per bar.

    Horizontal because the labels are words of uneven length -- rotating them under
    a vertical axis would make the chart harder to read, not denser.

    The value sits inside its bar when the bar is long enough to hold it, and
    outside when it is not. A fixed outside position collides with the next label
    on long bars and with the axis on short ones.
    """
    if not rows:
        return ""
    peak = max(v for _, v in rows) or Decimal(1)
    bar_h, gap, width_total = 34, 13, 660
    plot_w = width_total - label_w - 8
    height = len(rows) * (bar_h + gap)
    out = [
        f'<svg class="chart" viewBox="0 0 {width_total} {height}" role="img" '
        f'aria-label="Values by category" preserveAspectRatio="xMinYMin meet">'
    ]
    for i, (name, value) in enumerate(rows):
        y = i * (bar_h + gap)
        w = max(float(value) / float(peak) * plot_w, 4)
        amount = fmt(value)
        # ~7.6px per character at 14px; keep the value inside only with room to spare.
        inside = w > len(amount) * 7.6 + 22
        vx = label_w + w - 10 if inside else label_w + w + 9
        out.append(
            f'<g class="bar-row" tabindex="0" role="listitem" '
            f'aria-label="{_t(name)}: {_t(amount)}">'
            f"<title>{_t(name)} — {_t(amount)}</title>"
            f'<text class="bar-label" x="0" y="{y + bar_h / 2 + 5}">'
            f"{_t(_truncate(name, budget))}</text>"
            f'<rect class="bar-track" x="{label_w}" y="{y}" width="{plot_w}" '
            f'height="{bar_h}" rx="7"/>'
            f'<rect class="bar" x="{label_w}" y="{y}" width="{w:.1f}" '
            f'height="{bar_h}" rx="7" fill="var(--series-{i % 8 + 1})"/>'
            f'<text class="bar-value{" inside" if inside else ""}" x="{vx:.1f}" '
            f'y="{y + bar_h / 2 + 5}"{" text-anchor=\"end\"" if inside else ""}>'
            f"{_t(amount)}</text>"
            f"</g>"
        )
    out.append("</svg>")
    return "".join(out)


def _gain_bar(gain: Decimal, peak: Decimal) -> str:
    """This line's share of the total value found.

    A single mark, not a two-bar comparison: the per-item baseline value is not in
    the plan payload, so a second bar would have had nothing real to plot.
    """
    w = max(float(gain) / (float(peak) or 1.0) * 200, 2) if gain > 0 else 0
    if w == 0:
        return '<svg class="delta" viewBox="0 0 210 12" aria-hidden="true"></svg>'
    return (
        f'<svg class="delta" viewBox="0 0 210 12" role="img" '
        f'aria-label="Value found on this item: {_t(fmt(gain))}">'
        f'<rect class="d-track" x="0" y="2" width="200" height="8" rx="4"/>'
        f'<rect class="d-opt" x="0" y="2" width="{w:.1f}" height="8" rx="4"/>'
        f"</svg>"
    )


def _ring(pct: float, label: str) -> str:
    """A single-value ring. One number, so no legend and no colour coding."""
    r, c = 26, 2 * 3.14159 * 26
    filled = max(0.0, min(1.0, pct)) * c
    return (
        f'<svg class="ring" viewBox="0 0 64 64" role="img" aria-label="{_t(label)}">'
        f'<circle cx="32" cy="32" r="{r}" class="ring-track"/>'
        f'<circle cx="32" cy="32" r="{r}" class="ring-fill" '
        f'stroke-dasharray="{filled:.1f} {c - filled:.1f}" transform="rotate(-90 32 32)"/>'
        f'<text x="32" y="37" class="ring-text">{int(round(pct * 100))}%</text>'
        f"</svg>"
    )


# ---------------------------------------------------------------------------
# Section 1 -- header: name, potential savings over last year, further potential savings
# ---------------------------------------------------------------------------

def _header(full_name: str, accumulated: dict, wallet_annual: Decimal) -> str:
    return f"""
    <section class="hero" aria-labelledby="hero-h">
      <p class="eyebrow">SmartPay · Open Finance profile</p>
      <h1 id="hero-h" class="name">{_t(full_name)}</h1>
      <div class="hero-stats">
        <div class="stat accent">
          <dt>Potential savings over last year</dt>
          <dd class="figure" data-count="{accumulated['guaranteed']}">
            {_money(accumulated['guaranteed'])}</dd>
          <p>Guaranteed value SmartPay's rules have identified across the last 12
             months of payments Mastercard has already seen for
             {_t(accumulated['transaction_count'])} transactions.</p>
        </div>
        <div class="stat accent2">
          <dt>Recurring wallet opportunity</dt>
          <dd class="figure" data-count="{wallet_annual}">{_money(wallet_annual)}</dd>
          <p>Identified from reviewing your current cards against your predicted
             spend — see the wallet advice below.</p>
        </div>
      </div>
    </section>"""


# ---------------------------------------------------------------------------
# Flipper offers -- a large, general Mastercard-funded cash back campaign,
# never tied to any one transaction or merchant. See app.engines.flipper_offers
# for the "n purchases to $y spend" progress rule this renders, and
# app/admin_dashboard.py's Flipper campaign studio for where one is configured.
# ---------------------------------------------------------------------------

def _flipper_section(offer_list: list[dict]) -> str:
    if not offer_list:
        return ""
    heroes = []
    for i, o in enumerate(offer_list):
        txn_pct = min(
            100, round(o["progress_transaction_count"] / o["required_transaction_count"] * 100)
        )
        spend_pct = min(
            100,
            round(Decimal(o["progress_spend_amount"]) / Decimal(o["required_spend_amount"]) * 100),
        )
        # The card art itself is the progress indicator: washed-out grey at zero
        # usage, resolving into its real colour as the cardholder actually uses
        # it -- "evolving" toward the reward rather than a static picture next
        # to a number. Driven by the lower of the two requirements so the art
        # never looks "nearly there" while one threshold is still barely started.
        progress = min(txn_pct, spend_pct) / 100
        status = "Ready to redeem" if o["complete"] else "In progress"
        pulsing = not o["complete"]
        classes = "flipper-hero" + (" complete" if o["complete"] else "") + (
            " pulsing" if pulsing else ""
        )
        headline_html = (
            f'<p class="flipper-headline">{_t(o["headline"])}</p>' if o.get("headline") else ""
        )
        art = CARD_ART.get(o.get("card_product_id", ""), "")
        art_html = (
            f'<img class="flipper-hero-art" src="{_t(art)}" alt="{_t(o["card"])}" loading="lazy">'
            if art else f'<div class="flipper-hero-art placeholder">{_t(o["card"])}</div>'
        )
        heroes.append(f"""
        <section class="{classes}" aria-labelledby="flipper-h-{i}" style="--progress:{progress:.3f}">
          <div class="flipper-hero-glow" aria-hidden="true"></div>
          <div class="flipper-hero-copy">
            <span class="flipper-status">{_t(status)}</span>
            {headline_html}
            <div class="flipper-badge"><b>{_money(Decimal(o['cashback_value']))}</b><small>CASH BACK</small></div>
            <h3 id="flipper-h-{i}">{_t(o['display_name'])} — {_t(o['card'])}</h3>
            <div class="flipper-progress">
              <div class="flipper-progress-row">
                <span>{_t(o['progress_transaction_count'])} of {_t(o['required_transaction_count'])} purchases</span>
                <div class="flipper-track"><i style="width:{txn_pct}%"></i></div>
              </div>
              <div class="flipper-progress-row">
                <span>{_money(o['progress_spend_amount'])} of {_money(o['required_spend_amount'])} spent</span>
                <div class="flipper-track"><i style="width:{spend_pct}%"></i></div>
              </div>
            </div>
            <p class="flipper-meta">{_t(o['why'])}</p>
          </div>
          <div class="flipper-hero-card">{art_html}</div>
        </section>""")

    return "".join(heroes)


# ---------------------------------------------------------------------------
# Priceless -- real Mastercard Priceless catalogue offers, matched to what
# Alex's real spend history already supports. See app.engines.priceless for
# the matching/ranking rules and app.priceless_images for where the photos
# come from.
# ---------------------------------------------------------------------------

def _priceless_card(offer: dict) -> str:
    # Defensive .get() throughout: an enquiry recorded before this richer
    # shape existed only ever carried {experience_id, title, why}, and old
    # history entries on disk must still render, not crash the page.
    category = offer.get("category") or "Experience"
    price = (
        f"From {_money(offer['price_amount'])}" if offer.get("price_amount") else "Priceless"
    )
    if offer.get("image_url"):
        visual = f'<div class="priceless-img" style="background-image:url(\'{_t(offer["image_url"])}\')"></div>'
    else:
        # No verified photo for this one -- a plain category plate, never a
        # fabricated or mismatched image standing in for a real place.
        visual = f'<div class="priceless-img placeholder"><span>{_t(category)}</span></div>'
    city_line = f" · {_t(offer['city'])}" if offer.get("city") else ""
    return f"""
    <article class="priceless-card">
      {visual}
      <div class="priceless-body">
        <span class="priceless-cat">{_t(category)}{city_line}</span>
        <h4>{_t(offer.get('title', 'Priceless experience'))}</h4>
        <p class="priceless-why">{_t(offer.get('why', ''))}</p>
        <div class="priceless-foot">
          <span class="priceless-price">{price}</span>
          {f'<a href="{_t(offer["source_url"])}" target="_blank" rel="noopener noreferrer">Priceless.com</a>' if offer.get('source_url') else ''}
        </div>
      </div>
    </article>"""


def _priceless_section(offers: list[dict]) -> str:
    if not offers:
        return ""
    cards = "".join(_priceless_card(o) for o in offers)
    return f"""
    <section class="panel expandable priceless-panel" aria-labelledby="priceless-h">
      <button class="expand-toggle" id="priceless-toggle" type="button" aria-expanded="false"
              aria-controls="priceless-body">
        <div class="expand-toggle-text">
          <h2 id="priceless-h">Priceless offers for you</h2>
          <p>Real Mastercard Priceless experiences, matched to what you've recently
             researched through ChatGPT and your own spending.</p>
        </div>
        <span class="expand-figure small">{_t(len(offers))} matched</span>
        <svg class="chevron" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M5 7l5 6 5-6" fill="none" stroke="currentColor" stroke-width="2.2"
                stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      <div class="expand-body" id="priceless-body" hidden>
        <div class="priceless-strip">{cards}</div>
      </div>
    </section>"""


# ---------------------------------------------------------------------------
# Timeline slider -- "what could you have saved?" past on the left, a mocked
# Mastercard CommerceGPT forecast on the right, "today" in the middle. Rows carry
# their own data-* window info so the client math reads straight from the DOM.
# ---------------------------------------------------------------------------

def _retrospective_section(history: dict, accumulated: dict, projected: dict) -> str:
    past_months = history["months"]
    future_months = projected["months"]
    n_past = len(past_months) or 1
    n_future = len(future_months) or 1
    fee_total = sum((Decimal(f["amount"]) for f in history["fee_avoidable"]), Decimal(0))

    def past_mi(month: str) -> int:
        # -1 = most recent past month, -n_past = oldest.
        return past_months.index(month) - len(past_months) if month in past_months else -n_past

    def future_mi(month: str) -> int:
        # +1 = next month, +n_future = furthest projected.
        return future_months.index(month) + 1 if month in future_months else n_future

    past_txns = sorted(history["transactions"], key=lambda t: t["date"], reverse=True)
    future_txns = sorted(projected["transactions"], key=lambda t: t["date"])

    def _mc_item(kind: str, detail: str) -> str:
        label, series, icon = _OPT_TYPE[kind]
        return f"""
          <li class="rt-mc-item {kind}" style="--type-color:var(--{series})">
            <span class="rt-mc-icon">{icon}</span>
            <span class="rt-mc-text"><b>{_t(label)}</b> {detail}</span>
          </li>"""

    def _mc_chips(t: dict) -> str:
        """What actually fired on the Mastercard Alex actually used here --
        typed and coloured so it is clear at a glance whether this was a
        network Benefit, a card-linked Offer, or an issuer Reward program,
        with the specific detail behind each spelled out."""
        if not t.get("actual_is_mastercard"):
            return ""
        items = (
            [_mc_item("benefit", f'{_t(b["label"])} — {_money(b["value"])}')
             for b in t.get("actual_benefits", [])]
            + [_mc_item("offer", f'{_t(o["merchant"])} card-linked offer — {_money(o["value"])}')
               for o in t.get("actual_offers", [])]
            + [_mc_item(
                   "reward",
                   f'{_t(rp["program"])} ({_t(rp["issuer"].title())}) — '
                   f'+{int(rp["points"]):,} pts (~{_money(rp["value"])})',
               ) for rp in t.get("actual_reward_programs", [])]
        )
        if not items:
            return ""
        return f'<ul class="rt-mc">{"".join(items)}</ul>'

    def _data_attrs(t: dict, side: str, mi: int) -> str:
        return (
            f'data-side="{side}" data-mi="{mi}" data-kind="{_t(t["kind"])}" '
            f'data-guaranteed="{t["guaranteed_delta"]}" '
            f'data-avoidable="{t.get("avoidable_amount", "0.00")}" '
            f'data-improved="{"1" if t["improved"] else "0"}" '
            f'data-habit="{_t(t["habit_label"] or "")}" data-category="{_t(t["category"])}"'
        )

    def _row(t: dict, mi: int) -> str:
        is_fee = t["kind"] == "fee"
        flagged = is_fee or t["improved"]
        display_amount = t["avoidable_amount"] if is_fee else t["guaranteed_delta"]
        category_label = "Late fee" if is_fee else _label(t["category"])
        change_line = (
            f'<span class="rt-change">{_t(t["habit_label"])}</span>' if t["habit_label"] else ""
        )
        mc_chips = _mc_chips(t)
        classes = (
            "retro-txn" + (" fee" if is_fee else "") + (" improved" if flagged else "")
            + (" mc-lit" if mc_chips else "")
        )
        return f"""
      <li class="{classes}" {_data_attrs(t, "past", mi)}>
        <span class="rt-date">{_t(t['date'][5:])}</span>
        <span class="rt-merchant">{_t(t['description'].title())}</span>
        <span class="rt-category">{category_label}</span>
        <span class="rt-card">{_t(t['actual_card'])}</span>
        <span class="rt-delta">{_money(display_amount) if flagged else '—'}{' avoidable' if is_fee else ''}</span>
        {change_line}
        {mc_chips}
      </li>"""

    def _future_row(t: dict, mi: int) -> str:
        change_line = (
            f'<span class="rt-change">{_t(t["habit_label"])}</span>' if t["habit_label"] else ""
        )
        classes = "retro-txn projected" + (" improved" if t["improved"] else "")
        return f"""
      <li class="{classes}" {_data_attrs(t, "future", mi)}>
        <span class="rt-date">{_t(t['date'][:7])}</span>
        <span class="rt-merchant">{_t(t['description'].title())}</span>
        <span class="rt-category">{_label(t['category'])}</span>
        <span class="rt-card">{_t(t['best_card'])}</span>
        <span class="rt-delta">{_money(t['guaranteed_delta']) if t['improved'] else '—'}</span>
        {change_line}
      </li>"""

    past_rows = "".join(_row(t, past_mi(t["month"])) for t in past_txns)
    future_rows = "".join(_future_row(t, future_mi(t["month"])) for t in future_txns)

    # Only window sizes travel as JSON now; every per-row number lives on the row
    # itself as data-*, so the slider math reads straight from the DOM.
    payload = json.dumps({"past_months": n_past, "future_months": n_future})

    fee_note = (
        f'''<small class="retro-fee-total" id="retro-fee-total-wrap">
           + <span id="retro-fee-total">{_money(fee_total)}</span> in late fees you could
           have avoided with autopay</small>''' if history["fee_avoidable"] else ''
    )

    return f"""
    <section class="panel expandable retro" aria-labelledby="retro-h">
      <button class="expand-toggle" id="retro-toggle" type="button" aria-expanded="false"
              aria-controls="retro-body">
        <div class="expand-toggle-text">
          <h2 id="retro-h">What could you have saved?</h2>
          <p>We've modelled how you could have benefited, or how you can benefit
             into the future — rewind through your history on the left, or let
             Mastercard CommerceGPT project the next {_t(n_future)} months on the right.</p>
        </div>
        <span class="expand-figure">{_money(accumulated['guaranteed'])}</span>
        <svg class="chevron" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M5 7l5 6 5-6" fill="none" stroke="currentColor" stroke-width="2.2"
                stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      <div class="expand-body" id="retro-body" hidden>
        <noscript><p class="sub-lede">Enable JavaScript to use the timeline slider.</p></noscript>

        <div class="timeline" id="timeline">
          <div class="timeline-head">
            <span class="tl-end past">{_t(n_past)} months of history</span>
            <span class="tl-now">Today</span>
            <span class="tl-end future">CommerceGPT · next {_t(n_future)} months</span>
          </div>
          <input type="range" min="-{_t(n_past)}" max="{_t(n_future)}" value="0" step="1"
                 id="retro-slider" class="retro-slider timeline-slider"
                 aria-label="Scrub between spending history and CommerceGPT forecast">
          <div class="ai-predict" id="ai-predict" aria-hidden="true">
            <span class="ai-orb"></span>
            <span class="ai-predict-text">Mastercard CommerceGPT is predicting your next
              {_t(n_future)} months…</span>
          </div>
        </div>

        <div class="tl-figures">
          <div class="tl-fig past" id="lookback-fig">
            <span class="tl-fig-tag">Looking back</span>
            <span class="figure" id="retro-total">{_money(accumulated['guaranteed'])}</span>
            <small>guaranteed you could have saved, across
               <span id="retro-txn-count">0</span> transactions{fee_note}</small>
          </div>
          <div class="tl-fig future" id="forecast-fig">
            <span class="tl-fig-tag"><span class="ai-badge">CommerceGPT</span> forecast
              <span class="ai-mock">mocked</span></span>
            <span class="figure" id="forecast-total">$0</span>
            <small>projected uplift over the next <span id="forecast-months">{_t(n_future)}</span>
               months on <span id="forecast-spend">{_money(projected['projected_spend'])}</span>
               of predicted spend if you pay smarter</small>
          </div>
        </div>

        <div class="retro-grid">
          <div class="retro-habits" id="retro-summary">
            <h3 class="sub-h" style="margin-top:0">Spending habits that would need to change</h3>
            <ul class="habit-list" id="habit-list"></ul>
          </div>
          <div class="retro-tables">
            <div class="retro-table-block" id="forecast-table" data-side="future">
              <h3 class="sub-h" style="margin-top:0">CommerceGPT forecast — your projected spend
                <span class="ai-mock">simulation</span></h3>
              <p class="sub-lede">Your recent habits replayed forward and scored the same way
                 SmartPay scores the past — a deterministic mock, not a live prediction.</p>
              <ul class="retro-txn-list future-list" id="future-txn-list">{future_rows}</ul>
            </div>
            <div class="retro-table-block" id="history-table" data-side="past" hidden>
              <h3 class="sub-h" style="margin-top:0">Your spending history</h3>
              <p class="sub-lede">Every scored purchase and late fee. Highlighted rows spell out
                 the specific change and what it would have been worth.</p>
              <ul class="retro-txn-list" id="retro-txn-list">{past_rows}</ul>
            </div>
          </div>
        </div>
      </div>
    </section>
    <script type="application/json" id="retro-data">{payload}</script>"""


# ---------------------------------------------------------------------------
# Section 2 -- potential future savings identified
# ---------------------------------------------------------------------------

def _plan_rows(plan: dict) -> tuple[str, Decimal]:
    recs = plan["recommendations"]
    peak = max(
        [Decimal(r["guaranteed_savings"]) + Decimal(r["estimated_reward_value_delta"])
         for r in recs] + [Decimal(1)]
    )
    rows = []
    for r in recs:
        guaranteed = Decimal(r["guaranteed_savings"])
        estimated = Decimal(r["estimated_reward_value_delta"])
        gained = guaranteed + estimated
        channel = r["recommended_channel"]
        channel_tag = (
            f'<span class="chip portal">{_t(channel)}</span>'
            if channel != "booked direct" else ""
        )
        note = (
            f'<span class="chip tie" title="{_t(r["tiebreak_note"])}">'
            "tie · +5% Mastercard credit</span>" if r["tiebreak_note"] else ""
        )
        why = "".join(
            f'<li>{_t(b)}</li>' for b in r["benefits"]
        ) + "".join(
            f'<li>{_t(o["label"])}: {_t(o["merchant"])} — {_money(o["value"])}</li>' for o in r["offers"]
        ) + "".join(
            f'<li>{_t(rp["program"])} ({_t(rp["issuer"].title())}) — '
            f'+{int(rp["points"]):,} pts (~{_money(rp["value"])})</li>'
            for rp in r.get("reward_programs", [])
        )
        risk_items = [
            note for note in (r.get("late_fee_warning"), r.get("payoff_recommendation")) if note
        ]
        risk_notes = "".join(f'<li>{_t(note)}</li>' for note in risk_items)
        upside = upside_sentence(
            r["recommended_payment"], r["baseline_payment"], guaranteed, estimated,
            r["tiebreak_note"],
        )
        rows.append(f"""
        <article class="plan-row{' has-gain' if gained > 0 else ''}">
          <div class="plan-item">
            <h3>{_t(r["item"])}</h3>
            <span class="amount">{_money(r["amount"])}</span>
          </div>
          <div class="plan-swap">
            <div class="from">
              <span class="tag">You would use</span>
              <strong>{_t(r["baseline_payment"])}</strong>
              <span class="prob">{_t(r["baseline_probability"])} of the time</span>
            </div>
            <div class="arrow" aria-hidden="true">→</div>
            <div class="to">
              <span class="tag">SmartPay says</span>
              <strong>{_t(r["recommended_payment"])}</strong>
              <span class="chips">{channel_tag}{note}</span>
            </div>
          </div>
          <div class="plan-value">
            <span class="gain">{_money(guaranteed)}</span>
            <span class="sub">+{_money(estimated)} est.</span>
            {_gain_bar(gained, peak)}
          </div>
          <p class="plan-upside">{_t(upside)}</p>
          {f'<ul class="plan-why">{why}</ul>' if why else ''}
          {f'<ul class="plan-risk">{risk_notes}</ul>' if risk_notes else ''}
        </article>""")
    return "".join(rows), peak


def _enquiry_item(entry: dict, index: int, is_active: bool) -> str:
    """One distinct ChatGPT enquiry, collapsed to a summary line by default.

    Expanding it reveals exactly the same per-item detail the old "latest
    enquiry" block always showed for just one entry -- now available for
    whichever enquiry the reader actually wants to look at, not just the most
    recent one.
    """
    guaranteed = Decimal(str(entry.get("guaranteed", "0")))
    plan = entry.get("plan")
    body_id = f"enq-body-{index}"
    if plan:
        plan_rows, _peak = _plan_rows(plan)
        priceless_offers = plan.get("priceless") or []
        priceless_block = (
            f"""
          <h3 class="sub-h">Priceless offers for this trip</h3>
          <div class="priceless-grid">{"".join(_priceless_card(o) for o in priceless_offers)}</div>"""
            if priceless_offers else ""
        )
        detail = f"""
          <div class="chips-row">
            <span class="kv"><b>{_money(plan["incremental_guaranteed"])}</b>
              <small>Guaranteed on this enquiry</small></span>
            <span class="kv"><b>{_money(plan["incremental_estimated"])}</b>
              <small>Estimated rewards on this enquiry</small></span>
            <span class="kv"><b>{int(plan["incremental_points"]):,}</b>
              <small>Extra points on this enquiry</small></span>
          </div>
          <div class="plan">{plan_rows}</div>
          {priceless_block}"""
    else:
        detail = '<p class="sub-lede">No detail recorded for this enquiry.</p>'
    return f"""
    <li class="q{' on' if is_active else ''}">
      <button class="expand-toggle" id="enq-toggle-{index}" type="button" aria-expanded="false"
              aria-controls="{body_id}">
        <div class="expand-toggle-text">
          <div class="q-meta-row">
            <span class="q-when">{_t(_ago(entry.get("asked_at")))}</span>
            {_ai_badge(entry.get("platform", "chatgpt"), small=True)}
          </div>
          <h3>{_t(entry.get("title", "Untitled"))}</h3>
          <p class="q-meta">{_t(entry.get("items", 0))} items · {_money(entry.get("total", "0"))}</p>
        </div>
        {'<span class="q-tag">Latest</span>' if is_active else ''}
        <span class="expand-figure">{_money(guaranteed)}</span>
        <svg class="chevron" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M5 7l5 6 5-6" fill="none" stroke="currentColor" stroke-width="2.2"
                stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      <div class="expand-body" id="{body_id}" hidden>{detail}</div>
    </li>"""


def _potential_section(
    potential: dict,
    entries: list[dict],
    active_key: str,
) -> str:
    """Every distinct question asked of SmartPay through a connected AI
    assistant, most recent first, each collapsed to a one-line summary that
    expands to the full per-item detail.

    No single aggregate figure heads this section: mixing a recurring wallet
    opportunity with however many distinct trips happen to have been asked
    about reads as one number when it is really several unrelated ones (see
    app.analytics.potential_future_savings) -- each enquiry's own guaranteed
    figure is the number that means something, so that is what is prominent.
    """
    items_html = "".join(
        _enquiry_item(e, i, e.get("key") == active_key) for i, e in enumerate(entries)
    )
    platform_row = "".join(_ai_badge(p, small=True) for p in _AI_PLATFORM)
    return f"""
    <section class="panel expandable" aria-labelledby="future-h">
      <button class="expand-toggle" id="future-toggle" type="button" aria-expanded="false"
              aria-controls="future-body">
        <div class="expand-toggle-text">
          <h2 id="future-h">Your AI Chats</h2>
          <p>Every distinct question you've asked SmartPay, from any connected AI
             assistant, added here automatically.</p>
          <div class="ai-chip-row">{platform_row}</div>
        </div>
        <svg class="chevron" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M5 7l5 6 5-6" fill="none" stroke="currentColor" stroke-width="2.2"
                stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      <div class="expand-body" id="future-body" hidden>
        <div class="chips-row">
          <span class="kv"><b>{_money(potential['wallet_annual'])}</b>
            <small>Recurring wallet opportunity</small></span>
          <span class="kv"><b>{_t(potential['enquiry_count'])}</b>
            <small>Distinct enquiries asked</small></span>
          <span class="kv"><b>{_money(potential['enquiries_guaranteed'])}</b>
            <small>Guaranteed, across all enquiries</small></span>
          <span class="kv"><b>{_money(potential['enquiries_estimated'])}</b>
            <small>Estimated rewards, across all enquiries</small></span>
        </div>

        <h3 class="sub-h">Every distinct enquiry</h3>
        <p class="sub-lede">Baseline is inferred from 12 months of your own
           transactions, not assumed. Expand any enquiry to see the full
           breakdown.</p>
        <ul class="qlist">{items_html}</ul>
      </div>
    </section>"""


# ---------------------------------------------------------------------------
# Section 3 -- financial institutions and accounts, logos prominent
# ---------------------------------------------------------------------------

def _institutions_grid(profile: FinancialProfile) -> str:
    by_institution: dict[str, list[Account]] = defaultdict(list)
    for a in profile.accounts:
        by_institution[a.institution].append(a)

    blocks = []
    for institution, accounts in sorted(by_institution.items()):
        logo = ISSUER_LOGO.get(institution, "")
        name = ISSUER_NAME.get(institution, institution.title())
        rows = "".join(f"""
          <li class="acct-row">
            <span class="acct-name">{_t(a.display_name)}</span>
            <span class="acct-type">{_t(ACCOUNT_TYPE_LABEL.get(a.account_type.value, a.account_type.value))}
              · ····{_t(a.mask)}</span>
            <span class="acct-balance">{_money(a.current_balance)}</span>
          </li>""" for a in sorted(accounts, key=lambda a: a.display_name))
        blocks.append(f"""
        <article class="inst-card">
          <header class="inst-head">
            {f'<span class="inst-logo-plate"><img src="{_t(logo)}" alt="{_t(name)}" '
             f'class="inst-logo"></span>' if logo else ''}
            <div>
              <h3>{_t(name)}</h3>
              <p>{_t(len(accounts))} account{'s' if len(accounts) != 1 else ''} connected</p>
            </div>
          </header>
          <ul class="acct-list">{rows}</ul>
        </article>""")

    return f'<div class="inst-grid">{"".join(blocks)}</div>'


# ---------------------------------------------------------------------------
# Everything shared: financial institutions, accounts, transactions
# ---------------------------------------------------------------------------

def _shared_data_section(profile: FinancialProfile) -> str:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for txn in profile.spend_transactions:
        totals[txn.category.value] += txn.amount
    spend_rows = sorted(totals.items(), key=lambda kv: -kv[1])[:9]
    labelled = [(CATEGORY_LABEL.get(k, k.title()), v) for k, v in spend_rows]
    total = sum(totals.values(), Decimal(0))
    months = len({t.posted_at.strftime("%Y-%m") for t in profile.spend_transactions}) or 1

    account_lookup = {a.account_id: a for a in profile.accounts}
    # Every raw ledger entry, not just consumer spend -- card payments, ATM cash
    # out and income are real information Open Finance shared too, and hiding
    # them here would make "here's all the information you've shared" untrue.
    # The Type column is what lets a reader tell them apart from spend at a
    # glance, since is_consumer_spend already dims the row.
    txns = sorted(profile.transactions, key=lambda t: t.posted_at, reverse=True)
    txn_rows = "".join(f"""
      <tr{'' if t.is_consumer_spend else ' class="non-spend"'}>
        <td>{t.posted_at.isoformat()}</td>
        <td>{_t(t.description.title())}</td>
        <td>{_label(t.category.value)}</td>
        <td>{_t(TXN_TYPE_LABEL.get(t.transaction_type.value, t.transaction_type.value.title()))}</td>
        <td>{_t(account_lookup[t.account_id].display_name) if t.account_id in account_lookup else '—'}</td>
        <td class="num">{_money(t.amount)}</td>
      </tr>""" for t in txns)

    return f"""
    <section class="panel expandable" aria-labelledby="shared-h">
      <button class="expand-toggle" id="shared-toggle" type="button" aria-expanded="false"
              aria-controls="shared-body">
        <div class="expand-toggle-text">
          <h2 id="shared-h">Here's all the information you've shared</h2>
          <p>Every financial institution, account and transaction Open Finance has
             given SmartPay access to for Alex — nothing more, nothing hidden.</p>
        </div>
        <span class="expand-figure small">{_t(len({a.institution for a in profile.accounts}))} banks ·
          {_t(len(profile.accounts))} account{'s' if len(profile.accounts) != 1 else ''}</span>
        <svg class="chevron" viewBox="0 0 20 20" aria-hidden="true">
          <path d="M5 7l5 6 5-6" fill="none" stroke="currentColor" stroke-width="2.2"
                stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      <div class="expand-body" id="shared-body" hidden>
        <h3 class="sub-h">Financial institutions &amp; accounts connected</h3>
        <p class="sub-lede">Read live over FDX, the US open banking standard.</p>
        {_institutions_grid(profile)}

        <details class="mini-collapse">
          <summary class="sub-h collapse-summary">Where your money goes</summary>
          <div class="chart-wrap" role="list">{_bar_chart(labelled)}</div>
        </details>

        <details class="mini-collapse">
          <summary class="sub-h collapse-summary">Every transaction shared ({_t(len(txns))})</summary>
          <p class="sub-lede">Every raw ledger entry Open Finance returned, nothing
             held back. Rows dimmed and marked <b>Card payment</b>,
             <b>ATM withdrawal</b> or <b>Income</b> are not counted as spend anywhere
             on this page -- counting a card repayment as a purchase would double-count
             money already counted when it was first spent.</p>
          <div class="table-wrap scroll">
            <table class="data-table">
              <thead><tr><th>Date</th><th>Description</th><th>Category</th><th>Type</th>
                <th>Account</th><th>Amount</th></tr></thead>
              <tbody>{txn_rows}</tbody>
            </table>
          </div>
        </details>

        <h3 class="sub-h">Your card benefits, rewards, offers &amp; terms</h3>
        <p class="sub-lede">{_t(sum(1 for i in profile.instruments if i.is_card))} cards,
           read live over FDX from
           {_t(len({a.institution for a in profile.accounts}))} institutions.</p>
        {_wallet_carousel(profile)}
        <details class="mini-collapse">
          <summary class="sub-h collapse-summary">Detailed card benefits &amp; rules</summary>
          {_card_detail_tables(profile)}
        </details>
        {_offers_and_terms(profile)}
      </div>
    </section>"""


# ---------------------------------------------------------------------------
# Section 6 -- card benefits, rewards, offers, terms
# ---------------------------------------------------------------------------

def _wallet_carousel(profile: FinancialProfile) -> str:
    from app.knowledge import rewards_programs

    programs_by_issuer: dict[str, list] = defaultdict(list)
    for program in rewards_programs():
        programs_by_issuer[program.issuer_key].append(program)

    cards = []
    for i, inst in enumerate(profile.instruments):
        product = inst.product
        if product is None or inst.card is None:
            continue
        art = _card_art_uri(product.product_id)
        logo = ISSUER_LOGO.get(product.issuer, "")
        tier = product.network_tier.value.replace("_", " ").title()
        network_label = _t(tier if tier != "None" else product.network.value.title())
        # A concise earn summary: best rate per distinct category, so the card reads
        # as headline rates ("3× travel") rather than a paragraph of rule prose.
        seen: set[str] = set()
        rule_items: list[str] = []
        for r in sorted(product.reward_rules, key=lambda r: -r.multiplier):
            summary = r.category_summary
            if summary in seen:
                continue
            seen.add(summary)
            unit = "%" if r.reward_currency is RewardCurrency.USD_CASHBACK else "×"
            hint = ""
            if r.required_channels:
                channel = r.required_channels[0].value.replace("_", " ").title()
                hint = f' <span class="channel-hint">via {_t(channel)}</span>'
            rule_items.append(
                f'<li><b>{_t(_rate(r.multiplier))}{unit}</b> {_t(summary)}{hint}</li>'
            )
            if len(rule_items) == 3:
                break
        rules = "".join(rule_items)
        base_unit = "%" if product.base_currency is RewardCurrency.USD_CASHBACK else "×"
        base_line = (
            f'<li><b>{_t(_rate(product.base_multiplier))}{base_unit}</b> '
            "on all purchases</li>"
        )
        # Show the base rate as the floor when a card has room, so a flat-rate card
        # (Double Cash's 2%) is not misrepresented by a lone portal bonus.
        if rules and len(rule_items) < 3:
            rules += base_line
        # Cards that earn their bonuses through sourced Mastercard rewards programs
        # (rather than hard-coded rules) show those programs instead of a bare base.
        if not rules:
            ranked = sorted(programs_by_issuer.get(product.issuer, []), key=lambda p: -p.rate)
            # Best program per distinct category, so three travel tiers don't all show.
            seen_p: set[str] = set()
            distinct = []
            for p in ranked:
                if p.category_summary in seen_p:
                    continue
                seen_p.add(p.category_summary)
                distinct.append(p)
            rules = "".join(
                f'<li><b>+{_t(_rate(p.rate))}×</b> {_t(p.category_summary)} '
                f'<span class="sourced-tag">sourced</span></li>'
                for p in distinct[:3]
            )
        if not rules:
            rules = base_line
        perks = "".join(
            f"<li>{_t(b.display_name)}</li>" for b in _card_benefits(inst)[:3]
        )
        fee = product.annual_fee
        issuer_name = ISSUER_NAME.get(product.issuer, product.issuer.replace("_", " ").title())
        art_html = (
            f'<img src="{_t(art)}" alt="{_t(product.display_name)}" loading="lazy" '
            f'width="300" height="190">' if art
            # No product shot on file for this card -- a plain plate naming the
            # issuer beats an empty <img src=""> (a broken-image icon on the
            # dashboard's own wallet, which reads as this session's own bug).
            else f'<div class="card-art-placeholder">{_t(issuer_name)}</div>'
        )
        cards.append(f"""
        <article class="wallet-card art-{i}">
          <div class="card-art">
            {art_html}
          </div>
          <div class="card-body">
            <header>
              {f'<img class="issuer" src="{_t(logo)}" alt="{_t(issuer_name)}" '
               f'width="52" height="18">' if logo else ''}
              <h3>{_t(product.display_name)}</h3>
              <p class="card-meta">
                <span class="chip{' mc' if product.is_mastercard else ''}">{network_label}</span><span class="chip{' free' if fee == 0 else ''}">{'No annual fee' if fee == 0 else f'{_money(fee)} a year'}</span>
              </p>
            </header>
            <ul class="card-rules">{rules}</ul>
            {f'<ul class="card-perks">{perks}</ul>' if perks else ''}
          </div>
        </article>""")

    return f"""
      <div class="wallet-carousel" tabindex="0">{''.join(cards)}</div>
      <div class="carousel-dots" aria-hidden="true"></div>"""


def _card_detail_tables(profile: FinancialProfile) -> str:
    """Every reward rule and benefit, per card, in full -- not just the top 3."""
    blocks = []
    for inst in profile.instruments:
        product = inst.product
        if product is None:
            continue
        reward_rows = "".join(f"""
          <tr>
            <td><b>{_t(r.multiplier.normalize())}×</b></td>
            <td>{_t(r.description)}</td>
            <td>{_label(r.reward_currency.value)}</td>
            <td>{_label(', '.join(c.value for c in r.required_channels) or 'Any')}</td>
          </tr>""" for r in sorted(product.reward_rules, key=lambda r: -r.multiplier))
        benefit_rows = "".join(f"""
          <tr>
            <td>{_t(b.display_name)}</td>
            <td>{_t(b.description or '—')}</td>
            <td>{_t(b.evidence.source_name)}</td>
            <td>{_t(b.evidence.verified_at.isoformat() if b.evidence.verified_at else '—')}</td>
          </tr>""" for b in _card_benefits(inst))
        blocks.append(f"""
        <div class="card-detail">
          <h3 class="sub-h">{_t(product.display_name)}</h3>
          <table class="data-table">
            <thead><tr><th>Rate</th><th>Rule</th><th>Currency</th><th>Channel</th></tr></thead>
            <tbody>{reward_rows}</tbody>
          </table>
          {f'''<table class="data-table" style="margin-top:10px">
            <thead><tr><th>Network benefit</th><th>Detail</th><th>Source</th>
              <th>Verified</th></tr></thead>
            <tbody>{benefit_rows}</tbody>
          </table>''' if benefit_rows else ''}
          <p class="evidence-line">Source: {_t(product.evidence.source_name)}
             {f"· verified {_t(product.evidence.verified_at.isoformat())}" if product.evidence.verified_at else ""}
             {f'· <a href="{_t(product.evidence.source_url)}" target="_blank" rel="noopener noreferrer">terms</a>' if product.evidence.source_url else ''}</p>
        </div>""")
    return "".join(blocks)


def _offers_and_terms(profile: FinancialProfile) -> str:
    """Sourced Mastercard card-linked offers, and the source table for every benefit."""
    from app.knowledge import offers as all_offers

    catalogue = all_offers()
    #: The catalogue carries near-duplicate campaigns per merchant (an activation
    #: vs a standing offer -- see app.engines.offers), which would otherwise show
    #: the same merchant twice in a row with identical terms. One row per
    #: merchant here, same "keep the most valuable" rule the engine itself uses.
    by_merchant: dict[str, object] = {}
    for o in catalogue:
        current = by_merchant.get(o.merchant_name)
        if current is None or o.value > current.value:
            by_merchant[o.merchant_name] = o
    merchants = sorted(by_merchant.values(), key=lambda o: o.merchant_name.lower())
    #: A reference panel only needs a representative slice, with an honest count
    #: of the full set.
    shown = merchants[:12]
    offer_rows = "".join(f"""
      <li class="offer-row">
        <span class="offer-tag">{_t(o.provenance.label)}</span>
        <h4>{_t(o.merchant_name)}</h4>
        <p>{_t(o.description)}</p>
      </li>""" for o in shown)
    offer_lede = (
        f'<p class="sub-lede">{len(shown)} of {len(merchants)} real Mastercard '
        f"card-linked offer merchants from the US catalogue.</p>"
        if merchants else ""
    )

    seen: dict[tuple[str, str], str] = {}
    for b in benefits():
        e = b.evidence
        if e.source_url:
            seen[(e.source_name, e.source_url)] = (
                e.verified_at.isoformat() if e.verified_at else "—"
            )
    prov_rows = "".join(
        f'<tr><td>{_t(name)}</td><td>{_t(date)}</td>'
        f'<td><a href="{_t(url)}" rel="noopener noreferrer" target="_blank">source</a></td></tr>'
        for (name, url), date in sorted(seen.items())
    )

    return f"""
      {f'<details class="mini-collapse"><summary class="sub-h collapse-summary">Merchant offers for you on your Mastercard</summary>{offer_lede}<ul class="offer-list">{offer_rows}</ul></details>' if offer_rows else ''}
      <h3 class="sub-h">Every rule, and where it came from</h3>
      <p class="sub-lede">Read off live issuer and network pages. Nothing here is estimated.</p>
      <table class="data-table">
        <thead><tr><th>Source</th><th>Verified</th><th></th></tr></thead>
        <tbody>{prov_rows}</tbody>
      </table>"""


# ---------------------------------------------------------------------------
# "And one more thing..." -- always last
# ---------------------------------------------------------------------------

def _wallet_advice(wallet: dict) -> str:
    rec = wallet["recommendation"]
    delta = Decimal(rec["net_annual_incremental_value"])
    current = Decimal(rec["current_wallet_value"])
    drivers = "".join(f"<li>{_t(d)}</li>" for d in rec["drivers"][:5])
    return f"""
    <section class="panel closing" aria-labelledby="adv-h">
      <header class="panel-head">
        <div>
          <h2 id="adv-h">And one more thing…</h2>
          <p>Your wallet is not matched to what you are predicted to spend.</p>
        </div>
      </header>
      <div class="advice">
        <div class="advice-main">
          <div class="advice-headline">
            <p class="verdict">{_t(rec["headline"])}</p>
            <div class="advice-figure">
              <span class="figure" data-count="{delta}">{_money(delta)}</span>
              <small>net a year, after annual fees</small>
            </div>
          </div>
          <div class="advice-meta">
            {_ring(float(delta / current) if current else 0.0, "Share of wallet value gained")}
            <ul>{drivers}</ul>
          </div>
        </div>
        <figure class="advice-card">
          <img class="whopper-card"
               src="{_card_art_uri('first_hawaiian_priority_destinations')}"
               alt="First Hawaiian Priority Destinations World Elite Mastercard"
               width="400" height="251">
          <figcaption>First Hawaiian Priority Destinations World Elite Mastercard</figcaption>
        </figure>
      </div>
    </section>"""


# ---------------------------------------------------------------------------
# Page shell
# ---------------------------------------------------------------------------

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --bg:#f6f6f4; --surface:#fcfcfb; --surface-2:#ffffff; --line:#e6e5e1;
  --ink:#111110; --ink-2:#52514e; --ink-3:#86847e;
  --brand:#EB001B; --brand-2:#F79E1B; --brand-3:#FF5F00; --brand-ink:#C60016;
  --good:#046c4e; --good-bg:#e8f5ef;
  --warn:#9a5b00; --warn-bg:#fdf1de;
  --series-1:#2a78d6; --series-2:#eb6834; --series-3:#1baf7a; --series-4:#eda100;
  --series-5:#e87ba4; --series-6:#008300; --series-7:#4a3aa7; --series-8:#e34948;
  --radius:16px; --shadow:0 1px 2px rgba(17,17,16,.05),0 8px 24px -12px rgba(17,17,16,.15);
  --max:1240px;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --bg:#111110; --surface:#1a1a19; --surface-2:#212120; --line:#302f2c;
    --ink:#f7f7f5; --ink-2:#c3c2b7; --ink-3:#8e8c84;
    --brand-ink:#FF8A73;
    --good:#5fd0a4; --good-bg:#12281f;
    --warn:#e0a341; --warn-bg:#2b2210;
    --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70; --series-4:#c98500;
    --series-5:#d55181; --series-6:#008300; --series-7:#9085e9; --series-8:#e66767;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 28px -14px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#111110; --surface:#1a1a19; --surface-2:#212120; --line:#302f2c;
  --ink:#f7f7f5; --ink-2:#c3c2b7; --ink-3:#8e8c84;
  --good:#5fd0a4; --good-bg:#12281f;
  --warn:#e0a341; --warn-bg:#2b2210;
  --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70; --series-4:#c98500;
  --series-5:#d55181; --series-6:#008300; --series-7:#9085e9; --series-8:#e66767;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 28px -14px rgba(0,0,0,.7);
}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font:17px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,Roboto,sans-serif;
  font-feature-settings:"cv05","ss01"; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:var(--max);margin:0 auto;padding:0 24px}
h1,h2,h3{margin:0;letter-spacing:-.021em;line-height:1.15}
p{margin:0}
a{color:inherit}
.num,.figure,.amount,.gain,dd,.bar-value{font-variant-numeric:tabular-nums}

/* top bar */
.topbar{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 82%,transparent);
  backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.topbar .wrap{display:flex;align-items:center;gap:16px;height:64px}
.brand{display:flex;align-items:center;gap:10px;font-weight:650;letter-spacing:-.02em;font-size:19px}
.brand-mark{width:32px;height:21px;flex:none}
.status{margin-left:auto;display:flex;align-items:center;gap:8px;color:var(--ink-2);font-size:14px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--good);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--good) 22%,transparent)}
.theme-toggle{border:1px solid var(--line);background:var(--surface);color:var(--ink-2);
  border-radius:999px;height:34px;padding:0 14px;font:inherit;font-size:14px;cursor:pointer}
.theme-toggle:hover{color:var(--ink);border-color:var(--ink-3)}

/* header / section 1 */
.hero{padding:52px 0 40px}
.eyebrow{font-size:13px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);
  font-weight:650;margin-bottom:10px}
.name{font-size:clamp(38px,6vw,64px);font-weight:720;letter-spacing:-.03em;
  display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.hero-stats{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:30px}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:20px;
  padding:26px 28px;box-shadow:var(--shadow)}
.stat.accent{border-color:color-mix(in srgb,var(--brand) 34%,var(--line));
  background:linear-gradient(180deg,color-mix(in srgb,var(--brand) 6%,var(--surface)),var(--surface))}
.stat.accent2{border-color:color-mix(in srgb,var(--brand-2) 40%,var(--line));
  background:linear-gradient(180deg,color-mix(in srgb,var(--brand-2) 7%,var(--surface)),var(--surface))}
.stat dt{font-size:15px;color:var(--ink-2);font-weight:600}
.stat dd{margin:6px 0 0;font-size:clamp(36px,4.6vw,56px);font-weight:700;letter-spacing:-.03em;
  background:linear-gradient(96deg,var(--brand),var(--brand-2));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.stat.accent2 dd{background:linear-gradient(96deg,var(--brand-2),var(--brand-3));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.stat p{font-size:14.5px;color:var(--ink-3);margin-top:8px;line-height:1.5}

/* panels */
.panel{background:var(--surface);border:1px solid var(--line);border-radius:20px;
  padding:28px;margin-bottom:24px;box-shadow:var(--shadow)}
.panel-head{display:flex;gap:20px;align-items:flex-start;justify-content:space-between;
  margin-bottom:22px;flex-wrap:wrap}
.panel-head h2{font-size:27px;font-weight:680}
.panel-head p{color:var(--ink-2);font-size:15px;margin-top:6px;max-width:64ch}
.sub-h{font-size:18px;font-weight:660;margin:22px 0 6px}
.sub-h:first-of-type{margin-top:6px}
.sub-lede{color:var(--ink-2);font-size:14px;margin-bottom:12px}
.legend{display:flex;gap:14px;font-size:13px;color:var(--ink-2);align-items:center}
.legend i{width:11px;height:11px;border-radius:3px;display:inline-block;margin-right:6px;
  vertical-align:-1px}
.sw.base{background:var(--ink-3)}
.sw.opt{background:linear-gradient(90deg,var(--brand),var(--brand-2))}
.mini-stats{display:flex;gap:24px}
.mini-stats span{display:block;font-size:21px;font-weight:660;letter-spacing:-.02em}
.mini-stats small{color:var(--ink-3);font-size:12.5px}

/* Flipper -- an immersive hero, not a bordered utility panel. Deliberately
   fixed dark colours rather than the light/dark theme tokens, the same way
   the card art itself carries the visual weight regardless of site theme. */
.flipper-hero{position:relative;overflow:hidden;display:grid;
  grid-template-columns:1.3fr 1fr;gap:36px;align-items:center;border-radius:26px;
  padding:44px 48px;margin-bottom:24px;color:#f6f5f3;
  background:radial-gradient(120% 160% at 100% 0%,#2a2130,transparent 60%),
    linear-gradient(135deg,#15161f,#1c1e2b 55%,#231920)}
.flipper-hero-glow{position:absolute;inset:-40% -10% auto auto;width:60%;aspect-ratio:1;
  border-radius:50%;pointer-events:none;
  background:radial-gradient(circle,color-mix(in srgb,var(--brand) 55%,transparent),transparent 70%);
  filter:blur(10px);opacity:.55}
.flipper-hero-copy{position:relative;z-index:1}
.flipper-hero .flipper-status{display:inline-block;font-size:10.5px;font-weight:700;
  letter-spacing:.05em;text-transform:uppercase;color:#f6f5f3;
  background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.18);
  border-radius:999px;padding:4px 10px}
.flipper-hero.complete .flipper-status{color:#e8fff4;background:rgba(27,175,122,.22);
  border-color:rgba(27,175,122,.5)}
.flipper-headline{font-size:27px;font-weight:760;letter-spacing:-.02em;line-height:1.28;
  margin:14px 0 18px;max-width:32ch}
.flipper-badge{display:flex;align-items:baseline;gap:7px;margin-bottom:16px}
.flipper-badge b{font-size:46px;font-weight:800;letter-spacing:-.03em;
  background:linear-gradient(96deg,#ffffff,var(--brand-2));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.flipper-badge small{font-size:12.5px;font-weight:700;letter-spacing:.07em;
  color:rgba(246,245,243,.65)}
.flipper-hero h3{font-size:13.5px;font-weight:600;color:rgba(246,245,243,.72);
  margin-bottom:14px}
.flipper-progress{display:grid;gap:9px;max-width:440px}
.flipper-progress-row{display:grid;gap:5px;font-size:12.5px;color:rgba(246,245,243,.8)}
.flipper-track{height:6px;border-radius:4px;background:rgba(255,255,255,.16);overflow:hidden}
.flipper-track i{display:block;height:100%;border-radius:4px;
  background:linear-gradient(90deg,var(--brand),var(--brand-2))}
.flipper-meta{color:rgba(246,245,243,.6);font-size:12.5px;margin-top:14px;line-height:1.5}
.flipper-hero-card{position:relative;z-index:1;display:flex;justify-content:center}
.flipper-hero-art{width:100%;max-width:260px;border-radius:18px;object-fit:contain;
  box-shadow:0 30px 70px -12px rgba(0,0,0,.6);transform:rotate(-5deg);
  filter:grayscale(calc(100% - (var(--progress,0) * 100%)))
         saturate(calc(35% + (var(--progress,0) * 90%)))
         brightness(calc(.85 + (var(--progress,0) * .2)));
  transition:filter 1.4s ease}
.flipper-hero-art.placeholder{aspect-ratio:1.58;display:flex;align-items:center;
  justify-content:center;text-align:center;font-size:14px;font-weight:650;padding:0 16px;
  background:rgba(255,255,255,.08);color:rgba(246,245,243,.7)}
@media (prefers-reduced-motion:no-preference){
  .flipper-hero.pulsing .flipper-hero-art{animation:flipperfloat 3.6s ease-in-out infinite}
  .flipper-hero.pulsing .flipper-hero-glow{animation:flipperglow 3.6s ease-in-out infinite}
}
@keyframes flipperfloat{
  0%,100%{transform:rotate(-5deg) translateY(0)}
  50%{transform:rotate(-3deg) translateY(-10px)}
}
@keyframes flipperglow{0%,100%{opacity:.4}50%{opacity:.75}}
@media (max-width:820px){
  .flipper-hero{grid-template-columns:1fr;padding:32px 26px}
  .flipper-hero-card{order:-1}
  .flipper-hero-art{max-width:200px}
}

/* Priceless -- real catalogue offers matched to Alex's history */
.priceless-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}
.priceless-card{border:1px solid var(--line);border-radius:14px;overflow:hidden;
  background:var(--surface-2);display:flex;flex-direction:column;transition:transform .18s,box-shadow .18s}
.priceless-card:hover{transform:translateY(-3px);box-shadow:var(--shadow)}
.priceless-img{aspect-ratio:16/10;background-size:cover;background-position:center;
  background-color:var(--line)}
.priceless-img.placeholder{display:grid;place-items:center;
  background:linear-gradient(135deg,color-mix(in srgb,var(--brand) 12%,var(--surface)),
  color-mix(in srgb,var(--brand-2) 10%,var(--surface)))}
.priceless-img.placeholder span{font-size:12px;font-weight:650;letter-spacing:.04em;
  color:var(--ink-3);text-transform:uppercase}
.priceless-body{padding:14px 15px 16px;display:flex;flex-direction:column;gap:6px;flex:1}
.priceless-cat{font-size:11px;font-weight:650;letter-spacing:.05em;text-transform:uppercase;
  color:var(--brand-ink)}
.priceless-body h4{font-size:15px;font-weight:660;line-height:1.3}
.priceless-why{font-size:12.5px;color:var(--ink-3);line-height:1.4}
.priceless-foot{margin-top:auto;padding-top:8px;display:flex;justify-content:space-between;
  align-items:center;font-size:12px}
.priceless-price{font-weight:650;color:var(--ink-2)}
.priceless-foot a{color:var(--brand-ink);font-weight:600;text-decoration:none}
.priceless-foot a:hover{text-decoration:underline}

/* history <-> mocked CommerceGPT forecast timeline */
.timeline{position:relative;margin:4px 0 20px}
.timeline-head{display:flex;justify-content:space-between;align-items:center;gap:8px;
  font-size:12px;font-weight:650;color:var(--ink-3);margin-bottom:10px}
.tl-end.future{color:var(--brand-ink)}
.tl-now{font-weight:750;color:var(--ink);text-transform:uppercase;letter-spacing:.06em;
  border:1px solid var(--line);border-radius:999px;padding:2px 10px;background:var(--surface)}
input.timeline-slider{background:linear-gradient(90deg,
  color-mix(in srgb,var(--ink-3) 38%,transparent) 0 50%,
  color-mix(in srgb,var(--brand) 45%,transparent) 50% 100%)}
.ai-predict{display:none;align-items:center;gap:10px;margin-top:12px;font-size:13px;
  font-weight:620;color:var(--brand-ink)}
.ai-predict.on{display:flex}
.ai-orb{width:16px;height:16px;border-radius:50%;flex:none;
  background:radial-gradient(circle at 30% 30%,var(--brand),var(--brand-2));
  animation:aipulse 1s ease-out infinite}
@keyframes aipulse{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--brand) 45%,transparent)}
  70%{box-shadow:0 0 0 13px transparent}100%{box-shadow:0 0 0 0 transparent}}

.tl-figures{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:22px}
.tl-fig{border:1px solid var(--line);border-radius:16px;padding:16px 18px;
  display:flex;flex-direction:column;gap:5px;transition:opacity .2s,border-color .2s}
.tl-fig.future{border-color:color-mix(in srgb,var(--brand) 28%,var(--line))}
.tl-fig .figure{font-size:30px;font-weight:720;letter-spacing:-.02em}
.tl-fig.future .figure{background:linear-gradient(96deg,var(--brand),var(--brand-2));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.tl-fig small{font-size:12.5px;color:var(--ink-3);line-height:1.45}
.tl-fig-tag{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  color:var(--ink-3);display:flex;align-items:center;gap:6px}
.timeline.focus-past~.tl-figures .tl-fig.future{opacity:.4}
.timeline.focus-future~.tl-figures .tl-fig.past{opacity:.4}
.ai-badge{font-size:10px;font-weight:800;letter-spacing:.04em;color:#fff;
  background:linear-gradient(96deg,var(--brand),var(--brand-2));border-radius:6px;padding:2px 6px}
.ai-mock{font-size:10px;font-weight:700;letter-spacing:.03em;color:var(--ink-3);
  border:1px dashed var(--line);border-radius:6px;padding:1px 6px;text-transform:uppercase}
.retro-txn.projected{opacity:0;transform:translateY(6px);
  transition:opacity .35s ease,transform .35s ease}
.retro-txn.projected.revealed{opacity:1;transform:none}
.retro-txn.projected.revealed.out-of-window{opacity:.3}
.retro-txn.projected .rt-delta{color:var(--brand-ink);font-weight:640}
.future-list .retro-txn.projected.improved{background:color-mix(in srgb,var(--brand) 6%,transparent)}
@media (max-width:640px){.tl-figures{grid-template-columns:1fr}}

/* retro two-column: habits on the left, the active table (history or forecast) on the right */
.retro-grid{display:grid;grid-template-columns:minmax(240px,320px) 1fr;gap:24px;align-items:start}
.retro-habits{position:sticky;top:16px}
.retro-tables{min-width:0}
.retro-table-block[hidden]{display:none}
@media (max-width:820px){.retro-grid{grid-template-columns:1fr}.retro-habits{position:static}}

/* native mini-collapse for the spend categorisation chart */
.mini-collapse{border:1px solid var(--line);border-radius:12px;padding:0 14px;margin:8px 0 16px}
.mini-collapse>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;
  padding:12px 0}
.mini-collapse>summary::-webkit-details-marker{display:none}
.mini-collapse>summary::after{content:'▸';margin-left:auto;color:var(--ink-3);transition:transform .2s}
.mini-collapse[open]>summary::after{transform:rotate(90deg)}
.collapse-summary{margin:0!important}

/* discrete single-row Priceless strip */
.priceless-strip{display:flex;gap:14px;overflow-x:auto;padding-bottom:8px;
  scroll-snap-type:x mandatory}
.priceless-strip .priceless-card{flex:0 0 236px;scroll-snap-align:start}
.priceless-strip .priceless-img{height:116px}
.priceless-strip .priceless-body{padding:12px 13px 13px}
.priceless-strip .priceless-body h4{font-size:14px}

/* generic expandable panel -- retro, enquiries, institutions, shared data all
   use this same toggle/body pair so one delegated click handler covers all of
   them (see the SCRIPT block). */
.expandable{padding:0;overflow:hidden}
.expand-toggle{all:unset;box-sizing:border-box;display:flex;align-items:center;gap:20px;
  width:100%;padding:26px 28px;cursor:pointer}
.expand-toggle:hover{background:color-mix(in srgb,var(--brand) 4%,transparent)}
.expand-toggle:focus-visible{outline:2px solid var(--brand);outline-offset:-2px}
.expand-toggle-text{flex:1 1 auto;min-width:0}
.expand-toggle-text h2{font-size:23px;font-weight:680}
.expand-toggle-text p{color:var(--ink-2);font-size:14.5px;margin-top:5px;max-width:56ch}
.expand-figure{font-size:26px;font-weight:700;letter-spacing:-.02em;flex:none;
  background:linear-gradient(96deg,var(--brand),var(--brand-2));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.expand-figure.small{font-size:14.5px;font-weight:600;color:var(--ink-2);background:none;
  -webkit-background-clip:unset;background-clip:unset}
.expandable .chevron{width:20px;height:20px;flex:none;color:var(--ink-3);transition:transform .22s}
.expandable.open .chevron{transform:rotate(180deg)}
.expand-body{padding:0 28px 28px}

/* retrospective slider ("what could you have saved?") */
.retro-slider-row{display:flex;flex-direction:column;gap:8px;margin-bottom:18px}
.retro-slider-label{font-size:14px;color:var(--ink-2);font-weight:600}
.retro-slider-label b{color:var(--ink);font-weight:700}
.retro-slider{-webkit-appearance:none;appearance:none;width:100%;height:6px;border-radius:99px;
  background:var(--line);outline:none;cursor:pointer}
.retro-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:20px;
  height:20px;border-radius:50%;background:var(--brand);border:3px solid var(--surface);
  box-shadow:0 1px 4px rgba(0,0,0,.25);cursor:pointer}
.retro-slider::-moz-range-thumb{width:20px;height:20px;border-radius:50%;background:var(--brand);
  border:3px solid var(--surface);box-shadow:0 1px 4px rgba(0,0,0,.25);cursor:pointer}
.retro-summary{display:grid;grid-template-columns:1fr 1.4fr;gap:24px;align-items:start;
  background:var(--surface-2);border:1px solid var(--line);border-radius:16px;padding:20px 22px;
  margin-bottom:22px}
.retro-summary-figure .figure{display:block;font-size:38px;font-weight:700;letter-spacing:-.03em;
  background:linear-gradient(96deg,var(--brand),var(--brand-2));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.retro-summary-figure small{color:var(--ink-3);font-size:13px;line-height:1.5;display:block;
  margin-top:6px}
.retro-summary-figure small.retro-fee-total{color:var(--warn);font-weight:600}
.habit-list{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:6px}
.habit-row{display:grid;grid-template-columns:1fr auto auto;gap:10px;align-items:center;
  font-size:13.5px;padding:7px 10px;border-radius:9px;background:var(--surface)}
.habit-row.empty{grid-template-columns:1fr;color:var(--ink-3);font-style:italic}
.habit-label{color:var(--ink-2)}
.habit-count{color:var(--ink-3);font-size:12.5px}
.habit-value{font-weight:660;letter-spacing:-.01em;color:var(--good)}
.retro-txn-list{list-style:none;margin:0;padding:0;display:grid;gap:2px;max-height:420px;
  overflow-y:auto;border:1px solid var(--line);border-radius:12px;padding:4px}
.retro-txn{display:grid;grid-template-columns:56px 1.6fr 1fr 1.4fr auto;gap:4px 12px;
  align-items:center;padding:9px 10px;border-radius:8px;font-size:13.5px;
  transition:opacity .15s,background-color .15s}
.retro-txn.improved{background:var(--good-bg)}
.retro-txn.improved .rt-delta{color:var(--good);font-weight:660}
.retro-txn.fee.improved{background:var(--warn-bg)}
.retro-txn.fee.improved .rt-delta{color:var(--warn)}
.retro-txn .rt-date{color:var(--ink-3);font-weight:600}
.retro-txn .rt-category{color:var(--ink-3)}
.retro-txn .rt-card{color:var(--ink-3);font-size:12.5px}
.retro-txn .rt-delta{text-align:right;color:var(--ink-3)}
.retro-txn .rt-change{grid-column:1/-1;font-size:12px;color:var(--ink-2);padding-top:2px}
.retro-txn.out-of-window{opacity:.32}
.retro-txn.out-of-window.improved{background:transparent}
.retro-txn.mc-lit:not(.improved){background:color-mix(in srgb,var(--brand) 5%,transparent)}
.retro-txn .rt-mc{grid-column:1/-1;list-style:none;margin:4px 0 0;padding:0;
  display:flex;flex-direction:column;gap:4px}
.rt-mc-item{display:flex;align-items:center;gap:6px;font-size:11.5px;
  color:var(--type-color);background:color-mix(in srgb,var(--type-color) 10%,var(--surface));
  border:1px solid color-mix(in srgb,var(--type-color) 25%,var(--line));
  padding:4px 9px;border-radius:999px;width:fit-content}
.rt-mc-icon{display:flex;flex:none}
.rt-mc-text{color:var(--ink-2)}
.rt-mc-text b{color:var(--type-color);font-weight:700;margin-right:2px}

/* AI assistant badges -- a monogram plate, the same convention the admin
   dashboard uses for this exact row of names, not a sourced logo mark */
.ai-chip-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.ai-chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:620;
  color:var(--ink-2);background:var(--surface-2);border:1px solid var(--line);
  border-radius:999px;padding:4px 10px 4px 4px}
.ai-chip i{width:18px;height:18px;border-radius:6px;flex:none;color:#fff;font-style:normal;
  font-weight:800;font-size:9.5px;display:grid;place-items:center}
.ai-chip.small{font-size:11px;padding:3px 9px 3px 3px}
.ai-chip.small i{width:15px;height:15px;font-size:8.5px;border-radius:5px}

/* stat chip row (section 2) */
.chips-row{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:6px}
.kv{border:1px solid var(--line);border-radius:14px;padding:12px 16px;background:var(--surface-2);
  flex:1 1 180px}
.kv b{display:block;font-size:22px;font-weight:680;letter-spacing:-.02em}
.kv small{font-size:12.5px;color:var(--ink-3)}

/* plan */
.plan{display:grid;gap:10px}
.plan-row{display:grid;grid-template-columns:1.15fr 2fr .9fr;gap:22px;align-items:center;
  padding:16px 18px;border:1px solid var(--line);border-radius:14px;background:var(--surface-2);
  transition:border-color .18s,transform .18s}
.plan-row.has-gain{border-left:3px solid var(--brand)}
.plan-row:hover{border-color:var(--ink-3);transform:translateY(-1px)}
.plan-item h3{font-size:16px;font-weight:620}
.plan-item .amount{color:var(--ink-3);font-size:14px}
.plan-swap{display:grid;grid-template-columns:1fr auto 1fr;gap:14px;align-items:center}
.plan-swap .tag{display:block;font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink-3);font-weight:600;margin-bottom:3px}
.plan-swap strong{font-size:15px;font-weight:620;display:block;line-height:1.3}
.plan-swap .from strong{color:var(--ink-2);font-weight:500}
.plan-swap .prob{font-size:12.5px;color:var(--ink-3)}
.arrow{color:var(--brand-ink);font-size:20px;font-weight:700}
.chips{display:flex;gap:5px;flex-wrap:wrap;margin-top:4px}
.chip{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:620;
  padding:3px 9px;border-radius:999px;border:1px solid var(--line);color:var(--ink-2);
  background:var(--surface);white-space:nowrap;flex:none}
.chip.portal{border-color:color-mix(in srgb,var(--brand) 40%,var(--line));
  color:var(--brand-ink);background:color-mix(in srgb,var(--brand) 7%,transparent)}
.chip.tie{border-style:dashed}
.chip.mc{border-color:color-mix(in srgb,var(--brand) 40%,var(--line));color:var(--brand-ink)}
.chip.free{color:var(--good);border-color:color-mix(in srgb,var(--good) 40%,var(--line))}
.plan-value{text-align:right}
.plan-value .gain{display:block;font-size:22px;font-weight:680;letter-spacing:-.02em}
.plan-value .sub{font-size:12.5px;color:var(--ink-3)}
.delta{width:100%;max-width:210px;height:12px;margin-left:auto;display:block;margin-top:7px}
.d-track{fill:var(--line);opacity:.6}
.d-opt{fill:var(--brand)}
.bar-value.inside{fill:#fff}
.plan-upside{grid-column:1/-1;margin:0;font-size:13.5px;color:var(--ink-2);
  padding-top:8px;border-top:1px dashed var(--line)}
.plan-why{grid-column:1/-1;margin:2px 0 0;padding:6px 0 0;
  list-style:none;display:flex;gap:8px;flex-wrap:wrap}
.plan-why li{font-size:12.5px;color:var(--good);background:var(--good-bg);
  padding:4px 10px;border-radius:999px}
.plan-risk{grid-column:1/-1;margin:0;padding:8px 0 0;list-style:none;
  display:flex;flex-direction:column;gap:6px}
.plan-risk li{font-size:12.5px;color:var(--warn);background:var(--warn-bg);
  padding:6px 10px;border-radius:10px}

/* enquiries list -- each <li> is its own nested expandable */
.qlist{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.q{position:relative;border:1px solid var(--line);border-radius:13px;
  background:var(--surface-2);overflow:hidden}
.q.on{border-color:color-mix(in srgb,var(--brand) 42%,var(--line));
  background:linear-gradient(100deg,color-mix(in srgb,var(--brand) 6%,var(--surface-2)),
  var(--surface-2))}
.q .expand-toggle{padding:14px 16px;gap:14px}
.q .expand-toggle-text{display:flex;flex-direction:column;gap:2px}
.q-meta-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.q-when{font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-3);
  font-weight:600}
.q .expand-toggle-text h3{font-size:16px;font-weight:620;margin:0}
.q-meta{font-size:12.5px;color:var(--ink-3)}
.q-tag{font-size:11px;font-weight:700;letter-spacing:.06em;flex:none;
  text-transform:uppercase;color:var(--brand-ink)}
.q .expand-body{padding:0 16px 16px}
.q .expand-body .plan{margin-top:2px}

/* charts */
.chart-wrap{overflow-x:auto}
.mini-collapse .chart-wrap{max-width:600px}
.chart{width:100%;max-width:600px;height:auto}
.chart{width:100%;min-width:520px;height:auto;display:block}
.bar-track{fill:var(--line);opacity:.5}
.bar{transition:opacity .16s}
.bar-row:hover .bar,.bar-row:focus .bar{opacity:.78}
.bar-row:focus{outline:2px solid var(--brand);outline-offset:2px;border-radius:6px}
.bar-label{font-size:14px;fill:var(--ink-2)}
.bar-value{font-size:14px;fill:var(--ink);font-weight:620}
.ring{width:64px;height:64px;flex:none}
.ring-track{fill:none;stroke:var(--line);stroke-width:7}
.ring-fill{fill:none;stroke:var(--brand);stroke-width:7;stroke-linecap:round}
.ring-text{font-size:15px;font-weight:660;fill:var(--ink);text-anchor:middle}

/* institutions (section 3) */
.inst-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}
.inst-card{border:1px solid var(--line);border-radius:16px;background:var(--surface-2);
  padding:22px}
.inst-head{display:flex;align-items:center;gap:18px;margin-bottom:18px}
.inst-logo-plate{flex:none;width:76px;height:76px;border-radius:16px;background:var(--surface);
  border:1px solid var(--line);display:grid;place-items:center;padding:12px}
.inst-logo{height:100%;width:100%;object-fit:contain}
.inst-head h3{font-size:23px;font-weight:680}
.inst-head p{font-size:14px;color:var(--ink-3);margin-top:2px}
.acct-list{list-style:none;margin:0;padding:0;display:grid;gap:2px}
.acct-row{display:grid;grid-template-columns:1.3fr 1fr auto;gap:10px;align-items:baseline;
  padding:10px 0;border-top:1px solid var(--line)}
.acct-row:first-child{border-top:none}
.acct-name{font-size:15px;font-weight:600}
.acct-type{font-size:13px;color:var(--ink-3)}
.acct-balance{font-size:16px;font-weight:640;text-align:right;letter-spacing:-.01em}

/* recent activity (section 4) */
.activity-list{list-style:none;margin:0;padding:0;display:grid;gap:2px}
.activity-row{display:grid;grid-template-columns:64px 1.6fr 1fr 1.4fr auto;gap:14px;
  align-items:center;padding:11px 4px;border-top:1px solid var(--line);font-size:14.5px}
.activity-row:first-child{border-top:none}
.act-date{color:var(--ink-3);font-weight:600}
.act-merchant{font-weight:600}
.act-category{color:var(--ink-2)}
.act-card{color:var(--ink-3);font-size:13px}
.act-amount{text-align:right;font-weight:640}

/* shared data (section 5) */
.table-wrap{overflow-x:auto}
.table-wrap.scroll{max-height:480px;overflow-y:auto;border:1px solid var(--line);
  border-radius:12px}
.data-table{width:100%;border-collapse:collapse;font-size:14px}
.data-table th{position:sticky;top:0;background:var(--surface-2);text-align:left;
  font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);
  padding:9px 12px;font-weight:650;border-bottom:1px solid var(--line)}
.data-table td{padding:9px 12px;border-top:1px solid var(--line);color:var(--ink-2)}
.data-table td.num{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink)}
.data-table tr.non-spend td{color:var(--ink-3)}
.data-table tr.non-spend td:nth-child(4){font-style:italic}

/* wallet (section 6) */
.wallet-carousel{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(268px,1fr);
  gap:16px;overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:8px;
  scrollbar-width:thin}
.wallet-carousel::-webkit-scrollbar{height:6px}
.wallet-carousel::-webkit-scrollbar-thumb{background:var(--line);border-radius:9px}
.wallet-card{scroll-snap-align:start;border:1px solid var(--line);border-radius:16px;
  background:var(--surface-2);overflow:hidden;display:flex;flex-direction:column;
  transition:transform .2s,box-shadow .2s}
.wallet-card:hover{transform:translateY(-3px);box-shadow:var(--shadow)}
.card-art{aspect-ratio:1.58;background:linear-gradient(135deg,var(--surface),var(--line));
  display:grid;place-items:center;padding:16px}
.card-art img{width:100%;height:100%;object-fit:contain;
  filter:drop-shadow(0 6px 14px rgba(0,0,0,.22))}
.card-art-placeholder{display:flex;align-items:center;justify-content:center;
  width:100%;height:100%;font-size:15px;font-weight:650;color:var(--ink-2);
  text-align:center;padding:0 12px}
.card-body{padding:14px 16px 16px;display:flex;flex-direction:column;gap:9px}
.issuer{height:17px;width:auto;object-fit:contain;object-position:left;display:block;
  margin-bottom:6px}
.card-body h3{font-size:15px;font-weight:660;line-height:1.3}
.card-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.card-rules,.card-perks{list-style:none;margin:0;padding:0;display:grid;gap:5px}
.card-rules li{font-size:13px;color:var(--ink-2)}
.card-rules b{color:var(--ink);font-weight:660}
.card-perks li{font-size:12.5px;color:var(--good);background:var(--good-bg);
  padding:3px 8px;border-radius:8px}
.carousel-nav{display:flex;gap:6px}
.carousel-nav button{width:34px;height:34px;border-radius:50%;border:1px solid var(--line);
  background:var(--surface);color:var(--ink-2);font-size:18px;cursor:pointer;line-height:1}
.carousel-nav button:hover{color:var(--ink);border-color:var(--ink-3)}
.carousel-dots{display:flex;gap:5px;justify-content:center;margin-top:14px}
.carousel-dots i{width:5px;height:5px;border-radius:50%;background:var(--line)}
.carousel-dots i.on{background:var(--brand);width:16px;border-radius:3px}
.card-detail{margin-top:26px;padding-top:20px;border-top:1px solid var(--line)}
.evidence-line{font-size:12.5px;color:var(--ink-3);margin-top:8px}
.evidence-line a{color:var(--brand-ink);font-weight:620;text-decoration:none}
.evidence-line a:hover{text-decoration:underline}
.offer-list{list-style:none;margin:0 0 8px;padding:0;display:grid;gap:10px}
.offer-row{border:1px dashed var(--line);border-radius:12px;padding:12px 14px}
.offer-tag{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  color:var(--brand-ink)}
.sourced-tag{font-size:9.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
  color:var(--brand-ink);border:1px solid var(--line);border-radius:6px;padding:1px 5px;margin-left:4px}
.channel-hint{font-size:11.5px;color:var(--ink-3)}
.offer-row h4{font-size:15px;font-weight:640;margin-top:4px}
.offer-row p{font-size:13.5px;color:var(--ink-2);margin-top:4px}

/* closing */
.closing{background:linear-gradient(150deg,color-mix(in srgb,var(--brand) 7%,var(--surface)),
  color-mix(in srgb,var(--brand-2) 5%,var(--surface)));
  border-color:color-mix(in srgb,var(--brand) 24%,var(--line))}
.advice{display:grid;grid-template-columns:1.4fr .95fr;gap:32px;align-items:center}
.advice-main{display:grid;gap:22px;min-width:0}
.advice-card{margin:0;display:flex;flex-direction:column;align-items:center;gap:10px}
.whopper-card{width:100%;max-width:400px;border-radius:16px;
  box-shadow:0 22px 55px -18px rgba(15,76,74,.55),0 2px 10px rgba(0,0,0,.18);
  animation:whopperFloat 6s ease-in-out infinite}
.advice-card figcaption{font-size:12px;color:var(--ink-3);text-align:center;max-width:340px}
@keyframes whopperFloat{0%,100%{transform:translateY(0) rotate(-1.2deg)}
  50%{transform:translateY(-9px) rotate(1.2deg)}}
@media (prefers-reduced-motion:reduce){.whopper-card{animation:none}}
.verdict{font-size:20px;font-weight:620;letter-spacing:-.02em;max-width:34ch}
.advice-figure{margin-top:14px}
.advice-figure .figure{font-size:44px;font-weight:700;letter-spacing:-.03em;
  background:linear-gradient(96deg,var(--brand),var(--brand-2));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.advice-figure small{display:block;color:var(--ink-2);font-size:13px}
.advice-meta{display:flex;gap:18px;align-items:flex-start}
.advice-meta ul{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.advice-meta li{font-size:13.5px;color:var(--ink-2)}

footer.foot{padding:26px 0 56px;color:var(--ink-3);font-size:13px;display:grid;gap:6px}

/* motion */
@media (prefers-reduced-motion:no-preference){
  .panel,.hero{animation:rise .5s cubic-bezier(.22,.9,.3,1) both}
  .panel:nth-of-type(2){animation-delay:.05s}
  .panel:nth-of-type(3){animation-delay:.1s}
  .bar{animation:grow .7s cubic-bezier(.22,.9,.3,1) both}
  @keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
  @keyframes grow{from{transform:scaleX(0);transform-origin:left}to{transform:none}}
}

@media (max-width:920px){
  .hero-stats{grid-template-columns:1fr}
  .plan-row{grid-template-columns:1fr;gap:14px}
  .plan-value{text-align:left}
  .delta{margin-left:0}
  .advice{grid-template-columns:1fr}
  .panel{padding:20px}
  .activity-row{grid-template-columns:56px 1fr auto;grid-template-areas:
    "date merchant amount" ". category card"}
  .act-category,.act-card{grid-column:2/4}
  .expand-toggle{padding:20px}
  .expand-body{padding:0 20px 20px}
  .retro-summary{grid-template-columns:1fr}
  .retro-txn{grid-template-columns:1fr auto;
    grid-template-areas:"merchant delta" "category delta" "change change"}
  .retro-txn .rt-date,.retro-txn .rt-card{display:none}
  .retro-txn .rt-merchant{grid-area:merchant}
  .retro-txn .rt-category{grid-area:category;font-size:12px}
  .retro-txn .rt-delta{grid-area:delta}
  .retro-txn .rt-change{grid-area:change}
}
@media (max-width:560px){
  .wrap{padding:0 16px}
  /* The connection string wraps to two lines and doubles the bar's height on a
     phone. The status dot and the toggle carry the same meaning in less room. */
  .status span:not(.dot){display:none}
  .plan-swap{grid-template-columns:1fr;gap:8px}
  .arrow{transform:rotate(90deg);width:min-content}
  .mini-stats{gap:14px}
  /* Three flex children (text, figure, chevron) in one row leaves the text
     block only a sliver of width on a phone, wrapping its heading to one word
     per line. Wrapping the row lets the figure and chevron drop to their own
     line instead of starving the text next to them. */
  .expand-toggle{flex-wrap:wrap;row-gap:12px}
  .expand-toggle-text{flex:1 1 100%}
  .expand-figure{font-size:21px}
  .retro-summary{padding:16px}
  .habit-row{grid-template-columns:1fr auto;row-gap:2px}
  .habit-label{grid-column:1/-1}
  .habit-count{justify-self:start}
  .habit-value{justify-self:end}
}
"""

SCRIPT = """
(function(){
  function money(v){
    var n = Number(v || 0);
    return (n < 0 ? '-$' : '$') + Math.abs(n).toLocaleString('en-US',
      {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }
  function esc(s){
    return String(s == null ? '' : s).replace(/[&<>"]/g,
      function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; });
  }

  var root=document.documentElement, KEY='smartpay.theme';
  try{var saved=localStorage.getItem(KEY); if(saved) root.dataset.theme=saved;}catch(e){}
  var btn=document.getElementById('theme');
  function label(){
    var dark = root.dataset.theme==='dark' ||
      (!root.dataset.theme && matchMedia('(prefers-color-scheme:dark)').matches);
    if(btn) btn.textContent = dark ? 'Light' : 'Dark';
  }
  label();
  if(btn) btn.addEventListener('click',function(){
    var dark = root.dataset.theme==='dark' ||
      (!root.dataset.theme && matchMedia('(prefers-color-scheme:dark)').matches);
    root.dataset.theme = dark ? 'light' : 'dark';
    try{localStorage.setItem(KEY,root.dataset.theme);}catch(e){}
    label();
  });

  // Count the headline figures up. Purely decorative: the final text is already
  // in the DOM, so this never invents or alters a number.
  if(!matchMedia('(prefers-reduced-motion:reduce)').matches){
    document.querySelectorAll('.figure[data-count]').forEach(function(el){
      var target=parseFloat(el.dataset.count), final=el.textContent, t0=null;
      function step(ts){
        if(!t0) t0=ts;
        var p=Math.min((ts-t0)/900,1), eased=1-Math.pow(1-p,3);
        el.textContent = p<1
          ? '$'+(target*eased).toLocaleString('en-US',{minimumFractionDigits:2,
              maximumFractionDigits:2})
          : final;
        if(p<1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    });
  }

  // Watch for a newer question and pick it up without a manual refresh, so the
  // dashboard follows the conversation while it is on screen. Polling rather than
  // a socket: the two servers are separate processes and this needs no plumbing.
  var stamp = document.body.dataset.latest || '';
  setInterval(function(){
    fetch('/history.json', {cache:'no-store'}).then(function(r){ return r.json(); })
      .then(function(d){
        var now = d.latest ? (d.latest.key + '|' + (d.latest.asked_at || '')) : '';
        if(now && now !== stamp) location.reload();
      }).catch(function(){ /* the dashboard keeps working offline */ });
  }, 4000);

  // Wallet carousel
  var rail=document.querySelector('.wallet-carousel');
  if(rail){
    var dots=document.querySelector('.carousel-dots');
    var cards=rail.querySelectorAll('.wallet-card');
    function page(){ return Math.max(rail.clientWidth-40,240); }
    document.querySelector('[data-carousel-next]')?.addEventListener('click',
      function(){ rail.scrollBy({left:page(),behavior:'smooth'}); });
    document.querySelector('[data-carousel-prev]')?.addEventListener('click',
      function(){ rail.scrollBy({left:-page(),behavior:'smooth'}); });
    if(dots){
      cards.forEach(function(){ dots.appendChild(document.createElement('i')); });
      var marks=dots.querySelectorAll('i');
      function sync(){
        var i=Math.round(rail.scrollLeft/(rail.scrollWidth/cards.length));
        marks.forEach(function(m,n){ m.classList.toggle('on', n===Math.min(i,cards.length-1)); });
      }
      rail.addEventListener('scroll',sync,{passive:true}); sync();
    }
  }

  // Generic expand/collapse: one delegated handler for every .expand-toggle
  // button on the page (retro, potential-future-savings, institutions, shared
  // data, and each individual enquiry inside the enquiry list).
  document.addEventListener('click', function(e){
    var btn = e.target.closest('.expand-toggle');
    if(!btn) return;
    var body = document.getElementById(btn.getAttribute('aria-controls'));
    if(!body) return;
    var open = btn.getAttribute('aria-expanded') === 'true';
    btn.setAttribute('aria-expanded', String(!open));
    body.hidden = open;
    var container = btn.closest('.expandable');
    if(container) container.classList.toggle('open', !open);
  });

  // Timeline slider: spending history on the left, a mocked Mastercard
  // CommerceGPT forecast on the right, "today" in the middle. Every per-row
  // number lives on the row as data-*, so this reads straight from the DOM.
  var retroSection=document.querySelector('.retro');
  if(retroSection){
    var cfgEl=document.getElementById('retro-data');
    var CFG = cfgEl ? JSON.parse(cfgEl.textContent) : {past_months:1, future_months:1};
    var slider=document.getElementById('retro-slider');
    var timeline=document.getElementById('timeline');
    var rows=Array.prototype.slice.call(document.querySelectorAll('.retro-txn'));
    var reduce = matchMedia('(prefers-reduced-motion:reduce)').matches;
    var predicted=false;

    function update(v){
      var pastWindow = v < 0 ? -v : CFG.past_months;
      var futureWindow = v > 0 ? v : CFG.future_months;
      var activeSide = v < 0 ? 'past' : 'future';
      timeline.classList.toggle('focus-past', v < 0);
      timeline.classList.toggle('focus-future', v > 0);
      // The transaction table on the right follows the slider side.
      var hist=document.getElementById('history-table'), fore=document.getElementById('forecast-table');
      if(hist) hist.hidden = activeSide!=='past';
      if(fore) fore.hidden = activeSide!=='future';

      var pastTotal=0, pastCount=0, feeTotal=0, futureTotal=0, futureCount=0;
      var habitsBy={past:{}, future:{}};
      rows.forEach(function(row){
        var mi = parseInt(row.dataset.mi, 10);
        var side = row.dataset.side;
        var inWindow = side==='past' ? (-mi <= pastWindow) : (mi <= futureWindow);
        row.classList.toggle('out-of-window', !inWindow);
        if(!inWindow) return;
        var g = parseFloat(row.dataset.guaranteed || 0);
        if(side==='past'){
          pastCount++;
          if(row.dataset.kind==='fee'){ feeTotal += parseFloat(row.dataset.avoidable||0); return; }
          pastTotal += g;
        } else {
          futureCount++; futureTotal += g;
        }
        if(row.dataset.improved==='1' && row.dataset.habit){
          var bucket = habitsBy[side];
          var h = bucket[row.dataset.habit] || {count:0,total:0};
          h.count++; h.total += g; bucket[row.dataset.habit]=h;
        }
      });

      // Follow the slider: scroll the active list so the transaction right at
      // the edge of the current window stays in view, instead of leaving the
      // reader to separately scroll a ~420px box to find where the timeline
      // position they just dragged to actually landed. Rows are already in
      // chronological order per side, so the boundary is simply the last
      // still-in-window row before the first out-of-window one.
      var activeList = document.getElementById(activeSide==='past' ? 'retro-txn-list' : 'future-txn-list');
      if(activeList){
        var boundary=null;
        for(var bi=0; bi<rows.length; bi++){
          if(rows[bi].dataset.side!==activeSide) continue;
          if(!rows[bi].classList.contains('out-of-window')) boundary=rows[bi]; else break;
        }
        if(boundary){
          // getBoundingClientRect deltas rather than offsetTop: the list has
          // no declared position, so offsetTop would resolve against whatever
          // ancestor happens to be positioned instead of the scroll container.
          var rowRect = boundary.getBoundingClientRect(), listRect = activeList.getBoundingClientRect();
          var target = activeList.scrollTop + (rowRect.top - listRect.top)
            - activeList.clientHeight/2 + boundary.offsetHeight/2;
          activeList.scrollTop = Math.max(0, target);
        } else {
          activeList.scrollTop = 0;
        }
      }

      document.getElementById('retro-txn-count').textContent = pastCount;
      document.getElementById('retro-total').textContent = money(pastTotal);
      var feeEl=document.getElementById('retro-fee-total'); if(feeEl) feeEl.textContent = money(feeTotal);
      document.getElementById('forecast-months').textContent = (v>0 ? futureWindow : CFG.future_months);
      retroSection.dataset.futureTotal = futureTotal;
      // The forecast figure is driven by the predict animation the first time;
      // after that (or under reduced motion) the slider keeps it in sync.
      if(predicted || reduce) document.getElementById('forecast-total').textContent = money(futureTotal);

      var habits = habitsBy[activeSide];
      var list=document.getElementById('habit-list');
      var ranked=Object.keys(habits).map(function(l){return {label:l,count:habits[l].count,total:habits[l].total};})
        .sort(function(a,b){return b.total-a.total;}).slice(0,8);
      list.innerHTML = ranked.length ? ranked.map(function(h){
        return '<li class="habit-row"><span class="habit-label">'+esc(h.label)+'</span>'
          +'<span class="habit-count">'+h.count+'&times;</span>'
          +'<span class="habit-value">'+money(h.total)+'</span></li>';
      }).join('') : '<li class="habit-row empty">No habit change needed in this window.</li>';
    }

    function predictFuture(){
      if(predicted) return; predicted=true;
      var futureRows = rows.filter(function(r){return r.dataset.side==='future';});
      var target = parseFloat(retroSection.dataset.futureTotal || 0);
      var forecastEl = document.getElementById('forecast-total');
      if(reduce){
        futureRows.forEach(function(r){ r.classList.add('revealed'); });
        forecastEl.textContent = money(target);
        return;
      }
      var ai=document.getElementById('ai-predict');
      if(ai) ai.classList.add('on');
      futureRows.forEach(function(r,i){ setTimeout(function(){ r.classList.add('revealed'); }, 80 + i*20); });
      var t0=null, dur=1500;
      (function step(ts){ if(!t0)t0=ts; var p=Math.min((ts-t0)/dur,1), e=1-Math.pow(1-p,3);
        forecastEl.textContent = money(target*e);
        if(p<1){ requestAnimationFrame(step); }
        else { forecastEl.textContent = money(target); if(ai) ai.classList.remove('on'); }
      })();
    }

    slider.addEventListener('input', function(){ update(parseInt(slider.value,10)); });
    update(0);
    if(reduce){ predictFuture(); }
    // Kick off the CommerceGPT prediction the first time the panel is opened.
    var toggle=document.getElementById('retro-toggle');
    if(toggle){ toggle.addEventListener('click', function(){
      setTimeout(function(){
        var body=document.getElementById('retro-body');
        if(body && !body.hidden) predictFuture();
      }, 280);
    }); }
  }
})();
"""



def render_alex_dashboard(profile: FinancialProfile) -> str:
    """Render the full dashboard for the demo consumer."""
    from app import analytics, history
    from app.engines import priceless as priceless_engine
    from app.services.smartpay import SmartPayService

    service = SmartPayService()
    wallet = service.optimise_wallet()["data"]
    flipper_list = wallet.get("flipper_offers", [])
    priceless_offers = priceless_engine.historic_matches(profile)

    entries = history.load()
    if entries and entries[0].get("plan"):
        latest = entries[0]
    else:
        # Nothing asked yet: show the rehearsed scenario so the page is never empty,
        # and do NOT record it -- rendering a page is not a question, and recording
        # here would put a phantom entry at the top of the user's own history.
        result = service.optimise_itinerary(record=False)
        plan = result["data"]
        latest = {
            "key": plan["itinerary_id"],
            "title": "Walt Disney World, October",
            "asked_at": None,
            "guaranteed": plan["incremental_guaranteed"],
            "total": plan["itinerary_total"],
            "items": len(plan["recommendations"]),
            "plan": plan,
        }
        entries = [latest]

    active_key = latest.get("key", "")

    accumulated = analytics.accumulated_savings(profile)
    retrospective = analytics.retrospective_history(profile)
    projected = analytics.projected_history(profile)
    potential = analytics.potential_future_savings(
        Decimal(wallet["recommendation"]["net_annual_incremental_value"])
    )

    institutions = ", ".join(
        sorted({ISSUER_NAME.get(a.institution, a.institution.replace("_", " ").title())
                for a in profile.accounts})
    )
    # FinancialProfile carries a customer_id, not a human name -- Open Finance does
    # not model "full name" as a first-class field. DEMO_CUSTOMER_NAME is
    # presentation-layer knowledge for this one demo persona, same as the name
    # already printed in the page <title> and the BankSym seed script.
    full_name = DEMO_CUSTOMER_NAME
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alex · SmartPay by Mastercard</title>
<link rel="icon" href="/static/logos/mastercard-favicon.svg" type="image/svg+xml">
<link rel="alternate icon" href="/static/logos/mastercard.svg" type="image/svg+xml">
<link rel="mask-icon" href="/static/logos/mastercard-favicon.svg" color="#EB001B">
<style>{CSS}</style>
</head>
<body data-latest="{_t(active_key)}|{_t(latest.get('asked_at') or '')}">
<header class="topbar">
  <div class="wrap">
    <div class="brand">
      <svg class="brand-mark" viewBox="0 0 48 30" aria-hidden="true">
        <circle cx="17" cy="15" r="14" fill="#EB001B"/>
        <circle cx="31" cy="15" r="14" fill="#F79E1B"/>
        <path fill="#FF5F00" d="M24 4.2a14 14 0 0 0 0 21.6 14 14 0 0 0 0-21.6z"/>
      </svg>
      SmartPay by Mastercard
    </div>
    <div class="status">
      <span class="dot" aria-hidden="true"></span>
      <span>Open Finance · FDX · {_t(institutions)} connected</span>
      <button class="theme-toggle" id="theme" type="button">Dark</button>
    </div>
  </div>
</header>
<main class="wrap">
  {_header(full_name, accumulated, potential["wallet_annual"])}
  {_flipper_section(flipper_list)}
  {_potential_section(potential, entries, active_key)}
  {_retrospective_section(retrospective, accumulated, projected)}
  {_priceless_section(priceless_offers)}
  {_shared_data_section(profile)}
  {_wallet_advice(wallet)}
  <footer class="foot">
    <p>Alex Morgan is a synthetic demo consumer. Accounts, cards and transaction
       history are generated for demonstration and are not real financial data.</p>
    <p>Potential savings over last year is computed by re-scoring every real
       historical transaction against every card in the wallet; it excludes
       itinerary-specific offers, which carry redemption caps that do not apply
       to arbitrary past purchases. Offers marked as simulated are modelled on
       real Mastercard card-linked offer mechanics and are not live offers.
       Points valued at 1.0¢.</p>
  </footer>
</main>
<script>{SCRIPT}</script>
</body>
</html>"""
