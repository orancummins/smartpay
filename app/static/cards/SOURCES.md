# Card art and logo sources

Downloaded 2026-09-01 from the current issuer product pages for local demo use.

- `citi_strata_premier.webp`: https://aemapi.citi.com/content/dam/cfs/uspb/usmkt/cards/en/static/images/citi-strata-premier-credit-card/citi-strata-premier-credit-card_306x192.webp
- `citi_double_cash.webp`: https://aemapi.citi.com/content/dam/cfs/uspb/usmkt/cards/en/static/images/citi-double-cash-credit-card/citi-double-cash-credit-card_306x192.webp
- `citi_aa_platinum_select.webp`: https://aemapi.citi.com/content/dam/cfs/uspb/usmkt/cards/en/static/images/citi-aadvantage-platinum-elite-credit-card/citi-aadvantage-platinum-select-elite-credit-card_306x192.webp
- `chase_sapphire_preferred.png`: https://creditcards.chase.com/content/dam/jpmc-marketplace/card-art/sapphire-preferredcard2026.png
- `chase_freedom_unlimited.png`: https://creditcards.chase.com/content/dam/jpmc-marketplace/card-art/freedom_unlimited_card_alt.png

## Institution logos

- `../logos/citi.svg`: https://aemapi.citi.com/content/dam/cfs/mobile/assets/CBOL/IA/Angular/assets/citiredesign.svg
- `../logos/chase.svg`: https://creditcards.chase.com/content/dam/jpmc-marketplace/site-assets/logos/chasebank-logo-icon-bluebg_2025.svg
- `../logos/mastercard.svg`: https://www.mastercard.com/content/dam/mccom/shared/header/ma_symbol.svg

## Cardholder name

The three Citi shots ship embossed with **LINDA WALKER**, Citi's marketing
placeholder. On a dashboard about Alex Morgan that reads as a bug, so
`scripts/restyle_card_art.py` rewrites the name to match the persona. The Chase art
carries no name and is untouched.

Unmodified downloads are kept in `_original/`, so the edit is reversible and the
provenance above still refers to files you can diff against. Re-run the script after
re-downloading any card.

These images and marks remain the property of their respective issuers and are used
here only to identify the products a simulated wallet holds.
