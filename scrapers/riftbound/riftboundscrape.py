import os
import json
import time
import sys
import re
import base64
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.googlecloudservice import upload_image_to_gcs
from service.mongo_service import MongoService
from service.github_service import GitHubService
load_dotenv()

# Initialize Service Layer
github_service = GitHubService()
mongo_service = MongoService()

# Variables
FILE_PATH = "riftbounddb/db.json"
BASE_URL = "https://riftbound.leagueoflegends.com/en-us/card-gallery/"

DB_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'riftbounddb', 'db.json')

# Define card sets
CARD_SETS = {
    'SFD': 'Spiritforged',
    'OGN': 'Origins - Main Set',
    'OGS': 'Origins - Proving Grounds'
}

def detect_available_sets(driver):
    """Detect all available sets from the website with card counts"""
    try:
        print(f"🔍 Detecting available sets...")
        
        # Open filters and expand sets section
        click_show_filters(driver)
        expand_set_section(driver)
        
        time.sleep(1)
        
        # Get all set radio buttons
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        available_sets = []
        
        # Find all radio buttons in the card sets radio group
        radio_buttons = soup.find_all('button', {'data-testid': re.compile('card-sets-radio-group-item-')})
        
        for button in radio_buttons:
            data_testid = button.get('data-testid', '')
            match = re.search(r'card-sets-radio-group-item-(\w+)$', data_testid)
            
            if match:
                set_code = match.group(1)
                # Skip "all" option
                if set_code.lower() == 'all':
                    continue
                
                # Get the set name from button text
                set_name = button.get_text(strip=True)
                
                available_sets.append({
                    'code': set_code,
                    'name': set_name,
                    'detected_at': datetime.now().isoformat(),
                    'card_count': 0  # Will be populated when scraped
                })
                print(f"  📚 Detected: {set_name} ({set_code})")
        
        return available_sets
    except Exception as e:
        print(f"  ⚠️ Error detecting sets: {str(e)}")
        return []

def get_sets_to_scrape(available_sets):
    """Determine which sets need scraping based on card count comparison"""
    scraped_sets_data = {}
    
    # Get card counts for each set from MongoDB
    for set_info in available_sets:
        set_code = set_info.get('code')
        # Query MongoDB for cards with this booster code
        cards = list(mongo_service.find_all_by_field('CL_riftbound', 'booster', set_code))
        scraped_sets_data[set_code] = cards
    
    sets_to_scrape = []
    
    for set_info in available_sets:
        set_code = set_info.get('code')
        set_name = set_info.get('name')
        detected_card_count = set_info.get('card_count', 0)
        
        existing_cards = scraped_sets_data.get(set_code, [])
        existing_count = len(existing_cards)
        
        if existing_count == 0:
            sets_to_scrape.append({
                'code': set_code,
                'name': set_name,
                'reason': 'not_scraped'
            })
            print(f"  📚 {set_name} ({set_code}) - Not scraped yet")
        else:
            # Already scraped, check if card count matches
            if detected_card_count > 0 and existing_count != detected_card_count:
                # Card count mismatch - need to rescrape
                missing_count = detected_card_count - existing_count
                sets_to_scrape.append({
                    'code': set_code,
                    'name': set_name,
                    'reason': 'card_count_mismatch',
                    'existing_count': existing_count,
                    'expected_count': detected_card_count,
                    'missing_count': missing_count,
                    'existing_cards': existing_cards  # Pass existing cards to skip them during scraping
                })
                print(f"  📊 {set_name} ({set_code}) - Card count mismatch: has {existing_count}, expected {detected_card_count} ({missing_count} missing)")
            else:
                # Up to date
                print(f"  ✅ {set_name} ({set_code}) - Already has {existing_count} cards (up to date)")
    
    return sets_to_scrape

