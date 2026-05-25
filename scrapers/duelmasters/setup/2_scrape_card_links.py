import json
import os
import sys
import random
import time

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

WIKI_SETS_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'duelmasterdb', 'wiki_sets.json')
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'duelmasterdb', 'wiki_set_cards.json')
WIKI_BASE = "https://duelmasters.fandom.com"

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
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options,
    )


def fetch_card_links(url: str) -> list[str]:
    """Fetch card links from a booster set page using a fresh driver per call."""
    driver = create_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "ul"))
        )
        time.sleep(1)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
    finally:
        driver.quit()

    # Find the "Contents" h2 and collect links until the next h2
    contents_h2 = None
    for h2 in soup.find_all('h2'):
        if h2.find('span', {'id': 'Contents'}):
            contents_h2 = h2
            break

    if not contents_h2:
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

    return sorted(card_urls)


def load_existing_output():
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_output(data):
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def scrape_all_set_card_links(limit=None):
    with open(WIKI_SETS_PATH, 'r', encoding='utf-8') as f:
        wiki_sets = json.load(f)

    sets = wiki_sets['sets']
    total = len(sets)
    print(f"Total sets to scrape: {total}")

    results = load_existing_output()
    already_done = len([v for v in results.values() if not v.get('error')])
    if already_done:
        print(f"Resuming — {already_done} sets already scraped, skipping them.")

    for idx, entry in enumerate(sets[:limit] if limit else sets, 1):
        set_code = entry.get('set_code') or entry.get('name')
        url = entry.get('url')

        if not url:
            print(f"[{idx}/{total}] {set_code}: no URL, skipping")
            continue

        # Skip only successful previous results (re-try errors)
        if set_code in results and not results[set_code].get('error'):
            print(f"[{idx}/{total}] {set_code}: already done, skipping")
            continue

        print(f"[{idx}/{total}] Scraping {set_code} — {url}")
        try:
            card_urls = fetch_card_links(url)
            results[set_code] = {
                "name": entry.get('name'),
                "set_url": url,
                "card_count": len(card_urls),
                "cards": card_urls,
            }
            print(f"  -> {len(card_urls)} card links found")
        except Exception as e:
            print(f"  -> ERROR: {e}")
            results[set_code] = {
                "name": entry.get('name'),
                "set_url": url,
                "card_count": 0,
                "cards": [],
                "error": str(e),
            }

        save_output(results)

    print(f"\nDone. Results saved to {OUTPUT_PATH}")
    total_cards = sum(v['card_count'] for v in results.values())
    print(f"Sets scraped: {len(results)} / {total}")
    print(f"Total card links collected: {total_cards}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Scrape only the first set')
    args = parser.parse_args()
    scrape_all_set_card_links(limit=1 if args.test else None)
