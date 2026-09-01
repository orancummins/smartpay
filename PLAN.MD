# SmartPay Hackathon Demo — Agent Build Plan

## 1. Objective

Build a credible, deterministic SmartPay demo in Python that can be invoked from real ChatGPT through MCP.

The demo must show that SmartPay can:

1. Understand a consumer's current financial behaviour across two banks.
2. Know which cards the consumer owns.
3. Evaluate card rewards, benefits, fees, Mastercard benefits, offers, and Priceless experiences.
4. Infer how the consumer would normally pay.
5. Recommend a better way to pay for an itinerary or individual purchase.
6. Quantify hard savings, rewards, fees avoided, and incremental benefits.
7. Forecast future spend using a CommerceGPT adapter.
8. Recommend whether the consumer should keep, replace, or add a card.
9. Explain every recommendation with provenance.
10. Run locally in Python and be exposed to real ChatGPT through MCP.

The system should feel evidence-backed rather than scripted.

---

# 2. Product Positioning

SmartPay is not simply a card recommender.

It is:

> An AI payment intelligence layer that understands what a consumer intends to buy, how they currently manage their money, and the economics of every available payment option — then constructs the optimal way to pay.

Primary demo tagline:

> Your AI knows what you want. SmartPay knows how you should pay.

---

# 3. Primary Demo Scenario

Use one consumer persona only.

## Persona: Alex

Alex is a US-based consumer with:

- Two connected financial institutions.
- Five payment cards.
- Two checking accounts.
- Roughly 12 months of synthetic but realistic transaction history.
- Travel, dining, grocery, entertainment, utility, transport, ATM, card payment and ACH behaviour.
- A mixture of Mastercard and non-Mastercard cards.
- Imperfect payment habits.

The main scripted scenario is:

> "Plan Alex a five-night Disney World vacation for a family of four in October. Include flights, hotel, Disney tickets, airport transport, restaurants and incidentals. Then use SmartPay to determine how Alex should pay for each part of the trip and show how this compares with how Alex would normally pay."

ChatGPT should plan the itinerary and call the SmartPay MCP server.

SmartPay should return:

- Alex's likely baseline payment choice.
- Recommended payment method per itinerary item.
- Hard savings.
- Reward points/cashback.
- Fees avoided.
- Qualifying benefits.
- Simulated Mastercard offer effects.
- Relevant Priceless experience suggestions.
- Total incremental value.
- Evidence/provenance.
- Optional wallet optimisation recommendation.

---

# 4. Demo Consumer Wallet

Use publicly credible card products and rules.

Recommended demo wallet:

| Institution | Instrument | Purpose |
|---|---|---|
| Citi | Citi Strata Premier Mastercard | Travel/dining/supermarket/gas rewards |
| Citi | Citi Double Cash Mastercard | Everyday baseline card |
| Citi | Citi / AAdvantage Platinum Select World Elite Mastercard | Airline + World Elite benefits |
| Chase | Chase Sapphire Preferred | Strong competing travel card |
| Chase | Chase Freedom Unlimited | Strong competing everyday card |
| Citi | Checking + debit | Debit / ACH / ATM |
| Chase | Checking + debit | Debit / ACH / ATM |

Important principle:

SmartPay must occasionally recommend a non-Mastercard card if it is genuinely the best option.

This makes later Mastercard acquisition recommendations more credible.

---

# 5. Synthetic Transaction Dataset

Generate approximately 12 months of transactions.

Target:

- ~550–600 total payment events.
- Realistic monthly cadence.
- Realistic merchant/category distribution.
- Internal transfers reconciled correctly.
- Card payments not double-counted as consumer spend.
- ATM withdrawals visible but cash usage not over-inferred.
- Recurring subscriptions and utilities.
- Travel patterns.
- Restaurant patterns.
- Grocery patterns.
- Ride-hailing usage.
- Credit card autopay behaviour.
- Salary / income deposits.
- ACH payments.
- Debit spending.

Suggested annual spend profile:

| Category | Approx Annual Spend |
|---|---:|
| Housing | $36,000 |
| Groceries | $10,800 |
| Dining | $11,500 |
| Travel | $15,000 |
| Entertainment | $4,500 |
| Fuel / Transport | $5,500 |
| Shopping | $8,000 |
| Utilities / Subscriptions | $6,000 |
| Other | $8,000 |