def setup_selenium_driver():
    """Setup Selenium Chrome driver with CI/CD support"""
    chrome_options = Options()
    
    # Enable headless mode for CI/CD environments
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"❌ Failed to create Chrome driver: {str(e)}")
        print("⚠️ Make sure chromedriver is installed and in PATH")
        raise

def click_show_filters(driver):
    """Click the 'Show Filters' button to reveal filter options"""
    try:
        print(f"🔓 Opening filters...")
        
        # Wait for Show Filters button to be present
        # Look for button containing div with "Show Filters" text
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//button[contains(., 'Show Filters')]"))
        )
        
        # Find and click the Show Filters button
        show_filters_button = driver.find_element(By.XPATH, "//button[contains(., 'Show Filters')]")
        driver.execute_script("arguments[0].click();", show_filters_button)
        print(f"  ✅ Filters opened")
        time.sleep(1)
        
        return True
    except Exception as e:
        print(f"  ⚠️ Could not find Show Filters button: {str(e)}")
        return False

def expand_set_section(driver):
    """Click the 'Set' trigger to expand the sets section"""
    try:
        print(f"📂 Expanding sets section...")
        
        # Wait for Set trigger button to be present
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'button[data-testid="card-sets-trigger"]'))
        )
        
        # Find and click the Set trigger button
        set_trigger = driver.find_element(By.CSS_SELECTOR, 'button[data-testid="card-sets-trigger"]')
        
        # Check if it's already expanded
        is_expanded = set_trigger.get_attribute('aria-expanded') == 'true'
        
        if not is_expanded:
            driver.execute_script("arguments[0].click();", set_trigger)
            print(f"  ✅ Sets section expanded")
            time.sleep(1)
        else:
            print(f"  ℹ️ Sets section already expanded")
        
        return True
    except Exception as e:
        print(f"  ⚠️ Could not expand sets section: {str(e)}")
        return False

def select_set_radio(driver, set_code):
    """Select a card set using the radio group"""
    try:
        print(f"🔄 Selecting set: {set_code}")
        
        # Wait for radio button to be present
        radio_selector = f'button[data-testid="card-sets-radio-group-item-{set_code}"]'
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, radio_selector))
        )
        
        # Click the radio button
        radio_button = driver.find_element(By.CSS_SELECTOR, radio_selector)
        driver.execute_script("arguments[0].click();", radio_button)
        
        print(f"  ✅ Set {set_code} selected")
        time.sleep(2)  # Wait for cards to load
        
        return True
    except Exception as e:
        print(f"  ❌ Error selecting set {set_code}: {str(e)}")
        return False

def get_card_list_from_gallery(driver):
    """Get all cards currently displayed in the gallery"""
    try:
        # Wait for cards to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, '[data-testid*="card-gallery"]'))
        )
        
        # Get the page source and parse with BeautifulSoup
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find all card elements - they typically have a data-testid or link structure
        cards = []
        
        # Look for card links in the gallery
        for card_element in soup.find_all('a', href=True):
            href = card_element.get('href', '')
            if '#card-gallery--' in href:
                # Extract card code from URL (e.g., "ogs-001-024")
                match = re.search(r'#card-gallery--(.+?)$', href)
                if match:
                    card_code = match.group(1).upper()
                    cards.append({
                        'code': card_code,
                        'url_hash': href
                    })
        
        print(f"  📊 Found {len(cards)} cards in gallery")
        return cards
    except Exception as e:
        print(f"  ❌ Error getting card list: {str(e)}")
        return []

def navigate_to_card(driver, card_code):
    """Navigate to a specific card detail page"""
    try:
        url = f"{BASE_URL}#card-gallery--{card_code}"
        driver.get(url)
        
        # Wait for lightbox to appear
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="lightbox"]'))
        )
        
        time.sleep(1)  # Extra wait for content to render
        return True
    except Exception as e:
        print(f"    ⚠️ Failed to load card modal: {str(e)}")
        return False

