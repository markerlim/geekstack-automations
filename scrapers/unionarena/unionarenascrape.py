import requests
import re
from bs4 import BeautifulSoup
import os
import sys
import json
from selenium.webdriver.common.by import By

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from scrapers.unionarena.uamapping import CATEGORY_MAP, COLOR_MAP, TRIGGER_STATE_MAP, UATAG_MAP
from service.github_service import GitHubService
from service.selenium_service import SeleniumService
from service.mongo_service import MongoService
from service.api_service import ApiService
from service.translationservice import translate_data

# Initialize Service Layer
github_service = GitHubService()
selenium = SeleniumService(headless=True, window_size="1920,1080", timeout=10)
mongo_service = MongoService()
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

        if(listofcards.__contains__(processedCardUid)):
            print(f"Skipping existing card: {processedCardUid}")
            continue
        
        try:
            response = api_service.get(f"/jp/cardlist/detail_iframe.php?card_no={card_no}")
            
            if response['status'] == 200:
                soup = BeautifulSoup(response['data'], "html.parser")
                
                # Extract card name
                try:
                    cardname_element = soup.find('div', class_="cardNameCol")
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
                        energycost_alt = energycost_element['alt']
                        energycost = energycost_alt
                        
                        # Color mapping from Japanese to English
                        color_map = COLOR_MAP
                        
                        # Extract color from alt text (e.g., "黄-", "赤2", "青1")
                        color = ""
                        for char in energycost_alt:
                            if char in color_map:
                                color = color_map[char]
                                break
                    else:
                        energycost = "-"
                        color = ""
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
                    traits = soup.find('dl', class_="attributeData").find('dd', class_="cardDataContents").text.strip()
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

                # Extract energy generate
                energygenerate = "none"
                try:
                    image2 = soup.find('dl', class_="generatedEnergyData").find('img')
                    if image2:
                        energygenerate = image2['alt']
                except AttributeError:
                    pass

                # Skip if this appears to be an empty/invalid card
                if apcost == "-" and category == "-" and bpcost == "-":
                    continue
                
                # Map States
                triggerState = TRIGGER_STATE_MAP.get(trigger, "-")
                mappedCategory = CATEGORY_MAP.get(category, "-")
                # Create card object structure
                card_object = {
                    "anime": anime,
                    "animeCode": animeCode,  # Need to derive this
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
                    "energygen": energygenerate if energygenerate != "none" else "",
                    "image": "",  # Need to build image path
                    "rarity": "ALT" if rarity != "-" and "★" in rarity else (rarity if rarity != "-" else ""),
                    "traits": traits,
                    "trigger": trigger,
                    "triggerState": triggerState,
                    "urlimage": "",  # Need to build URL
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

    translate_data(card_objects,fields_to_translate=["effect"], src_lang="ja", dest_lang="en")
    # Save data to local JSON file for testing
    if card_objects:
        json_filename = f'test.json'
        local_json_path = os.path.join(os.path.dirname(__file__), json_filename)
        
        try:
            with open(local_json_path, 'w', encoding='utf-8') as json_file:
                json.dump(card_objects, json_file, ensure_ascii=False, indent=2)
            print(f"Successfully saved {len(card_objects)} card objects to {json_filename}")
        except Exception as e:
            print(f"Error saving JSON file: {e}")

        exit()
    # Also save all card numbers to series.json
    if card_numbers:
        try:
            # Load existing series.json
            existing_series, file_sha = github_service.load_json_file("unionarenadb/series.json")
            if existing_series is None:
                existing_series = []
            
            # Add new card numbers to the list
            all_card_numbers = list(set(existing_series + card_numbers))
            all_card_numbers.sort()
            
            # Update series.json
            updated_content = json.dumps(all_card_numbers, indent=4)
            commit_message = f"Add {len(card_numbers)} card links from series: {series_value}"
            
            success = github_service.update_file("unionarenadb/series.json", updated_content, commit_message, file_sha)
            if success:
                print(f"Successfully added {len(card_numbers)} card links to series.json")
            else:
                print("Failed to update series.json")
        except Exception as e:
            print(f"Error updating series.json: {e}")
    
    else:
        print(f"No cards found for series: {series_value}")
    
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
            if "-AP" not in each:
                cleaned_cards.append(each)
            else:
                print(f"Removed AP card: {each}")
        
        print(f"Cleaned {len(card_numbers) - len(cleaned_cards)} AP cards")
        return cleaned_cards
    except Exception as e:
        print(f"Error cleaning out collection: {e}")
        return card_numbers