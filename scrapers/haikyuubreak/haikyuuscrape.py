import os
import sys
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime
from pymongo import MongoClient
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
import time
import certifi

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.selenium_service import SeleniumService
from service.mongo_service import MongoService
from service.googlecloudservice import upload_image_to_gcs
from service.openrouter_service import OpenRouterService
from haikyuu_mappings import (AFFILIATION_MAPPING,GRADE_MAPPING)
from service.mappings.haikyuu_mappings import process_icons_in_text

load_dotenv()

mongo_service = MongoService()
COLLECTION = os.getenv("C_HAIKYUU")  # Use booster-specific collection from env
BASE_URL = "https://www.takaratomy.co.jp/products/haikyuvobacabreak"
CARDLIST_URL = f"{BASE_URL}/cardlist/"

def extract_text_with_icons(div_element):
    """
    Extract text from a div while preserving image icons as [icon_name] placeholders.
    Images are converted from paths like /products/.../icon_feint_04.png to [icon_feint_04]
    
    The div uses 'white-space: pre-line;' CSS, so newlines and formatting are intentional
    and should be preserved as much as possible.
    
    Args:
        div_element: BeautifulSoup div element containing text and img tags
    
    Returns:
        String with text and icon representations, preserving line breaks
    """
    if not div_element:
        return '-'
    
    parts = []
    
    # Iterate through all children (both text nodes and tags)
    for element in div_element.children:
        if isinstance(element, str):
            # Text node - preserve as-is but clean up excessive whitespace
            text = element
            # Don't completely strip - just clean up tabs and reduce multiple spaces
            text = text.replace('\t', ' ')
            parts.append(text)
        elif element.name == 'img':
            # Image tag - convert to icon placeholder
            src = element.get('src', '')
            if src:
                icon_name = src.split('/')[-1].replace('.png', '')
                parts.append(f'[{icon_name}]')
        else:
            # Other elements - get text recursively
            text = element.get_text()
            if text:
                parts.append(text)
    
    # Join all parts and do minimal cleanup
    result = ''.join(parts)
    
    # Clean up only excessive whitespace while preserving newlines
    # Remove leading/trailing whitespace from the whole string
    result = result.strip()
    
    # Clean up lines: remove leading/trailing spaces from each line but keep the line structure
    lines = result.split('\n')
    cleaned_lines = [line.rstrip() for line in lines]
    result = '\n'.join(cleaned_lines)
    
    return result if result else '-'


def parse_affiliation_with_year(affiliation_text):
    """
    Parse affiliation text with years using the mapping.
    Example: "烏野·1年,音駒·3年" → ["Karasuno", "1st Year", "Nekoma", "3rd Year"]
    
    Args:
        affiliation_text: Raw affiliation string from card detail page
    
    Returns:
        List of mapped school names and years, or None if empty
    """
    if not affiliation_text or affiliation_text.strip() == '-':
        return None
    
    result = []
    # Split by comma to get individual school·year combinations
    combinations = affiliation_text.split(',')
    
    for combo in combinations:
        combo = combo.strip()
        if not combo:
            continue
        
        # Split by · (middle dot) to separate school and year
        parts = combo.split('·')
        
        # Map the school using AFFILIATION_MAPPING
        school = parts[0].strip() if parts else None
        mapped_school = AFFILIATION_MAPPING.get(school) if school else None
        
        if mapped_school:
            result.append(mapped_school)
        
        # Map the year using GRADE_MAPPING if present
        if len(parts) > 1:
            year = parts[1].strip() if parts[1] else None
            mapped_year = GRADE_MAPPING.get(year) if year else None
            if mapped_year:
                result.append(mapped_year)
    
    return result if result else None