The exact numbers are less important than believable patterns.

---

# 6. Alex's Existing Payment Habits

Do not generate optimised behaviour.

Alex needs predictable but imperfect habits.

Suggested probability patterns:

| Category | Current Behaviour |
|---|---|
| Everyday purchases | Freedom Unlimited 65% |
| Restaurants | Sapphire Preferred 70% |
| Flights | Sapphire Preferred 75% |
| Hotels | Sapphire Preferred 60% |
| Groceries | Citi Double Cash 50% |
| Gas | Freedom Unlimited 55% |
| Lyft | Randomly split |
| Large purchases | Double Cash |
| Rent | ACH |
| Utilities | ACH / debit |
| ATM | Chase checking |
| Foreign purchases | Sometimes wrong card |

This allows SmartPay to calculate:

> What would Alex probably have done?

versus:

> What should Alex do?

---

# 7. Data Integrity Rules

Transaction generation must be ledger-consistent.

Example:

A $1,200 card purchase is:

- Spend on a credit card account.

Later, payment of that balance is:

- Outflow from checking.
- Credit card payment / internal transfer.
- Excluded from consumer spend totals.

The validator must detect:

- Double counting.
- Missing card payment relationships.
- Impossible balances.
- Invalid dates.
- Negative/incorrect account math.
- Duplicate transactions.
- Unrealistic monthly volumes.

ATM withdrawals:

- Count as cash withdrawal activity.
- Do not fabricate merchant-level cash spending.

---

# 8. Mastercard Open Finance Abstraction

Implement a provider abstraction.

```python
class OpenFinanceProvider(Protocol):
    def get_accounts(self, customer_id: str): ...
    def get_transactions(self, customer_id: str): ...
    def get_balances(self, customer_id: str): ...
```

Implement two providers:

```text
SyntheticAlexProvider
MastercardTestDriveProvider
```

Default to `SyntheticAlexProvider`.

The application should be structured so Mastercard Open Finance Test Drive can later be plugged in without changing the optimisation engine.

---

# 9. Card Knowledge Base

Do not scrape card rules live during the demo.

Create curated structured files.

Suggested structure:

```text
data/
  cards/
    citi_strata_premier.yaml
    citi_double_cash.yaml
    citi_aa_world_elite.yaml
    chase_sapphire_preferred.yaml
    chase_freedom_unlimited.yaml

  mastercard/
    world.yaml
    world_elite.yaml
    offers.yaml
    priceless.yaml
```

Every rule must include provenance.

Example:

```yaml
rule_id: CSP_DINING_3X
card_product: chase_sapphire_preferred

rule:
  category: restaurant
  reward_currency: ultimate_rewards
  multiplier: 3.0

evidence:
  source_name: Chase
  source_type: issuer
  verified_at: 2026-09-01
  source_url: "..."
  confidence: authoritative
```

Do not copy full legal terms.

Store structured facts plus evidence.

---

# 10. Mastercard Benefits

Include a small number of real Mastercard benefit rules.

Examples of categories to model:

- Lyft credits/discounts.
- Instacart credits.
- Peacock credit.
- Priceless access.
- Travel-related benefits.
- Purchase protection where appropriate.
- World / World Elite eligibility.

Represent benefits separately from issuer rewards.

Example:

```yaml
benefit_id: MC_WE_LYFT_MONTHLY
network: mastercard
tier: world_elite
merchant: lyft
benefit_type: statement_credit
qualification:
  min_rides_per_month: 3
value:
  currency: USD
  amount: 5.00
```

---

# 11. Mastercard Offers

Include synthetic offer instances based on real card-linked offer mechanics.

Never imply a fictional offer is genuinely live.

Example:

```yaml
offer_id: DEMO_DISNEY_001

merchant:
  name: Walt Disney World

eligibility:
  card_product: citi_strata_premier
  minimum_spend: 750

benefit:
  type: statement_credit
  value: 75

valid_from: 2026-08-01
valid_to: 2026-11-30

provenance:
  status: synthetic_demo_offer
  modelled_on: mastercard_card_linked_offer_mechanics
```

