import json
import re
import sys
import time
from pathlib import Path
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

sys.path.append(str(Path(__file__).parent.parent))
from scrapers.riftbound.riftboundscrape import setup_selenium_driver, navigate_to_card

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent
INPUT_FILE = PROJECT_ROOT / "riftbounddb" / "RB_UPDATED.json"
PARTIAL_FILE = HERE / "RB_UPDATED_partial.json"
BASE_URL = "https://riftbound.leagueoflegends.com/en-us/card-gallery/"
SAVE_INTERVAL = 50


def replace_glyph(match):
    name = match.group(1)
    if name.startswith('rune_'):
        name = name[5:]
    parts = name.replace('_', ' ').split()
    return '{' + ' '.join(p.capitalize() for p in parts) + '}'


def extract_ability_text(driver):
    try:
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        lightbox = soup.find('div', {'data-testid': 'lightbox'})
        if not lightbox:
            return None
        ability_elem = lightbox.find('div', {'data-testid': 'rich-text'})
        if not ability_elem:
            return None
        ability_text_elem = ability_elem.find('div', class_=re.compile('sc-4225abdc'))
        if not ability_text_elem:
            inner_p = ability_elem.find('p')
            if inner_p:
                ability_text_elem = ability_elem
            else:
                return None
        ability_html = str(ability_text_elem)
        ability_html = re.sub(
            r'<img[^>]*src="[^"]*/([a-z0-9_]+)\.svg"[^>]*>',
            replace_glyph,
            ability_html
        )
        ability_html = re.sub(r'\s*<br\s*/?>\s*', '\n', ability_html)
        p_tags = BeautifulSoup(ability_html, 'html.parser').find_all('p')
        ability_text = '\n'.join(p.get_text() for p in p_tags)
        return ability_text if ability_text else None
    except Exception as e:
        print(f"      ⚠️ Error extracting ability text: {e}")
        return None


def main():
    print("=" * 60)
    print("Riftbound Card Ability Cleanup Script")
    print("=" * 60)

    if not INPUT_FILE.exists():
        print(f"❌ Input file not found: {INPUT_FILE}")
        sys.exit(1)

    print(f"📂 Loading cards from {INPUT_FILE}...")
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        cards = json.load(f)

    if isinstance(cards, dict):
        cards = [cards]
    if not isinstance(cards, list):
        print("❌ Unexpected JSON format — expected array of card objects")
        sys.exit(1)

    total = len(cards)
    print(f"📊 Loaded {total} cards")

    succeeded = 0
    failed = 0
    skipped_no_ability = 0

    driver = None
    try:
        print("🔧 Setting up Selenium driver...")
        driver = setup_selenium_driver()
        driver.get(BASE_URL)
        time.sleep(2)

        for idx, card in enumerate(cards):
            code = card.get('code', 'UNKNOWN')
            title = card.get('title', 'Unknown')
            print(f"\n[{idx + 1}/{total}] {title} ({code})")

            has_ability = card.get('ability') is not None
            if not has_ability:
                skipped_no_ability += 1
                print(f"      ⏭️ No existing ability field — skipping")
                continue

            if not navigate_to_card(driver, code):
                failed += 1
                print(f"      ⚠️ Failed to load card modal — keeping existing ability")
                continue

            ability_text = extract_ability_text(driver)
            if ability_text is None:
                skipped_no_ability += 1
                print(f"      ⏭️ No rich-text element found (vanilla unit) — keeping existing ability")
                continue

            card['ability'] = ability_text
            succeeded += 1
            print(f"      ✅ Ability updated")

            if (idx + 1) % SAVE_INTERVAL == 0:
                print(f"\n💾 Periodic save at card {idx + 1}/{total}...")
                with open(PARTIAL_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cards, f, indent=2, ensure_ascii=False)
                print(f"✅ Saved partial progress to {PARTIAL_FILE}")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n\n⚠️ Interrupted — saving progress...")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            driver.quit()
            print("\n🔐 Browser closed")

        print(f"\n💾 Saving final output to {INPUT_FILE}...")
        with open(INPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(cards, f, indent=2, ensure_ascii=False)

        print(f"\n{'=' * 60}")
        print(f"📊 SUMMARY")
        print(f"{'=' * 60}")
        print(f"  Total cards:     {total}")
        print(f"  Updated:         {succeeded}")
        print(f"  Failed to load:  {failed}")
        print(f"  Skipped (no ability): {skipped_no_ability}")
        print(f"{'=' * 60}")
        print(f"✅ Output written to {INPUT_FILE}")

        if PARTIAL_FILE.exists():
            import os
            os.remove(PARTIAL_FILE)
            print(f"🧹 Cleaned up partial save file")


if __name__ == "__main__":
    main()
