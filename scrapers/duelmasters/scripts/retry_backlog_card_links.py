"""
Retry the sets that failed during setup/2_scrape_card_links.py.

Reads duelmasterdb/backlog.json, retries every entry with reason="scrape_error"
(skips no_url — can't scrape what has no URL), and writes recovered sets back
into duelmasterdb/wiki_set_cards.json. Also drops the now-recovered entries
from backlog.json.

Logic mirrors setup/2_scrape_card_links.py: fresh Selenium driver per page
(fandom blocks plain HTTP, and reusing a driver across pages crashes Chrome),
parse the Contents section, collect /wiki/ links.

Run from project root:
    python scrapers/duelmasters/scripts/retry_backlog_card_links.py
"""
import json
import random
import sys
import time
from pathlib import Path

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

WIKI_SET_CARDS_PATH = project_root / "duelmasterdb" / "wiki_set_cards.json"
BACKLOG_PATH = project_root / "duelmasterdb" / "backlog.json"
WIKI_BASE = "https://duelmasters.fandom.com"
MAX_RETRIES_PER_SET = 3
RETRY_BACKOFF_SECS = 5
DELAY_BETWEEN_SETS = 3

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
    chrome_options.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options,
    )


def fetch_card_links(url: str) -> list[str]:
    """Fetch card links from a booster set page using a fresh driver per call."""
    driver = create_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "ul"))
        )
        time.sleep(1)
        soup = BeautifulSoup(driver.page_source, "html.parser")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    contents_h2 = None
    for h2 in soup.find_all("h2"):
        if h2.find("span", {"id": "Contents"}):
            contents_h2 = h2
            break
    if not contents_h2:
        return []

    card_urls = set()
    current = contents_h2.find_next_sibling()
    while current:
        if current.name == "h2":
            break
        if current.name == "ul":
            for a in current.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("/wiki/"):
                    continue
                if ":" in href[len("/wiki/"):]:
                    continue
                card_urls.add(WIKI_BASE + href)
        current = current.find_next_sibling()

    return sorted(card_urls)


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    backlog = load_json(BACKLOG_PATH)
    set_cards = load_json(WIKI_SET_CARDS_PATH)

    targets = [b for b in backlog if b.get("reason") == "scrape_error"]
    no_url = [b for b in backlog if b.get("reason") != "scrape_error"]

    print(f"Backlog: {len(targets)} scrape_error + {len(no_url)} no_url")
    print(f"Will retry {len(targets)} sets, up to {MAX_RETRIES_PER_SET} attempts each.\n")
    if not targets:
        print("Nothing to do.")
        return

    recovered = []
    still_failing = []

    for idx, entry in enumerate(targets, 1):
        set_code = entry["set_code"]
        url = entry["url"]
        print(f"[{idx}/{len(targets)}] {set_code} — {url}")

        cards = []
        last_err = None
        for attempt in range(1, MAX_RETRIES_PER_SET + 1):
            try:
                cards = fetch_card_links(url)
                if cards:
                    print(f"  ✓ attempt {attempt}: {len(cards)} card links")
                    break
                last_err = "no card links found on page"
                print(f"  ⚠️ attempt {attempt}: {last_err}")
            except Exception as e:
                last_err = str(e).splitlines()[0][:150]
                print(f"  ✗ attempt {attempt}: {last_err}")
            if attempt < MAX_RETRIES_PER_SET:
                time.sleep(RETRY_BACKOFF_SECS)

        if cards:
            recovered.append(set_code)
            set_cards[set_code] = {
                "name": entry.get("name"),
                "set_url": url,
                "card_count": len(cards),
                "cards": cards,
            }
        else:
            entry_with_err = dict(entry)
            entry_with_err["error"] = last_err or entry.get("error", "")
            still_failing.append(entry_with_err)
            print(f"  💀 still failing: {last_err}")

        # Save after each set so an interrupt doesn't lose progress
        save_json(WIKI_SET_CARDS_PATH, set_cards)
        if idx < len(targets):
            time.sleep(DELAY_BETWEEN_SETS)

    save_json(BACKLOG_PATH, no_url + still_failing)

    print(f"\n📊 Done.")
    print(f"   ✅ Recovered: {len(recovered)} sets")
    for sc in recovered:
        print(f"      {sc}")
    print(f"   💀 Still failing: {len(still_failing)} sets")
    for e in still_failing:
        print(f"      {e['set_code']}")
    print(f"   📦 Backlog now: {len(no_url) + len(still_failing)} entries")

    if recovered:
        print(
            "\nNext step — refresh the deduped card URL list, then re-run Pipeline C:"
            "\n  python scrapers/duelmasters/setup/3_dedupe_card_urls.py"
            "\n  python scrapers/duelmasters/pipelines/c_scrape_wiki_cards.py"
        )


if __name__ == "__main__":
    main()
