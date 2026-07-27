import requests
from bs4 import BeautifulSoup
import json
import os
import sys
import time
import re
from datetime import datetime
from urllib.parse import urljoin

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.mongo_service import MongoService
from service.github_service import GitHubService
from service.googlecloudservice import upload_image_to_gcs
from service.selenium_service import SeleniumService
from hololivescrape import scrape_hololive_card

github_service = GitHubService()
mongo_service = MongoService()

FILE_PATH = "hololivedb/db.json"

BASE_URL = "https://hololive-official-cardgame.com"


def parse_japanese_date(date_str):
    if not date_str or date_str.strip() == "":
        return None
    date_clean = re.sub(r'（[^）]*）', '', date_str).strip()
    date_clean = re.sub(r'発売日\s*', '', date_clean)
    match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_clean)
    if match:
        year, month, day = match.groups()
        try:
            dt = datetime(int(year), int(month), int(day))
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            return date_str
    return date_str


def scrape_expansions_from_cardlist():
    """Scrape all expansions listed on the main cardlist page"""
    url = f"{BASE_URL}/cardlist/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "ja,en;q=0.9"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        expansions = []
        seen_codes = set()

        product_items = soup.find_all('li', class_=re.compile(r'\bproduct-item\b'))
        for li in product_items:
            a = li.find('a', class_='anchor', href=re.compile(r'/cardlist/cardsearch/\?expansion='))
            if not a:
                continue
            href = a.get('href', '')
            exp_match = re.search(r'expansion=([\w]+)', href)
            if not exp_match:
                continue
            expansion_code = exp_match.group(1)
            if expansion_code in seen_codes:
                continue
            seen_codes.add(expansion_code)

            classes = [c for c in li.get('class', []) if 'product-type-' in c]
            raw_type = ''
            for tc in classes:
                val = tc.replace('product-type-', '')
                if val != 'deck':
                    raw_type = val
                    break
            if not raw_type and classes:
                raw_type = classes[0].replace('product-type-', '')
            category_map = {'boosters': 'expansion', 'booster': 'expansion', 'decks': 'deck', 'deck': 'deck', 'accessories': 'accessory', 'accessory': 'accessory', 'pr': 'pr'}
            category = category_map.get(raw_type, 'other')

            img = a.find('img')
            title = img.get('alt', '') if img else ''

            name_div = a.find('div', class_='name')
            if name_div:
                title = name_div.get_text(strip=True)

            thumb_img = a.find('img')
            expansion_image = ''
            if thumb_img and thumb_img.get('src'):
                src = thumb_img.get('src', '')
                expansion_image = urljoin(BASE_URL, src) if not src.startswith('http') else src

            detail_dd = a.find('dd', class_='detail')
            release_date = None
            if detail_dd:
                release_raw = detail_dd.get_text(strip=True)
                release_date = parse_japanese_date(release_raw) if release_raw else None

            expansion_data = {
                "booster": expansion_code,
                "title": title,
                "category": category,
                "release_date": release_date,
                "url": urljoin(BASE_URL, href)
            }
            if expansion_image:
                expansion_data["expansion_image"] = expansion_image

            expansions.append(expansion_data)

        print(f"Found {len(expansions)} expansions on cardlist page")
        return expansions

    except Exception as e:
        print(f"Error scraping expansions: {e}")
        return []


def get_card_ids_for_expansion(expansion_code):
    """Get card IDs for an expansion. First tries Selenium for JS-loaded pages,
    falls back to brute-force scan of the text view first page."""
    selenium = SeleniumService(headless=True, window_size="1920,1080", timeout=15)
    card_ids = []

    try:
        url = f"{BASE_URL}/cardlist/cardsearch/?expansion={expansion_code}&view=text"
        print(f"  Loading card list via Selenium: {url}")
        selenium.driver.get(url)
        time.sleep(4)

        for _ in range(20):
            selenium.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

        page_source = selenium.driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')

        links = soup.find_all('a', href=re.compile(r'/cardlist/\?id='))
        for link in links:
            href = link.get('href', '')
            id_match = re.search(r'id=(\d+)', href)
            if id_match:
                cid = id_match.group(1)
                if cid not in card_ids:
                    card_ids.append(cid)

        print(f"  Found {len(card_ids)} cards")
        return card_ids

    except Exception as e:
        print(f"  Selenium error: {e}")
        return card_ids
    finally:
        selenium.close()


