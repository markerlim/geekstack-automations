"""
Scrape promotional card links from the year-range and special promo pages.

setup/1 only scrapes the main "List of Duel Masters OCG Sets" page, which lists
promo PACKS but not the year-by-year promo CARD lists. Those live on separate
pages reachable from https://duelmasters.fandom.com/wiki/Promotional :

  - Japanese Promotional Cards (Year 1-5) ... (Year 21-25)   ← matches promoy1..promoy25 in our data
  - English Promotional Cards
  - Holiday Card

Each page is a wikitable with rows like:
  | P1/Y21 || [[Johnny-MAX]] || Monthly CoroCoro Comic April 2022 Issue

This script fetches each page via the MediaWiki API (faster + more reliable
than Selenium), pulls every [[Link]] target that isn't an obvious namespace
prefix, and writes the results to duelmasterdb/wiki_set_cards.json under
synthetic set codes (PROMO-Y1-5, PROMO-EN, etc.). setup/3 will then dedupe
them into wiki_unique_cards.json and Pipeline C scrapes them like any other
card URL.

Run from project root:
  python scrapers/duelmasters/setup/4_scrape_promo_card_links.py
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

WIKI_API = "https://duelmasters.fandom.com/api.php"
WIKI_BASE = "https://duelmasters.fandom.com/wiki/"
OUTPUT_PATH = project_root / "duelmasterdb" / "wiki_set_cards.json"

SOURCE_PAGES = [
    ("PROMO-Y1-5",   "Japanese Promotional Cards (Year 1-5)"),
    ("PROMO-Y6-10",  "Japanese Promotional Cards (Year 6-10)"),
    ("PROMO-Y11-15", "Japanese Promotional Cards (Year 11-15)"),
    ("PROMO-Y16-20", "Japanese Promotional Cards (Year 16-20)"),
    ("PROMO-Y21-25", "Japanese Promotional Cards (Year 21-25)"),
    ("PROMO-EN",     "English Promotional Cards"),
    ("PROMO-HOLIDAY", "Holiday Card"),
]

# Skip links into other wiki namespaces — these aren't cards
NAMESPACE_PREFIXES = (
    "File:", "Category:", "Template:", "Help:", "User:", "Talk:",
    "Special:", "Project:", "MediaWiki:",
)

# Skip these specific page targets — they're navigation/index pages
SKIP_TARGETS = {
    "promotional", "english promotional cards", "holiday card",
    "corocoro comic", "coro coro comic", "duel masters books", "manga",
    "food product", "regulation",
}

# Skip targets that look like packs/decks/etc. rather than individual cards
SET_KEYWORDS = (" pack", " deck", " box", " edition", " volume", " series",
                "block", "gallery", "tournament", "campaign", "fest",
                "promotional cards", "expansion")

LINK_RE = re.compile(r'\[\[([^|\]#]+?)(?:\|[^\]]*)?\]\]')


def fetch_wikitext(page: str) -> str:
    r = requests.get(
        WIKI_API,
        params={"action": "parse", "page": page, "prop": "wikitext", "format": "json"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("info", "unknown wiki API error"))
    return data["parse"]["wikitext"]["*"]


def extract_card_links(wikitext: str) -> list[str]:
    """Return unique card wiki URLs from page wikitext, filtering namespace
    links and obvious non-card pages (packs, decks, galleries, etc.)."""
    urls = set()
    for match in LINK_RE.finditer(wikitext):
        target = match.group(1).strip()
        if not target:
            continue
        if any(target.startswith(p) for p in NAMESPACE_PREFIXES):
            continue
        lowered = target.lower()
        if lowered in SKIP_TARGETS:
            continue
        if any(kw in lowered for kw in SET_KEYWORDS):
            continue
        urls.add(WIKI_BASE + target.replace(' ', '_'))
    return sorted(urls)


def main():
    existing = {}
    if OUTPUT_PATH.exists():
        existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    print(f"📂 Loaded wiki_set_cards.json: {len(existing)} existing entries")

    new_total = 0
    for code, page in SOURCE_PAGES:
        print(f"\n📥 [{code}] {page}")
        try:
            wt = fetch_wikitext(page)
        except Exception as e:
            print(f"  ✗ failed: {type(e).__name__}: {e}")
            continue
        cards = extract_card_links(wt)
        before = len(existing.get(code, {}).get("cards", []))
        existing[code] = {
            "name": page,
            "set_url": WIKI_BASE + page.replace(' ', '_'),
            "card_count": len(cards),
            "cards": cards,
        }
        delta = len(cards) - before
        new_total += max(delta, 0)
        print(f"  ✓ {len(cards)} card URLs (Δ {delta:+d})")
        time.sleep(1)

    OUTPUT_PATH.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n💾 Saved {OUTPUT_PATH.relative_to(project_root)}")
    print(f"   Total set entries: {len(existing)}")
    print(f"   New URLs added (approx): {new_total}")

    print("\nNext steps:")
    print("  python scrapers/duelmasters/setup/3_dedupe_card_urls.py")
    print("  python scrapers/duelmasters/pipelines/c_scrape_wiki_cards.py")


if __name__ == "__main__":
    main()
