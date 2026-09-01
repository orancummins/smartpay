"""Server-rendered Open Finance dashboard for the live demo."""

from __future__ import annotations

import html
from collections import defaultdict
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


def _text(value: object) -> str:
    return html.escape(str(value))


def _label(value: object) -> str:
    return _text(str(value).replace("_", " ").title())


def _money(value: Decimal) -> str:
    return _text(fmt(value))


def _card_benefits(instrument: PaymentInstrument) -> list:
    product = instrument.product
    if product is None:
        return []
    return [
        benefit
        for benefit in benefits()
        if (
            (benefit.eligible_products and product.product_id in benefit.eligible_products)
            or (benefit.network_tiers and product.network_tier in benefit.network_tiers)
        )
    ]


def _render_card(instrument: PaymentInstrument, index: int) -> str:
    product = instrument.product
    card = instrument.card
    if product is None or card is None:
        return ""

    network = product.network.value.title()
    tier = product.network_tier.value.replace("_", " ").title()
    reward_rules = "".join(
        f"""
        <tr>
          <td><strong>{_text(rule.multiplier)}x</strong></td>
          <td>{_text(rule.description)}</td>
          <td>{_label(rule.reward_currency.value)}</td>
          <td>{_label(', '.join(channel.value for channel in rule.required_channels) or 'Any')}</td>
        </tr>"""
        for rule in product.reward_rules
    )
    card_benefits = _card_benefits(instrument)
    benefit_items = "".join(
        f"""
        <li>
          <span class="benefit-mark">+</span>
          <span><strong>{_text(benefit.display_name)}</strong><small>{_text(benefit.description)}</small></span>
        </li>"""
        for benefit in card_benefits
    )
    soft_items = "".join(
        f'<li><span class="benefit-mark">+</span><span>{_text(item)}</span></li>'
        for item in product.soft_benefits
    )
    source = product.evidence
    source_link = (
        f'<a href="{_text(source.source_url)}" target="_blank" rel="noreferrer">View issuer source</a>'
        if source.source_url
        else "No source URL"
    )

    return f"""
    <article class="card-detail" data-search="{_text(product.display_name.lower())} {_text(product.issuer.lower())} {network.lower()}">
      <div class="payment-card art-{_text(product.product_id)}">
        <img src="{CARD_ART[product.product_id]}" alt="{_text(product.display_name)} card art" width="306" height="192">
        <span class="art-cleanup" aria-hidden="true"></span>
        <span class="actual-card-mask">Alex's card · •••• {_text(card.mask)}</span>
      </div>
      <div class="card-copy">
        <div class="section-heading compact">
          <div><p class="eyebrow">{_text(product.issuer.title())} · {network} {tier}</p><h3>{_text(product.display_name)}</h3></div>
          <span class="status"><i></i> Connected</span>
        </div>
        <div class="card-stats">
          <div><span>Annual fee</span><strong>{_money(product.annual_fee)}</strong></div>
          <div><span>Foreign transaction fee</span><strong>{_text(product.foreign_transaction_fee_pct)}%</strong></div>
          <div><span>Base earn</span><strong>{_text(product.base_multiplier)}x</strong></div>
          <div><span>Opened</span><strong>{card.opened_at.strftime('%b %Y')}</strong></div>
        </div>
        <details>
          <summary>Rewards, benefits and source <span>{len(product.reward_rules) + len(card_benefits) + len(product.soft_benefits)} details</span></summary>
          <div class="details-body">
            <h4>Reward rules</h4>
            <div class="table-scroll"><table class="rules"><thead><tr><th>Rate</th><th>Eligible spend</th><th>Currency</th><th>Channel</th></tr></thead><tbody>{reward_rules}</tbody></table></div>
            <h4>Card benefits</h4>
            <ul class="benefits">{benefit_items or '<li>No additional priced benefits in the knowledge base.</li>'}{soft_items}</ul>
            <div class="source"><span>Verified {_text(source.verified_at or 'not dated')} · {_label(source.confidence.value)}</span>{source_link}</div>
          </div>
        </details>
      </div>
    </article>"""


def _render_wallet_preview(instrument: PaymentInstrument, index: int) -> str:
    product = instrument.product
    card = instrument.card
    if product is None or card is None:
        return ""
    return f"""
    <button class="wallet-card art-{_text(product.product_id)}" type="button" data-card-index="{index}"
      data-name="{_text(product.display_name)}"
      data-meta="{_text(product.issuer.title())} · {_text(product.network.value.title())} · •••• {_text(card.mask)}"
      aria-label="Show {_text(product.display_name)}">
      <img src="{CARD_ART[product.product_id]}" alt="" width="306" height="192">
      <span class="art-cleanup" aria-hidden="true"></span>
    </button>"""


