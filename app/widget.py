"""The SmartPay UI embedded in ChatGPT.

ChatGPT renders an Apps SDK component by fetching one HTML resource and running it
in a sandboxed iframe. That inverts how the standalone dashboard works: there,
Python renders the page with the plan already baked in; here the same HTML is
served once and hydrates itself from ``window.openai.toolOutput`` on every tool
call.

Two consequences drive the shape of this file:

* **Nothing may be fetched.** The iframe cannot reach the dashboard server, so
  images are inlined as data URIs. That is also why it needs no CSP configuration
  and keeps working with no network.
* **Inline is small.** A component renders inline in the conversation by default,
  with limited height, so the inline view is a summary and the detail lives behind
  ``requestDisplayMode('fullscreen')``.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from functools import lru_cache
from pathlib import Path

from app import config

STATIC = config.ROOT / "app" / "static"

#: The resource ChatGPT fetches. The ui:// scheme is required, and the tool's
#: _meta must point at exactly this URI or the component is never discovered.
WIDGET_URI = "ui://widget/smartpay-plan.html"


@lru_cache(maxsize=32)
def data_uri(relative: str) -> str:
    """Inline an asset so the sandboxed iframe can render it."""
    path = STATIC / relative
    if not path.exists():
        return ""
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


@lru_cache(maxsize=1)
def _assets() -> str:
    """Every image the component can show, keyed the way the plan data names them."""
    return json.dumps(
        {
            "logos": {
                "citi": data_uri("logos/citi.svg"),
                "chase": data_uri("logos/chase.svg"),
                "mastercard": data_uri("logos/mastercard.svg"),
            },
            "cards": {
                "Citi Strata Premier Card": data_uri("cards/citi_strata_premier.webp"),
                "Citi Double Cash Card": data_uri("cards/citi_double_cash.webp"),
                "Citi / AAdvantage Platinum Select World Elite Mastercard": data_uri(
                    "cards/citi_aa_platinum_select.webp"
                ),
                "Chase Sapphire Preferred": data_uri("cards/chase_sapphire_preferred.png"),
                "Chase Freedom Unlimited": data_uri("cards/chase_freedom_unlimited.png"),
            },
        }
    )


CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --bg:transparent; --surface:#fcfcfb; --surface-2:#ffffff; --line:#e6e5e1;
  --ink:#111110; --ink-2:#52514e; --ink-3:#86847e;
  --brand:#EB001B; --brand-2:#F79E1B; --brand-ink:#C60016;
  --good:#046c4e; --good-bg:#e8f5ef;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100;
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --surface:#1a1a19; --surface-2:#212120; --line:#302f2c;
  --ink:#f7f7f5; --ink-2:#c3c2b7; --ink-3:#8e8c84;
  --brand-ink:#FF8A73; --good:#5fd0a4; --good-bg:#12281f;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
}
html,body{margin:0;background:var(--bg)}
body{color:var(--ink);
  font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,Roboto,sans-serif;
  -webkit-font-smoothing:antialiased}
.num,.figure,.gain,.amount{font-variant-numeric:tabular-nums}
h1,h2,h3{margin:0;letter-spacing:-.02em;line-height:1.2}
p{margin:0}
.wrap{padding:16px}

.head{display:flex;align-items:center;gap:9px;margin-bottom:14px}
.head img{width:26px;height:auto;flex:none}
.head .who{font-weight:650;letter-spacing:-.02em}
.head .ctx{color:var(--ink-3);font-size:12px;margin-left:auto;text-align:right}

.hero{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:4px}
.hero .figure{font-size:34px;font-weight:680;letter-spacing:-.03em;
  background:linear-gradient(96deg,var(--brand),var(--brand-2));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.hero .cap{font-size:13px;color:var(--ink-2)}
.sub{color:var(--ink-3);font-size:12.5px;margin-bottom:14px}

.chips{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:14px}
.kv{border:1px solid var(--line);border-radius:11px;padding:7px 11px;background:var(--surface-2)}
.kv b{display:block;font-size:15px;font-weight:650;letter-spacing:-.02em}
.kv span{font-size:10.5px;color:var(--ink-3)}

.rows{display:grid;gap:7px}
.row{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;
  padding:10px 12px;border:1px solid var(--line);border-radius:11px;background:var(--surface-2)}
.row.win{border-left:3px solid var(--brand)}
.row .item{font-size:13px;font-weight:600;line-height:1.3}
.row .swap{font-size:11.5px;color:var(--ink-3);margin-top:2px}
.row .swap b{color:var(--ink-2);font-weight:600}
.row .swap .to{color:var(--ink);font-weight:600}
.row .val{text-align:right;white-space:nowrap}
.row .val .gain{display:block;font-size:15px;font-weight:660}
.row .val .est{font-size:10.5px;color:var(--ink-3)}
.tag{display:inline-block;font-size:10px;font-weight:650;padding:1px 6px;border-radius:99px;
  border:1px solid color-mix(in srgb,var(--brand) 40%,var(--line));color:var(--brand-ink);
  margin-left:5px}
.tag.tie{border-style:dashed;color:var(--ink-3);border-color:var(--line)}

.actions{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}
button{font:inherit;font-size:12.5px;font-weight:600;border-radius:9px;cursor:pointer;
  padding:8px 13px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink)}
button:hover{border-color:var(--ink-3)}
button.primary{background:linear-gradient(96deg,var(--brand),var(--brand-2));
  border-color:transparent;color:#fff}

.note{margin-top:13px;font-size:11px;color:var(--ink-3);line-height:1.45}

/* fullscreen-only detail */
.detail{display:none;margin-top:18px;border-top:1px solid var(--line);padding-top:16px}
:root[data-mode="fullscreen"] .detail{display:block}
:root[data-mode="fullscreen"] .wrap{padding:24px;max-width:900px;margin:0 auto}
.detail h3{font-size:14px;margin-bottom:9px}
.bars{display:grid;gap:6px;margin-bottom:20px}
.bar{display:grid;grid-template-columns:150px 1fr auto;gap:10px;align-items:center;font-size:12px}
.bar .track{display:block;height:22px;border-radius:6px;background:var(--line);
  position:relative;overflow:hidden}
.bar .fill{display:block;height:100%;border-radius:6px}
.bar .lab{color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar .amt{font-weight:650;font-variant-numeric:tabular-nums}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.cards figure{margin:0;border:1px solid var(--line);border-radius:11px;overflow:hidden;
  background:var(--surface-2)}
.cards img{width:100%;height:auto;display:block;padding:9px}
.cards figcaption{font-size:11px;padding:0 9px 9px;color:var(--ink-2);line-height:1.35}
.empty{padding:22px;text-align:center;color:var(--ink-3);font-size:13px}
"""

