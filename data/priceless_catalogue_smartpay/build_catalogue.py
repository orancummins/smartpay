#!/usr/bin/env python3
import csv
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "priceless_catalogue.sqlite"
CSV = ROOT / "priceless_catalogue.csv"
JSON = ROOT / "priceless_catalogue.json"
VERIFIED = "2026-09-02T08:00:00Z"
COLLECTION = "https://www.priceless.com/filter/options/collection/2534?fromCatId=1679&tab=diningReservations"

def slug(value):
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

def offer(title, offer_type, category, city=None, region=None, price=None,
          price_note=None, valid_to=None, booking_end=None, status="SURFACED",
          tier="MASTERCARD", url=COLLECTION, method="PUBLIC_SEARCH_INDEX",
          confidence="MEDIUM", tags=(), venue=None, eligibility=None, notes=None):
    return {
        "offer_id": "PRICELESS_US_" + slug(title).upper(), "title": title,
        "offer_type": offer_type, "category": category, "country_code": "US",
        "region": region, "city": city, "venue": venue,
        "price_amount": price, "currency": "USD" if price is not None else None,
        "price_note": price_note, "valid_from": None, "valid_to": valid_to,
        "booking_end": booking_end, "availability_status": status,
        "eligibility_tier": tier,
        "eligibility_text": eligibility or tier.replace("_", " ").title(),
        "source_url": url, "visual_page_url": url, "direct_image_url": None,
        "source_method": method, "confidence": confidence,
        "last_verified_at": VERIFIED, "notes": notes,
        "tags": sorted(set(("alex",) + tuple(tags)))
    }

