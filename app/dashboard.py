"""Server-rendered SmartPay dashboard.

The point of this page is not to show Alex's bank data -- an aggregator does that.
It is to show SmartPay's *answer*: what Alex would pay, what they should pay, and
the money between the two. So the page leads with the number and works back to the
evidence, rather than opening with a table of transactions.

Charts are inline SVG with direct labels. Colours come from the validated
categorical palette, which fails the 3:1 contrast check for three light-mode
slots -- hence labels on every bar rather than a legend-only chart.
"""

from __future__ import annotations

import html
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from app.knowledge import benefits
from app.models.financial import FinancialProfile, PaymentInstrument
from app.money import fmt

CARD_ART = {
    "citi_strata_premier": "/static/cards/citi_strata_premier.webp",
    "citi_double_cash": "/static/cards/citi_double_cash.webp",
    "citi_aa_platinum_select": "/static/cards/citi_aa_platinum_select.webp",
    "chase_sapphire_preferred": "/static/cards/chase_sapphire_preferred.png",
    "chase_freedom_unlimited": "/static/cards/chase_freedom_unlimited.png",
}

ISSUER_LOGO = {"citi": "/static/logos/citi.svg", "chase": "/static/logos/chase.svg"}

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
    return text if len(text) <= budget else text[: budget - 1].rstrip() + "\u2026"


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
    bar_h, gap, width_total = 32, 12, 660
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
        # ~7.2px per character at 12.5px; keep the value inside only with room to spare.
        inside = w > len(amount) * 7.2 + 22
        vx = label_w + w - 10 if inside else label_w + w + 9
        out.append(
            f'<g class="bar-row" tabindex="0" role="listitem" '
            f'aria-label="{_t(name)}: {_t(amount)}">'
            f"<title>{_t(name)} \u2014 {_t(amount)}</title>"
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
    the plan payload, so a second bar would have had nothing real to plot -- which
    is what it did before, drawing a 2px stub and calling it "your habit".
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
# Sections
# ---------------------------------------------------------------------------

def _hero(plan: dict, title: str, asked: object) -> str:
    guaranteed = Decimal(plan["incremental_guaranteed"])
    estimated = Decimal(plan["incremental_estimated"])
    points = plan["incremental_points"]
    total = Decimal(plan["itinerary_total"])
    return f"""
    <section class="hero" aria-labelledby="hero-h">
      <div class="hero-copy">
        <p class="eyebrow">Latest question · {_t(title)} · {_t(_ago(asked))}</p>
        <h1 id="hero-h">SmartPay found
          <span class="figure" data-count="{guaranteed}">{_money(guaranteed)}</span>
          you would otherwise leave behind.</h1>
        <p class="lede">On a {_money(total)} trip, paying the way you normally do
          costs you real money. Here is the difference, line by line, with the
          issuer rule behind every number.</p>
      </div>
      <dl class="hero-stats">
        <div class="stat accent">
          <dt>Guaranteed savings</dt><dd>{_money(guaranteed)}</dd>
          <p>Credits, discounts and waived fees</p>
        </div>
        <div class="stat">
          <dt>Estimated rewards</dt><dd>{_money(estimated)}</dd>
          <p>Valued at 1.0¢ per point</p>
        </div>
        <div class="stat">
          <dt>Extra points</dt><dd>{points:,}</dd>
          <p>Above your usual cards</p>
        </div>
      </dl>
    </section>"""


def _plan_section(plan: dict) -> str:
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
            '<span class="chip tie" title="Options were worth exactly the same">'
            "tie · disclosed</span>" if r["tiebreak_note"] else ""
        )
        why = "".join(
            f'<li>{_t(b)}</li>' for b in r["benefits"]
        ) + "".join(
            f'<li>{_t(o["label"])} — {_money(o["value"])}</li>' for o in r["offers"]
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
          {f'<ul class="plan-why">{why}</ul>' if why else ''}
        </article>""")

    return f"""
    <section class="panel" aria-labelledby="plan-h">
      <header class="panel-head">
        <div>
          <h2 id="plan-h">How you would pay, versus how you should</h2>
          <p>Baseline is inferred from 12 months of your own transactions, not assumed.</p>
        </div>
        <div class="legend" role="note">
          <span><i class="sw opt"></i>Value found, relative to the largest line</span>
        </div>
      </header>
      <div class="plan">{''.join(rows)}</div>
    </section>"""


def _sources_section(plan: dict) -> str:
    sources: list[tuple[str, Decimal]] = []
    for r in plan["recommendations"]:
        for b in r["benefits"]:
            value = Decimal(r["guaranteed_savings"])
            if value > 0 and not r["offers"]:
                sources.append((b, value))
        for o in r["offers"]:
            sources.append((f'{o["merchant"]} offer', Decimal(o["value"])))
            remainder = Decimal(r["guaranteed_savings"]) - Decimal(o["value"])
            if remainder > 0 and r["benefits"]:
                sources.append((r["benefits"][0], remainder))
    sources = sorted(sources, key=lambda kv: -kv[1])
    return f"""
    <section class="panel" aria-labelledby="src-h">
      <header class="panel-head">
        <div>
          <h2 id="src-h">Where the guaranteed value comes from</h2>
          <p>Every figure is a published issuer or network rule, not an estimate.</p>
        </div>
      </header>
      <div class="chart-wrap" role="list">{_bar_chart(sources, label_w=210, budget=32)}</div>
    </section>"""


def _spend_section(profile: FinancialProfile) -> str:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for txn in profile.spend_transactions:
        totals[txn.category.value] += txn.amount
    rows = sorted(totals.items(), key=lambda kv: -kv[1])[:9]
    labelled = [(CATEGORY_LABEL.get(k, k.title()), v) for k, v in rows]
    total = sum(totals.values(), Decimal(0))
    months = len({t.posted_at.strftime("%Y-%m") for t in profile.spend_transactions}) or 1
    return f"""
    <section class="panel" aria-labelledby="spend-h">
      <header class="panel-head">
        <div>
          <h2 id="spend-h">Where your money goes</h2>
          <p>{len(profile.spend_transactions)} payments across
             {len({a.institution for a in profile.accounts})} institutions,
             {months} months.</p>
        </div>
        <div class="mini-stats">
          <div><span>{_money(total)}</span><small>Total</small></div>
          <div><span>{_money(total / months)}</span><small>Monthly average</small></div>
        </div>
      </header>
      <div class="chart-wrap" role="list">{_bar_chart(labelled)}</div>
    </section>"""


def _wallet_section(profile: FinancialProfile) -> str:
    cards = []
    for i, inst in enumerate(profile.instruments):
        product = inst.product
        if product is None or inst.card is None:
            continue
        art = CARD_ART.get(product.product_id, "")
        logo = ISSUER_LOGO.get(product.issuer, "")
        tier = product.network_tier.value.replace("_", " ").title()
        # "Mastercard World Elite" is too long for the card column: it overflowed its
        # own chip and collided with the annual-fee pill. The tier alone identifies
        # the product, and the network mark is already printed on the card art.
        network_label = _t(tier if tier != "None" else product.network.value.title())
        top = sorted(product.reward_rules, key=lambda r: -r.multiplier)[:3]
        rules = "".join(
            f'<li><b>{_t(r.multiplier.normalize())}×</b> {_t(r.description)}</li>'
            for r in top
        ) or "<li>Base earn only</li>"
        perks = "".join(
            f"<li>{_t(b.display_name)}</li>" for b in _card_benefits(inst)[:3]
        )
        fee = product.annual_fee
        cards.append(f"""
        <article class="wallet-card art-{i}">
          <div class="card-art">
            <img src="{_t(art)}" alt="{_t(product.display_name)}" loading="lazy"
                 width="300" height="190">
          </div>
          <div class="card-body">
            <header>
              {f'<img class="issuer" src="{_t(logo)}" alt="{_t(product.issuer.title())}" '
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
    <section class="panel" aria-labelledby="wallet-h">
      <header class="panel-head">
        <div>
          <h2 id="wallet-h">Your wallet</h2>
          <p>{len(cards)} cards, read live over FDX from two institutions.</p>
        </div>
        <div class="carousel-nav">
          <button type="button" data-carousel-prev aria-label="Previous cards">‹</button>
          <button type="button" data-carousel-next aria-label="Next cards">›</button>
        </div>
      </header>
      <div class="wallet-carousel" tabindex="0">{''.join(cards)}</div>
      <div class="carousel-dots" aria-hidden="true"></div>
    </section>"""


def _wallet_advice(wallet: dict) -> str:
    rec = wallet["recommendation"]
    delta = Decimal(rec["net_annual_incremental_value"])
    current = Decimal(rec["current_wallet_value"])
    drivers = "".join(f"<li>{_t(d)}</li>" for d in rec["drivers"][:5])
    return f"""
    <section class="panel closing" aria-labelledby="adv-h">
      <header class="panel-head">
        <div>
          <h2 id="adv-h">And one more thing</h2>
          <p>Your wallet is not matched to what you are predicted to spend.</p>
        </div>
      </header>
      <div class="advice">
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
    </section>"""


def _history_section(entries: list[dict], active_key: str) -> str:
    """What SmartPay has been asked, most recent first.

    Present even with a single entry: the point is to show the dashboard tracks the
    conversation rather than displaying one frozen scenario.
    """
    if not entries:
        return ""
    cards = []
    for e in entries:
        is_active = e.get("key") == active_key
        guaranteed = Decimal(str(e.get("guaranteed", "0")))
        cards.append(f"""
        <li class="q{' on' if is_active else ''}">
          <span class="q-when">{_t(_ago(e.get("asked_at")))}</span>
          <h3>{_t(e.get("title", "Untitled"))}</h3>
          <p class="q-figures">
            <b>{_money(guaranteed)}</b>
            <span>{_t(e.get("items", 0))} items · {_money(e.get("total", "0"))}</span>
          </p>
          {'<span class="q-tag">Showing now</span>' if is_active else ''}
        </li>""")
    return f"""
    <section class="panel" aria-labelledby="hist-h">
      <header class="panel-head">
        <div>
          <h2 id="hist-h">Everything you have asked</h2>
          <p>Each question SmartPay answered, newest first. The dashboard follows
             the most recent one.</p>
        </div>
      </header>
      <ul class="qlist">{''.join(cards)}</ul>
    </section>"""


def _provenance() -> str:
    seen: dict[tuple[str, str], str] = {}
    for b in benefits():
        e = b.evidence
        if e.source_url:
            seen[(e.source_name, e.source_url)] = (
                e.verified_at.isoformat() if e.verified_at else "—"
            )
    rows = "".join(
        f'<tr><td>{_t(name)}</td><td>{_t(date)}</td>'
        f'<td><a href="{_t(url)}" rel="noopener noreferrer" target="_blank">source</a></td></tr>'
        for (name, url), date in sorted(seen.items())
    )
    return f"""
    <section class="panel provenance" aria-labelledby="prov-h">
      <header class="panel-head">
        <div>
          <h2 id="prov-h">Every rule, and where it came from</h2>
          <p>Read off live issuer and network pages. Nothing here is estimated.</p>
        </div>
      </header>
      <table class="prov-table">
        <thead><tr><th>Source</th><th>Verified</th><th></th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
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
  --series-1:#2a78d6; --series-2:#eb6834; --series-3:#1baf7a; --series-4:#eda100;
  --series-5:#e87ba4; --series-6:#008300; --series-7:#4a3aa7; --series-8:#e34948;
  --radius:16px; --shadow:0 1px 2px rgba(17,17,16,.05),0 8px 24px -12px rgba(17,17,16,.15);
  --max:1180px;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --bg:#111110; --surface:#1a1a19; --surface-2:#212120; --line:#302f2c;
    --ink:#f7f7f5; --ink-2:#c3c2b7; --ink-3:#8e8c84;
    --brand-ink:#FF8A73;
    --good:#5fd0a4; --good-bg:#12281f;
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
  --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70; --series-4:#c98500;
  --series-5:#d55181; --series-6:#008300; --series-7:#9085e9; --series-8:#e66767;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 28px -14px rgba(0,0,0,.7);
}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,Roboto,sans-serif;
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
.topbar .wrap{display:flex;align-items:center;gap:16px;height:60px}
.brand{display:flex;align-items:center;gap:10px;font-weight:650;letter-spacing:-.02em}
.brand-mark{width:30px;height:19px;flex:none}
.status{margin-left:auto;display:flex;align-items:center;gap:8px;color:var(--ink-2);font-size:13px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--good);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--good) 22%,transparent)}
.theme-toggle{border:1px solid var(--line);background:var(--surface);color:var(--ink-2);
  border-radius:999px;height:32px;padding:0 13px;font:inherit;font-size:13px;cursor:pointer}