def extract_card_data(driver, card_code, booster):
    """Extract card data from the lightbox modal"""
    try:
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find lightbox
        lightbox = soup.find('div', {'data-testid': 'lightbox'})
        if not lightbox:
            print(f"    ❌ Lightbox not found for card {card_code}")
            return None
        
        # Define expected fields - initialize all to None
        expected_fields = [
            'title', 'cardUid', 'cardId', 'urlimage', 'alt',
            'energy', 'power', 'might', 'domain', 'card_type', 'tags',
            'ability', 'rarity', 'artist', 'card_set'
        ]
        
        card_data = {
            'code': card_code,
            'scraped_at': datetime.now().isoformat()
        }
        
        # Initialize all expected fields to None
        for field in expected_fields:
            card_data[field] = None
        
        # Extract card title and number using HTML structure
        title_elem = lightbox.find('h3')
        if title_elem:
            card_data['title'] = title_elem.text.strip()
            
            # Card number is the <p> tag right after the title
            card_number_elem = title_elem.find_next('p')
            if card_number_elem:
                card_uid = card_number_elem.text.strip()
                card_data['cardUid'] = card_uid
                
                # Extract cardId by removing variant letters (e.g., OGN-030a/298 -> OGN-030/298)
                card_id = re.sub(r'([A-Z]+)-(\d+)[a-z]*/(\d+)', r'\1-\2/\3', card_uid)
                card_data['cardId'] = card_id
        
        # Extract card image
        img_elem = lightbox.find('img', class_=re.compile('main-card-image'))
        if img_elem:
            src = img_elem.get('src', '')
            if src:
                try:
                    # Remove query parameters from the URL (everything after .png, .jpg, etc.)
                    # e.g., "...file.png?auto=format&fit=fill&q=80&w=444" -> "...file.png"
                    src_clean = re.sub(r'(\.(png|jpg|jpeg|webp|gif))\?.*$', r'\1', src, flags=re.IGNORECASE)
                    
                    # Create a filename from the card code
                    card_data['urlimage'] = upload_image_to_gcs(
                        image_url=src_clean,
                        filename=card_code,
                        filepath=f'riftbound/{booster}/'
                    )
                except Exception as e:
                    print(f"    ⚠️ Failed to upload image: {str(e)}")
                    card_data['urlimage'] = src  # Fallback to original URL
            
            alt = img_elem.get('alt', '')
            if alt:
                card_data['alt'] = alt
        
        # Extract card stats based on HTML structure pattern
        stats_sections = lightbox.find_all('div', class_=re.compile('sc-3f327fbc-0'))
        
        for section in stats_sections:
            header = section.find('h6')
            if not header:
                continue
            
            stat_name = header.text.strip()
            
            # Handle multi-value stats (like Card Type or Domain)
            if stat_name in ['Card Type', 'Domain', 'Tags']:
                values = []
                # Find all <p> tags in this section that come after the header
                all_p_tags = section.find_all('p')
                for p_tag in all_p_tags:
                    text = p_tag.text.strip()
                    if text:
                        values.append(text)
                
                if values:
                    card_data[stat_name.lower().replace(' ', '_')] = values if len(values) > 1 else values[0]
            else:
                # For single-value stats, find the first <p> tag after the header
                p_tag = header.find_next('p')
                if p_tag:
                    stat_value = p_tag.text.strip()
                    if stat_value:
                        card_data[stat_name.lower().replace(' ', '_')] = stat_value
        
        # Extract ability text
        ability_elem = lightbox.find('div', {'data-testid': 'rich-text'})
        if ability_elem:
            ability_text_elem = ability_elem.find('div', class_=re.compile('sc-4225abdc'))
            if ability_text_elem:
                # Extract plain text from HTML
                p_tags = ability_text_elem.find_all('p')
                ability_text = ' '.join([p.get_text(strip=True) for p in p_tags])
                if ability_text:
                    card_data['ability'] = ability_text
        
        # Extract rarity
        rarity_section = None
        for section in stats_sections:
            header = section.find('h6', class_=re.compile('sc-fa72520a-0'))
            if header and 'Rarity' in header.text:
                rarity_section = section
                break
        
        if rarity_section:
            rarity_text = rarity_section.find('p', class_=re.compile('jlpCll'))
            if rarity_text:
                card_data['rarity'] = rarity_text.text.strip()
        
        # Extract artist
        artist_section = None
        for section in stats_sections:
            header = section.find('h6', class_=re.compile('sc-fa72520a-0'))
            if header and 'Artist' in header.text:
                artist_section = section
                break
        
        if artist_section:
            artist_text = artist_section.find('p', class_=re.compile('jlpCll'))
            if artist_text:
                card_data['artist'] = artist_text.text.strip()
        
        # Extract card set
        card_set_section = None
        for section in stats_sections:
            header = section.find('h6', class_=re.compile('sc-fa72520a-0'))
            if header and 'Card Set' in header.text:
                card_set_section = section
                break
        
        if card_set_section:
            set_text = card_set_section.find('p', class_=re.compile('jlpCll'))
            if set_text:
                card_data['card_set'] = set_text.text.strip()
        
        print(f"    ✅ Extracted card data: {card_data.get('title', 'Unknown')}")
        return card_data
    
    except Exception as e:
        print(f"    ❌ Error extracting card data: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

def scrape_set(driver, set_code, set_name, existing_cards=None):
    """Scrape all cards for a specific set, skipping ones that already exist"""
    print(f"\n🎴 Scraping set: {set_name} ({set_code})")
    
    # Build set of existing card codes
    existing_card_codes = set()
    if existing_cards:
        existing_card_codes = {card.get('code') for card in existing_cards}
        print(f"  📋 Checking against {len(existing_card_codes)} existing cards")
    
    # Navigate to base page
    driver.get(BASE_URL)
    time.sleep(2)
    
    # Open filters first
    if not click_show_filters(driver):
        print(f"  ⚠️ Could not open filters, continuing anyway...")
    
    # Expand the set section
    if not expand_set_section(driver):
        print(f"  ⚠️ Could not expand sets section, continuing anyway...")
    
    # Select the set
    if not select_set_radio(driver, set_code):
        return None
    
    # Get all cards in the gallery
    cards = get_card_list_from_gallery(driver)
    
    if not cards:
        print(f"  ⚠️ No cards found for set {set_code}")
        return []
    
    # Scrape each card
    scraped_cards = []
    skipped_cards = 0
    for i, card in enumerate(cards, 1):
        card_code = card['code']
        
        # Skip if this card code already exists
        if card_code in existing_card_codes:
            skipped_cards += 1
            continue
        
        print(f"  🎴 Card {i}/{len(cards)}: {card_code}")
        
        # Navigate to card detail
        if navigate_to_card(driver, card_code):
            # Extract card data
            card_data = extract_card_data(driver, card_code, set_code)
            if card_data:
                card_data['booster'] = set_code
                card_data['boosterfull'] = set_name
                scraped_cards.append(card_data)
        
        time.sleep(0.5)  # Be respectful with requests
    
    print(f"  ✅ Scraped {len(scraped_cards)} new cards, skipped {skipped_cards} existing cards")
    return scraped_cards

def main():
    """Main scraper function"""
    print("🎮 Riftbound TCG Card Scraper")
    print(f"📍 Base URL: {BASE_URL}")
    
    # Setup Selenium driver
    driver = None
    try:
        driver = setup_selenium_driver()
        
        # Navigate to page first
        driver.get(BASE_URL)
        time.sleep(2)
        
        # Detect available sets from website
        print("\n📚 Detecting available sets from website...")
        available_sets = detect_available_sets(driver)
        
        if not available_sets:
            print("❌ No sets found on website!")
            return
        
        # Get card count for each set by selecting it
        print("\n📊 Getting card counts for each set...")
        for set_info in available_sets:
            set_code = set_info['code']
            set_name = set_info['name']
            
            # Select the set (filters are already open from detect_available_sets)
            if select_set_radio(driver, set_code):
                # Get cards and count them
                cards_list = get_card_list_from_gallery(driver)
                set_info['card_count'] = len(cards_list)
                print(f"  📊 {set_name} ({set_code}) has {len(cards_list)} cards")
            
            time.sleep(0.5)
        
        
        # Load existing database from GitHub (for available_sets metadata)
        db, filesha = github_service.load_json_file(FILE_PATH)
        
        # Update available sets in database with current detection
        db['available_sets'] = available_sets
        updated_content = json.dumps(db, indent=2, ensure_ascii=False)
        commit_message = "Update available sets with latest detection"
        try:
            github_service.update_file(FILE_PATH, updated_content, commit_message, filesha)
            print(f"✅ Updated available sets on GitHub")
            # Reload file SHA after first update
            db, filesha = github_service.load_json_file(FILE_PATH)
        except Exception as e:
            print(f"⚠️ Failed to update available sets: {str(e)}")
            # Continue anyway
        
        # Determine which sets need scraping
        print("\n🔍 Checking which sets need scraping...")
        sets_to_scrape = get_sets_to_scrape(available_sets)
        
        if not sets_to_scrape:
            print("✅ All sets are up to date!")
            return
        
        print(f"\n🎯 Found {len(sets_to_scrape)} set(s) to scrape")
        
        # Scrape each set that needs updating
        all_scraped_cards = []
        for set_info in sets_to_scrape:
            set_code = set_info['code']
            set_name = set_info['name']
            reason = set_info.get('reason')
            
            # If card count mismatch, only scrape missing cards
            if reason == 'card_count_mismatch':
                print(f"\n🔄 Scraping missing cards for {set_name} ({set_code})...")
                existing_cards = set_info.get('existing_cards', [])
                
                # Scrape all cards for this set, passing existing cards to skip them
                new_cards = scrape_set(driver, set_code, set_name, existing_cards=existing_cards)
                
                if new_cards:
                    print(f"  ✨ Found {len(new_cards)} new cards")
                    all_scraped_cards.extend(new_cards)
                else:
                    print(f"  ℹ️ No new cards found")
            else:
                # Brand new set, scrape all cards
                cards = scrape_set(driver, set_code, set_name, existing_cards=None)
                
                if cards:
                    all_scraped_cards.extend(cards)
        
        # Display summary
        print(f"\n🎯 SCRAPING COMPLETE")
        print(f"📊 Total cards scraped: {len(all_scraped_cards)}")
        print(f"📦 From {len(sets_to_scrape)} set(s)")
        
        # Upload to MongoDB if environment variable is set
        collection_value = os.getenv("C_RIFTBOUND")
        if collection_value and all_scraped_cards:
            print(f"\n📤 Uploading to MongoDB...")
            mongo_service.upload_data(
                data=all_scraped_cards,
                collection_name=collection_value,
                backup_before_upload=True
            )
            print(f"✅ Uploaded {len(all_scraped_cards)} cards to MongoDB")
        else:
            if not collection_value:
                print("⚠️ C_RIFTBOUND environment variable not set, skipping MongoDB upload")
            else:
                print("⚠️ No cards to upload")
        
        # Display sample data
        if all_scraped_cards:
            print(f"\n📋 Sample card data:")
            sample = all_scraped_cards[0]
            for key, value in list(sample.items())[:8]:
                print(f"   {key}: {value}")
            if len(sample) > 8:
                print(f"   ... and {len(sample) - 8} more fields")
    
    finally:
        if driver:
            driver.quit()
            print("\n🔐 Browser closed")

if __name__ == "__main__":
    main()
