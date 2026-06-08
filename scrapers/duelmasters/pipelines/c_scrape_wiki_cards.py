import re
import sys
import json
import random
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
from dotenv import load_dotenv
from scrapers.duelmasters.lib.wiki_card_scraper import DuelMastersCardWikiScraper
from service.mongo_service import MongoService

load_dotenv()

WIKI_COLLECTION = "CL_duelmasters_wiki"
UNIQUE_CARDS_PATH = project_root / "duelmasterdb" / "wiki_unique_cards.json"
SET_CARDS_PATH = project_root / "duelmasterdb" / "wiki_set_cards.json"
WIKI_SETS_PATH = project_root / "duelmasterdb" / "wiki_sets.json"
WIKI_BASE = "https://duelmasters.fandom.com"
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


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        quote(parts.path, safe="/"),
        parts.query,
        parts.fragment,
    ))


def fetch_card_links_from_set(set_url: str) -> list[str]:
    print(f"  Fetching card links from set page: {set_url}")
    driver = create_driver()
    try:
        driver.get(_safe_url(set_url))
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "ul"))
        )
        time.sleep(1)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
    finally:
        driver.quit()

    contents_h2 = None
    for h2 in soup.find_all('h2'):
        if h2.find('span', {'id': 'Contents'}):
            contents_h2 = h2
            break

    if not contents_h2:
        print("  -> No 'Contents' section found on set page")
        return []

    card_urls = set()
    current = contents_h2.find_next_sibling()
    while current:
        if current.name == 'h2':
            break
        if current.name == 'ul':
            for a in current.find_all('a', href=True):
                href = a['href']
                if not href.startswith('/wiki/'):
                    continue
                path = href[len('/wiki/'):]
                if ':' in path:
                    continue
                card_urls.add(WIKI_BASE + href)
        current = current.find_next_sibling()

    result = sorted(card_urls)
    print(f"  -> {len(result)} card links found")
    return result


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


def rebuild_unique_cards():
    with open(SET_CARDS_PATH, encoding='utf-8') as f:
        data = json.load(f)
    all_urls = sorted({url for v in data.values() for url in v.get('cards', [])})
    output = {'total': len(all_urls), 'urls': all_urls}
    with open(UNIQUE_CARDS_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
    print(f"  wiki_unique_cards.json rebuilt: {len(all_urls)} unique URLs")
    return all_urls


def derive_set_code_from_url(set_url: str) -> str | None:
    page = set_url.rstrip('/').rsplit('/', 1)[-1]
    m = re.match(r'^(DM\d+-\d+\S*|[A-Za-z]+-\d+\S*)', page)
    return m.group(1) if m else None


def scrape_from_set_url(set_url: str, set_code: str | None):
    set_code_from_lookup = None
    if WIKI_SETS_PATH.exists():
        with open(WIKI_SETS_PATH, encoding='utf-8') as f:
            ws = json.load(f)
        for s in ws.get('sets', []):
            if s.get('url') == set_url:
                set_code_from_lookup = s['set_code']
                break

    if not set_code:
        set_code = set_code_from_lookup or derive_set_code_from_url(set_url)

    if not set_code:
        print("ERROR: could not determine set code from URL. Provide --set-code.")
        return

    print(f"Set code: {set_code}")

    card_urls = fetch_card_links_from_set(set_url)
    if not card_urls:
        print("No card links found. Exiting.")
        return

    set_cards = json.loads(SET_CARDS_PATH.read_text()) if SET_CARDS_PATH.exists() else {}
    set_cards[set_code] = {
        "name": set_code,
        "set_url": set_url,
        "card_count": len(card_urls),
        "cards": card_urls,
    }
    SET_CARDS_PATH.write_text(json.dumps(set_cards, indent=2, ensure_ascii=False))
    print(f"  wiki_set_cards.json updated ({set_code}: {len(card_urls)} cards)")

    rebuild_unique_cards()

    scrape_bulk()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Scrape only the first 3 cards')
    parser.add_argument('--set-url', type=str, help='Scrape cards from a specific wiki set page URL')
    parser.add_argument('--set-code', type=str, help='Set code for wiki_set_cards.json (auto-derived if omitted)')
    args = parser.parse_args()

    if args.set_url:
        scrape_from_set_url(args.set_url, args.set_code)
    else:
        scrape_bulk(limit=3 if args.test else None)
