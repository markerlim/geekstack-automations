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
UPDATE_CARDS_PATH = project_root / "duelmasterdb" / "update.json"
WIKI_SETS_PATH = project_root / "duelmasterdb" / "wiki_sets.json"
WIKI_BASE = "https://duelmasters.fandom.com"
UPLOAD_BATCH_SIZE = 10

# Known non-card wiki page paths (lowercase, for exact skip check)
NON_CARD_WIKI_PATHS = {
    "abyss-over", "abyss_revolution",
    "be☆the_wind", "brand_new_moment",
    "coro35th",
    "dm22-rp1_legendary_jashin:_transcend!_winning_selection!!",
    "dmc-32", "dmrp-02", "dmsp-01",
    "divine_evolution_saga",
    "duel_creatures",
    "duel_masters:_advance", "duel_masters:_beginner's_guide",
    "duel_masters:_birth_of_the_super_dragon",
    "duel_masters:_blazing_bonds_xx",
    "duel_masters:_curse_of_the_death_phoenix",
    "duel_masters:_entry_gate_of_dragon_saga",
    "duel_masters:_hamukatsu_and_dogiragon's_great_curry_bread_adventure_3d",
    "duel_masters:_here_come_the_jokers!!_strategy_book",
    "duel_masters:_introducing_-_revolution_final!_complete_guide",
    "duel_masters:_introducing_-_revolution_start!_complete_guide",
    "duel_masters:_lunatic_god_saga",
    "duel_masters:_nettou!_battle_arena",
    "duel_masters:_new_frontier", "duel_masters:_perfect_rule_book",
    "duel_masters:_super_complete_card_guide_ds",
    "duel_masters:_super_complete_card_guide_revolution",
    "duel_masters:_super_complete_card_guide_revolution_final",
    "duel_masters:_the_complete_cards_file_-_ultra_e1_(wonder_life_special)",
    "duel_masters:_the_complete_cards_file_-_ultra_e2_(wonder_life_special)",
    "duel_masters:_the_complete_cards_file_-_ultra_e3_(wonder_life_special)",
    "duel_masters:_walkthrough_e1", "duel_masters:_walkthrough_e2",
    "duel_masters_20th_anniversary!_the_rise_of_kings_start_book",
    "duel_masters_abyss_revolution_complete_fan_book",
    "duel_masters_abyss_revolution_expert_fan_book",
    "duel_masters_card_gummy", "duel_masters_card_gummy_2",
    "duel_masters_card_gummy_3", "duel_masters_card_gummy_4",
    "duel_masters_comics",
    "duel_masters_god_of_abyss_full_complete_book",
    "duel_masters_gum",
    "duel_masters_lost_manga_~crystal_of_remembrance~",
    "duel_masters_lost_manga_~forgotten_sun~",
    "duel_masters_new_era_full_complete_book",
    "duel_masters_new_era_full_complete_book_2",
    "duel_masters_royal_road_double_full_complete_book",
    "duel_masters_royal_road_full_complete_book",
    "duel_masters_super_gacharange_start_book",
    "duel_masters_the_rise_of_kings_full_complete_book",
    "duel_masters_the_rise_of_kings_full_complete_book_max",
    "duel_masters_the_rise_of_kings_max_full_complete_and_start_win_book",
    "duel_road",
    "episode_1", "episode_2", "episode_3",
    "fighting_spirit_saga",
    "game_japan",
    "god_apex_saga", "god_of_abyss",
    "holy_fist_saga",
    "jibun",
    "phoenix_saga",
    "psychic_shock",
    "reincarnation_saga",
    "royal_road", "royal_road_double",
    "sengoku_saga",
    "shadowclash_collector_tin",
    "story_of_duel_masters_code:bestie",
    "the_future_is_joe!_joe!",
    "the_rise_of_kings", "the_rise_of_kings_max",
    "toys_and_merchandise",
    "winner_card", "weekly_shonen_sunday",
    "wizards_of_the_coast",
}

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
        driver.set_page_load_timeout(30)
        driver.get(_safe_url(set_url))
        time.sleep(3)
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "content"))
        )
        time.sleep(2)
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
                if path.lower() in NON_CARD_WIKI_PATHS:
                    print(f"    skipping non-card: {path}")
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

    def _is_card_url(url: str) -> bool:
        path = url.replace(WIKI_BASE + "/wiki/", "")
        if ':' in path:
            return False
        return path.lower() not in NON_CARD_WIKI_PATHS

    urls_to_scrape = [u for u in all_urls if u not in existing_urls and _is_card_url(u)]
    skipped_non_card = len([u for u in all_urls if u not in existing_urls and not _is_card_url(u)])
    skipped = len(all_urls) - len(urls_to_scrape)

    print(f"Total unique URLs : {len(all_urls)}")
    print(f"Already in MongoDB: {len(all_urls) - len([u for u in all_urls if u in existing_urls])}")
    print(f"Skipped non-cards : {skipped_non_card}")
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

    update_data = {
        "set_code": set_code,
        "set_url": set_url,
        "card_count": len(card_urls),
        "cards": card_urls,
    }
    UPDATE_CARDS_PATH.write_text(json.dumps(update_data, indent=2, ensure_ascii=False))
    print(f"  update.json written ({len(card_urls)} cards)")

    mongo_service = MongoService()
    existing_urls = get_existing_urls(mongo_service)
    urls_to_scrape = [u for u in card_urls if u not in existing_urls]

    print(f"  Cards in set     : {len(card_urls)}")
    print(f"  Already in MongoDB: {len(card_urls) - len(urls_to_scrape)}")
    print(f"  To scrape        : {len(urls_to_scrape)}")

    if not urls_to_scrape:
        print("Nothing to scrape.")
        return

    batch = []
    failed = []
    scraped = 0

    for idx, url in enumerate(urls_to_scrape, 1):
        print(f"  [{idx}/{len(urls_to_scrape)}] {url}")
        driver = create_driver()
        try:
            card_obj = DuelMastersCardWikiScraper(driver).scrape_card(url)
            if card_obj:
                batch.append(card_obj)
                scraped += 1
                forms = [c.get('name', '?') for c in card_obj.get('cards', [])]
                print(f"    -> {' / '.join(forms)}")
            else:
                print(f"    -> no data returned")
                failed.append(url)
        except Exception as e:
            print(f"    -> ERROR: {e}")
            failed.append(url)
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        if len(batch) >= UPLOAD_BATCH_SIZE:
            flush_batch(mongo_service, batch)

    flush_batch(mongo_service, batch)

    print(f"\nDone scraping set {set_code}.")
    print(f"  Scraped & uploaded : {scraped}")
    print(f"  Failed            : {len(failed)}")
    if failed:
        print("  Failed URLs:")
        for u in failed:
            print(f"    {u}")


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
