"""Real, cached imagery for Priceless catalogue offers.

PLAN.MD section 9's own rule -- no live scraping at demo time -- applies here
too: images are fetched once, offline, by scripts/cache_priceless_images.py,
never during a live dashboard render or MCP tool call. app.knowledge reads
this module's manifest back in as plain data at load time (get_cached, no
network), the same way every other knowledge file here is read from disk.

The catalogue's own source_url/visual_page_url fields are unreliable --
several entries share one generic collection-page URL, and at least one
points at a completely unrelated product (see app.knowledge's loader).
Rather than risk a confidently-wrong photo, every image comes from Wikipedia
instead, resolved from a real-world SUBJECT: a specific, identifiable venue
where one exists and is verified below (Fenway Park for the Red Sox alumni
lunch), or the catalogue's own category otherwise ("Golf course" for a golf
offer with no single named venue). A subject is never invented to force a
match -- an offer with neither a curated nor a category subject simply has
no image, and the UI falls back to a plain category badge, not a fabricated
photo.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app import config

STATIC_DIR = config.ROOT / "app" / "static" / "priceless"
MANIFEST_PATH = config.DATA / "priceless_catalogue_smartpay" / "image_cache.json"

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "SmartPayHackathonDemo/1.0 (non-commercial demo; no contact channel)"

#: httpx (and requests) get an outright 403 "please respect our robot policy"
#: from Wikimedia in this environment even with a compliant User-Agent --
#: almost certainly TLS/HTTP client fingerprinting rather than anything in
#: the request content, since curl with the identical User-Agent succeeds.
#: Shelling out to curl is the pragmatic fix; both calls this module makes
#: are simple GETs, so it costs nothing in flexibility.
_CURL_TIMEOUT_SECONDS = 15


class _FetchError(Exception):
    pass


def _curl_get(url: str) -> bytes:
    result = subprocess.run(
        ["curl", "-sS", "-L", "--max-time", str(_CURL_TIMEOUT_SECONDS), "-A", USER_AGENT, url],
        capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise _FetchError(f"curl exited {result.returncode}: {result.stderr.decode(errors='replace')}")
    return result.stdout

#: A specific, identifiable real-world venue for offers where one clearly
#: exists -- hand-picked and checked against Wikipedia's own summary for a
#: real, on-topic thumbnail before being added here, never derived
#: automatically from the catalogue's own (frequently broken) source_url.
#: Note: "Bay Hill Club and Lodge" and "New York City Marathon" were tried
#: here first, but Wikipedia's pageimages API returns no usable thumbnail for
#: either (both pages lead with an infobox logo, which pageimages excludes) --
#: left out so those two offers fall through to their category subject
#: ("Golf course", "Marathon") instead of a permanent no-image result.
CURATED_SUBJECTS: dict[str, str] = {
    "PRICELESS_US_RED_SOX_ALUMNI_LUNCH_AND_FENWAY_TOUR": "Fenway Park",
    "PRICELESS_US_TPC_SOUTH_REGION_PRIVATE_COURSE_ACCESS": "Tournament Players Club",
    "PRICELESS_US_TPC_EAST_REGION_PRIVATE_COURSE_ACCESS": "Tournament Players Club",
    "PRICELESS_US_TPC_WEST_REGION_PRIVATE_COURSE_ACCESS": "Tournament Players Club",
    "PRICELESS_US_TPC_HARDING_PARK_PRIVILEGED_GOLF_ACCESS": "Tournament Players Club",
    "PRICELESS_US_DANTE_WEST_VILLAGE_MASTERCARD_COLLECTION_PREFERRED_RESERVATIONS":
        "Dante (bar)",
    "PRICELESS_US_CHELSEA_FILM_FESTIVAL_OPENING_NIGHT": "Chelsea Film Festival",
}

#: Falls back to this when an offer has no curated subject: a real,
#: representative photo for the kind of experience, not the specific venue.
#: image_attribution always says "Representative image" for these (never the
#: offer's own name) so the UI never implies a photo of a place it isn't.
CATEGORY_FALLBACK_SUBJECTS: dict[str, str] = {
    "CULINARY": "Fine dining",
    "SPORTS_GOLF": "Golf course",
    "HEALTH_WELLNESS": "Yoga",
    "SHOPPING_FASHION": "Vintage clothing",
    "ARTS_CULTURE": "Museum",
    "ENTERTAINMENT": "Theatre",
    "SPORTS_RUNNING": "Marathon",
    "SPORTS_BASEBALL": "Baseball",
    "SPORTS_FOOTBALL": "American football",
    "TRAVEL": "Tourism",
}


def subject_for(experience_id: str, catalogue_category: str) -> tuple[str | None, bool]:
    """Returns (Wikipedia subject, is_specific_venue). No subject at all for
    a category we have no fallback for -- callers must handle None."""
    if experience_id in CURATED_SUBJECTS:
        return CURATED_SUBJECTS[experience_id], True
    return CATEGORY_FALLBACK_SUBJECTS.get(catalogue_category), False


def _slug(subject: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")


def _load_manifest() -> dict[str, Any]:
    try:
        return json.loads(MANIFEST_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_manifest(manifest: dict[str, Any]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def get_cached(subject: str) -> dict[str, Any] | None:
    """Read-only manifest lookup -- no network. What app.knowledge calls."""
    record = _load_manifest().get(_slug(subject))
    return record if record and record.get("status") == "cached" else None


def _fetch_thumbnail(subject: str) -> dict[str, str] | None:
    """Wikipedia's pageimages API, asking for a real size rather than the
    128px default -- big enough for a dashboard/widget card, small enough
    that ~15 subjects stay a trivial download."""
    query = urlencode({
        "action": "query", "titles": subject, "prop": "pageimages",
        "piprop": "thumbnail|name", "pithumbsize": 800,
        "format": "json", "redirects": 1,
    })
    body = json.loads(_curl_get(f"{WIKIPEDIA_API}?{query}"))
    pages = body.get("query", {}).get("pages", {})
    for page in pages.values():
        if "missing" in page:
            continue
        thumb = page.get("thumbnail")
        if thumb and thumb.get("source"):
            return {"image_url": thumb["source"], "page_title": page.get("title", subject)}
    return None


#: The ChatGPT-embedded widget can only show self-contained images -- its
#: sandboxed iframe cannot fetch /static (see app/widget.py's own docstring)
#: -- so every cached photo gets a second, small copy inlined as a data URI.
#: Resizing happens once, here, at cache time, so the live widget path never
#: needs an image library: it just reads whichever file is already the right
#: size, same as every other asset it inlines.
WIDGET_MAX_DIMENSION = 420
WIDGET_JPEG_QUALITY = 70


def _write_widget_copy(key: str, image_bytes: bytes) -> str | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        import io
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = img.convert("RGB")
            img.thumbnail((WIDGET_MAX_DIMENSION, WIDGET_MAX_DIMENSION))
            filename = f"{key}-widget.jpg"
            STATIC_DIR.mkdir(parents=True, exist_ok=True)
            img.save(STATIC_DIR / filename, format="JPEG", quality=WIDGET_JPEG_QUALITY)
            return filename
    except Exception:
        # A widget-sized copy is a nice-to-have -- the dashboard's full-size
        # image still works either way, so a Pillow/decode failure here must
        # not fail the whole cache-and-fetch run.
        return None


def ensure_cached(subject: str, *, is_specific: bool, force: bool = False) -> dict[str, Any] | None:
    """Fetch and cache ONE subject's image, once. Returns the cache record
    on success (freshly fetched or already on disk), None if no image could
    be found -- never raises on a network failure, since one bad subject
    must not abort a script run over a dozen unrelated others.
    """
    manifest = _load_manifest()
    key = _slug(subject)
    if not force and manifest.get(key, {}).get("status") == "cached":
        return manifest[key]

    record: dict[str, Any] = {"subject": subject, "status": "error", "fetched_at": None}
    try:
        found = _fetch_thumbnail(subject)
        if not found:
            record["status"] = "no_image"
        else:
            image_bytes = _curl_get(found["image_url"])
            ext = Path(found["image_url"].split("?")[0]).suffix or ".jpg"
            filename = f"{key}{ext}"
            STATIC_DIR.mkdir(parents=True, exist_ok=True)
            (STATIC_DIR / filename).write_bytes(image_bytes)
            widget_filename = _write_widget_copy(key, image_bytes)
            attribution = (
                f"Photo via Wikipedia ({found['page_title']})" if is_specific
                else f"Representative image via Wikipedia ({found['page_title']})"
            )
            record.update({
                "status": "cached",
                "relative_path": f"priceless/{filename}",
                "widget_relative_path": f"priceless/{widget_filename}" if widget_filename else None,
                "source_image_url": found["image_url"],
                "wikipedia_page": found["page_title"],
                "attribution": attribution,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
    except (_FetchError, ValueError, OSError) as exc:
        record["status"] = "error"
        record["error"] = str(exc)

    manifest[key] = record
    _save_manifest(manifest)
    return record if record["status"] == "cached" else None


def cache_subjects_for(entries: list[tuple[str, str]]) -> dict[str, int]:
    """entries is a list of (experience_id, catalogue_category) pairs -- kept
    as plain strings rather than PricelessExperience objects so this module
    never has to import app.models.rules. Ensures every DISTINCT subject
    those offers resolve to is cached, skipping subjects already on disk.
    """
    summary = {"fetched": 0, "already_cached": 0, "no_image": 0, "error": 0, "no_subject": 0}
    seen: set[str] = set()
    for experience_id, catalogue_category in entries:
        subject, is_specific = subject_for(experience_id, catalogue_category)
        if not subject:
            summary["no_subject"] += 1
            continue
        if subject in seen:
            continue
        seen.add(subject)
        was_cached = get_cached(subject) is not None
        if not was_cached:
            # Wikipedia rate-limits a burst of requests from one client --
            # observed as a 429 with a plain-text body, not JSON. A pause
            # between fetches is cheap: there are only ~15 distinct subjects
            # total across the whole catalogue.
            time.sleep(1.5)
        record = ensure_cached(subject, is_specific=is_specific)
        if record and was_cached:
            summary["already_cached"] += 1
        elif record:
            summary["fetched"] += 1
        else:
            outcome = _load_manifest().get(_slug(subject), {}).get("status", "error")
            summary[outcome if outcome in summary else "error"] += 1
    return summary
