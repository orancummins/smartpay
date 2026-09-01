"""Maps free-text merchant descriptions onto the canonical taxonomy.

This engine exists for ONE reason: ChatGPT sends us prose. It will say
"Disney's Art of Animation Resort", "American Airlines BOS-MCO", or "Uber to the
airport", and the reward rules are keyed on Category and merchant_key. Our own
generated data is already categorised, so this is purely the LLM-text boundary.

Order of resolution, most trustworthy first:
  1. An explicit category supplied by the caller.
  2. Exact merchant alias.
  3. Keyword match on the description.
  4. Fuzzy merchant match (rapidfuzz) above a confidence floor.
  5. Give up -> OTHER, and say so, so the purchase earns base rate only.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

from app.models.common import Category

#: merchant_key -> the strings ChatGPT plausibly emits for it.
MERCHANT_ALIASES: dict[str, list[str]] = {
    "american_airlines": ["american airlines", "american", "aa", "aadvantage"],
    "delta": ["delta", "delta air lines", "delta airlines"],
    "jetblue": ["jetblue", "jetblue airways"],
    "united_airlines": ["united", "united airlines"],
    "southwest": ["southwest", "southwest airlines"],
    "walt_disney_world": [
        "walt disney world", "disney world", "disney", "magic kingdom", "epcot",
        "disney park tickets", "disney tickets", "hollywood studios", "animal kingdom",
    ],
    "disney_resort": [
        "disney resort", "disney's art of animation resort", "art of animation",
        "disney's pop century resort", "pop century", "disney's contemporary resort",
        "caribbean beach resort", "coronado springs",
    ],
    "universal_orlando": ["universal orlando", "universal studios", "islands of adventure"],
    "marriott": ["marriott", "marriott bonvoy", "courtyard", "residence inn"],
    "hilton": ["hilton", "hampton inn", "doubletree", "embassy suites"],
    "hyatt": ["hyatt", "hyatt regency"],
    "lyft": ["lyft"],
    "uber": ["uber", "uber ride"],
    "hertz": ["hertz", "hertz rent a car"],
    "avis": ["avis"],
    "instacart": ["instacart"],
    "publix": ["publix"],
    "whole_foods": ["whole foods", "whole foods market"],
    "peacock": ["peacock", "peacock premium"],
}

#: Keyword -> category. Checked against the whole description, longest first.
KEYWORD_CATEGORY: dict[str, Category] = {
    "airfare": Category.AIRFARE, "flight": Category.AIRFARE, "flights": Category.AIRFARE,
    "airline": Category.AIRFARE, "airways": Category.AIRFARE, "plane ticket": Category.AIRFARE,
    "hotel": Category.HOTEL, "resort": Category.HOTEL, "accommodation": Category.HOTEL,
    "lodging": Category.HOTEL, "inn": Category.HOTEL, "nights stay": Category.HOTEL,
    "park ticket": Category.ATTRACTION, "theme park": Category.ATTRACTION,
    "admission": Category.ATTRACTION, "attraction": Category.ATTRACTION,
    "tickets": Category.ATTRACTION, "museum": Category.ATTRACTION, "tour": Category.ATTRACTION,
    "car rental": Category.CAR_RENTAL, "rental car": Category.CAR_RENTAL,
    "restaurant": Category.RESTAURANT, "dining": Category.RESTAURANT,
    "dinner": Category.RESTAURANT, "lunch": Category.RESTAURANT, "meals": Category.RESTAURANT,
    "breakfast": Category.RESTAURANT, "food": Category.RESTAURANT, "cafe": Category.RESTAURANT,
    "rideshare": Category.RIDESHARE, "ride share": Category.RIDESHARE,
    "airport transfer": Category.RIDESHARE, "airport transport": Category.RIDESHARE,
    "taxi": Category.RIDESHARE, "shuttle": Category.TRANSPORT,
    "parking": Category.TRANSPORT, "train": Category.TRANSPORT, "transit": Category.TRANSPORT,
    "groceries": Category.SUPERMARKET, "grocery": Category.SUPERMARKET,
    "supermarket": Category.SUPERMARKET,
    "gas": Category.GAS, "fuel": Category.GAS, "petrol": Category.GAS,
    "pharmacy": Category.DRUGSTORE, "drugstore": Category.DRUGSTORE,
    "streaming": Category.STREAMING, "golf": Category.GOLF,
    "souvenir": Category.SHOPPING, "shopping": Category.SHOPPING, "gift": Category.SHOPPING,
    "entertainment": Category.ENTERTAINMENT, "show": Category.ENTERTAINMENT,
}

#: Fallback category for a merchant we recognise but whose description is vague.
MERCHANT_CATEGORY: dict[str, Category] = {
    "american_airlines": Category.AIRFARE, "delta": Category.AIRFARE,
    "jetblue": Category.AIRFARE, "united_airlines": Category.AIRFARE,
    "southwest": Category.AIRFARE,
    "walt_disney_world": Category.ATTRACTION, "universal_orlando": Category.ATTRACTION,
    "disney_resort": Category.HOTEL, "marriott": Category.HOTEL,
    "hilton": Category.HOTEL, "hyatt": Category.HOTEL,
    "lyft": Category.RIDESHARE, "uber": Category.RIDESHARE,
    "hertz": Category.CAR_RENTAL, "avis": Category.CAR_RENTAL,
    "instacart": Category.GROCERY_ONLINE, "publix": Category.SUPERMARKET,
    "whole_foods": Category.SUPERMARKET, "peacock": Category.STREAMING,
}

#: Sorted longest-alias-first. Without this, the short alias "disney" swallows
#: "disney's art of animation resort" and the resort is mis-keyed to the park.
_ALIAS_LOOKUP: dict[str, str] = {
    alias: key
    for alias, key in sorted(
        ((a, k) for k, aliases in MERCHANT_ALIASES.items() for a in aliases),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
}

FUZZY_FLOOR = 88


@dataclass(frozen=True)
class Categorisation:
    merchant_key: str
    category: Category
    method: str
    confident: bool

    @property
    def explanation(self) -> str:
        if not self.confident:
            return (
                "Merchant not recognised; treated as an uncategorised purchase "
                "earning base rate only."
            )
        return f"Matched to {self.merchant_key} / {self.category.value} by {self.method}."


def _normalise(text: str) -> str:
    return " ".join(text.lower().replace("'", "").replace("-", " ").split())


def categorise(
    merchant: str,
    description: str | None = None,
    explicit_category: Category | None = None,
) -> Categorisation:
    text = _normalise(f"{merchant} {description or ''}")
    merchant_norm = _normalise(merchant)

    merchant_key = _ALIAS_LOOKUP.get(merchant_norm)
    method = "exact merchant alias"

    if merchant_key is None:
        for alias, key in _ALIAS_LOOKUP.items():
            if alias in text:
                merchant_key, method = key, "merchant name found in description"
                break

    if merchant_key is None:
        match = process.extractOne(
            merchant_norm, list(_ALIAS_LOOKUP), scorer=fuzz.WRatio, score_cutoff=FUZZY_FLOOR
        )
        if match:
            merchant_key, method = _ALIAS_LOOKUP[match[0]], f"fuzzy match ({int(match[1])}%)"

    # An explicit category from the caller always wins -- ChatGPT passing
    # category="hotel" is better evidence than anything we can infer.
    if explicit_category is not None and explicit_category is not Category.OTHER:
        return Categorisation(
            merchant_key or merchant_norm.replace(" ", "_"),
            explicit_category,
            "category supplied by caller",
            True,
        )

    for keyword in sorted(KEYWORD_CATEGORY, key=len, reverse=True):
        if keyword in text:
            return Categorisation(
                merchant_key or merchant_norm.replace(" ", "_"),
                KEYWORD_CATEGORY[keyword],
                f"{method} + keyword '{keyword}'" if merchant_key else f"keyword '{keyword}'",
                True,
            )

    if merchant_key and merchant_key in MERCHANT_CATEGORY:
        return Categorisation(merchant_key, MERCHANT_CATEGORY[merchant_key], method, True)

    return Categorisation(
        merchant_norm.replace(" ", "_") or "unknown", Category.OTHER, "no match", False
    )
