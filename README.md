# SmartPay

> Your AI knows what you want. SmartPay knows how you should pay.

A deterministic payment-intelligence service, exposed to real ChatGPT over MCP.
ChatGPT plans a trip; SmartPay reads the consumer's connected bank and card data,
infers how they normally pay, and computes how they *should* pay — with every
figure traceable to a source.

**No LLM performs any calculation.** Every number is computed in Python from
curated rules and returned as pre-rendered markdown that ChatGPT presents verbatim.

## Quick start

```bash
./run_demo.sh
```

Creates the virtualenv, generates Alex's dataset if missing, runs the test suite,
serves MCP on `http://127.0.0.1:9022/mcp`, and starts the visual dashboard on
`http://127.0.0.1:9023/demo/alex`.

Open `http://127.0.0.1:9023/demo/alex` for Alex's Open Finance dashboard. It
shows every connected account, card, reward rule, benefit and transaction used
by SmartPay.

### Reaching ChatGPT

The demo uses the **OpenAI MCP control-plane tunnel**. In a second terminal:

```bash
tunnel-client run --profile smartpay
```

The tunnel is registered at
<https://platform.openai.com/settings/organization/tunnels> and its profile
(`~/.config/tunnel-client/smartpay.yaml`) points at `http://127.0.0.1:9022/mcp`.
It dials outbound, so nothing is exposed to the public internet.

Check both halves:

```bash
curl -s http://127.0.0.1:9022/health   # SmartPay
curl -s http://127.0.0.1:8080/readyz   # tunnel
```

`tunnel-client` connects over loopback, so the Host header is already allowed and
**`SMARTPAY_PUBLIC_HOST` is not needed**. It is only required for a tunnel that
forwards its own public hostname — ngrok or Cloudflare. Miss it there and `/mcp`
returns `421` while `/health` returns `200`, which looks healthy and is not:

```bash
SMARTPAY_PUBLIC_HOST=https://your-host.example.com ./run_demo.sh --ngrok
```

## The demo

Ask ChatGPT:

> Plan Alex a five-night Disney World trip for a family of four in October.
> Include flights, hotel, Disney tickets, airport transport and dining. Then use
> SmartPay to optimise how Alex pays for it.

SmartPay returns, for each line: how Alex would normally pay (from observed
history), how they should pay, guaranteed savings, estimated reward value and the
evidence. Then ask it to review the wallet for the closing beat.

## Where the value comes from

On a domestic, card-only trip there are no foreign-exchange fees or surcharges to
avoid, so the guaranteed savings have to come from real benefits. They do:

| Source | Value | Verified against |
|---|---:|---|
| First checked bag free, 4 bags × 2 directions × $45 | $360 | Citi + American Airlines newsroom |
| Citi Travel hotel benefit, on a $500+ stay | $100 | citi.com |
| Simulated Mastercard card-linked offer | $75 | *synthetic, labelled everywhere* |
| 10% off scheduled Lyft airport rides (World Elite) | $18 | mastercard.com |
| **Total guaranteed** | **$553** | |

Plus ~35,620 additional points, largely from booking the hotel and tickets through
Citi Travel at 10x instead of direct at 3x/1x.

## Honesty rules

These are enforced by tests, not by convention.

- **Guaranteed value and estimated value are never merged.** Guaranteed means money
  the consumer verifiably does not pay. Reward earn is an estimate at a configurable
  1.0 cent per point and is always reported separately.
- **Provenance is never fabricated.** A rule is marked `authoritative` only if it was
  read off a live issuer page, with a real URL and verification date. Everything
  else is `demo_approximation` or `synthetic_demo`.
- **The one synthetic offer is labelled everywhere it appears.**
- **The network tiebreak is disclosed.** Where two options are worth *exactly* the
  same, SmartPay prefers the Mastercard — and says so, on the line and in the
  disclaimers. It cannot fire on a genuine difference, and a card that genuinely
  wins always wins regardless of network. Both are enforced by tests.
- **Channel rules are enforced.** A 10x travel-portal rate can never be awarded to a
  purchase booked directly with the merchant.
- **Every inference is planted in the data.** SmartPay only suggests the golf
  experience because there are 16 golf transactions in Alex's ledger.
- **Read-only.** No tool moves money, applies for anything, or changes state.
- **Domestic-only benefits are enforced.** The AAdvantage checked-bag waiver covers
  "domestic American Airlines itineraries", so it does not pay out on an
  international origin — worth $360, and easy to overstate if the model plans the
  trip from wherever the operator happens to be sitting.

## Running the demo from outside the US

Alex is a US persona. If the operator is elsewhere, ChatGPT will otherwise plan
the trip from *their* city, which quietly removes the domestic baggage benefit and
changes the headline number. Two things guard against that:

