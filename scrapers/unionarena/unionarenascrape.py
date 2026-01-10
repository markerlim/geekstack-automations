import requests
import re
from bs4 import BeautifulSoup
import os
import sys
from selenium.webdriver.common.by import By

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from scrapers.unionarena.uamapping import CATEGORY_MAP, COLOR_MAP, TRIGGER_STATE_MAP,TRIGGER_MAP, UATAG_MAP
from service.github_service import GitHubService
from service.selenium_service import SeleniumService
from service.mongo_service import MongoService
from service.api_service import ApiService
from service.openrouter_service import OpenRouterService
from service.googlecloudservice import upload_image_to_gcs
from service.translationservice import translate_data

# Initialize Service Layer
github_service = GitHubService()
selenium = SeleniumService(headless=True, window_size="1920,1080", timeout=10)
mongo_service = MongoService()
openrouter_service = OpenRouterService()
api_service = ApiService("https://www.unionarena-tcg.com")

# Variables
FILE_PATH = "unionarenadb/series.json"
C_UNIONARENA = os.getenv('C_UNIONARENA')
try:
    ANIME_MAP, FILE_SHA = github_service.load_json_file(FILE_PATH)
    print(f"✅ ANIME_MAP loaded successfully, type: {type(ANIME_MAP)}, keys count: {len(ANIME_MAP) if ANIME_MAP else 0}")
except Exception as e:
    print(f"❌ Error loading ANIME_MAP: {e}")
    ANIME_MAP = {}

def allocate_alt_suffix(processedCardUid, cardId, booster, card_no, alt_allocation_map):
    """
    Allocate appropriate ALT suffix for UAPR cards to avoid duplicates
    
    Args:
        processedCardUid: Current processed card UID
        cardId: Base card ID (without ALT suffix)
        booster: Booster type
        alt_allocation_map: Dictionary tracking ALT allocations in current run
    
    Returns:
        Updated processedCardUid with appropriate ALT suffix
    """
    # Only process UAPR cards that don't already have ALT suffix
    if booster != "UAPR" or "_ALT" in processedCardUid:
        return processedCardUid
    
    # Skip promo cards (indicated by -P- in cardId) as they are unique
    if "-P-" in cardId:
        print(f"Skipping ALT allocation for promo card: {cardId}")
        return processedCardUid
    
    listofcarduid = mongo_service.get_unique_values_scoped(C_UNIONARENA,"cardId",cardId,"cardUid")\

    if listofcarduid:
        alt_variants = [uid for uid in listofcarduid if "_ALT" in uid]
        alt_count = len(alt_variants)
        print(f"Found {alt_count} ALT variants for cardId: {cardId}: {alt_variants}")
        
        if alt_count == 0:
            # No ALT variants exist in DB, check current run allocation
            if cardId in alt_allocation_map:
                # Already allocated ALT in this run, increment
                next_alt_num = alt_allocation_map[cardId] + 1
                processedCardUid = f"{processedCardUid}_ALT{next_alt_num}"
                alt_allocation_map[cardId] = next_alt_num
                print(f"Auto-allocated _ALT{next_alt_num} suffix for UAPR card (run allocation): {processedCardUid}")
            else:
                # First ALT allocation for this cardId in this run
                processedCardUid = f"{processedCardUid}_ALT"
                alt_allocation_map[cardId] = 1
                print(f"Auto-allocated _ALT suffix for UAPR card: {processedCardUid}")
        else:
            # ALT variants exist in DB, find highest ALT number and increment
            max_alt_num = 0
            for uid in alt_variants:
                # Extract number from _ALT patterns like _ALT, _ALT2, _ALT3, etc.
                if "_ALT" in uid:
                    alt_part = uid.split("_ALT")[1]
                    if alt_part == "":  # _ALT with no number
                        max_alt_num = max(max_alt_num, 1)
                    elif alt_part.isdigit():  # _ALT2, _ALT3, etc.
                        max_alt_num = max(max_alt_num, int(alt_part))
            
            # Check current run allocations for this cardId
            if cardId in alt_allocation_map:
                max_alt_num = max(max_alt_num, alt_allocation_map[cardId])
            
            next_alt_num = max_alt_num + 1
            processedCardUid = f"{processedCardUid}_ALT{next_alt_num}"
            alt_allocation_map[cardId] = next_alt_num
            print(f"Auto-allocated _ALT{next_alt_num} suffix for UAPR card: {processedCardUid}")
    else:
        print(f"No existing cards found for cardId: {cardId}")
        # If this is the first card with this cardId and booster is UAPR, add _ALT suffix
        if cardId in alt_allocation_map:
            # Already allocated ALT in this run, increment
            next_alt_num = alt_allocation_map[cardId] + 1
            processedCardUid = f"{processedCardUid}_ALT{next_alt_num}"
            alt_allocation_map[cardId] = next_alt_num
            print(f"Auto-allocated _ALT{next_alt_num} suffix for first UAPR card (run allocation): {processedCardUid}")
        else:
            # First ALT allocation for this cardId in this run
            processedCardUid = f"{processedCardUid}_ALT"
            alt_allocation_map[cardId] = 1
            print(f"Auto-allocated _ALT suffix for first UAPR card: {processedCardUid}")
    
    return processedCardUid