UI should explicitly label such offers:

> Simulated Mastercard card-linked offer

---

# 12. Priceless

Support a small set of real or evidence-backed Priceless experiences.

Priceless recommendations should not necessarily be included in hard savings.

Treat them as:

```text
Additional Experience Value
```

Example output:

> Your historical spending suggests you enjoy golf. A Mastercard-exclusive Orlando experience is available during your trip.

---

# 13. Core Domain Models

Implement with Pydantic.

Minimum models:

```text
Account
Transaction
Merchant
CardProduct
CardInstance
RewardRule
BenefitRule
Offer
PricelessExperience
FinancialProfile
PurchaseIntent
Itinerary
ItineraryItem
PaymentOption
PaymentRecommendation
PaymentPlan
WalletRecommendation
Evidence
FutureSpendForecast
```

---

# 14. PurchaseIntent Model

Example:

```json
{
  "merchant": "Delta",
  "category": "airfare",
  "amount": 1650,
  "currency": "USD",
  "date": "2026-10-12",
  "location": "US",
  "purchase_channel": "direct",
  "metadata": {
    "origin": "BOS",
    "destination": "MCO",
    "travellers": 4,
    "checked_bags": 2
  }
}
```

Another example:

```json
{
  "merchant": "Walt Disney World",
  "category": "attraction",
  "amount": 1780,
  "currency": "USD",
  "purchase_channel": "merchant_direct"
}
```

---

# 15. Purchase Channel Qualification

This is critical.

Reward rules may depend on booking channel.

Example:

If a reward rule says attractions receive 10x only through an issuer travel portal, then:

```text
purchase_channel = issuer_travel_portal
```

qualifies.

But:

```text
purchase_channel = merchant_direct
```

does not.

The engine must never award portal-specific rewards to direct merchant purchases.

---

# 16. Optimisation Logic

For each purchase, evaluate all available payment instruments.

Potential instruments:

```text
Card 1
Card 2
Card 3
Card 4
Card 5
Debit
ACH / A2A
```

Compute independently:

```text
Hard savings
Cashback
Statement credits
Reward points
Estimated reward value
Fees avoided
FX fees
Interest/financing cost
Quantifiable benefits
Soft benefits
```

Keep them separate.

Do not collapse uncertain value into fake precision.

Recommended presentation:

```text
Guaranteed savings: $183
Estimated reward value: $72
Additional benefits:
- Travel protection
- Lounge access
- 18,420 points
```

---

# 17. Rewards Engine

Create:

```python
class RewardsEngine:
    def evaluate(
        self,
        purchase: PurchaseIntent,
        card: CardInstance
    ) -> RewardEvaluation:
        ...
```

It must support:

- Base earn.
- Category multipliers.
- Merchant-specific multipliers.
- Portal/channel requirements.
- Caps.
- Minimum transaction values.
- Date windows.
- Annual limits where needed.
- Reward currency type.
- Card-specific rules.

---

# 18. Offers Engine

Create:

```python
class OffersEngine:
    def evaluate(
        self,
        purchase: PurchaseIntent,
        card: CardInstance,
        customer_profile: FinancialProfile
    ) -> list[OfferEvaluation]:
        ...
```

Support:

- Merchant.
- Card eligibility.
- Minimum spend.
- Campaign start/end dates.
- Cashback.
- Statement credits.
- Points offers.
- Frequency limits.

---

# 19. Benefits Engine

Create:

```python
class BenefitsEngine:
    def evaluate_purchase(...): ...
    def evaluate_monthly_behavior(...): ...
```

This engine should handle benefits that are not simple transaction multipliers.

Example:

Three Lyft rides in a month may activate a Mastercard benefit.

It may require looking at monthly transaction history, not only the current transaction.

---

# 20. Baseline Engine

This is a key differentiator.

Build a simple probabilistic baseline.

Calculate:

```text
P(payment instrument | category)
P(payment instrument | merchant)
P(payment instrument | merchant + category)
```

No ML framework required.

Use observed transaction frequencies.

Example:

```text
Travel:
  Sapphire Preferred     0.72
  Citi Strata            0.15
  Freedom Unlimited      0.07
  Double Cash            0.06
```

