# Priceless catalogue seed for SmartPay

This package contains a structured US Priceless catalogue compiled from public,
search-indexed information available on 2 September 2026. It does **not** scrape
Priceless.com. Priceless's terms prohibit automated site scraping.

## Files

- `priceless_catalogue.sqlite` — ready-to-query SQLite database
- `priceless_catalogue.csv` — flattened export
- `priceless_catalogue.json` — full records with tags
- `schema.sql` — schema, indexes and SmartPay-oriented views
- `build_catalogue.py` — deterministic database/export builder

## Data-quality rules

- `HIGH`: a specific public product URL and principal details were substantiated.
- `MEDIUM`: publicly surfaced or Collection-listed, but one or more fields or the
  exact product URL still needs enrichment.
- `source_url` is the evidence URL.
- `visual_page_url` is the canonical page from which SmartPay may link users to
  imagery. `direct_image_url` is deliberately empty: image reuse rights and URL
  stability cannot be assumed without the official API or an approved media feed.
- No record should be described to a user as "live" without checking
  `availability_status`, `valid_to`, `booking_end`, and `last_verified_at`.

## Useful queries

```sql
SELECT title, city, price_amount, source_url
FROM active_offers
WHERE city = 'New York'
ORDER BY category, title;

SELECT title, city, eligibility_tier, alex_signal_count, visual_page_url
FROM alex_relevant_offers
LIMIT 20;
```

## Rebuild

```bash
python3 build_catalogue.py
```

## Production recommendation

Replace this research seed with the Priceless Platform API or an approved
Mastercard catalogue export when credentials become available. The seed remains
useful for demos, matching logic, MCP development and UI work.