SCRIPT = """
const ASSETS = __ASSETS__;
const oai = () => (typeof window !== 'undefined' ? window.openai : undefined);
const money = (v) => {
  const n = Number(v || 0);
  return (n < 0 ? '-$' : '$') + Math.abs(n).toLocaleString('en-US',
    {minimumFractionDigits: 2, maximumFractionDigits: 2});
};
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g,
  (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function applyHostContext() {
  const api = oai();
  const root = document.documentElement;
  // Follow the host's theme and display mode. Both are read defensively: the
  // component must still render if opened outside ChatGPT.
  root.dataset.theme = (api && api.theme) === 'dark' ? 'dark'
    : (api && api.theme) ? 'light'
    : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  root.dataset.mode = (api && api.displayMode) || 'inline';
}

function envelope() {
  const api = oai();
  const out = (api && api.toolOutput) || null;
  // Tools return {display_markdown, data, disclaimers}. The plan is in `data`, but
  // the disclaimers sit alongside it -- reading only `data` silently dropped them,
  // and they are the part that must never go missing.
  return out && out.structuredContent ? out.structuredContent : out;
}

function renderRows(plan) {
  return (plan.recommendations || []).map((r) => {
    const gain = Number(r.guaranteed_savings || 0);
    const est = Number(r.estimated_reward_value_delta || 0);
    const portal = r.recommended_channel && r.recommended_channel !== 'booked direct'
      ? `<span class="tag">${esc(r.recommended_channel)}</span>` : '';
    const tie = r.tiebreak_note ? '<span class="tag tie">tie · disclosed</span>' : '';
    return `
      <div class="row${gain > 0 ? ' win' : ''}">
        <div>
          <div class="item">${esc(r.item)}</div>
          <div class="swap"><b>${esc(r.baseline_payment)}</b> &rarr;
            <span class="to">${esc(r.recommended_payment)}</span>${portal}${tie}</div>
        </div>
        <div class="val">
          <span class="gain">${money(gain)}</span>
          <span class="est">${est > 0 ? '+' + money(est) + ' est.' : '&nbsp;'}</span>
        </div>
      </div>`;
  }).join('');
}

function renderDetail(plan) {
  const sources = [];
  (plan.recommendations || []).forEach((r) => {
    (r.offers || []).forEach((o) => sources.push([o.merchant + ' offer', Number(o.value)]));
    const rest = Number(r.guaranteed_savings || 0)
      - (r.offers || []).reduce((n, o) => n + Number(o.value), 0);
    if (rest > 0 && (r.benefits || []).length) sources.push([r.benefits[0], rest]);
  });
  sources.sort((a, b) => b[1] - a[1]);
  const peak = sources.length ? sources[0][1] : 1;
  const bars = sources.map(([label, value], i) => `
    <div class="bar">
      <span class="lab" title="${esc(label)}">${esc(label)}</span>
      <span class="track"><span class="fill" style="width:${Math.max(value / peak * 100, 2)}%;
        background:var(--s${(i % 4) + 1})"></span></span>
      <span class="amt">${money(value)}</span>
    </div>`).join('');

  const seen = new Set();
  const cards = (plan.recommendations || []).map((r) => r.recommended_payment)
    .filter((n) => n && ASSETS.cards[n] && !seen.has(n) && seen.add(n))
    .map((n) => `<figure><img src="${ASSETS.cards[n]}" alt="${esc(n)}">
      <figcaption>${esc(n)}</figcaption></figure>`).join('');

  return `
    ${bars ? `<h3>Where the guaranteed value comes from</h3><div class="bars">${bars}</div>` : ''}
    ${cards ? `<h3>Cards SmartPay recommends here</h3><div class="cards">${cards}</div>` : ''}`;
}

function render() {
  applyHostContext();
  const root = document.getElementById('root');
  const out = envelope();
  const plan = out && out.data;
  const disclaimers = (out && out.disclaimers) || [];

  if (!plan) {
    root.innerHTML = `<div class="wrap"><div class="empty">
      Ask SmartPay to optimise a trip and the plan appears here.</div></div>`;
    reportHeight();
    return;
  }

  const guaranteed = Number(plan.incremental_guaranteed || 0);
  const est = Number(plan.incremental_estimated || 0);
  const pts = Number(plan.incremental_points || 0);
  const mc = (plan.recommendations || []).filter((r) => r.is_mastercard).length;
  const total = plan.recommendations ? plan.recommendations.length : 0;

  root.innerHTML = `
    <div class="wrap">
      <div class="head">
        <img src="${ASSETS.logos.mastercard}" alt="">
        <span class="who">SmartPay</span>
        <span class="ctx">${esc(total)} items · ${money(plan.itinerary_total)}</span>
      </div>

      <div class="hero">
        <span class="figure">${money(guaranteed)}</span>
        <span class="cap">of guaranteed value on this trip</span>
      </div>
      <p class="sub">Compared with how you normally pay, inferred from 12 months of
        your own transactions.</p>

      <div class="chips">
        <span class="kv"><b>${money(est)}</b><span>Est. rewards</span></span>
        <span class="kv"><b>${pts.toLocaleString('en-US')}</b><span>Extra points</span></span>
        <span class="kv"><b>${mc}/${total}</b><span>On Mastercard</span></span>
      </div>

      <div class="rows">${renderRows(plan)}</div>

      <div class="detail">${renderDetail(plan)}</div>

      <div class="actions">
        <button class="primary" id="expand">See full breakdown</button>
        <button id="why">Why these cards?</button>
      </div>
      <p class="note">${esc(disclaimers.join(' '))}</p>
    </div>`;

  const api = oai();
  const expand = document.getElementById('expand');
  if (api && api.requestDisplayMode) {
    expand.addEventListener('click', () => {
      const next = document.documentElement.dataset.mode === 'fullscreen'
        ? 'inline' : 'fullscreen';
      api.requestDisplayMode({ mode: next });
    });
  } else {
    // Outside ChatGPT the button still works, it just toggles locally.
    expand.addEventListener('click', () => {
      const root = document.documentElement;
      root.dataset.mode = root.dataset.mode === 'fullscreen' ? 'inline' : 'fullscreen';
      reportHeight();
    });
  }

  const why = document.getElementById('why');
  if (api && api.sendFollowUpMessage) {
    why.addEventListener('click', () => api.sendFollowUpMessage({
      prompt: 'Show me the evidence behind those card recommendations.' }));
  } else {
    why.disabled = true;
  }

  reportHeight();
}

function reportHeight() {
  const api = oai();
  const h = document.documentElement.scrollHeight;
  if (api && api.notifyIntrinsicHeight) api.notifyIntrinsicHeight(h);
}

// The host swaps globals (tool output, theme, display mode) in place rather than
// reloading the iframe, so re-render on its notification as well as at startup.
window.addEventListener('openai:set_globals', render);
window.addEventListener('DOMContentLoaded', render);
if (document.readyState !== 'loading') render();
"""


def widget_html() -> str:
    """The complete, self-contained component ChatGPT fetches once and hydrates."""
    return f"""<!doctype html>
<html lang="en" data-mode="inline">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SmartPay payment plan</title>
<style>{CSS}</style>
</head>
<body>
<div id="root"></div>
<script>{SCRIPT.replace("__ASSETS__", _assets())}</script>
</body>
</html>"""
