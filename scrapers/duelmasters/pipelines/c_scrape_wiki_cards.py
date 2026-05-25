import sys
import json
import random
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
from dotenv import load_dotenv
from scrapers.duelmasters.lib.wiki_card_scraper import DuelMastersCardWikiScraper
from service.mongo_service import MongoService

load_dotenv()

WIKI_COLLECTION = "CL_duelmasters_wiki"
UNIQUE_CARDS_PATH = project_root / "duelmasterdb" / "wiki_unique_cards.json"
UPLOAD_BATCH_SIZE = 10

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.85 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.94 Safari/537.36",
    "Mozilla/5.0 (Macintosh; ARM Mac OS X 13_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.94 Safari/537.36",
]


def create_driver():
    chrome_options = Options()
    chrome_options.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options,
    )


def get_existing_urls(mongo_service):
    existing = mongo_service.get_unique_values(WIKI_COLLECTION, "url")
    return set(existing) if existing else set()


def flush_batch(mongo_service, batch):
    if batch:
        print(f"  Uploading {len(batch)} cards to MongoDB...")
        mongo_service.upload_data(batch, WIKI_COLLECTION)
        batch.clear()


def scrape_bulk(limit=None):
    with open(UNIQUE_CARDS_PATH, encoding='utf-8') as f:
        data = json.load(f)
    all_urls = data['urls']
    if limit:
        all_urls = all_urls[:limit]

    mongo_service = MongoService()
    existing_urls = get_existing_urls(mongo_service)
    urls_to_scrape = [u for u in all_urls if u not in existing_urls]
    skipped = len(all_urls) - len(urls_to_scrape)

    print(f"Total unique URLs : {len(all_urls)}")
    print(f"Already in MongoDB: {skipped}")
    print(f"To scrape         : {len(urls_to_scrape)}")

    if not urls_to_scrape:
        print("Nothing to scrape.")
        return

    batch = []
    failed = []
    scraped = 0

    for idx, url in enumerate(urls_to_scrape, 1):
        print(f"[{idx}/{len(urls_to_scrape)}] {url}")
        driver = create_driver()
        try:
            card_obj = DuelMastersCardWikiScraper(driver).scrape_card(url)
            if card_obj:
                batch.append(card_obj)
                scraped += 1
                forms = [c.get('name', '?') for c in card_obj.get('cards', [])]
                print(f"  -> {' / '.join(forms)}")
            else:
                print(f"  -> no data returned")
                failed.append(url)
        except Exception as e:
            print(f"  -> ERROR: {e}")
            failed.append(url)
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        if len(batch) >= UPLOAD_BATCH_SIZE:
            flush_batch(mongo_service, batch)

    flush_batch(mongo_service, batch)

    print(f"\nDone.")
    print(f"  Scraped & uploaded : {scraped}")
    print(f"  Failed             : {len(failed)}")
    if failed:
        print("  Failed URLs:")
        for u in failed:
            print(f"    {u}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Scrape only the first 3 cards')
    args = parser.parse_args()
    scrape_bulk(limit=3 if args.test else None)