- Server instructions state that Alex is US-based and is not the person chatting,
  and that the itinerary must not be localised to the operator.
- Omitting `itinerary` uses the frozen BOS→MCO scenario, which is the safest
  option for a rehearsed run.

## Open Finance via BankSym (FDX)

By default SmartPay reads Alex from the frozen fixture. It can equally read the same
profile from [BankSym](../banksym), where Citi and Chase exist as two separate bank
tenants serving **FDX**, the US open banking standard:

```bash
# in the banksym repo
./run.sh start

# in this repo, once
python scripts/seed_banksym.py          # creates Citi + Chase, imports 644 transactions
SMARTPAY_PROVIDER=banksym ./run_demo.sh
```

Alex is seeded with online-banking credentials at both institutions, so the PSU
consent journey works as well as the aggregation one:

| | |
|---|---|
| username | `alex.morgan@example.com` |
| password | `foobar!` |

A demo credential for a synthetic customer in a test bank — it guards nothing real.
`example.com` is reserved for documentation (RFC 2606), so the address cannot
collide with a real mailbox. Both banks enable **Open Finance** (what SmartPay
reads) and **Berlin Group XS2A** (the PSU login → consent → OAuth authorise →
account access journey).

Both sources produce **identical** recommendations — $553.00 guaranteed, $359.70
estimated, 35,620 points, same card on every line. That equivalence is asserted by
`tests/test_banksym_provider.py`, which skips when BankSym is not running.

Three things the BankSym path does that a real FDX integration must:

- **Decodes direction from `debitCreditMemo`.** FDX amounts are always positive and
  direction is a separate field. Reading the amount alone would make every payroll
  deposit look like spending and invert the entire profile.
- **Dispatches on polymorphic envelopes.** Deposits arrive as `depositAccount` /
  `depositTransaction`, credit cards as `locAccount` / `locTransaction`. Handling
  only one silently drops five of Alex's seven accounts.

- **Aggregates across institutions.** Citi and Chase are separate tenants with
  separate customer ids; one financial picture is reassembled from both.
- **Classifies raw postings.** FDX returns money movements, not meaning.
  Nothing in the payload says "this is a card repayment, exclude it from spend" —
  SmartPay derives that, and getting it wrong would double-count everything Alex
  repays.

## Architecture

```
ChatGPT  ->  HTTPS tunnel  ->  MCP server  ->  SmartPayService  ->  engines
                                                                      |
                                      OpenFinanceProvider  <----------+
```

`SmartPayService` is the only thing the MCP layer calls, so the core is
channel-independent. `OpenFinanceProvider` is a Protocol — `SyntheticAlexProvider`
reads the frozen dataset today, and a Mastercard Open Finance Test Drive provider
can replace it without the engines noticing.

The optimiser runs **two passes**. Scoring each item independently would let a
one-time $75 offer pay out on every matching line, so the second pass reconciles
plan-wide: each limited artefact is granted on exactly one item. The baseline is
reconciled identically, so the comparison stays apples-to-apples.

```
app/
  mcp_server.py       six read-only MCP tools, streamable HTTP
  services/smartpay.py application service — the only entry point
  render.py           deterministic markdown (this is what enforces "no LLM maths")
  engines/            categorizer, rewards, offers, benefits, baseline,
                      counterfactual, optimizer (two-pass), wallet_optimizer
  providers/          open_finance (Protocol + synthetic + selection),
                      banksym (live Open Finance), future_spend
data/
  alex/               frozen, committed transaction history
  cards/              five card products, with evidence on every rule
  mastercard/         network benefits, the simulated offer, Priceless
  itineraries/        the frozen rehearsed scenario
```

## Determinism

The dataset is generated under a fixed seed **and committed**, so regeneration
cannot drift. `tests/fixtures/golden_disney_plan.json` snapshots every figure in
the rehearsed run; `test_disney_itinerary_matches_golden_line_by_line` fails the
moment any of them changes.

```bash
.venv/bin/python -m pytest        # 115 tests
```

## Known deviations

- Alex's `other` spend lands near $1,200 against the $8,000 in the original plan.
  That bucket is a residual, and padding it would have meant ~100 meaningless
  transactions. Every other category tracks its target closely.
- Restaurant spend is a genuine three-way tie at 1.0 cents per point between Citi
  Strata Premier, Chase Freedom Unlimited and Chase Sapphire Preferred. The
  disclosed network tiebreak resolves it to the Strata Premier. If a judge asks why
  that line went to Mastercard, the honest answer is in the output itself: the
  options were worth exactly the same, and the preference is stated rather than
  hidden. No figure changes either way.