For a future flight purchase SmartPay can say:

> Based on Alex's previous behaviour, Alex would most likely have used Sapphire Preferred.

The counterfactual is therefore grounded in actual behaviour.

---

# 21. Counterfactual Engine

Create:

```python
class CounterfactualEngine:
    def estimate_baseline(
        self,
        purchase: PurchaseIntent,
        profile: FinancialProfile
    ) -> BaselinePayment:
        ...
```

For each purchase calculate:

```text
Likely baseline payment method
Baseline expected value
Optimal payment method
Optimal expected value
Delta
```

The main SmartPay metric is:

```text
SmartPay Incremental Value
```

---

# 22. Future Spend / CommerceGPT Adapter

Define:

```python
class FutureSpendProvider(Protocol):
    def predict(
        self,
        profile: FinancialProfile,
        horizon_months: int
    ) -> FutureSpendForecast:
        ...
```

Implement:

```text
CommerceGPTProvider
CommerceGPTMockProvider
```

Until a real API exists, the mock should use:

- 12-month spend history.
- Category run rate.
- Seasonal effects.
- Recurring merchants.
- Known upcoming itinerary.
- Simple growth/decay assumptions.

Example output:

```json
{
  "travel": 17400,
  "restaurants": 10800,
  "groceries": 9600,
  "transport": 5100,
  "entertainment": 3900
}
```

Label this clearly in the demo as:

> Demo CommerceGPT adapter

---

# 23. Wallet Optimisation

Evaluate the current wallet against candidate card configurations.

For each candidate:

```text
Current wallet expected annual value
Candidate wallet expected annual value
Incremental rewards
Fees avoided
Likely-used credits
Annual fees
Net incremental value
```

Formula:

```text
Net Annual Incremental Value
=
Incremental reward value
+ credits likely to be used
+ fees avoided
- incremental annual fee
```

The recommendation should explain why.

Example:

> Consider replacing Card X with Mastercard Y.

> Estimated incremental annual value: $410.

> Driven by:
> - $17,400 predicted travel
> - $10,800 dining
> - $9,600 groceries
> - Alex's historical merchant mix
> - Current card fees and rewards

---

# 24. Point Valuation

Do not hard-code controversial market valuations.

Make valuations configurable.

Example:

```yaml
reward_valuations:
  citi_thankyou:
    cents_per_point: 1.0
  chase_ultimate_rewards:
    cents_per_point: 1.0
  american_airlines_miles:
    cents_per_point: 1.0
```

Output:

```text
Guaranteed value
Estimated reward value
Additional benefits
```

rather than one misleading number.

---

# 25. Evidence / Provenance

Every recommendation must be auditable.

Model:

```python
class Evidence(BaseModel):
    evidence_type: str
    source_name: str
    source_url: str | None
    verified_at: date | None
    confidence: str
    note: str | None
```

Every result should be able to answer:

> Why did SmartPay choose this?

Possible evidence categories:

```text
Issuer reward rule
Mastercard network benefit
Synthetic demo offer
Priceless experience
Open Finance transaction history
CommerceGPT prediction
SmartPay deterministic calculation
```

---

# 26. Repository Structure

Use:

```text
smartpay/
│
├── app/
│   ├── main.py
│   ├── mcp_server.py
│   ├── config.py
│   │
│   ├── models/
│   │   ├── account.py
│   │   ├── transaction.py
│   │   ├── merchant.py
│   │   ├── card.py
│   │   ├── benefit.py
│   │   ├── offer.py
│   │   ├── itinerary.py
│   │   ├── recommendation.py
│   │   ├── evidence.py
│   │   └── forecast.py
│   │
│   ├── providers/
│   │   ├── open_finance.py
│   │   ├── synthetic_alex.py
│   │   ├── mastercard_testdrive.py
│   │   ├── future_spend.py
│   │   ├── commercegpt.py
│   │   └── commercegpt_mock.py
│   │
│   ├── engines/
│   │   ├── categorizer.py
│   │   ├── baseline.py
│   │   ├── rewards.py
│   │   ├── offers.py
│   │   ├── benefits.py
│   │   ├── counterfactual.py
│   │   ├── optimizer.py
│   │   └── wallet_optimizer.py
│   │
│   ├── services/
│   │   ├── smartpay.py
│   │   └── evidence.py
│   │
│   └── db/
│       ├── session.py
│       └── schema.py
│
├── data/
│   ├── alex/
│   ├── cards/
│   ├── mastercard/
│   └── merchants/
│
├── scripts/
│   ├── generate_alex.py
│   ├── validate_ledger.py
│   ├── validate_rules.py
│   └── seed_demo.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── docs/
│   └── evidence/
│
├── pyproject.toml
├── README.md
└── .env.example
```