.theme-toggle:hover{color:var(--ink);border-color:var(--ink-3)}

/* hero */
.hero{display:grid;grid-template-columns:1.35fr 1fr;gap:40px;align-items:center;
  padding:56px 0 40px}
.eyebrow{font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);
  font-weight:600;margin-bottom:14px}
.hero h1{font-size:clamp(30px,4.4vw,50px);font-weight:680;max-width:19ch}
.hero h1 .figure{
  background:linear-gradient(96deg,var(--brand) 8%,var(--brand-3) 52%,var(--brand-2) 96%);
  -webkit-background-clip:text;background-clip:text;color:transparent;white-space:nowrap}
.lede{margin-top:18px;color:var(--ink-2);max-width:52ch;font-size:16px}
.hero-stats{display:grid;gap:12px;margin:0}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px 18px;box-shadow:var(--shadow)}
.stat.accent{border-color:color-mix(in srgb,var(--brand) 34%,var(--line));
  background:linear-gradient(180deg,color-mix(in srgb,var(--brand) 5%,var(--surface)),var(--surface))}
.stat dt{font-size:12.5px;color:var(--ink-2);font-weight:550}
.stat dd{margin:2px 0 0;font-size:29px;font-weight:660;letter-spacing:-.03em}
.stat p{font-size:12px;color:var(--ink-3);margin-top:2px}

