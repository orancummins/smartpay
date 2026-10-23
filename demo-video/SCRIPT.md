# SmartPay demo film — narration script
Runtime 3:45 · 1920×1080 · 30 fps · neural voice-over (Kokoro, voice `af_heart`)

## 0:00 — Title

Meet SmartPay. Payment intelligence from Mastercard, built to live inside the AI assistants people already use. Your AI knows what you want. SmartPay knows how you should pay.

## 0:14 — Meet Alex

This is Alex. Three banks, nine accounts, seven cards, and twelve months of spending, all connected through Open Finance. Like most of us, Alex pays by habit. The Sapphire Preferred for flights and dinners, the Double Cash at the supermarket. And habit is rarely the best way to pay.

## 0:33 — How it works

SmartPay runs as a Model Context Protocol server. ChatGPT understands the request and calls SmartPay's read-only tools. A deterministic Python engine then does the work. It infers how Alex normally pays, tests every eligible benefit, offer and reward rule, and compares cards and booking channels. No language model calculates a single figure, and every number comes back with its evidence.

## 1:00 — Inside ChatGPT — the ask

Here's what it feels like inside ChatGPT. Alex asks for a five-night Disney World trip for a family of four in October. ChatGPT plans it: flights, hotel, park tickets, airport transfers and dining. Seven thousand, eight hundred and forty-eight dollars in all. Then it hands the itinerary to SmartPay.

## 1:22 — The SmartPay component

The answer arrives as a live SmartPay component, right inside the conversation. Five hundred and forty-two dollars and ninety cents of guaranteed value, compared with how Alex would normally pay. And for every line: the card Alex would have reached for, the card SmartPay recommends, and the channel to book it through.

## 1:42 — Full breakdown

Three hundred and sixty dollars in checked-bag fees waived, by paying for the American Airlines flights with the AAdvantage World Elite Mastercard. A hundred dollars off the hotel, booked through Citi Travel on the Strata Premier, at ten times points instead of three. Real Mastercard card-linked offers on the airport Lyft and the Orlando Eye. And where two cards are worth exactly the same, Mastercard funds the difference, and says so, right on the line.

## 2:09 — Honesty rules

Every figure is traceable. Guaranteed value, money Alex verifiably does not pay, is never merged with estimated rewards. Every rule carries its source and the date it was verified. Channel rules are enforced, so a portal rate never pays out on a direct booking. SmartPay is read-only. It never moves money and never applies for anything. Even the Priceless golf experience it suggests is there because Alex's own ledger shows sixteen rounds of golf.

## 2:38 — Open Finance dashboard

Behind the conversation sits Alex's Open Finance dashboard. One thousand, four hundred and seventy-seven dollars Alex could have saved last year, computed by re-scoring every one of five hundred and seventy-two real transactions against every card in the wallet. Every question asked through any connected assistant lands here automatically, alongside Priceless experiences and Mastercard offers matched to what Alex has been researching.

## 3:06 — Wallet review + Admin

And one more thing. Ask SmartPay to review the wallet, and it forecasts the next twelve months of spend and tests every card against it. Here, it flags an annual fee that no longer earns its keep, and a funded offer that would change that. For Mastercard, the same engine powers an internal view: portfolio performance across every AI platform, and Flipper, a campaign studio that funds offers exactly where a card switch is in play.

## 3:34 — Close

SmartPay. The right card, every time. From accepted everywhere, to chosen every time.

## How it was made

Everything on screen is driven by the real repo:

- `optimise_itinerary`, `optimise_wallet`, `get_wallet`, `get_financial_profile` and
  `get_recommendation_evidence` were run through `SmartPayService` to produce the exact
  tool output ChatGPT receives; the figures in the film ($542.90 guaranteed, $379.62
  estimated, 37,612 points, $1,477.44 retrospective, $99 wallet switch) come from that run.
- The ChatGPT component is the real `ui://widget/smartpay-plan.html` from `app/widget.py`,
  hydrated with that tool output through `window.openai.toolOutput`, in both inline and
  fullscreen display modes.
- The Open Finance dashboard and SmartPay Admin screens are screenshots of
  `app.dashboard_server` running against the committed Alex dataset.
- Card art, bank logos, the Mastercard mark and the Priceless imagery are the files under
  `app/static/`; the "How it works" scene reuses the copy and structure of
  `smartpay-slide.svg`.
- The ChatGPT chrome around the component is a faithful recreation, not a screen recording.

To re-render: see `build/README.md`.