def render_alex_dashboard(profile: FinancialProfile) -> str:
    accounts = {account.account_id: account for account in profile.accounts}
    cards = [instrument for instrument in profile.instruments if instrument.is_card]
    spend = profile.spend_transactions
    total_spend = sum((transaction.amount for transaction in spend), Decimal("0"))
    total_income = abs(sum(
        (transaction.amount for transaction in profile.transactions if transaction.transaction_type.value == "income"),
        Decimal("0"),
    ))
    dates = [transaction.posted_at for transaction in profile.transactions]

    category_totals: dict[str, Decimal] = defaultdict(Decimal)
    for transaction in spend:
        category_totals[transaction.category.value] += transaction.amount
    ranked_categories = sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
    largest_category = ranked_categories[0][1] if ranked_categories else Decimal("1")
    chart_colors = ("#635bff", "#00a6a6", "#ff7a59", "#f4b740", "#2979c4", "#d9dee8")
    chart_items = ranked_categories[:5]
    chart_total = sum((amount for _, amount in ranked_categories), Decimal("0"))
    chart_stops = []
    chart_legend = []
    chart_position = Decimal("0")
    for index, (category, amount) in enumerate(chart_items):
      percentage = amount / chart_total * 100 if chart_total else Decimal("0")
      relative_width = amount / largest_category * 100 if largest_category else Decimal("0")
      next_position = chart_position + percentage
      chart_stops.append(
        f"{chart_colors[index]} {chart_position:.2f}% {next_position:.2f}%"
      )
      chart_legend.append(
        f'<li><div class="legend-line"><span class="legend-name"><i style="background:{chart_colors[index]}"></i>{_label(category)}</span>'
        f'<strong>{_money(amount)} <em>{percentage:.0f}%</em></strong></div>'
        f'<div class="spend-track"><i style="--bar:{relative_width:.1f}%;background:{chart_colors[index]}"></i></div></li>'
      )
      chart_position = next_position
    chart_stops.append(f"{chart_colors[-1]} {chart_position:.2f}% 100%")
    categories_html = "".join(
        f"""
        <div class="category-row">
          <span>{_label(category)}</span>
          <div class="bar"><i style="width:{(amount / largest_category * 100):.1f}%"></i></div>
          <strong>{_money(amount)}</strong>
        </div>"""
        for category, amount in ranked_categories[:10]
    )

    accounts_html = "".join(
        f"""
        <div class="account-row" data-search="{_text(account.display_name.lower())} {_text(account.institution.lower())}">
          <div class="bank-logo {account.institution}"><img src="/static/logos/{_text(account.institution)}.svg" alt="{_text(account.institution.title())}"></div>
          <div><strong class="account-name">{_text(account.display_name)}</strong><span>{_label(account.account_type.value)} · •••• {_text(account.mask)}</span></div>
          <div class="account-bank">{_text(account.institution.title())}<span>Connected</span></div>
        </div>"""
        for account in profile.accounts
    )

    cards_html = "".join(_render_card(card, index) for index, card in enumerate(cards))
    transaction_rows = "".join(
        f"""
        <tr data-transaction data-search="{_text(transaction.description.lower())} {_text(transaction.merchant.lower())} {_text(transaction.category.value)} {_text(accounts[transaction.account_id].display_name.lower())}" data-type="{_text(transaction.transaction_type.value)}">
          <td><span class="merchant-icon">{_text(transaction.merchant[:1].upper())}</span><span class="merchant"><strong>{_text(transaction.description.title())}</strong><small>{_text(transaction.transaction_id)}</small></span></td>
          <td>{transaction.posted_at.strftime('%b %d, %Y')}</td>
          <td><span class="category-pill">{_label(transaction.category.value)}</span></td>
          <td>{_text(accounts[transaction.account_id].display_name)}</td>
          <td class="amount {'credit' if transaction.amount < 0 else ''}">{'-' if transaction.amount >= 0 else '+'}{_money(abs(transaction.amount))}</td>
        </tr>"""
        for transaction in sorted(profile.transactions, key=lambda item: (item.posted_at, item.transaction_id), reverse=True)
    )

    wallet_preview = "".join(
      _render_wallet_preview(card, index) for index, card in enumerate(cards)
    )
    wallet_dots = "".join(
      f'<button class="carousel-dot{(" active" if index == 0 else "")}" '
      f'data-carousel-dot="{index}" type="button" aria-label="Show card {index + 1}"></button>'
      for index in range(len(cards))
    )
    first_card = cards[0]
    first_product = first_card.product
    first_instance = first_card.card

    return _PAGE.replace("{{ACCOUNTS}}", accounts_html).replace(
        "{{CARDS}}", cards_html
    ).replace("{{WALLET_PREVIEW}}", wallet_preview).replace(
        "{{WALLET_DOTS}}", wallet_dots
    ).replace("{{ACTIVE_CARD}}", _text(first_product.display_name)).replace(
        "{{ACTIVE_CARD_META}}",
        f"{_text(first_product.issuer.title())} · {_text(first_product.network.value.title())} · •••• {_text(first_instance.mask)}",
    ).replace(
      "{{CHART_GRADIENT}}", ", ".join(chart_stops)
    ).replace("{{CHART_LEGEND}}", "".join(chart_legend)).replace(
      "{{TOP_CATEGORY}}", _label(ranked_categories[0][0])
    ).replace("{{TOP_CATEGORY_AMOUNT}}", _money(ranked_categories[0][1])).replace(
      "{{MONTHLY_AVERAGE}}", _money(total_spend / Decimal("12"))
    ).replace("{{CATEGORIES}}", categories_html).replace(
        "{{TRANSACTIONS}}", transaction_rows
    ).replace("{{ACCOUNT_COUNT}}", str(len(profile.accounts))).replace(
        "{{CARD_COUNT}}", str(len(cards))
    ).replace("{{TRANSACTION_COUNT}}", f"{len(profile.transactions):,}").replace(
        "{{TOTAL_SPEND}}", _money(total_spend)
    ).replace("{{TOTAL_INCOME}}", _money(total_income)).replace(
        "{{PERIOD}}", f"{min(dates).strftime('%b %Y')} – {max(dates).strftime('%b %Y')}"
    )