/* panels */
.panel{background:var(--surface);border:1px solid var(--line);border-radius:20px;
  padding:26px;margin-bottom:22px;box-shadow:var(--shadow)}
.panel-head{display:flex;gap:20px;align-items:flex-start;justify-content:space-between;
  margin-bottom:22px;flex-wrap:wrap}
.panel-head h2{font-size:21px;font-weight:640}
.panel-head p{color:var(--ink-2);font-size:14px;margin-top:5px;max-width:62ch}
.legend{display:flex;gap:14px;font-size:12.5px;color:var(--ink-2);align-items:center}
.legend i{width:11px;height:11px;border-radius:3px;display:inline-block;margin-right:6px;
  vertical-align:-1px}
.sw.base{background:var(--ink-3)}
.sw.opt{background:linear-gradient(90deg,var(--brand),var(--brand-2))}
.mini-stats{display:flex;gap:22px}
.mini-stats span{display:block;font-size:19px;font-weight:640;letter-spacing:-.02em}
.mini-stats small{color:var(--ink-3);font-size:11.5px}

/* plan */
.plan{display:grid;gap:10px}
.plan-row{display:grid;grid-template-columns:1.15fr 2fr .9fr;gap:22px;align-items:center;
  padding:16px 18px;border:1px solid var(--line);border-radius:14px;background:var(--surface-2);
  transition:border-color .18s,transform .18s}
