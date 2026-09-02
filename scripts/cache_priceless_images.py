"""Fetch and cache a real image for every Priceless catalogue offer.

Run once (or whenever data/priceless_catalogue_smartpay/priceless_catalogue.json
changes) to populate app/static/priceless/ and
data/priceless_catalogue_smartpay/image_cache.json. Safe to re-run any time --
already-cached subjects are skipped, so this only ever fetches what changed.

No live scraping at demo time (PLAN.MD section 9): this is the one place
SmartPay reaches the network for Priceless imagery. app.knowledge reads the
manifest this script writes back in as plain, offline data.

Run:  python scripts/cache_priceless_images.py
"""

from __future__ import annotations

import json

from app import config, priceless_images

CATALOGUE_PATH = config.DATA / "priceless_catalogue_smartpay" / "priceless_catalogue.json"


def main() -> None:
    entries = json.loads(CATALOGUE_PATH.read_text())
    pairs = [(e["offer_id"], e.get("category") or "") for e in entries]
    print(f"{len(pairs)} catalogue offers, resolving to distinct image subjects...")

    summary = priceless_images.cache_subjects_for(pairs)

    print("Done.")
    for key, count in summary.items():
        print(f"  {key}: {count}")


if __name__ == "__main__":
    main()
