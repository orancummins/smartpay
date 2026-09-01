"""Seed Alex's profile into BankSym as two real bank tenants: Citi and Chase.

PLAN.MD section 8 asks for a provider abstraction so a real Open Finance source can
replace the synthetic one without touching the optimisation engine. This script
supplies that source: it replays the frozen Alex dataset into BankSym over its HTTP
API, after which SmartPay can read the same profile back through Open Finance.

Alex banks with two institutions, and BankSym is multi-tenant, so Citi and Chase are
separate banks here exactly as they are in reality. Reassembling one financial
picture across both is the aggregation step Open Finance exists to perform.

Run:  python scripts/seed_banksym.py [--base-url http://127.0.0.1:8000] [--reset]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

# Logos are served by BankSym itself (see ui/logos/) rather than hot-linked, so the
# demo still renders with no network. Both marks are published on Wikimedia Commons
# as public domain -- they fall below the threshold of originality, being simple
# shapes and text -- but they remain registered trademarks of their owners and are
# used here only to identify the institution each simulated tenant stands in for.
INSTITUTIONS = {
    "citi": {
        "display_name": "Citi",
        "primary_color": "#056DAE",
        "logo_url": "/logos/citi.svg",
    },
    "chase": {
        "display_name": "Chase",
        "primary_color": "#117ACA",
        "logo_url": "/logos/chase.svg",
    },
}

ACCOUNT_TYPE = {"checking": "current", "credit_card": "credit_card"}

CUSTOMER_NAME = "Alex Morgan"

# example.com is reserved for documentation (RFC 2606), so a synthetic persona's
# address can never collide with, or be mistaken for, a real mailbox.
CUSTOMER_EMAIL = "alex.morgan@example.com"

# BankSym issues online-banking credentials with every customer; the username
# defaults to the email. This is a demo credential for a synthetic customer in a
# test bank -- it guards nothing real.
CUSTOMER_PASSWORD = "foobar!"

# Alex's whole transaction history assumes Boston -- MBTA fares, Logan Airport
# parking, a City of Boston Water bill, and every flight departing BOS -- so the
# BankSym profile must say so explicitly. Without an address override BankSym
# generates a random US city per bank, which put Alex in Denver at Citi and Austin
# at Chase: harmless to the numbers, but visibly wrong the moment anyone looks.
CUSTOMER_ADDRESS = "22 Beacon Street\nBoston, MA 02108\nUnited States"


def load_dataset() -> dict:
    path = config.DATA / "alex" / "transactions.json"
    if not path.exists():
        raise SystemExit(f"{path} missing. Run: python scripts/generate_alex.py")
    return json.loads(path.read_text())


def reset_existing(client: httpx.Client) -> None:
    """Remove any previously seeded Citi/Chase tenants so re-running is idempotent."""
    for bank in client.get("/banks").json():
        if bank["display_name"] in {v["display_name"] for v in INSTITUTIONS.values()}:
            client.delete(f"/banks/{bank['id']}")
            print(f"  removed existing tenant {bank['display_name']} ({bank['id']})")


def create_bank(client: httpx.Client, institution: str) -> str:
    spec = INSTITUTIONS[institution]
    response = client.post(
        "/banks",
        json={
            "display_name": spec["display_name"],
            "country": "US",
            "locale": "en",
            "base_currency": "USD",
            "supported_currencies": ["USD"],
            "supported_languages": ["en"],
            "open_banking_enabled": True,
            "primary_color": spec["primary_color"],
            "logo_url": spec["logo_url"],
            # FDX is the US open banking standard and is what SmartPay reads from
            # these banks. Berlin Group stays enabled so the PSU consent/OAuth
            # journey works against them like every other BankSym tenant.
            "enabled_protocols": ["fdx", "berlin_group"],
            "capabilities": {"api": "fdx"},
        },
    )
    response.raise_for_status()
    bank_id = response.json()["id"]
    print(f"  {spec['display_name']:6} -> {bank_id}")
    return bank_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--reset", action="store_true", default=True)
    parser.add_argument("--out", default=str(config.DATA / "alex" / "banksym_handles.json"))
    args = parser.parse_args()

    data = load_dataset()
    accounts = data["accounts"]
    transactions = data["transactions"]

    with httpx.Client(base_url=args.base_url, timeout=120.0) as client:
        client.get("/health").raise_for_status()

        print("Creating bank tenants:")
        if args.reset:
            reset_existing(client)
        bank_ids = {name: create_bank(client, name) for name in INSTITUTIONS}

        print("Creating customer and accounts:")
        customer_ids: dict[str, str] = {}
        account_map: dict[str, tuple[str, str]] = {}  # smartpay id -> (bank_id, banksym id)

        for institution, bank_id in bank_ids.items():
            customer = client.post(
                f"/banks/{bank_id}/customers",
                json={
                    "full_name": CUSTOMER_NAME,
                    "email": CUSTOMER_EMAIL,
                    "country": "US",
                    "address": CUSTOMER_ADDRESS,
                    "username": CUSTOMER_EMAIL,
                    "password": CUSTOMER_PASSWORD,
                },
            )
            customer.raise_for_status()
            customer_ids[institution] = customer.json()["id"]

            for account in (a for a in accounts if a["institution"] == institution):
                created = client.post(
                    f"/banks/{bank_id}/accounts",
                    json={
                        "currency": "USD",
                        "customer_id": customer_ids[institution],
                        "type": ACCOUNT_TYPE[account["account_type"]],
                        "name": account["display_name"],
                        # Carried so the Open Finance mask matches the real card, and
                        # so SmartPay can map an aggregated account back to its product.
                        "metadata": {
                            "mask": account["mask"],
                            "smartpay_account_id": account["account_id"],
                        },
                    },
                )
                created.raise_for_status()
                account_map[account["account_id"]] = (bank_id, created.json()["id"])
            print(f"  {institution:6} customer {customer_ids[institution]}  "
                  f"login {customer.json()['username']}  "
                  f"accounts {sum(1 for a in accounts if a['institution'] == institution)}")

        print("Importing transactions:")
        by_bank: dict[str, list[dict]] = {bank_id: [] for bank_id in bank_ids.values()}
        for txn in transactions:
            target = account_map.get(txn["account_id"])
            if target is None:
                continue
            bank_id, banksym_account = target
            amount = float(txn["amount"])
            by_bank[bank_id].append({
                "account_id": banksym_account,
                # SmartPay signs money-out positive; BankSym takes a positive amount
                # plus an explicit side, so the sign becomes the side here.
                "amount": f"{abs(amount):.2f}",
                "side": "debit" if amount >= 0 else "credit",
                "booked_at": f"{txn['posted_at']}T00:00:00Z",
                "description": txn["description"],
                "reference": txn["transaction_id"],
                "merchant_name": txn["merchant"],
                "category": txn["category"],
                "channel": txn["channel"],
                "location": "US",
            })

        for institution, bank_id in bank_ids.items():
            batch = by_bank[bank_id]
            response = client.post(
                f"/banks/{bank_id}/transactions/import", json={"transactions": batch}
            )
            response.raise_for_status()
            print(f"  {institution:6} imported {response.json()['imported']} transactions")

        handles = {
            "base_url": args.base_url,
            "customer_name": CUSTOMER_NAME,
            "customer_email": CUSTOMER_EMAIL,
            "login": {"username": CUSTOMER_EMAIL, "password": CUSTOMER_PASSWORD},
            "institutions": {
                name: {"bank_id": bank_ids[name], "customer_id": customer_ids[name]}
                for name in bank_ids
            },
            "account_map": {k: {"bank_id": v[0], "account_id": v[1]}
                            for k, v in account_map.items()},
        }
        Path(args.out).write_text(json.dumps(handles, indent=2) + "\n")
        print(f"\nWrote handles to {args.out}")
        print("\nOpen Banking login for Alex, at both institutions:")
        print(f"  username  {CUSTOMER_EMAIL}")
        print(f"  password  {CUSTOMER_PASSWORD}")


if __name__ == "__main__":
    main()