.plan-row.has-gain{border-left:3px solid var(--brand)}
.plan-row:hover{border-color:var(--ink-3);transform:translateY(-1px)}
.plan-item h3{font-size:14.5px;font-weight:600}
.plan-item .amount{color:var(--ink-3);font-size:13px}
.plan-swap{display:grid;grid-template-columns:1fr auto 1fr;gap:14px;align-items:center}
.plan-swap .tag{display:block;font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink-3);font-weight:600;margin-bottom:3px}
.plan-swap strong{font-size:13.5px;font-weight:600;display:block;line-height:1.3}
.plan-swap .from strong{color:var(--ink-2);font-weight:500}
.plan-swap .prob{font-size:11.5px;color:var(--ink-3)}
.arrow{color:var(--brand-ink);font-size:19px;font-weight:700}
.chips{display:flex;gap:5px;flex-wrap:wrap;margin-top:4px}
.chip{display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:600;
  padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--ink-2);
  background:var(--surface);white-space:nowrap;flex:none}
.chip.portal{border-color:color-mix(in srgb,var(--brand) 40%,var(--line));
  color:var(--brand-ink);background:color-mix(in srgb,var(--brand) 7%,transparent)}
.chip.tie{border-style:dashed}
.chip.mc{border-color:color-mix(in srgb,var(--brand) 40%,var(--line));color:var(--brand-ink)}
.chip.free{color:var(--good);border-color:color-mix(in srgb,var(--good) 40%,var(--line))}
.plan-value{text-align:right}
.plan-value .gain{display:block;font-size:20px;font-weight:660;letter-spacing:-.02em}
.plan-value .sub{font-size:11.5px;color:var(--ink-3)}
.delta{width:100%;max-width:210px;height:12px;margin-left:auto;display:block;margin-top:7px}
.d-track{fill:var(--line);opacity:.6}
.d-opt{fill:var(--brand)}
.bar-value.inside{fill:#fff}
.plan-why{grid-column:1/-1;margin:2px 0 0;padding:10px 0 0;border-top:1px dashed var(--line);
  list-style:none;display:flex;gap:8px;flex-wrap:wrap}
.plan-why li{font-size:11.5px;color:var(--good);background:var(--good-bg);
  padding:3px 9px;border-radius:999px}

/* charts */
.chart-wrap{overflow-x:auto}
.chart{width:100%;min-width:520px;height:auto;display:block}
.bar-track{fill:var(--line);opacity:.5}
.bar{transition:opacity .16s}
.bar-row:hover .bar,.bar-row:focus .bar{opacity:.78}
.bar-row:focus{outline:2px solid var(--brand);outline-offset:2px;border-radius:6px}
.bar-label{font-size:12.5px;fill:var(--ink-2)}
.bar-value{font-size:12.5px;fill:var(--ink);font-weight:600}
.ring{width:64px;height:64px;flex:none}
.ring-track{fill:none;stroke:var(--line);stroke-width:7}
.ring-fill{fill:none;stroke:var(--brand);stroke-width:7;stroke-linecap:round}
.ring-text{font-size:15px;font-weight:660;fill:var(--ink);text-anchor:middle}

/* wallet */
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
.card-body{padding:14px 16px 16px;display:flex;flex-direction:column;gap:9px}
.issuer{height:17px;width:auto;object-fit:contain;object-position:left;display:block;
  margin-bottom:6px}
.card-body h3{font-size:14px;font-weight:640;line-height:1.3}
.card-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.card-rules,.card-perks{list-style:none;margin:0;padding:0;display:grid;gap:5px}
.card-rules li{font-size:12px;color:var(--ink-2)}
.card-rules b{color:var(--ink);font-weight:660}
.card-perks li{font-size:11.5px;color:var(--good);background:var(--good-bg);
  padding:3px 8px;border-radius:8px}
.carousel-nav{display:flex;gap:6px}
.carousel-nav button{width:32px;height:32px;border-radius:50%;border:1px solid var(--line);
  background:var(--surface);color:var(--ink-2);font-size:17px;cursor:pointer;line-height:1}
.carousel-nav button:hover{color:var(--ink);border-color:var(--ink-3)}
.carousel-dots{display:flex;gap:5px;justify-content:center;margin-top:12px}
.carousel-dots i{width:5px;height:5px;border-radius:50%;background:var(--line)}
.carousel-dots i.on{background:var(--brand);width:16px;border-radius:3px}

/* closing */
.closing{background:linear-gradient(150deg,color-mix(in srgb,var(--brand) 7%,var(--surface)),
  color-mix(in srgb,var(--brand-2) 5%,var(--surface)));
  border-color:color-mix(in srgb,var(--brand) 24%,var(--line))}
.advice{display:grid;grid-template-columns:1.5fr 1fr;gap:28px;align-items:center}
.verdict{font-size:19px;font-weight:600;letter-spacing:-.02em;max-width:34ch}
.advice-figure{margin-top:14px}
.advice-figure .figure{font-size:38px;font-weight:680;letter-spacing:-.03em;
  background:linear-gradient(96deg,var(--brand),var(--brand-2));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.advice-figure small{display:block;color:var(--ink-2);font-size:12.5px}
.advice-meta{display:flex;gap:18px;align-items:flex-start}
.advice-meta ul{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.advice-meta li{font-size:12.5px;color:var(--ink-2)}

/* asked-questions list */
.qlist{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.q{position:relative;display:grid;grid-template-columns:1fr auto;gap:16px;align-items:center;
  padding:13px 16px;border:1px solid var(--line);border-radius:13px;background:var(--surface-2)}
.q.on{border-color:color-mix(in srgb,var(--brand) 42%,var(--line));
  background:linear-gradient(100deg,color-mix(in srgb,var(--brand) 6%,var(--surface-2)),
  var(--surface-2))}
.q-when{font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-3);
  font-weight:600}
.q h3{font-size:14.5px;font-weight:600;margin-top:3px}
.q-figures{grid-row:1/3;grid-column:2;text-align:right;white-space:nowrap}
.q-figures b{display:block;font-size:17px;font-weight:660;letter-spacing:-.02em}
.q-figures span{font-size:11.5px;color:var(--ink-3)}
.q-tag{grid-column:1;font-size:10.5px;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;color:var(--brand-ink)}

/* provenance */
.prov-table{width:100%;border-collapse:collapse;font-size:13px}
.prov-table th{text-align:left;font-size:11px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink-3);padding:0 12px 9px 0;font-weight:600}
.prov-table td{padding:9px 12px 9px 0;border-top:1px solid var(--line);color:var(--ink-2)}
.prov-table a{color:var(--brand-ink);text-decoration:none;font-weight:600}
.prov-table a:hover{text-decoration:underline}

footer.foot{padding:26px 0 56px;color:var(--ink-3);font-size:12px;display:grid;gap:6px}

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
  .hero{grid-template-columns:1fr;gap:28px;padding:34px 0 26px}
  .plan-row{grid-template-columns:1fr;gap:14px}
  .plan-value{text-align:left}
  .delta{margin-left:0}
  .advice{grid-template-columns:1fr}
  .panel{padding:20px}
}
@media (max-width:560px){
  .wrap{padding:0 16px}
  /* The connection string wraps to two lines and doubles the bar's height on a
     phone. The status dot and the toggle carry the same meaning in less room. */
  .status span:not(.dot){display:none}
  .plan-swap{grid-template-columns:1fr;gap:8px}
  .arrow{transform:rotate(90deg);width:min-content}
  .mini-stats{gap:14px}
}
"""

SCRIPT = """
(function(){
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
})();
"""


def render_alex_dashboard(profile: FinancialProfile) -> str:
    """Render the full dashboard for the demo consumer."""
    from app import history
    from app.services.smartpay import SmartPayService

    service = SmartPayService()
    wallet = service.optimise_wallet()["data"]

    entries = history.load()
    if entries and entries[0].get("plan"):
        latest = entries[0]
        plan = latest["plan"]
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
        }
        entries = []

    title = latest.get("title") or "Latest itinerary"
    active_key = latest.get("key", "")

    institutions = ", ".join(sorted({a.institution.title() for a in profile.accounts}))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alex · SmartPay Open Finance</title>
<link rel="icon" href="/static/logos/mastercard.svg" type="image/svg+xml">
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
      SmartPay
    </div>
    <div class="status">
      <span class="dot" aria-hidden="true"></span>
      <span>Open Finance · FDX · {_t(institutions)} connected</span>
      <button class="theme-toggle" id="theme" type="button">Dark</button>
    </div>
  </div>
</header>
<main class="wrap">
  {_hero(plan, title, latest.get('asked_at'))}
  {_plan_section(plan)}
  {_sources_section(plan)}
  {_spend_section(profile)}
  {_wallet_section(profile)}
  {_wallet_advice(wallet)}
  {_history_section(entries, active_key)}
  {_provenance()}
  <footer class="foot">
    <p>Alex Morgan is a synthetic demo consumer. Accounts, cards and transaction
       history are generated for demonstration and are not real financial data.</p>
    <p>Offers marked as simulated are modelled on real Mastercard card-linked offer
       mechanics and are not live offers. Points valued at 1.0¢.</p>
  </footer>
</main>
<script>{SCRIPT}</script>
</body>
</html>"""