def scrape_unionarena_cards(series_value):
    """
    Scrape Union Arena cards for a specific series
    
    Args:
        series_value: The series value to scrape cards for
    """
    print(f"Starting scrape for series: {series_value}")
    
    # Debug: Check ANIME_MAP and mapping
    print(f"ANIME_MAP type: {type(ANIME_MAP)}")
    print(f"ANIME_MAP keys available: {list(ANIME_MAP.keys()) if ANIME_MAP else 'None'}")
    print(f"Looking for series_value: {series_value}")
    anime = ANIME_MAP.get(series_value, series_value) if ANIME_MAP else series_value
    print(f"Mapped anime value: {anime}")
    
    if not anime:
        print("Error: anime value is None, using series_value as fallback")
        anime = series_value
    
    card_objects = []  # Store card objects for JSON
    card_numbers_with_AP = navigate_to_selected_cardlist(series_value)
    card_numbers = clean_out_AP(card_numbers_with_AP)
    
    # Debug MongoDB call parameters
    print(f"MongoDB query params: collection={C_UNIONARENA}, field=anime, value={anime}, target_field=cardUid")
    
    # Get existing cards with null check
    existing_cards = mongo_service.get_unique_values_scoped(C_UNIONARENA, "anime", anime, "cardUid")
    if existing_cards is None:
        print("Warning: get_unique_values_scoped returned None, using empty set")
        listofcards = set()
    else:
        listofcards = set(existing_cards)
    if not card_numbers:
        print(f"No new cards found for series: {series_value}")
        return 0

    successful_scrapes = 0
    
    # Track ALT allocations within this run to avoid duplicates
    alt_allocation_map = {}  # cardId -> highest_alt_num_allocated
    
    for card_no in card_numbers:
        booster, cardUid = card_no.split('/') if '/' in card_no else (card_no, card_no)
        animeCode = cardUid.split('-')[0] if '-' in cardUid else cardUid
        cardId = cardUid.split('_')[0] if '_' in cardUid else cardUid

        if '_p1' in cardUid:
            processedCardUid = cardUid.replace('_p1', '_ALT')
        elif '_p' in cardUid:
            processedCardUid = re.sub(r'_p(\d+)', r'_ALT\1', cardUid)
        else:
            processedCardUid = cardUid

        listofcardcodes = mongo_service.get_unique_values_scoped(C_UNIONARENA,"cardId",cardId,"cardCode")

        # Skip card by CARDUID
        if listofcards.__contains__(processedCardUid):
            print(f"Skipping existing card: {processedCardUid}")
            continue

        # Skip card by CARDCODE
        if listofcardcodes.__contains__(card_no):
            print(f"Card code {card_no} already exists in DB for cardId: {cardId}, skipping ALT allocation")
            print(f"Skipping existing card: {processedCardUid}")
            continue

        # For UAPR cards, allocate ALT suffix first, then check if it exists
        if booster == "UAPR":
            processedCardUid = allocate_alt_suffix(processedCardUid, cardId, booster, card_no, alt_allocation_map)
        
        try:
            response = api_service.get(f"/jp/cardlist/detail_iframe.php?card_no={card_no}")
            
            if response['status'] == 200:
                soup = BeautifulSoup(response['data'], "html.parser")
                
                # Extract card name
                try:
                    cardname_element = soup.find('h2', class_="cardNameCol")
                    if cardname_element:
                        cardname = cardname_element.get_text(strip=True)
                    else:
                        cardname = ""
                except AttributeError:
                    cardname = ""
                
                # Extract energy cost and color
                try:
                    energycost_element = soup.find('dl', class_="needEnergyData").find('img')
                    if energycost_element:
                        energycost_alt = energycost_element['alt']  # e.g. "赤2", "青1", "黄-"

                        # Color mapping from Japanese to English
                        color_map = COLOR_MAP

                        # Extract color
                        color_char = energycost_alt[0]
                        color = color_map.get(color_char, "")

                        # Extract energy cost number
                        energycost = energycost_alt[1:]
                        
                    else:
                        energycost = "-"
                        color = "-"
                except AttributeError:
                    energycost = "-"
                    color = ""

                # Extract other card data with error handling
                try:
                    apcost = soup.find('dl', class_="apData").find('dd', class_="cardDataContents").text.strip()
                except AttributeError:
                    apcost = "-"
                
                try:
                    category = soup.find('dl', class_="categoryData").find('dd', class_="cardDataContents").text.strip()
                except AttributeError:
                    category = "-"
                
                try:
                    bpcost = soup.find('dl', class_="bpData").find('dd', class_="cardDataContents").text.strip()
                except AttributeError:
                    bpcost = "-"
                
                try:
                    traits_element = soup.find('dl', class_="attributeData")
                    if traits_element:
                        traits_dd = traits_element.find('dd', class_="cardDataContents")
                        if traits_dd:
                            traits = traits_dd.text.strip()
                            if not traits:  # If empty string
                                traits = "-"
                        else:
                            traits = "-"
                    else:
                        traits = "-"
                except AttributeError:
                    traits = "-"
                
                try:
                    rarity = soup.find('div', class_="cardNumCol").find('span', class_="rareData").text.strip()
                except AttributeError:
                    rarity = "-"

                try:
                    effects_dl = soup.find('dl', class_="effectData")
                    if effects_dl:
                        effects_element = effects_dl.find('dd', class_="cardDataContents")
                        if effects_element:
                            # Get all content including text and images
                            effect_parts = []
                            
                            # Use contents to get all child nodes including text nodes
                            for child in effects_element.contents:
                                if hasattr(child, 'name') and child.name:
                                    if child.name == 'img':
                                        # Handle image tags - map Japanese alt text to English tags
                                        alt_text = child.get('alt', '')
                                        jp_to_eng_map = UATAG_MAP
                                        if alt_text in jp_to_eng_map:
                                            effect_parts.append(jp_to_eng_map[alt_text])
                                        elif alt_text:
                                            effect_parts.append(f"[{alt_text}]")  # Fallback: wrap in brackets
                                    elif child.name == 'br':
                                        # Handle line breaks
                                        effect_parts.append('\\n')
                                else:
                                    # Handle text nodes (including whitespace)
                                    text = str(child).strip()
                                    if text:
                                        effect_parts.append(text)
                            
                            # Join all parts preserving original order
                            effects_jp = ''.join(effect_parts) if effect_parts else "-"

                            # Replace Japanese angle brackets with standard ones
                            if effects_jp != "-":
                                effects_jp = effects_jp.replace('〉', '>').replace('〈', '<')
                                
                                # Clean up raid text patterns - split by lines and process each
                                lines = effects_jp.split('\\n')
                                processed_lines = []
                                
                                for line in lines:
                                    if line.startswith('[Raid]'):
                                        # Extract content after [Raid] to avoid extracting "Raid" itself
                                        after_raid = line[line.find('[Raid]') + len('[Raid]'):].strip()
                                        
                                        # Extract bracketed content [xxx] and angled content <xxx> from after [Raid]
                                        brackets = re.findall(r'\[([^\]]+)\]', after_raid)
                                        angles = re.findall(r'<([^>]+)>', after_raid)
                                        
                                        # Build new raid line
                                        raid_parts = ['[Raid]']
                                        
                                        # Add all trait brackets found after [Raid]
                                        for bracket in brackets:
                                            raid_parts.append(f'[{bracket}]')
                                        
                                        # Add angled content
                                        for angle in angles:
                                            raid_parts.append(f'<{angle}>')
                                        
                                        # Join parts with space
                                        processed_line = ' '.join(raid_parts)
                                        processed_lines.append(processed_line)
                                        print(f"Raid line processed: '{line}' -> '{processed_line}'")
                                    else:
                                        processed_lines.append(line)
                                
                                effects_jp = '\\n'.join(processed_lines)


                            if effects_jp is None or effects_jp == "":
                                effects_jp = "-"
                        else:
                            effects_jp = "-"
                    else:
                        effects_jp = "-"
                except AttributeError:
                    effects_jp = "-"

                try:
                    trigger = soup.find('dl', class_="triggerData").find('dd', class_="cardDataContents").text.strip()
                except AttributeError:
                    trigger = "-"

                # Extract card image URL
                card_image_url = ""
                try:
                    card_img_dl = soup.find('dl', class_="cardImgTitleCol")
                    if card_img_dl:
                        img_dd = card_img_dl.find('dd', class_="cardDataImgCol")
                        if img_dd:
                            img_element = img_dd.find('img')
                            if img_element and img_element.get('src'):
                                # Extract the src and build the full URL
                                src_path = img_element.get('src')
                                if src_path.startswith('/jp/images/'):
                                    # Remove version parameter if present (e.g., ?v7)
                                    clean_path = src_path.split('?')[0]
                                    card_image_url = f"https://www.unionarena-tcg.com{clean_path}"
                                else:
                                    card_image_url = src_path  # Use as-is if not a relative path
                except AttributeError:
                    card_image_url = ""

                placeholder_url = "https://www.unionarena-tcg.com/jp/images/cardlist/card/comingsoon.png"
                if card_image_url == placeholder_url:
                    print(f"Skipping card with placeholder image: {processedCardUid}")
                    continue

                # Extract energy generate
                energygenerate = "-"

                try:
                    image2 = soup.find('dl', class_="generatedEnergyData").find('img')
                    if image2 and image2.get('alt'):
                        alt = image2['alt']  # e.g. "青青", "青"
                        energygenerate = len(alt)
                except AttributeError:
                    pass


                # Skip if this appears to be an empty/invalid card
                if apcost == "-" and category == "-" and bpcost == "-":
                    continue
                
                # Map States
                triggerState = TRIGGER_STATE_MAP.get(trigger, "-")
                triggerEN = TRIGGER_MAP.get(triggerState, "-")
                # If triggerState begins with "color", change it to just "color"
                if isinstance(triggerState, str) and triggerState.startswith("color"):
                    triggerState = "color"
                mappedCategory = CATEGORY_MAP.get(category, "-")

                # Handle Image upload
                # urlimage = upload_image_to_gcs(card_image_url,processedCardUid,"UD/")
                urlimage = card_image_url  # For now, just use the scraped URL
                # Create card object structure
                card_object = {
                    "anime": anime,
                    "animeCode": animeCode.lower(),  # Need to derive this
                    "apcost": int(apcost) if apcost != "-" and apcost.isdigit() else 0,
                    "banRatio": 4,  # Leave blank
                    "basicpower": bpcost if bpcost != "-" else "",
                    "booster": booster,  # Need to derive this
                    "cardId": cardId,
                    "cardUid": processedCardUid,
                    "cardName": cardname,
                    "category": mappedCategory.lower(),
                    "color": color,  # Extracted Japanese color character
                    "effect": effects_jp,
                    "energycost": int(energycost) if energycost != "-" and energycost.isdigit() else 0,
                    "energygen": str(energygenerate) if energygenerate != "none" else "",
                    "image": f"/UD/{processedCardUid}.webp",  # Need to build image path
                    "rarity": "ALT" if rarity != "-" and "★" in rarity else (rarity if rarity != "-" else ""),
                    "traits": traits,
                    "trigger": triggerEN,
                    "triggerState": triggerState,
                    "urlimage":urlimage ,  # Scraped card image URL
                    "rarityAct": rarity,
                    "cardcode": card_no,
                }
                
                print(f"Scraped card {card_no}: {category}")
                
                # Store card object for JSON export
                card_objects.append(card_object)
                
                successful_scrapes += 1

        except requests.RequestException as e:
            print(f"Error fetching card {card_no}: {e}")
            continue
        except AttributeError as e:
            print(f"AttributeError processing card {card_no}: {e} - Missing HTML element")
            continue
        except KeyError as e:
            print(f"KeyError processing card {card_no}: {e} - Missing data key")
            continue
        except ValueError as e:
            print(f"ValueError processing card {card_no}: {e} - Data conversion error")
            continue
        except Exception as e:
            import traceback
            print(f"Unexpected error processing card {card_no}: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            continue

    #json_data = translate_data(card_objects,fields_to_translate=["cardName","effect","traits"], src_lang="ja", dest_lang="en", keep_original=False)
    translation_result = openrouter_service.translate_fields(card_objects,fields_to_translate=["cardName","effect","traits"], source_lang="ja", target_lang="en", keep_original=False)

    if translation_result['success']:
        json_data = translation_result['translated_data']
        print(f"✅ Translation successful: {len(json_data)} objects translated")
    else:
        print(f"❌ Translation failed: {translation_result.get('error', 'Unknown error')}, falling back to translation service")
        json_data = translate_data(card_objects,fields_to_translate=["cardName","effect","traits"], src_lang="ja", dest_lang="en", keep_original=False)
    
    if C_UNIONARENA:
        try:
            mongo_service.upload_data(
                data=json_data,
                collection_name=C_UNIONARENA,
                backup_before_upload=True
            )
        except Exception as e:
            print(f"❌ MongoDB operation failed: {str(e)}")
    else:
        print("⚠️ MongoDB collection name not found in environment variables")    
    
    return successful_scrapes

def navigate_to_selected_cardlist(series_value):
    """ Navigate to Union Arena card list for a specific series using Selenium """
    all_card_numbers = []
    page_number = 1
    
    try:
        # Navigate to page
        selenium.navigate_to("https://www.unionarena-tcg.com/jp/cardlist/")
        selenium.sleep(3)  # Wait for page to load
        
        # Handle cookies if present
        try:
            selenium.click_element(By.CSS_SELECTOR, 'button[id="onetrust-reject-all-handler"]', timeout=5)
            selenium.sleep(2)  # Wait for overlay to disappear
        except:
            print("No cookie banner found, continuing...")
        
        # Open series dropdown
        selenium.click_element(By.CLASS_NAME,'selModalButton')
        selenium.sleep(2)  # Wait for dropdown to open
        
        # Select series
        selenium.click_element(By.CSS_SELECTOR, f'li[data-value="{series_value}"]')
        selenium.sleep(1)  # Wait for selection
        
        # Submit form
        selenium.click_element(By.CLASS_NAME,'submitBtn')
        selenium.sleep(5)  # Wait for results to load
        

        print(f"Scraping page {page_number}")
            
            # Get page content and parse card numbers
        pagecontent = selenium.get_page_source()
            
        if pagecontent:
            soup = BeautifulSoup(pagecontent, 'html.parser')
                
            # Find all card links on current page
            card_links = soup.find_all('a', class_='modalCardDataOpen')
                
            current_page_cards = []
            for link in card_links:
                href = link.get('href', '')
                if 'card_no=' in href:
                        # Extract card number from href
                    card_no = href.split('card_no=')[1]
                    current_page_cards.append(card_no)
                    print(f"Found card: {card_no}")
                
                
            all_card_numbers.extend(current_page_cards)
            print(f"Page {page_number}: {len(current_page_cards)} cards")
                

        else:
            print("No page content retrieved")
        
        print(f"Total cards found across {page_number} pages: {len(all_card_numbers)}")
        return all_card_numbers
        
    except Exception as e:
        print(f"Error fetching card list: {e}")
        return all_card_numbers

def clean_out_AP(card_numbers):    
    """ Clean out all documents in the unionarena_cards collection """
    try:
        cleaned_cards = []
        for each in card_numbers:
            if "-AP" not in each and "_AP" not in each:
                cleaned_cards.append(each)
            else:
                print(f"Removed AP card: {each}")
        
        print(f"Cleaned {len(card_numbers) - len(cleaned_cards)} AP cards")
        return cleaned_cards
    except Exception as e:
        print(f"Error cleaning out collection: {e}")
        return card_numbers
