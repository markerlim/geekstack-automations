"""
Rescrape one or more JP booster sets from takaratomy.co.jp and re-upload to MongoDB.

Usage:
    python rescrape_booster.py <booster_code> [<booster_code> ...]

Examples:
    python rescrape_booster.py dm25ex4
    python rescrape_booster.py dm25ex4 dm25ex5 dm25bd1

The booster code must match the product code used on dm.takaratomy.co.jp
(e.g. dm25ex4, dmc01, dmbd01). Check the card list URL for the exact code:
    https://dm.takaratomy.co.jp/card/?v={"products":"<booster_code>"}

What this does:
    1. Scrapes all card pages for the booster from takaratomy.co.jp
    2. Matches each card against CL_duelmasters_wiki (EN data) by JP name
    3. Translates any unmatched cards (JP -> EN)
    4. Uploads results to CL_duelmasters in MongoDB (with backup)

Note: Existing cards for this booster in MongoDB will be overwritten.
Run Pipeline C (pipelines/c_scrape_wiki_cards.py) first if new wiki data was added.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scrapers.duelmasters.pipelines.b_scrape_cards import startscraping

if __name__ == "__main__":
    boosters = sys.argv[1:]
    if not boosters:
        print("Usage: python rescrape_booster.py <booster_code> [<booster_code> ...]")
        print("Example: python rescrape_booster.py dm25ex4")
        sys.exit(1)

    print(f"Rescraping {len(boosters)} booster(s): {', '.join(boosters)}")
    startscraping(boosters)