records = [
    offer("Explore MoMA after hours with an expert guide", "EXPERIENCE", "ARTS_CULTURE", "New York", "NY", 50, status="SURFACED", tags=("nyc","culture","family"), url="https://www.priceless.com/arts-and-culture/product/230088/centimillimental-world-tour-2025-2026-cafun", confidence="MEDIUM", notes="Product URL should be rechecked; title was surfaced on US catalogue."),
    offer("Russ & Daughters after-hours bagel making", "EXPERIENCE", "CULINARY", "New York", "NY", 80, tags=("nyc","dining","family")),
    offer("Eataly cannoli-making class", "EXPERIENCE", "CULINARY", "New York", "NY", 105, booking_end="2026-09-25", status="LIMITED", tags=("nyc","dining","family"), url="https://www.priceless.com/m/culinary/product/231727/eataly-pre-sale-access-to-classes-tiramisu", confidence="MEDIUM", notes="Shared Eataly class source page; verify exact cannoli product URL."),
    offer("Eataly tiramisu masterclass", "EXPERIENCE", "CULINARY", "New York", "NY", 105, booking_end="2026-09-19", status="LIMITED", tags=("nyc","dining","family"), url="https://www.priceless.com/m/culinary/product/231727/eataly-pre-sale-access-to-classes-tiramisu", confidence="HIGH"),
    offer("Eataly ravioli-making class", "EXPERIENCE", "CULINARY", "New York", "NY", 105, tags=("nyc","dining","family")),
    offer("Eataly Flatiron insider food tour", "EXPERIENCE", "CULINARY", "New York", "NY", 100, tags=("nyc","dining","family")),
    offer("Shojin breakfast and Zen meditation with Hiroki Odo", "EXPERIENCE", "CULINARY", "New York", "NY", 117.45, valid_to="2026-12-13", booking_end="2026-12-10", status="AVAILABLE", tags=("nyc","dining","wellness"), url="https://origin-us.priceless.com/culinary/product/225563/2026-odo-zen-workshops", confidence="HIGH"),
    offer("Carla Hall and Nicolas Nuvan dinner at The Edge Harlem", "EXPERIENCE", "CULINARY", "New York", "NY", 50, valid_to="2026-09-22", booking_end="2026-09-21", status="AVAILABLE", tags=("nyc","dining"), url="https://www.priceless.com/m/culinary/product/237525/sbs-dinner", confidence="HIGH"),
    offer("Marquee Skydeck VIP parties at Edge", "EXPERIENCE", "ENTERTAINMENT", "New York", "NY", valid_to="2026-09-30", status="AVAILABLE", price_note="Variable", tags=("nyc","entertainment"), url="https://www.priceless.com/entertainment/product/232069/2026-marquee-sky-deck", confidence="HIGH"),
    offer("Sky High Yoga at Edge", "EXPERIENCE", "HEALTH_WELLNESS", "New York", "NY", 75, valid_to="2026-10-02", status="AVAILABLE", tags=("nyc","wellness"), url="https://www.priceless.com/health-and-wellness/product/230414/sky-high-yoga", confidence="HIGH"),
    offer("New Balance Bronx 10 Mile entry", "ACCESS", "SPORTS_RUNNING", "New York", "NY", 60, valid_to="2026-09-19", booking_end="2026-09-11", status="AVAILABLE", price_note="Plus race fee", tags=("nyc","sports","running"), url="https://www.priceless.com/m/sports/product/237844/get-ready-to-run-the-2026-new-balance-bronx-10-mile", confidence="HIGH"),
    offer("2026 TCS New York City Marathon guaranteed-entry experience", "ACCESS", "SPORTS_RUNNING", "New York", "NY", valid_to="2026-11-01", price_note="Race fee applies", tags=("nyc","sports","running"), url="https://www.priceless.com/sports/product/229431/new-york-city-marathon-cardholder", confidence="HIGH"),
    offer("Stranger Things: The First Shadow tickets", "PREFERRED_TICKET", "ENTERTAINMENT", "New York", "NY", 169.50, tags=("nyc","entertainment","family")),
    offer("Chamber Magic with Steve Cohen", "EXPERIENCE", "ENTERTAINMENT", "New York", "NY", 550, tags=("nyc","entertainment")),
    offer("Drew Tillman downtown architecture tour", "EXPERIENCE", "ARTS_CULTURE", "Los Angeles", "CA", 95, tags=("la","culture")),
    offer("Dodgers batting-practice field access and tickets", "EXPERIENCE", "SPORTS_BASEBALL", "Los Angeles", "CA", valid_to="2026-09-23", booking_end="2026-09-21", status="LIMITED", price_note="Package pricing", tags=("la","sports"), url="https://00.www.priceless.com/m/sports/product/229409/2026-dodgers-bp-viewing", confidence="HIGH"),
    offer("Call It's time for Dodger baseball auction", "AUCTION", "SPORTS_BASEBALL", "Los Angeles", "CA", 1500, valid_to="2026-09-23", booking_end="2026-09-16", status="AVAILABLE", price_note="Opening bid", tags=("la","sports"), url="https://www.priceless.com/m/sports/product/229333/2026-itfdb-auction", confidence="HIGH"),
    offer("The Way We Wore private vintage-fashion archive", "EXPERIENCE", "SHOPPING_FASHION", "Los Angeles", "CA", 350, tags=("la","culture","family")),
    offer("Frank Lloyd Wright Hollyhock House tour", "EXPERIENCE", "ARTS_CULTURE", "Los Angeles", "CA", 50, tags=("la","culture","family")),
    offer("Wynwood Walls VIP tour and spray painting", "EXPERIENCE", "ARTS_CULTURE", "Miami", "FL", 160, valid_to="2026-12-31", status="AVAILABLE", tags=("miami","culture","family"), url="https://www.priceless.com/arts-and-culture/product/229586/wynwood-walls-priceless-vip-experience", confidence="HIGH"),
    offer("Inter Miami CF warm-ups from the pitch", "EXPERIENCE", "SPORTS_FOOTBALL", "Miami", "FL", 700, price_note="Per pair", tags=("miami","sports","football")),
    offer("Inter Miami CF post-match pitch access", "EXPERIENCE", "SPORTS_FOOTBALL", "Miami", "FL", 250, tags=("miami","sports","football")),
    offer("Austin Food & Wine ticket cashback", "CASHBACK", "CULINARY", "Austin", "TX", 50, valid_to="2026-11-08", status="LIMITED", price_note="$50 cashback; first 500 qualifying orders", tags=("dining","texas"), url="https://www.priceless.com/m/culinary/product/238359/2026-austin-food-and-wine-festival-ticket-credit-offer", confidence="HIGH"),
    offer("Austin Food & Wine VIP Mastercard Collection ticket", "PREFERRED_TICKET", "CULINARY", "Austin", "TX", booking_end="2026-09-25", status="AVAILABLE", price_note="Ticket price varies", tier="WORLD_ELITE", eligibility="World Elite or World Legend consumer credit", tags=("dining","texas"), url="https://www.priceless.com/culinary/product/238502/2026-austin-food-and-wine-festival-preferred-tickets", confidence="HIGH"),
    offer("Red Sox alumni lunch and Fenway tour", "EXPERIENCE", "SPORTS_BASEBALL", "Boston", "MA", valid_to="2026-09-10", booking_end="2026-09-07", status="AVAILABLE", price_note="Pair package", tags=("boston","sports"), url="https://www.priceless.com/sports/product/231086/26-red-sox-player-lunch", confidence="HIGH"),
    offer("Trump National Doral stay and three rounds of golf", "EXPERIENCE", "SPORTS_GOLF", "Miami", "FL", 1085, valid_to="2026-12-31", status="AVAILABLE", price_note="From, per person", tags=("miami","golf","travel"), url="https://www.priceless.com/m/sports/product/231822/enjoy-a-luxurious-stay-and-play-trip-at-trump-national-doral-miami", confidence="HIGH"),
    offer("PGA National Resort stay-and-play", "EXPERIENCE", "SPORTS_GOLF", "Palm Beach", "FL", 1295, valid_to="2026-12-31", status="AVAILABLE", price_note="From, per person", tags=("florida","golf","travel")),
    offer("TPC Sawgrass stay-and-play", "EXPERIENCE", "SPORTS_GOLF", "Ponte Vedra Beach", "FL", 1459, valid_to="2026-12-31", status="AVAILABLE", price_note="From, per person", tags=("florida","golf","travel"), url="https://www.priceless.com/m/sports/product/231859/enjoy-a-stay-and-play-trip-in-florida-at-sawgrass-marriott-golf-resort-and-spa", confidence="HIGH"),
    offer("Arnold Palmer Bay Hill and Orlando golf package", "EXPERIENCE", "SPORTS_GOLF", "Orlando", "FL", 865, valid_to="2026-12-31", status="AVAILABLE", price_note="From, per person", tags=("orlando","golf","travel")),
    offer("Kiawah Island Resort stay-and-play", "EXPERIENCE", "SPORTS_GOLF", "Kiawah Island", "SC", 999, valid_to="2026-12-31", status="AVAILABLE", price_note="Per person", tags=("golf","travel"), url="https://www.priceless.com/m/sports/product/232021/enjoy-a-relaxing-stay-and-play-trip-along-the-south-carolina-coast-at-kiawah-island-golf-resort", confidence="HIGH"),
    offer("Palmetto Dunes golf getaway", "EXPERIENCE", "SPORTS_GOLF", "Hilton Head", "SC", 649, valid_to="2026-12-31", status="AVAILABLE", price_note="From, per person", tags=("golf","travel"), url="https://www.priceless.com/m/sports/product/232204/enjoy-a-stay-and-play-trip-on-hilton-head-island-to-the-palmetto-dunes-oceanfront-resort", confidence="HIGH"),
    offer("We-Ko-Pa desert golf getaway", "EXPERIENCE", "SPORTS_GOLF", "Fort McDowell", "AZ", 539, valid_to="2026-12-31", status="AVAILABLE", price_note="From, per person", tags=("golf","travel"), url="https://www.priceless.com/m/sports/product/232203/enjoy-a-stay-and-play-trip-in-arizona-to-the-we-ko-pa-casino-resort", confidence="HIGH"),
    offer("Access to 9,000+ public golf-course tee times", "ACCESS", "SPORTS_GOLF", region="Nationwide", valid_to="2026-12-31", status="AVAILABLE", price_note="Course dependent", tags=("golf","travel"), url="https://www.priceless.com/sports/product/196183/enjoy-exclusive-public-tee-time-engine-access", confidence="HIGH"),
    offer("Chelsea Film Festival opening night", "EXPERIENCE", "ENTERTAINMENT", "New York", "NY", 199, valid_to="2026-10-14", booking_end="2026-10-07", status="AVAILABLE", tags=("nyc","entertainment","culture"), url="https://www.priceless.com/m/entertainment/product/235097/chelsea-film-festival", confidence="HIGH"),
    offer("Edge private early-access skyline experience", "EXPERIENCE", "TRAVEL", "New York", "NY", 50, valid_to="2026-12-31", status="AVAILABLE", price_note="Plus tax, per person", tags=("nyc","travel","family"), url="https://www.priceless.com/m/travel/product/187696/sunrise-access", confidence="HIGH"),
    offer("NYRR Staten Island Half guaranteed race access", "ACCESS", "SPORTS_RUNNING", "New York", "NY", valid_to="2026-10-11", booking_end="2026-10-02", status="AVAILABLE", price_note="Race fee applies", tags=("nyc","sports","running"), url="https://00.www.priceless.com/sports/product/237846/nyrr-staten-island-half-cardholder", confidence="HIGH"),
    offer("Miami and Everglades private combination experience", "EXPERIENCE", "TRAVEL", "Miami", "FL", 491, valid_to="2026-12-31", status="AVAILABLE", price_note="From", tags=("miami","travel","family"), url="https://www.priceless.com/m/travel/product/225541/wide-angle-tours-ultimate-miami-combo", confidence="HIGH"),
    offer("TPC East Region private-course access", "ACCESS", "SPORTS_GOLF", region="MA/CT/NJ/MD", valid_to="2026-12-31", status="AVAILABLE", price_note="Course dependent", tags=("golf","travel"), url="https://www.priceless.com/m/health-and-wellness/product/205245/tpc-east-region", confidence="HIGH"),
    offer("TPC South Region private-course access", "ACCESS", "SPORTS_GOLF", region="Southern US", valid_to="2026-12-31", status="AVAILABLE", tier="WORLD_ELITE", price_note="Course dependent", eligibility="World Elite credit, debit, business or Corporate World Elite", tags=("golf","travel"), url="https://www.priceless.com/m/health-and-wellness/product/205242/tpc-south-region", confidence="HIGH"),
    offer("TPC West Region private-course access", "ACCESS", "SPORTS_GOLF", region="Western US", valid_to="2026-12-31", status="AVAILABLE", price_note="Course dependent", tags=("golf","travel"), url="https://www.priceless.com/m/health-and-wellness/product/205248/tpc-west-region", confidence="HIGH"),
    offer("TPC Harding Park privileged golf access", "ACCESS", "SPORTS_GOLF", "San Francisco", "CA", valid_to="2026-12-31", status="AVAILABLE", price_note="Course dependent", tags=("golf","travel","san_francisco"), url="https://www.priceless.com/m/sports/product/162532/play-where-the-pros-play-at-tpc-harding-park", confidence="HIGH"),
    offer("Peak with Priceless preferred reservations", "PREFERRED_RESERVATION", "CULINARY", "New York", "NY", 300, valid_to="2027-12-31", status="AVAILABLE", price_note="$300 per pair; $100 deposit", tier="WORLD_ELITE", tags=("nyc","dining"), url="https://www.priceless.com/m/culinary/product/231849/preferred-table-reservations", confidence="HIGH"),
    offer("Netflix House Is It Cake winner experience", "EXPERIENCE", "CULINARY", region="TX/PA", valid_to="2026-09-30", status="WAITLIST", tags=("dining","entertainment","family"), url="https://www.priceless.com/m/culinary/product/238406/netflix-house-is-it-cake", confidence="HIGH"),
    offer("US music and entertainment presale access", "PRESALE", "ENTERTAINMENT", region="Nationwide", valid_to="2028-12-31", status="AVAILABLE", tier="MASTERCARD_CREDIT", eligibility="Mastercard consumer credit cardholders", tags=("entertainment","travel"), url="https://www.priceless.com/m/Music-and-Entertainment-Presale-and-Preferred-Tickets-FAQs", confidence="HIGH"),
]