_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <link rel="icon" href="/static/logos/mastercard.svg" type="image/svg+xml">
  <title>Alex · SmartPay Open Finance</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700&display=swap');
    :root{--ink:#18202b;--muted:#697386;--line:#e7ebf0;--canvas:#f6f8fb;--blue:#635bff;--blue2:#0a66c2;--green:#16876b;--shadow:0 12px 36px rgba(50,50,93,.08),0 2px 8px rgba(0,0,0,.04)}
    *{box-sizing:border-box} body{margin:0;color:var(--ink);background:var(--canvas);font-family:'DM Sans',sans-serif;letter-spacing:0}button,input,select{font:inherit}
    .shell{min-height:100vh}.topbar{height:68px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 4vw;position:sticky;top:0;z-index:20}
    .brand{display:flex;align-items:center;gap:11px;font:700 18px 'Manrope',sans-serif}.brand-mark{width:34px;height:30px;position:relative;isolation:isolate}.brand-mark:before,.brand-mark:after{content:'';position:absolute;top:3px;width:24px;height:24px;border-radius:50%;box-shadow:0 4px 10px rgba(235,0,27,.14)}.brand-mark:before{left:0;background:#EB001B}.brand-mark:after{right:0;background:#F79E1B;z-index:-1}.brand-mark i{position:absolute;left:12px;top:3px;width:10px;height:24px;background:#FF5F00;clip-path:polygon(35% 0,100% 0,65% 100%,0 100%)}
    .live{font-size:13px;color:var(--muted);display:flex;align-items:center;gap:8px}.live i,.status i{width:7px;height:7px;background:#22a06b;border-radius:50%;box-shadow:0 0 0 4px #e3fcef}
    .hero{background:radial-gradient(circle at 80% 10%,rgba(99,91,255,.16),transparent 34%),linear-gradient(125deg,#fff 0%,#f1f6ff 52%,#fff8f5 100%);border-bottom:1px solid var(--line)}
    .hero-inner,.content{max-width:1240px;margin:auto;padding-left:28px;padding-right:28px}.hero-inner{padding-top:58px;padding-bottom:42px}.breadcrumb{font-size:13px;color:var(--muted);margin-bottom:22px}.profile{display:flex;align-items:center;gap:20px}.avatar{width:72px;height:72px;border-radius:20px;background:linear-gradient(145deg,#ffb199,#ff7d66);display:grid;place-items:center;color:#fff;font:700 25px 'Manrope';box-shadow:0 10px 25px rgba(218,86,72,.2)}
    h1,h2,h3,h4{font-family:'Manrope',sans-serif;margin:0}h1{font-size:34px;line-height:1.15}h2{font-size:22px}h3{font-size:19px}.profile p{margin:6px 0 0;color:var(--muted)}.profile .badge{display:inline-flex;margin-left:9px;vertical-align:4px;padding:4px 8px;background:#e3fcef;color:#087a55;border-radius:99px;font:600 11px 'DM Sans'}
    .metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:8px;overflow:hidden;margin-top:35px;box-shadow:var(--shadow)}.metric{background:#fff;padding:19px 21px}.metric span{font-size:12px;color:var(--muted);display:block;margin-bottom:6px}.metric strong{font:700 22px 'Manrope'}
    .tabs-wrap{background:#fff;border-bottom:1px solid var(--line);position:sticky;top:68px;z-index:15}.tabs{max-width:1240px;margin:auto;padding:0 28px;display:flex;gap:28px}.tab{border:0;background:none;padding:18px 2px 15px;color:var(--muted);font-weight:600;font-size:14px;border-bottom:3px solid transparent;cursor:pointer}.tab.active{color:var(--blue);border-color:var(--blue)}
    .content{padding-top:34px;padding-bottom:70px}.view{display:none}.view.active{display:block;animation:enter .28s ease both}@keyframes enter{from{opacity:0;transform:translateY(5px)}}
    .visual-grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(310px,.7fr);gap:24px;margin-bottom:24px}.visual-grid>*{min-width:0}.panel{background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.025)}.panel-head,.section-heading{display:flex;align-items:center;justify-content:space-between;padding:22px 24px;border-bottom:1px solid var(--line)}.panel-head p,.section-heading p{margin:5px 0 0;color:var(--muted);font-size:13px}.panel-head a,.panel-head button{font-size:13px;color:var(--blue);text-decoration:none;font-weight:600;border:0;background:none;cursor:pointer}
    .wallet-carousel{position:relative;overflow:hidden;outline:none;padding-bottom:22px}.wallet-stage{height:244px;position:relative;isolation:isolate;perspective:900px}.wallet-card{position:absolute;left:50%;top:50%;width:258px;aspect-ratio:1.586;border:0;padding:0;background:transparent;display:flex;filter:drop-shadow(0 18px 18px rgba(23,31,50,.24));opacity:0;pointer-events:none;transform:translate(-50%,-46%) scale(.72);transition:transform .52s cubic-bezier(.2,.8,.2,1),opacity .38s ease,filter .38s ease;cursor:pointer}.wallet-card img{display:block;width:100%;height:100%;object-fit:contain}.wallet-card.is-active{z-index:4;opacity:1;pointer-events:auto;transform:translate(-50%,-50%) scale(1);filter:drop-shadow(0 22px 22px rgba(23,31,50,.26))}.wallet-card.is-prev{z-index:2;opacity:.48;pointer-events:auto;transform:translate(-112%,-50%) scale(.72) rotateY(16deg)}.wallet-card.is-next{z-index:2;opacity:.48;pointer-events:auto;transform:translate(12%,-50%) scale(.72) rotateY(-16deg)}.wallet-card.is-far{z-index:1}.wallet-card:focus-visible{outline:3px solid rgba(99,91,255,.38);outline-offset:4px;border-radius:12px}.carousel-arrow{position:absolute;top:103px;z-index:8;width:38px;height:38px;border-radius:50%!important;border:1px solid var(--line)!important;background:rgba(255,255,255,.94)!important;color:var(--ink)!important;display:grid;place-items:center;font-size:25px!important;line-height:1;box-shadow:0 7px 18px rgba(24,32,43,.13);cursor:pointer}.carousel-arrow:hover{border-color:#b9b4ff!important;color:var(--blue)!important}.carousel-arrow.prev{left:18px}.carousel-arrow.next{right:18px}.carousel-caption{text-align:center;min-height:49px;padding:0 70px}.carousel-caption span,.carousel-caption strong{display:block}.carousel-caption strong{font:700 14px 'Manrope';white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.carousel-caption span{color:var(--muted);font-size:10px;margin-top:3px}.carousel-caption .carousel-count{color:var(--blue);font-weight:700;margin:0 0 3px}.carousel-dots{display:flex;justify-content:center;gap:7px;margin-top:12px}.carousel-dot{width:7px!important;height:7px;padding:0!important;border:0!important;border-radius:50%;background:#d8dce5!important;cursor:pointer}.carousel-dot.active{width:21px!important;border-radius:8px;background:var(--blue)!important}.carousel-dot,.carousel-arrow{transition:width .25s ease,background .25s ease,color .2s ease}
    .wallet-card:after,.payment-card:after{content:'';position:absolute;z-index:3;border-radius:2px;backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);box-shadow:inset 0 0 0 1px rgba(255,255,255,.06)}.art-citi_strata_premier:after{left:3.5%;bottom:4.5%;width:32%;height:9%;background:rgba(92,92,94,.68)}.art-citi_double_cash:after{left:3.5%;bottom:4%;width:33%;height:11%;background:rgba(0,54,52,.7)}.art-citi_aa_platinum_select:after{left:37%;top:51%;width:18%;height:17%;background:rgba(125,134,137,.64)}.art-chase_freedom_unlimited:after{left:18%;bottom:5%;width:29%;height:11%;background:rgba(7,21,55,.72)}
    .art-cleanup{display:none}.art-chase_freedom_unlimited .art-cleanup{display:block;position:absolute;z-index:2;right:0;top:0;width:54%;height:54%;clip-path:polygon(0 0,100% 0,100% 100%);background:linear-gradient(135deg,#0871bd 0%,#00549c 48%,#06396f 100%)}
    .spend-chart{padding:22px 24px 24px;background:#fff;color:var(--ink);min-height:410px}.spend-summary{display:grid;grid-template-columns:122px 1fr;gap:22px;align-items:center;padding-bottom:20px;border-bottom:1px solid var(--line)}.donut-wrap{display:grid;place-items:center}.donut{grid-area:1/1;width:122px;aspect-ratio:1;border-radius:50%;background:conic-gradient({{CHART_GRADIENT}});box-shadow:0 5px 16px rgba(50,50,93,.09);animation:donutReveal .8s cubic-bezier(.2,.8,.2,1) both}.donut-hole{grid-area:1/1;width:78px;aspect-ratio:1;border-radius:50%;background:#fff;display:grid;place-items:center;text-align:center;box-shadow:0 0 0 1px rgba(24,32,43,.04)}.donut-hole span{font-size:8px;color:var(--muted);display:block}.donut-hole strong{font:700 12px 'Manrope'}.spend-kpis{display:grid;gap:15px}.spend-kpi span,.spend-kpi strong{display:block}.spend-kpi span{font-size:8px;color:var(--muted);text-transform:uppercase}.spend-kpi strong{font:700 14px 'Manrope';margin-top:3px}.spend-kpi small{font-size:9px;color:#98a1b2}.chart-legend{list-style:none;padding:15px 0 0;margin:0}.chart-legend li{padding:5px 0}.legend-line{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:10px}.legend-name{display:flex;align-items:center;gap:7px;color:#404b5e}.legend-name i{width:7px;height:7px;border-radius:2px;flex:none}.legend-line strong{font-size:10px;white-space:nowrap}.legend-line em{font-style:normal;color:#98a1b2;margin-left:4px}.spend-track{height:4px;background:#edf0f5;border-radius:5px;overflow:hidden;margin-top:5px}.spend-track i{display:block;height:100%;width:var(--bar);border-radius:5px;transform-origin:left;animation:barReveal .7s .2s cubic-bezier(.2,.8,.2,1) both}@keyframes donutReveal{from{transform:rotate(-70deg);opacity:.25}}@keyframes barReveal{from{transform:scaleX(0)}}
    .accounts-panel{margin-bottom:24px}.accounts-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:0}.account-row{display:grid;grid-template-columns:44px minmax(0,1fr);gap:13px;align-items:center;padding:18px 20px;border-right:1px solid #f0f2f5;border-bottom:1px solid #f0f2f5;min-width:0}.account-row:nth-child(4n){border-right:0}.account-row .account-name{display:block;white-space:normal;overflow:visible;line-height:1.25}.account-row span{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11px;color:var(--muted);margin-top:4px}.bank-logo{width:40px;height:40px;border-radius:9px;display:grid;place-items:center;overflow:hidden}.bank-logo img{display:block;max-width:31px;max-height:31px}.bank-logo.citi{background:#f4f7ff;border:1px solid #e3e9fb;box-shadow:0 5px 12px rgba(37,91,227,.1)}.bank-logo.chase{background:#005eb8;box-shadow:0 5px 12px rgba(0,94,184,.2)}.bank-logo.chase img{width:22px;height:22px}.account-bank{display:none!important}
    .category-list{padding:17px 24px}.category-row{display:grid;grid-template-columns:112px 1fr 74px;gap:12px;align-items:center;padding:9px 0;font-size:12px}.category-row strong{text-align:right}.bar{height:7px;background:#eef1f5;border-radius:10px;overflow:hidden}.bar i{display:block;height:100%;background:linear-gradient(90deg,#635bff,#00a7c4);border-radius:10px}
    .notice{margin-top:24px;padding:17px 20px;border:1px solid #c9e9e0;background:#f0faf7;border-radius:8px;color:#276657;font-size:13px;display:flex;gap:11px}.notice strong{color:#145a48}
    .cards-header{margin-bottom:22px}.cards-header p{color:var(--muted);margin:7px 0 0}.card-detail{display:grid;grid-template-columns:320px 1fr;gap:28px;background:#fff;border:1px solid var(--line);border-radius:8px;padding:24px;margin-bottom:20px;box-shadow:0 3px 12px rgba(0,0,0,.03)}
    .payment-card{aspect-ratio:1.586;display:grid;place-items:center;position:relative;filter:drop-shadow(0 16px 15px rgba(25,30,50,.2))}.payment-card img{display:block;width:100%;height:100%;object-fit:contain}.actual-card-mask{position:absolute;left:50%;bottom:-25px;transform:translateX(-50%);font-size:10px;color:var(--muted);white-space:nowrap;background:#fff;padding:4px 8px;border-radius:99px;box-shadow:0 2px 8px rgba(0,0,0,.08)}
    .card-copy{min-width:0}.section-heading.compact{padding:0 0 17px}.eyebrow{font-size:11px!important;text-transform:uppercase;color:var(--blue)!important;font-weight:700}.status{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--green)}.card-stats{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);border-radius:7px;margin-top:17px}.card-stats div{padding:13px 14px;border-right:1px solid var(--line)}.card-stats div:last-child{border:0}.card-stats span,.card-stats strong{display:block}.card-stats span{font-size:10px;color:var(--muted);min-height:27px}.card-stats strong{font-size:14px}
    details{margin-top:16px;border-top:1px solid var(--line)}summary{cursor:pointer;list-style:none;padding:15px 0 0;font-size:13px;font-weight:600;color:var(--blue)}summary::-webkit-details-marker{display:none}summary span{float:right;color:var(--muted);font-weight:400}.details-body h4{font-size:12px;margin:19px 0 9px}.table-scroll{overflow:auto}.rules{width:100%;border-collapse:collapse;font-size:11px}.rules th{text-align:left;color:var(--muted);font-weight:500}.rules td,.rules th{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}.benefits{list-style:none;padding:0;margin:0}.benefits li{display:flex;gap:10px;font-size:12px;padding:7px 0}.benefits small{display:block;color:var(--muted);margin-top:2px;line-height:1.45}.benefit-mark{color:var(--green);font-weight:700}.source{background:#f7f9fc;border-radius:6px;padding:10px 12px;margin-top:13px;display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}.source a{color:var(--blue);font-weight:600;text-decoration:none}
    .activity-panel{overflow:hidden}.activity-tools{display:flex;gap:10px}.search{border:1px solid var(--line);border-radius:6px;padding:9px 12px;width:260px;color:var(--ink);outline:none}.search:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(99,91,255,.1)}select{border:1px solid var(--line);border-radius:6px;padding:9px 30px 9px 10px;background:#fff;color:var(--ink)}.transactions{width:100%;border-collapse:collapse;font-size:12px}.transactions th{text-align:left;padding:11px 18px;background:#f8fafc;color:var(--muted);font-weight:500;border-bottom:1px solid var(--line)}.transactions td{padding:13px 18px;border-bottom:1px solid #f0f2f5;vertical-align:middle}.transactions tbody tr:hover{background:#fafbff}.transactions th:last-child,.transactions td:last-child{text-align:right}.merchant-icon{width:31px;height:31px;border-radius:7px;background:#eef1ff;color:#5046e5;display:inline-grid;place-items:center;font-weight:700;margin-right:10px;vertical-align:middle}.merchant{display:inline-block;vertical-align:middle}.merchant strong,.merchant small{display:block;max-width:250px}.merchant small{color:var(--muted);margin-top:2px}.category-pill{background:#f0f3f7;border-radius:99px;padding:4px 8px;white-space:nowrap}.amount{font-weight:600}.amount.credit{color:var(--green)}.table-footer{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:14px 18px;color:var(--muted);font-size:12px}.pagination{display:flex;align-items:center;gap:8px}.page-button{width:32px;height:32px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);display:grid;place-items:center;font-size:20px;line-height:1;cursor:pointer}.page-button:hover:not(:disabled){border-color:#b9b4ff;color:var(--blue)}.page-button:disabled{opacity:.38;cursor:default}.page-status{min-width:82px;text-align:center;color:var(--ink);font-weight:600}.source-note{margin-left:auto}
    @media(min-width:1100px){.topbar{height:76px}.brand{font-size:22px}.brand-mark{transform:scale(1.12);margin-right:3px}.live{font-size:15px}.hero-inner,.content{max-width:1400px;padding-left:36px;padding-right:36px}.hero-inner{padding-top:38px;padding-bottom:32px}.breadcrumb{font-size:15px;margin-bottom:18px}.avatar{width:82px;height:82px;font-size:30px}.profile{gap:24px}h1{font-size:44px}h2{font-size:25px}h3{font-size:22px}.profile p{font-size:17px;margin-top:8px}.profile .badge{font-size:13px;padding:5px 10px}.metrics{margin-top:26px}.metric{padding:19px 24px;border-top:4px solid transparent}.metric:nth-child(1){border-top-color:#EB001B}.metric:nth-child(2){border-top-color:#FF5F00}.metric:nth-child(3){border-top-color:#F79E1B}.metric:nth-child(4){border-top-color:#16876b}.metric span{font-size:15px}.metric strong{font-size:30px}.tabs-wrap{top:76px}.tabs{max-width:1400px;padding:0 36px;gap:36px}.tab{font-size:17px;padding:19px 3px 16px}.content{padding-top:30px}.visual-grid{grid-template-columns:minmax(0,1.55fr) minmax(410px,.8fr);gap:28px}.panel-head,.section-heading{padding:24px 28px}.panel-head p,.section-heading p{font-size:15px}.panel-head a,.panel-head button{font-size:15px}.wallet-stage{height:290px}.wallet-card{width:310px}.carousel-arrow{top:124px;width:44px;height:44px;font-size:29px!important}.carousel-caption{min-height:58px}.carousel-caption strong{font-size:18px}.carousel-caption span{font-size:13px}.spend-chart{padding:26px 28px;min-height:458px}.spend-summary{grid-template-columns:142px 1fr}.donut{width:142px}.donut-hole{width:92px}.donut-hole span{font-size:11px}.donut-hole strong{font-size:15px}.spend-kpi span{font-size:11px}.spend-kpi strong{font-size:18px}.spend-kpi small{font-size:12px}.chart-legend li{padding:7px 0}.legend-line{font-size:13px}.legend-line strong{font-size:13px}.spend-track{height:6px}.account-row{grid-template-columns:50px minmax(0,1fr);padding:22px 24px;font-size:16px}.account-row span{font-size:13px}.bank-logo{width:46px;height:46px}.bank-logo img{max-width:35px;max-height:35px}.notice{font-size:15px;padding:19px 22px}.card-detail{grid-template-columns:370px 1fr;padding:30px;gap:36px}.eyebrow{font-size:13px!important}.status{font-size:14px}.card-stats span{font-size:13px}.card-stats strong{font-size:17px}summary{font-size:16px}.details-body h4{font-size:15px}.rules{font-size:14px}.benefits li{font-size:14px}.benefits small{font-size:13px}.source{font-size:13px}.transactions{font-size:15px}.transactions th{padding:14px 20px}.transactions td{padding:15px 20px}.merchant-icon{width:38px;height:38px}.merchant small{font-size:12px}.table-footer{font-size:14px}.search,select{font-size:15px;padding-top:11px;padding-bottom:11px}.search{width:320px}}
    @media(max-width:900px){.visual-grid{grid-template-columns:1fr}.accounts-grid{grid-template-columns:repeat(2,1fr)}.account-row:nth-child(4n){border-right:1px solid #f0f2f5}.account-row:nth-child(2n){border-right:0}.card-detail{grid-template-columns:1fr}.payment-card{max-width:360px}.card-stats{grid-template-columns:repeat(2,1fr)}.card-stats div:nth-child(2){border-right:0}.metrics{grid-template-columns:repeat(2,1fr)}.activity-tools{margin-top:12px}.panel-head{align-items:flex-start;flex-direction:column}.transactions{min-width:850px}.activity-panel{overflow:auto}}
    @media(max-width:600px){.topbar{padding:0 18px}.live span{display:none}.hero-inner,.content{padding-left:18px;padding-right:18px}.hero-inner{padding-top:36px}h1{font-size:27px}.profile{align-items:flex-start}.avatar{width:58px;height:58px}.metrics{grid-template-columns:1fr 1fr}.metric{padding:15px}.metric strong{font-size:17px}.tabs{padding:0 18px;gap:18px;overflow:auto}.tab{white-space:nowrap}.wallet-stage{height:205px}.wallet-card{width:218px}.wallet-card.is-prev{transform:translate(-108%,-50%) scale(.62) rotateY(16deg)}.wallet-card.is-next{transform:translate(8%,-50%) scale(.62) rotateY(-16deg)}.carousel-arrow{top:84px;width:34px;height:34px}.carousel-arrow.prev{left:10px}.carousel-arrow.next{right:10px}.carousel-caption{padding:0 48px}.accounts-grid{grid-template-columns:1fr}.account-row,.account-row:nth-child(4n){border-right:0}.card-detail{padding:15px}.payment-card{width:100%}.card-stats{grid-template-columns:1fr 1fr}.source{flex-direction:column;gap:6px}.activity-tools{width:100%;flex-direction:column}.search{width:100%}.category-row{grid-template-columns:92px 1fr 67px}.panel-head,.section-heading{padding:18px}.table-footer{flex-wrap:wrap}.pagination{order:3;width:100%;justify-content:center}.source-note{display:none}}
    @media(prefers-reduced-motion:reduce){.wallet-card,.carousel-dot,.carousel-arrow{transition:none}.view.active,.donut,.spend-track i{animation:none}}
  </style>
</head>
<body>
<div class="shell">
  <header class="topbar"><div class="brand"><span class="brand-mark"><i></i></span>SmartPay</div><div class="live"><i></i><span>Open Finance connection healthy</span></div></header>
  <section class="hero"><div class="hero-inner"><div class="breadcrumb">Customers / Financial profile</div><div class="profile"><div class="avatar">AM</div><div><h1>Alex Morgan <span class="badge">DEMO</span></h1><p>US consumer · Connected through Open Finance · {{PERIOD}}</p></div></div><div class="metrics"><div class="metric"><span>Connected accounts</span><strong>{{ACCOUNT_COUNT}}</strong></div><div class="metric"><span>Cards in wallet</span><strong>{{CARD_COUNT}}</strong></div><div class="metric"><span>12-month spend</span><strong>{{TOTAL_SPEND}}</strong></div><div class="metric"><span>Transactions analyzed</span><strong>{{TRANSACTION_COUNT}}</strong></div></div></div></section>
  <nav class="tabs-wrap" aria-label="Profile sections"><div class="tabs"><button class="tab active" data-view="overview">Overview</button><button class="tab" data-view="cards">Cards & benefits</button><button class="tab" data-view="activity">Activity</button></div></nav>
  <main class="content">
    <section class="view active" id="overview"><div class="visual-grid"><div class="panel"><div class="panel-head"><div><h2>Wallet at a glance</h2><p>Five cards connected across Citi and Chase</p></div><button data-open-cards type="button">Explore benefits →</button></div><div class="wallet-carousel" data-carousel tabindex="0" aria-label="Alex's cards"><button class="carousel-arrow prev" data-carousel-prev type="button" aria-label="Previous card">‹</button><div class="wallet-stage" aria-live="polite">{{WALLET_PREVIEW}}</div><button class="carousel-arrow next" data-carousel-next type="button" aria-label="Next card">›</button><div class="carousel-caption"><span class="carousel-count">1 of {{CARD_COUNT}}</span><strong>{{ACTIVE_CARD}}</strong><span class="carousel-meta">{{ACTIVE_CARD_META}}</span></div><div class="carousel-dots">{{WALLET_DOTS}}</div></div></div><div class="panel spend-panel"><div class="panel-head"><div><h2>Where Alex spends</h2><p>12-month consumer spend</p></div></div><div class="spend-chart"><div class="spend-summary"><div class="donut-wrap"><div class="donut"></div><div class="donut-hole"><div><span>Total spend</span><strong>{{TOTAL_SPEND}}</strong></div></div></div><div class="spend-kpis"><div class="spend-kpi"><span>Monthly average</span><strong>{{MONTHLY_AVERAGE}}</strong><small>across 12 months</small></div><div class="spend-kpi"><span>Top category</span><strong>{{TOP_CATEGORY}}</strong><small>{{TOP_CATEGORY_AMOUNT}} total</small></div></div></div><ul class="chart-legend">{{CHART_LEGEND}}</ul></div></div></div><div class="panel accounts-panel"><div class="panel-head"><div><h2>Connected accounts</h2><p>Accounts available to SmartPay across Alex's institutions</p></div><a href="/demo/alex.json">View raw JSON</a></div><div class="accounts-grid">{{ACCOUNTS}}</div></div><div class="notice"><strong>Data integrity</strong><span>{{TOTAL_INCOME}} of income is retained alongside internal card payments in the ledger. Neither is counted as consumer spend, preventing double counting.</span></div></section>
    <section class="view" id="cards"><div class="cards-header"><h2>Alex's complete wallet</h2><p>Issuer terms, earn rules, benefits, fees, provenance and account linkage.</p></div>{{CARDS}}</section>
    <section class="view" id="activity"><div class="panel activity-panel"><div class="panel-head"><div><h2>Recent activity</h2><p>All {{TRANSACTION_COUNT}} Open Finance records, newest first</p></div><div class="activity-tools"><input class="search" id="transaction-search" type="search" placeholder="Search merchant, category or account" aria-label="Search transactions"><select id="transaction-type" aria-label="Filter transaction type"><option value="all">All activity</option><option value="purchase">Purchases</option><option value="income">Income</option><option value="card_payment">Card payments</option><option value="transfer">Transfers</option><option value="atm_withdrawal">ATM withdrawals</option><option value="fee">Fees</option><option value="refund">Refunds</option></select></div></div><div class="table-scroll"><table class="transactions"><thead><tr><th>Description</th><th>Date</th><th>Category</th><th>Account</th><th>Amount</th></tr></thead><tbody>{{TRANSACTIONS}}</tbody></table></div><div class="table-footer"><span id="visible-count">1–25 of {{TRANSACTION_COUNT}} records</span><div class="pagination" aria-label="Activity pagination"><button class="page-button" id="page-previous" type="button" aria-label="Previous activity page">‹</button><span class="page-status" id="page-status">Page 1</span><button class="page-button" id="page-next" type="button" aria-label="Next activity page">›</button></div><span class="source-note">Source: synthetic Open Finance dataset</span></div></div></section>
  </main>
</div>
<script>
  const tabs = document.querySelectorAll('.tab');
  tabs.forEach(tab => tab.addEventListener('click', () => {
    tabs.forEach(item => item.classList.toggle('active', item === tab));
    document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.id === tab.dataset.view));
  }));
  document.querySelectorAll('[data-open-cards]').forEach(control => control.addEventListener('click', () => {
    document.querySelector('.tab[data-view="cards"]').click();
    document.querySelector('.tabs-wrap').scrollIntoView({ behavior: 'smooth' });
  }));
  const carousel = document.querySelector('[data-carousel]');
  const carouselCards = [...carousel.querySelectorAll('.wallet-card')];
  const carouselDots = [...carousel.querySelectorAll('[data-carousel-dot]')];
  let activeCard = 0;
  let carouselTimer;
  function showCard(index) {
    activeCard = (index + carouselCards.length) % carouselCards.length;
    carouselCards.forEach((card, cardIndex) => {
      const offset = (cardIndex - activeCard + carouselCards.length) % carouselCards.length;
      card.classList.toggle('is-active', offset === 0);
      card.classList.toggle('is-next', offset === 1);
      card.classList.toggle('is-prev', offset === carouselCards.length - 1);
      card.classList.toggle('is-far', offset > 1 && offset < carouselCards.length - 1);
      card.setAttribute('aria-current', offset === 0 ? 'true' : 'false');
      card.tabIndex = offset === 0 ? 0 : -1;
    });
    carouselDots.forEach((dot, dotIndex) => dot.classList.toggle('active', dotIndex === activeCard));
    const card = carouselCards[activeCard];
    carousel.querySelector('.carousel-count').textContent = `${activeCard + 1} of ${carouselCards.length}`;
    carousel.querySelector('.carousel-caption strong').textContent = card.dataset.name;
    carousel.querySelector('.carousel-meta').textContent = card.dataset.meta;
  }
  function stopCarousel() { clearInterval(carouselTimer); }
  function startCarousel() {
    stopCarousel();
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
      carouselTimer = setInterval(() => showCard(activeCard + 1), 4500);
    }
  }
  carousel.querySelector('[data-carousel-prev]').addEventListener('click', () => { showCard(activeCard - 1); startCarousel(); });
  carousel.querySelector('[data-carousel-next]').addEventListener('click', () => { showCard(activeCard + 1); startCarousel(); });
  carouselCards.forEach((card, index) => card.addEventListener('click', () => { showCard(index); startCarousel(); }));
  carouselDots.forEach((dot, index) => dot.addEventListener('click', () => { showCard(index); startCarousel(); }));
  carousel.addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      showCard(activeCard + (event.key === 'ArrowRight' ? 1 : -1));
      startCarousel();
    }
  });
  carousel.addEventListener('pointerenter', stopCarousel);
  carousel.addEventListener('pointerleave', startCarousel);
  carousel.addEventListener('focusin', stopCarousel);
  carousel.addEventListener('focusout', startCarousel);
  showCard(0);
  startCarousel();
  const search = document.querySelector('#transaction-search');
  const type = document.querySelector('#transaction-type');
  const rows = [...document.querySelectorAll('[data-transaction]')];
  const pageSize = 25;
  let activityPage = 1;
  function renderTransactions() {
    const query = search.value.trim().toLowerCase();
    const filteredRows = rows.filter(row =>
      (!query || row.dataset.search.includes(query)) &&
      (type.value === 'all' || row.dataset.type === type.value)
    );
    const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
    activityPage = Math.min(activityPage, totalPages);
    const start = (activityPage - 1) * pageSize;
    const pageRows = new Set(filteredRows.slice(start, start + pageSize));
    rows.forEach(row => { row.hidden = !pageRows.has(row); });
    const firstRecord = filteredRows.length ? start + 1 : 0;
    const lastRecord = Math.min(start + pageSize, filteredRows.length);
    document.querySelector('#visible-count').textContent = `${firstRecord.toLocaleString()}–${lastRecord.toLocaleString()} of ${filteredRows.length.toLocaleString()} records`;
    document.querySelector('#page-status').textContent = `Page ${activityPage} of ${totalPages}`;
    document.querySelector('#page-previous').disabled = activityPage === 1;
    document.querySelector('#page-next').disabled = activityPage === totalPages;
  }
  function resetActivityPage() {
    activityPage = 1;
    renderTransactions();
  }
  document.querySelector('#page-previous').addEventListener('click', () => {
    activityPage -= 1;
    renderTransactions();
  });
  document.querySelector('#page-next').addEventListener('click', () => {
    activityPage += 1;
    renderTransactions();
  });
  search.addEventListener('input', resetActivityPage);
  type.addEventListener('change', resetActivityPage);
  renderTransactions();
</script>
</body>
</html>"""