def scrape_cards_for_booster(booster_code):
    """
    Scrape card information for a specific booster from the cardlist page
    Handles pagination by clicking NEXT button
    
    Args:
        booster_code: The booster code to select (e.g., "HV-P01", "HV-D03")
    """
    print(f"\n🎯 Scraping cards for booster: {booster_code}")
    
    # Create fresh Selenium instance for this booster
    selenium = SeleniumService(headless=False, window_size="1920,1080", timeout=10)
    
    try:
        
        # Navigate to cardlist page
        print(f"  📄 Navigating to: {CARDLIST_URL}")
        selenium.driver.get(CARDLIST_URL)
        
        # Wait for page to load and find the select dropdown
        wait = WebDriverWait(selenium.driver, 10)
        select_element = wait.until(EC.presence_of_element_located((By.TAG_NAME, "select")))
        
        # Select the booster from dropdown
        print(f"  ✓ Found dropdown, selecting: {booster_code}")
        select = Select(select_element)
        select.select_by_value(booster_code)
        
        # Click the search button to execute the search
        print(f"  🔍 Clicking search button...")
        search_button = wait.until(EC.element_to_be_clickable((By.ID, "button_search")))
        search_button.click()
        
        # Wait for results to load
        time.sleep(3)
        
        # Get total page count
        page_count = 1
        try:
            pagenavi = selenium.driver.find_element(By.CLASS_NAME, "pagenavi")
            
            # Get all numbered divs in num_wrap
            num_divs = pagenavi.find_elements(By.CLASS_NAME, "num")
            
            # Extract the last actual number (ignore "..." and disabled)
            page_numbers = []
            for div in num_divs:
                text = div.text.strip()
                # Skip "..." and empty text
                if text and text != "...":
                    # Try to parse as integer
                    try:
                        page_numbers.append(int(text))
                    except ValueError:
                        pass
            
            if page_numbers:
                page_count = max(page_numbers)
                print(f"  📖 Total pages: {page_count}")
            else:
                print(f"  ⚠️ Could not determine page count, assuming 1 page")
                    
        except Exception as e:
            print(f"  ⚠️ Could not determine page count, assuming 1 page: {e}")
        
        all_cards = []
        current_page = 1
        
        while current_page <= page_count:
            print(f"  📄 Scraping page {current_page}/{page_count}...")
            
            # Wait for cardlist to load
            time.sleep(2)
            try:
                wait.until(EC.presence_of_element_located((By.CLASS_NAME, "cardlist")))
            except:
                print(f"    ⚠️ Timeout waiting for cardlist")
            
            page_source = selenium.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Find card list container
            cardlist = soup.find('div', class_='cardlist')
            
            if not cardlist:
                print(f"    ⚠️ No cardlist found on page {current_page}")
            else:
                # Find all card divs
                card_divs = cardlist.find_all('div', class_='card')
                print(f"    📊 Found {len(card_divs)} cards on this page")
                
                cards = []  # Initialize cards list for this page
                
                for card_div in card_divs:
                    try:
                        # Find the link and image
                        link = card_div.find('a', class_='placeholder')
                        img = card_div.find('img')
                        
                        if not link or not img:
                            continue
                        
                        # Extract from href: ./card.html?no=HV-P01-001&voba=秘
                        href = link.get('href', '')
                        card_id = ""
                        voba = ""
                        
                        if '?no=' in href:
                            params = href.split('?')[1]
                            for param in params.split('&'):
                                if param.startswith('no='):
                                    card_id = param.split('=')[1]
                                elif param.startswith('voba='):
                                    voba = param.split('=')[1]
                        
                        # Extract from img
                        img_src = img.get('src', '')
                        img_alt = img.get('alt', '')
                        
                        # Parse alt text: "HV-P01-001 日向 翔陽"
                        alt_parts = img_alt.split(' ', 1)
                        card_number = alt_parts[0] if alt_parts else ""
                        card_name = alt_parts[1] if len(alt_parts) > 1 else ""
                        
                        # Convert relative image path to absolute
                        if img_src.startswith('./'):
                            img_src = f"{BASE_URL}/cardlist/{img_src[2:]}"
                        elif img_src.startswith('/'):
                            img_src = f"https://www.takaratomy.co.jp{img_src}"
                        cardUid = f"{card_number}-{voba}" if voba else card_number
                        card_data = {
                            "booster": booster_code,
                            "cardId": card_id,
                            "cardUid": cardUid,
                            "cardNameJP": card_name,
                            "voba": voba,
                            "urlimage": upload_image_to_gcs(img_src, cardUid, "HVCG/"),
                            "detailLink": href,
                            "timestamp": datetime.now(),
                        }
                        
                        cards.append(card_data)
                        
                    except Exception as e:
                        print(f"      ⚠️ Error parsing card: {e}")
                        continue
                
                all_cards.extend(cards)
            
            # Go to next page if available
            if current_page < page_count:
                try:
                    print(f"  ➡️ Navigating to next page...")
                    next_button = selenium.driver.find_element(By.CLASS_NAME, "next")
                    
                    # Check if next button is disabled
                    if "disabled" in next_button.get_attribute("class"):
                        print(f"  ⏹️ Next button is disabled, stopping pagination")
                        break
                    
                    # Click next button
                    next_button.click()
                    
                    # Wait for page to transition and new cardlist to appear
                    time.sleep(3)
                    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "cardlist")))
                    
                    current_page += 1
                    
                except Exception as e:
                    print(f"  ⚠️ Error clicking next button or waiting for next page: {e}")
                    break
            else:
                break
        
        print(f"  ✅ Successfully scraped {len(all_cards)} total cards from all pages")
        
        # Fetch details for each card before returning
        if all_cards:
            all_cards = update_card_with_details(selenium, all_cards)
        
        return all_cards
        
    except Exception as e:
        print(f"  ❌ Error scraping cards for {booster_code}: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    finally:
        # Close Selenium instance for this booster
        try:
            selenium.close()
        except:
            pass


def scrape_card_details(selenium, detail_url, card_id):
    """
    Scrape detailed information from a card's detail page using Selenium
    (Page is client-side rendered with Vue.js, so we need Selenium)
    
    Args:
        selenium: SeleniumService instance
        detail_url: The detail page URL
        card_id: The card ID for logging
    
    Returns:
        Dictionary with card details
    """
    try:        
        # Use Selenium to load the page and let JavaScript render
        selenium.driver.get(detail_url)
        
        # Wait for the content to load
        import time
        time.sleep(2)
        
        # Get the rendered HTML
        page_source = selenium.driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        
        # Find main card section
        main_sec = soup.find('div', class_='main_sec_inner_card')
        if not main_sec:
            print(f"      ⚠️ Could not find main_sec_inner_card for {card_id}")
            return {}
        
        details = {}
        
        # Extract attribute information
        attribute_div = main_sec.find('div', class_='attribute')
        if attribute_div:
            for item in attribute_div.find_all('div'):
                h3 = item.find('h3')
                if h3:
                    label = h3.get_text(strip=True)
                    # Get the value (text after h3)
                    value = item.get_text(strip=True).replace(label, '').strip()
                    if label == 'カテゴリ':
                        details['category'] = value
                    elif label == 'バボリティ':
                        details['voba_detail'] = value
                    elif label == '所属':
                        # Extract text content, ignoring ruby tags
                        affiliation_text = ''
                        for text in item.stripped_strings:
                            if text != label:
                                affiliation_text += text
                        # Parse affiliation with year mapping
                        details['affiliation'] = parse_affiliation_with_year(affiliation_text.strip())
                        details['affiliationJP'] = affiliation_text.strip()  # Keep raw text for reference
                    elif label == 'ポジション':
                        # Extract text content, ignoring ruby tags
                        position_text = ''
                        for text in item.stripped_strings:
                            if text != label:
                                position_text += text
                        details['position'] = position_text.strip()
        else:
            print(f"      ⚠️ No attribute section found")
        
        # Extract skills and notes
        txt_div = main_sec.find('div', class_='txt')
        if txt_div:
            for item in txt_div.find_all('div'):
                h3 = item.find('h3')
                if h3:
                    label = h3.get_text(strip=True)
                    # Get value from the next div, preserving icon representations
                    value_div = item.find('div', style='white-space: pre-line;')
                    value = extract_text_with_icons(value_div)
                    if label == 'スキル':
                        details['effectsJP'] = value
                    elif label == '注釈':
                        details['notesJP'] = value
        else:
            print(f"      ⚠️ No txt section found")
        
        # Extract status (serve, block, receive, toss, attack)
        status_div = main_sec.find('div', class_='status')
        if status_div:
            for item in status_div.find_all('div'):
                h3 = item.find('h3')
                if h3:
                    label = h3.get_text(strip=True)
                    value = item.get_text(strip=True).replace(label, '').strip()
                    if label == 'サーブ':
                        details['serve'] = value
                    elif label == 'ブロック':
                        details['block'] = value
                    elif label == 'レシーブ':
                        details['receive'] = value
                    elif label == 'トス':
                        details['toss'] = value
                    elif label == 'アタック':
                        details['attack'] = value
        else:
            print(f"      ⚠️ No status section found")
        
        # Extract recorded in (product)
        products_div = main_sec.find('div', class_='products')
        if products_div:
            for item in products_div.find_all('div'):
                h3 = item.find('h3')
                if h3:
                    if h3.get_text(strip=True) == '収録先':
                        details['recorded_in'] = item.get_text(strip=True).replace('収録先', '').strip()
        else:
            print(f"      ⚠️ No products section found")
        
        # Extract illustrator
        other_div = main_sec.find('div', class_='other')
        if other_div:
            for item in other_div.find_all('div'):
                h3 = item.find('h3')
                if h3:
                    label = h3.get_text(strip=True)
                    if label == 'illust:':
                        details['illustrator'] = item.get_text(strip=True).replace('illust:', '').strip()
        else:
            print(f"      ⚠️ No other section found")
        
        return details
        
    except Exception as e:
        print(f"      ❌ Error scraping card details for {card_id}: {e}")
        return {}

def update_card_with_details(selenium, cards_list):
    """
    Iterate through cards and fetch detailed information for each
    
    Args:
        selenium: SeleniumService instance
        cards_list: List of card dictionaries from initial scrape
    
    Returns:
        List of cards with detailed information added
    """
    print(f"\n📚 Fetching details for {len(cards_list)} cards...")
    
    for i, card in enumerate(cards_list, 1):
        try:
            # Fix the detail URL - remove ./ and build proper path
            detail_path = card['detailLink'].lstrip('./')
            detail_url = f"{BASE_URL}/cardlist/{detail_path}"
            
            if i % 10 == 0:
                print(f"  ⏳ Progress: {i}/{len(cards_list)}")
            
            # Scrape details
            card_details = scrape_card_details(selenium, detail_url, card['cardId'])
            
            # Merge details into card data
            card.update(card_details)
            
            # Small delay to avoid rate limiting
            import time
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  ⚠️ Error updating card {card['cardId']}: {e}")
            continue
    
    print(f"✅ Completed fetching details for all {len(cards_list)} cards")
    return cards_list


def preprocess_icons_in_cards(cards_data):
    """
    Process icon placeholders in card effects and notes fields.
    Converts [icon_xxx] to readable text like [Phase Name] or [Area Name].
    
    This should be done before saving to MongoDB to make the data more readable.
    
    Args:
        cards_data: List of card dictionaries
    
    Returns:
        List of cards with processed icons in effectsJP, notesJP, effects, and notes fields
    """
    for card in cards_data:
        # Process Japanese fields
        if 'effectsJP' in card and card['effectsJP']:
            card['effectsJP'] = process_icons_in_text(card['effectsJP'])
        
        if 'notesJP' in card and card['notesJP']:
            card['notesJP'] = process_icons_in_text(card['notesJP'])
        
        # Process English fields (if they exist after translation)
        if 'effects' in card and card['effects']:
            card['effects'] = process_icons_in_text(card['effects'])
        
        if 'notes' in card and card['notes']:
            card['notes'] = process_icons_in_text(card['notes'])
    
    return cards_data


def save_cards_to_mongodb(cards_data):
    """
    Save card data to MongoDB collection
    
    Args:
        cards_data: List of card dictionaries to insert
    """
    if not cards_data:
        print("⚠️ No cards to save")
        return False
    
    try:
        print(f"\n💾 Saving {len(cards_data)} cards to MongoDB...")
        
        # Get MongoDB collection directly
        mongo_uri = f"mongodb+srv://{os.getenv('MONGO_USER')}:{os.getenv('MONGO_PASSWORD')}@{os.getenv('MONGO_CLUSTER')}/{os.getenv('MONGO_DATABASE')}?retryWrites=true&w=majority"
        client = MongoClient(mongo_uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
        
        # Test connection
        client.admin.command('ping')
        print("✅ MongoDB connection successful")
        
        db = client[os.getenv('MONGO_DATABASE')]
        collection = db[COLLECTION]
        
        # Check for existing cardUids to prevent duplicates
        card_uids_to_insert = [card['cardUid'] for card in cards_data]
        existing_uids = set()
        
        if card_uids_to_insert:
            existing_records = collection.find(
                {'cardUid': {'$in': card_uids_to_insert}},
                {'cardUid': 1}
            )
            existing_uids = {record['cardUid'] for record in existing_records}
        
        # Filter out duplicates
        new_cards = [card for card in cards_data if card['cardUid'] not in existing_uids]
        
        if existing_uids:
            print(f"   ⚠️  Found {len(existing_uids)} existing card(s) with matching cardUid - skipping duplicates")
        
        # Insert only new cards
        if new_cards:
            result = collection.insert_many(new_cards)
            print(f"✅ Successfully inserted {len(result.inserted_ids)} new cards into MongoDB")
        else:
            print("⚠️  No new cards to insert (all cards already exist)")
        
        client.close()
        return True
        
    except Exception as e:
        print(f"❌ Error saving to MongoDB: {e}")
        import traceback
        traceback.print_exc()
        return False


def scrape_booster_list():
    """
    Get list of available boosters from MongoDB
    """
    print("📚 Fetching available boosters from MongoDB...")
    
    try:
        boosters = mongo_service.get_unique_values(COLLECTION, "booster")
        
        if not boosters:
            print("⚠️ No boosters found in MongoDB")
            return []
        
        print(f"✅ Found {len(boosters)} boosters: {boosters}")
        return boosters
        
    except Exception as e:
        print(f"❌ Error fetching boosters: {e}")
        return []


def start_scraping(booster_list=None):
    """
    Scrape cards for all boosters or specific booster list
    1. Scrape card list for each booster
    2. Fetch details for each card
    3. Upload images to GCS
    4. Translate card data
    5. Save to MongoDB
    
    Args:
        booster_list: Optional list of booster codes to scrape. If None, scrapes all available.
    """
    if booster_list is None:
        booster_list = scrape_booster_list()
    
    if not booster_list:
        print("❌ No boosters to scrape")
        return
    
    print(f"\n🚀 Starting card scrape for {len(booster_list)} boosters")
    
    try:
        all_cards = []
        
        for booster in booster_list:
            cards = scrape_cards_for_booster(booster)
            
            if cards:
                all_cards.extend(cards)
        
        # Translate card data if we have cards
        if all_cards:
            print(f"\n🌐 Translating {len(all_cards)} cards...")
            
            try:
                openrouter = OpenRouterService()
                
                # Translate card data using in-memory method
                translation_result = openrouter.translate_haikyuu(
                    data=all_cards,
                    fields_to_translate=[
                        ('cardNameJP', 'cardName'),
                        ('effectsJP', 'effects'),
                        ('notesJP', 'notes')
                    ],
                    batch_size=8
                )
                
                if translation_result['success']:
                    all_cards = translation_result['data']
                    print(f"✅ Translation completed")
                    print(f"   - Card names translated: {translation_result['cardnames_translated']}")
                    print(f"   - Effects translated: {translation_result['effects_translated']}")
                    print(f"   - Notes translated: {translation_result['notes_translated']}")
                else:
                    print(f"⚠️ Translation failed: {translation_result.get('error', 'Unknown error')}")
                    print(f"   Continuing with original Japanese text...")
            
            except Exception as e:
                print(f"⚠️ Translation service error: {e}")
                print(f"   Continuing with original Japanese text...")
        
        # Save all cards to MongoDB
        if all_cards:
            print(f"\n� Processing icons in card data...")
            all_cards = preprocess_icons_in_cards(all_cards)
            print(f"✅ Icon processing completed")
            
            print(f"\n Saving {len(all_cards)} cards to MongoDB...")
            save_cards_to_mongodb(all_cards)
            
    except KeyboardInterrupt:
        print("\n⏹️ Scraping interrupted by user")
    except Exception as e:
        print(f"\n❌ Error during scraping: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n✅ Scraping completed")