restaurants = {
    "Los Angeles": ["Etra", "ALBA Los Angeles", "Jacaranda", "Picala"],
    "Santa Monica": ["Citrin", "Crudo e Nudo"],
    "Beverly Hills": ["Dante Beverly Hills"],
    "New York": ["ALBA NYC", "Casa Cruz", "Dante Aperitivo Bar", "Dante NYC", "Dante West Village", "Forge", "HaSalon NYC", "KEES", "La Marchande", "Ma.de", "Massara", "OPTO", "Pearl Box", "Peasant", "Piccolo Morini", "Please Don't Tell", "Port Said", "Roscioli"],
    "Brooklyn": ["Fausto", "gertrude's"],
    "Queens": ["Hellbender", "Rolo's"],
    "Chicago": ["Aba Chicago", "Cafe Yaya", "Cantina Rosa", "Crying Tiger", "Hawksmoor Chicago", "LUXBAR", "Pizzeria Portofino", "The Alston", "Tre Dita"],
    "Austin": ["Aba Austin"], "Nashville": ["Aba Nashville"],
    "San Francisco": ["Delfina", "Aziza"],
    "Washington": ["Cucina MORINI"],
    "Boston": ["Eastern Standard Kitchen & Drinks", "Grill 23 & Bar", "Vermilion Club"],
    "Las Vegas": ["HaSalon Las Vegas"],
}