def scrape_cards_for_expansion(expansion_code, expansion_title):
    """Scrape all cards for an expansion"""
    card_ids = get_card_ids_for_expansion(expansion_code)
    if not card_ids:
        print(f"  No cards found for {expansion_code}, skipping")
        return []

    cards_data = []
    total = len(card_ids)

    for idx, cid in enumerate(card_ids):
        print(f"  [{idx+1}/{total}] Scraping card ID {cid}")
        try:
            card_data = scrape_hololive_card(cid, translate=False)
            if card_data:
                card_data['booster'] = expansion_code
                card_data['expansionTitle'] = expansion_title
                cards_data.append(card_data)
            time.sleep(0.3)
        except Exception as e:
            print(f"    Error: {e}")
            continue

    print(f"  Scraped {len(cards_data)}/{total} cards for {expansion_title}")
    return cards_data


def update_github_expansions(expansions, file_sha=None):
    expansions_db = {
        "expansions": expansions,
        "total_count": len(expansions),
        "updated_at": datetime.now().isoformat()
    }
    updated_content = json.dumps(expansions_db, indent=2, ensure_ascii=False)
    success = github_service.update_file(FILE_PATH, updated_content, "Update hololive db.json", file_sha)
    if success:
        print("GitHub db.json updated")
    else:
        print("Error updating GitHub db.json")
    return success


def upload_expansion_image(expansion_code, image_url):
    try:
        if not image_url:
            return None
        filename = f"hocgCover{expansion_code}"
        filepath = "boostercover/"
        gcs_url = upload_image_to_gcs(image_url, filename, filepath)
        print(f"  Uploaded expansion image: {filename}")
        return gcs_url
    except Exception as e:
        print(f"  Failed to upload expansion image: {e}")
        return image_url


def check_and_scrape_new_expansions():
    current_expansions = scrape_expansions_from_cardlist()
    if not current_expansions:
        print("No expansions found on website")
        return []

    current_codes = {exp['booster'] for exp in current_expansions}

    existing_data, file_sha = github_service.load_json_file(file_path=FILE_PATH)

    if existing_data and 'expansions' in existing_data:
        known_codes = set()
        for item in existing_data['expansions']:
            if isinstance(item, dict):
                bc = item.get('booster', '')
                if bc:
                    known_codes.add(bc)
        new_expansions = [e for e in current_expansions if e['booster'] not in known_codes]
        expansions_to_process = new_expansions
        print(f"Known expansions: {len(known_codes)}, New: {len(new_expansions)}")
    else:
        expansions_to_process = current_expansions
        print(f"No existing data - will process all {len(expansions_to_process)} expansions")

    if not expansions_to_process:
        print("No new expansions to scrape")
        return []

    all_cards = []
    for exp in expansions_to_process:
        print(f"\nProcessing: {exp['title']} (code: {exp['booster']})")

        if exp.get('expansion_image'):
            gcs_url = upload_expansion_image(exp['booster'], exp['expansion_image'])
            if gcs_url:
                exp['urlimage'] = gcs_url

        cards = scrape_cards_for_expansion(exp['booster'], exp['title'])
        all_cards.extend(cards)

    update_github_expansions(current_expansions, file_sha)

    if all_cards:
        collection_value = os.getenv('C_HOLOLIVE')
        if collection_value:
            mongo_service.upload_data(
                data=all_cards,
                collection_name=collection_value,
                backup_before_upload=True
            )
            print(f"Uploaded {len(all_cards)} cards to MongoDB")
        else:
            print("C_HOLOLIVE not set in .env")

    print(f"\nDone. Scraped {len(all_cards)} cards from {len(expansions_to_process)} expansion(s)")
    return all_cards


if __name__ == "__main__":
    check_and_scrape_new_expansions()