---

# 27. Python Stack

Use a simple stack.

```text
Python 3.12+
FastAPI
Pydantic
MCP Python SDK
SQLite
SQLAlchemy
pandas
numpy
faker
httpx
pytest
uvicorn
rapidfuzz
```

Rules:

- Use `Decimal` for money.
- Do not use floats for monetary calculations.
- No LangChain.
- No vector database.
- No agent framework inside SmartPay core.
- No LLM for optimisation.
- Deterministic logic only.

LLMs may explain results but must not calculate them.

---

# 28. SmartPay Service Interface

Create an application service:

```python
class SmartPayService:
    def get_financial_profile(self, customer_id: str): ...
    def get_wallet(self, customer_id: str): ...
    def optimise_purchase(self, customer_id: str, purchase: PurchaseIntent): ...
    def optimise_itinerary(self, customer_id: str, itinerary: Itinerary): ...
    def optimise_wallet(self, customer_id: str): ...
    def get_recommendation_evidence(self, recommendation_id: str): ...
```

MCP and REST should both call this same service.

---

# 29. MCP Tools

Expose only high-level tools.

Required MCP tools:

```text
get_financial_profile
get_wallet
optimise_purchase
optimise_itinerary
optimise_wallet
get_recommendation_evidence
```

Do not expose implementation-level tools unless needed.

Example:

```python
@mcp.tool()
def optimise_itinerary(customer_id: str, itinerary: dict):
    return smartpay.optimise_itinerary(
        customer_id=customer_id,
        itinerary=Itinerary.model_validate(itinerary)
    )
```

---

# 30. MCP Transport

Run the server locally using Streamable HTTP.

Target local endpoint:

```text
http://localhost:9022/mcp
```

The server should also expose:

```text
GET /health
GET /demo/alex
```

for debugging.

---

# 31. Real ChatGPT Integration

Real ChatGPT cannot directly call the local localhost MCP endpoint.

Expose it securely using one of:

```text
Secure MCP Tunnel
Cloudflare Tunnel
Other HTTPS tunnel approved for the demo
```

Target:

```text
https://<public-demo-host>/mcp
```

Then register the MCP endpoint in ChatGPT Developer Mode / custom app configuration.

The demo must use:

```text
Real ChatGPT
    ↓
Public HTTPS MCP endpoint
    ↓
Local Python SmartPay MCP server
    ↓
SmartPay deterministic engine
```

Do not build a fake ChatGPT UI.

---

# 32. REST API

MCP should not be the architecture.

Also expose REST.

Suggested endpoints:

```text
GET  /api/customers/{customer_id}/profile
GET  /api/customers/{customer_id}/wallet
POST /api/customers/{customer_id}/optimise/purchase
POST /api/customers/{customer_id}/optimise/itinerary
POST /api/customers/{customer_id}/optimise/wallet
GET  /api/recommendations/{recommendation_id}/evidence
```

SmartPay core should remain channel-independent.

---

# 33. Demo Itinerary

Target itinerary:

```text
Flights                   ~$1,420
Hotel                     ~$2,450
Disney tickets            ~$1,780
Airport transport           ~$180
Restaurants                 ~$950
Other                       ~$700

Total                     ~$7,480
```

These values may change but should stay stable for the rehearsed demo.

---

# 34. Demo Output

Target response shape:

```json
{
  "customer_id": "alex",
  "itinerary_total": 7480,
  "baseline_value": {
    "hard_value": 0,
    "reward_value": 105
  },
  "smartpay_value": {
    "hard_savings": 287,
    "estimated_reward_value": 173,
    "additional_points": 18420
  },
  "incremental_hard_value": 287,
  "recommendations": [
    {
      "purchase": "Flights",
      "baseline_payment": "Chase Sapphire Preferred",
      "recommended_payment": "Citi / AAdvantage World Elite",
      "hard_savings": 0,
      "estimated_reward_value_delta": 22,
      "benefits": [
        "..."
      ]
    }
  ]
}
```

Do not hard-code the result.

The value should emerge from rules and data.

---

# 35. Demo Flow

## Step 1

User asks ChatGPT:

> Plan Alex a five-night Disney World trip for a family of four in October. Budget around $8,000. Include flights, hotel, Disney tickets, airport transport and dining. Then use SmartPay to optimise how Alex pays for it.

## Step 2

ChatGPT creates itinerary.

## Step 3

ChatGPT calls:

```text
SmartPay.optimise_itinerary(...)
```

## Step 4

SmartPay returns:

- baseline payment method per item.
- recommended method.
- guaranteed savings.
- estimated reward value.
- additional benefits.
- evidence.

## Step 5

ChatGPT presents:

> SmartPay found $X of guaranteed value plus Y points.

## Step 6

ChatGPT calls:

```text
SmartPay.optimise_wallet(...)
```

## Step 7

SmartPay returns future wallet recommendation.

## Step 8

ChatGPT presents:

> SmartPay noticed something else...

> Your wallet is not optimal for your predicted spend.

This is the closing moment.

---

# 36. Build Phases

## Phase 1 — Foundation

Deliverables:

- Project skeleton.
- Pydantic models.
- SQLite schema.
- Data loader.
- Basic tests.
- Decimal money utilities.
- Customer = `alex`.

Acceptance criteria:

- App starts.
- SQLite creates cleanly.
- Core models validate.
- Test suite runs.

---

## Phase 2 — Alex Dataset

Deliverables:

- `generate_alex.py`.
- Two banks.
- Checking accounts.
- Five cards.
- ~550–600 transactions.
- Salary.
- ACH.
- ATM.
- Credit card payments.
- Recurring payments.
- Merchant/category mappings.
- Spend habits.

Acceptance criteria:

- Ledger validator passes.
- No card payment double counting.
- Monthly payment counts plausible.
- Category totals approximately align to target profile.

---

## Phase 3 — Card Intelligence

Deliverables:

- Five card YAML files.
- Reward rules.
- Mastercard benefits.
- Simulated offers.
- Priceless records.
- Evidence metadata.
- Rule validator.

Acceptance criteria:

- Every rule has evidence metadata.
- Rules load without conflicts.
- Portal/channel qualification works.
- Expired rules/offers do not qualify.

---

## Phase 4 — Engines

Deliverables:

- Categorizer.
- Rewards engine.
- Offers engine.
- Benefits engine.
- Baseline engine.
- Counterfactual engine.
- Purchase optimiser.
- Itinerary optimiser.

Acceptance criteria:

- Unit tests for known purchases.
- Same purchase can produce different results by channel.
- Non-Mastercard card can win when appropriate.
- Baseline is driven by Alex history.
- Optimiser is deterministic.

---

## Phase 5 — Forecast and Wallet

Deliverables:

- FutureSpendProvider.
- CommerceGPTMockProvider.
- Wallet optimiser.

Acceptance criteria:

- Forecast reproducible with fixed seed.
- Wallet recommendation includes net annual incremental value.
- Annual fees included.
- Recommendation lists key drivers.

---

## Phase 6 — MCP

Deliverables:

- MCP server.
- Six tools.
- Streamable HTTP.
- `/health`.
- MCP Inspector test.

Acceptance criteria:

- MCP Inspector can call all tools.
- JSON responses validate.
- No LLM dependency.

---

## Phase 7 — ChatGPT Integration

Deliverables:

- Public HTTPS tunnel.
- ChatGPT app/custom MCP connection.
- Rehearsed Disney prompt.

Acceptance criteria:

- ChatGPT successfully invokes SmartPay.
- SmartPay returns deterministic results.
- Evidence can be queried.
- Demo can run repeatedly without code changes.

---

## Phase 8 — Polish

Deliverables:

- Cleaner output formatting.
- Human-readable card names.
- Evidence URLs.
- Demo reset script.
- Seeded data.
- README.
- One-command startup.

Desired commands:

```bash
make demo
```

or:

```bash
./run_demo.sh
```

---

# 37. Testing Requirements

Minimum unit tests:

```text
test_reward_base_earn
test_reward_category_multiplier
test_portal_only_rule
test_direct_booking_does_not_receive_portal_bonus
test_offer_minimum_spend
test_offer_date_window
test_world_elite_benefit
test_card_payment_is_not_consumer_spend
test_atm_withdrawal_classification
test_baseline_probability
test_counterfactual_delta
test_non_mastercard_can_win
test_wallet_annual_fee_deduction
test_decimal_money
```

Integration tests:

```text
test_alex_profile_builds
test_disney_itinerary_optimises
test_wallet_optimisation
test_mcp_get_wallet
test_mcp_optimise_itinerary
```

---

# 38. Demo Reliability Rules

Hackathon demo reliability matters more than breadth.

Rules:

- Use fixed seeds.
- No live scraping.
- No live dependency on card issuer sites.
- No uncontrolled LLM calculations.
- No random itinerary values once demo is rehearsed.
- Cache/card data locally.
- Keep external dependencies minimal.
- MCP should be read-only.
- Ensure demo can run offline except for ChatGPT connectivity/tunnel.

---

# 39. Security Scope

For the hackathon:

Do not implement:

```text
apply_for_card
make_payment
purchase
move_money
switch_card
open_account
```

SmartPay is read-only and advisory.

Allowed:

```text
read profile
read wallet
analyse
optimise
recommend
explain
```

---

# 40. Success Criteria

The demo is complete when all eight conditions are met:

1. ChatGPT genuinely calls the SmartPay MCP server.
2. Alex has realistic two-bank synthetic transaction history.
3. SmartPay infers how Alex normally pays.
4. Real card reward rules influence recommendations.
5. Real Mastercard benefits influence at least one recommendation.
6. A clearly labelled simulated Mastercard offer influences at least one Disney purchase.
7. Future spend prediction drives a wallet recommendation.
8. Every recommendation can show evidence/provenance.

Do not add more major functionality until all eight work reliably.

---

# 41. Recommended Agent Execution Order

An implementation agent should work in this order:

```text
1. Create repo structure.
2. Create domain models.
3. Create SQLite schema.
4. Build Alex generator.
5. Build ledger validator.
6. Seed card knowledge.
7. Build reward rules engine.
8. Build offers engine.
9. Build benefits engine.
10. Build baseline engine.
11. Build counterfactual engine.
12. Build itinerary optimiser.
13. Build future spend mock.
14. Build wallet optimiser.
15. Add evidence system.
16. Add REST API.
17. Add MCP server.
18. Test with MCP Inspector.
19. Expose via HTTPS tunnel.
20. Connect real ChatGPT.
21. Rehearse Disney scenario.
22. Freeze demo seed/data.
23. Polish README and startup script.
```

---

# 42. First Agent Task

Start by creating:

```text
smartpay/
pyproject.toml
README.md
app/models/
app/db/
data/
scripts/
tests/
```

Then implement:

```python
Money
Account
Transaction
CardProduct
CardInstance
PurchaseIntent
Evidence
```

Then add a minimal CLI:

```bash
python scripts/generate_alex.py
python scripts/validate_ledger.py
pytest
```

Do not start MCP work until the underlying SmartPay engine works from direct Python tests.

---

# 43. Definition of Done

A judge should be able to watch the following without being told anything is mocked except where explicitly labelled:

> ChatGPT plans Alex's Disney trip.

> SmartPay reads Alex's synthetic two-bank Open Finance profile.

> SmartPay knows the economics of Alex's real card products.

> SmartPay predicts what Alex would normally use.

> SmartPay finds a better payment plan.

> SmartPay quantifies value.

> SmartPay identifies benefits and experiences.

> SmartPay explains the evidence behind the recommendation.

> SmartPay predicts Alex's future spending.

> SmartPay recommends a better wallet.

The final impression should be:

> This is not a card picker. It is a payment intelligence layer.