regions = {"Los Angeles":"CA","Santa Monica":"CA","Beverly Hills":"CA","New York":"NY","Brooklyn":"NY","Queens":"NY","Chicago":"IL","Austin":"TX","Nashville":"TN","San Francisco":"CA","Washington":"DC","Boston":"MA","Las Vegas":"NV"}
direct_urls = {
    "Eastern Standard Kitchen & Drinks":"https://www.priceless.com/culinary/product/215977/eastern-standard-kitchen-and-drinks-reservations",
    "Grill 23 & Bar":"https://www.priceless.com/culinary/product/215900/grill-23-and-bar-reservations",
    "LUXBAR":"https://www.priceless.com/culinary/product/229455/luxbar-reservations",
    "Dante West Village":"https://alb.www.priceless.com/m/culinary/product/225861/dante-west-village-reservations",
    "HaSalon Las Vegas":"https://www.priceless.com/culinary/product/195072/",
}
for city, names in restaurants.items():
    for name in names:
        url = direct_urls.get(name, COLLECTION)
        records.append(offer(
            f"{name} Mastercard Collection preferred reservations",
            "PREFERRED_RESERVATION", "CULINARY", city, regions[city],
            status="AVAILABLE", tier="WORLD_ELITE",
            eligibility="Eligible Mastercard Collection tiers; verify exact product rules",
            url=url, method="PUBLIC_COLLECTION_INDEX",
            confidence="HIGH" if name in direct_urls else "MEDIUM",
            tags=("dining", "vegas" if city == "Las Vegas" else "nyc" if city in ("New York","Brooklyn","Queens") else slug(city)),
            notes=None if name in direct_urls else "Restaurant is publicly listed in the Collection catalogue; canonical product URL requires enrichment."
        ))

columns = [
    "offer_id","title","offer_type","category","country_code","region","city","venue",
    "price_amount","currency","price_note","valid_from","valid_to","booking_end",
    "availability_status","eligibility_tier","eligibility_text","source_url",
    "visual_page_url","direct_image_url","source_method","confidence","last_verified_at","notes"
]

if DB.exists():
    DB.unlink()
conn = sqlite3.connect(DB)
conn.executescript((ROOT / "schema.sql").read_text())
for row in records:
    conn.execute(
        f"INSERT INTO offers ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        [row[c] for c in columns]
    )
    conn.executemany("INSERT INTO offer_tags(offer_id, tag) VALUES (?, ?)", [(row["offer_id"], t) for t in row["tags"]])
conn.commit()
conn.close()

with CSV.open("w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=columns + ["tags"])
    writer.writeheader()
    for row in records:
        writer.writerow({**{c: row[c] for c in columns}, "tags": "|".join(row["tags"])})

with JSON.open("w", encoding="utf-8") as fh:
    json.dump(records, fh, ensure_ascii=False, indent=2)

print(json.dumps({"records": len(records), "database": str(DB), "csv": str(CSV), "json": str(JSON)}))
