"""One-off: re-scrape the 2 wiki pages we stubbed in R12 and replace
the stubs in dmwikifull_cleaned.json with the real scraped data.

Run from repo root: `venv/bin/python datacleaning/rescrape_two_wiki.py`
"""
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

from scrapers.duelmasters.lib.wiki_card_scraper import DuelMastersCardWikiScraper

WIKI_CLEAN = REPO_ROOT / "datacleaning" / "dmwikifull_cleaned.json"

TARGETS = [
    "https://duelmasters.fandom.com/wiki/Blankas",
]

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.85 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.94 Safari/537.36",
    "Mozilla/5.0 (Macintosh; ARM Mac OS X 13_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.94 Safari/537.36",
]


def create_driver():
    opts = Options()
    opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)


def main():
    print(f"Loading {WIKI_CLEAN.name}...")
    wiki = json.loads(WIKI_CLEAN.read_text())
    by_url = {d.get("url"): i for i, d in enumerate(wiki)}

    scraped = {}
    for url in TARGETS:
        print(f"\n=== Scraping {url} ===")
        driver = create_driver()
        try:
            data = DuelMastersCardWikiScraper(driver).scrape_card(url)
            if data:
                forms = [c.get("name", "?") for c in data.get("cards", [])]
                print(f"  -> twinpact={data.get('is_twinpact')}  forms: {' / '.join(forms)}")
                for c in data.get("cards", []):
                    print(f"     name={c.get('name')!r}")
                    print(f"     name_jp={c.get('name_jp')!r}")
                    print(f"     card_type={c.get('card_type')!r}")
                    print(f"     race={c.get('race')!r}")
                scraped[url] = data
            else:
                print(f"  -> scrape_card returned None — leaving stub")
        except Exception as e:
            print(f"  -> ERROR: {e} — leaving stub")
        finally:
            try:
                driver.quit()
            except Exception:
                pass

    if not scraped:
        print("\nNothing was scraped; not modifying wiki JSON.")
        return

    replaced = 0
    for url, data in scraped.items():
        idx = by_url.get(url)
        if idx is None:
            wiki.append(data)
            print(f"\n  appended new wiki doc: {url.rsplit('/', 1)[-1]}")
        else:
            wiki[idx] = data
            replaced += 1
            print(f"\n  replaced wiki doc: {url.rsplit('/', 1)[-1]}")

    WIKI_CLEAN.write_text(json.dumps(wiki, ensure_ascii=False, indent=2))
    print(f"\nWrote {WIKI_CLEAN.name}: replaced {replaced}, appended {len(scraped) - replaced}")


if __name__ == "__main__":
    main()
