import requests
from bs4 import BeautifulSoup
import time
import re
import json
import os
import sys
import base64
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from scrapers.duelmasters.dmwikiscraper import DuelMastersCardWikiScraper
from service.googlecloudservice import upload_image_to_gcs
from service.mongo_service import MongoService
from service.translationservice import translate_data
from service.github_service import GitHubService

# Initialize Service Layer
github_service = GitHubService()
mongo_service = MongoService()

def get_total_pages(driver, booster):
    url = f"https://dm.takaratomy.co.jp/card/?v=%7B%22suggest%22:%22on%22,%22keyword_type%22:%5B%22card_name%22,%22card_ruby%22,%22card_text%22%5D,%22culture_cond%22:%5B%22%E5%8D%98%E8%89%B2%22,%22%E5%A4%9A%E8%89%B2%22%5D,%22pagenum%22:%221%22,%22samename%22:%22show%22,%22products%22:%22{booster}%22,%22sort%22:%22release_new%22%7D"
    
    driver.get(url)
    time.sleep(3)

    try:
        pagination = driver.find_elements(By.CSS_SELECTOR, "div.wp-pagenavi a.page")
        page_numbers = []
        
        for p in pagination:
            try:
                page_num = int(p.text)
                page_numbers.append(page_num)
            except ValueError:
                continue
        
        current_page = driver.find_element(By.CSS_SELECTOR, "div.wp-pagenavi span.current")
        if current_page:
            try:
                page_numbers.append(int(current_page.text))
            except ValueError:
                pass
        
        if page_numbers:
            max_page = max(page_numbers)
            print(f"🔢 Total pages for booster '{booster}': {max_page}")
            return max_page
        else:
            print("⚠️ No pagination found. Assuming single page.")
            return 1
    except Exception as e:
        print(f"⚠️ Error detecting total pages: {e}")
        return 1

def split_race(race_string):
    """Splits a race string by '/' and returns a list of cleaned race names.
    
    Args:
        race_string: The race string to process (e.g., "ドラゴン/デーモン")
    
    Returns:
        List[str]: List of race names (empty list if input is empty/None)
    """
    if not race_string:
        return []
    
    return [r.strip() for r in race_string.split("/") if r.strip()]

def scrape_all_pages(driver, booster):
    total_pages = get_total_pages(driver, booster)
    all_card_data = []

    for page_num in range(1, total_pages + 1):
        print(f"\n📄 Scraping Page {page_num} of {total_pages}")
        url = f"https://dm.takaratomy.co.jp/card/?v=%7B%22suggest%22:%22on%22,%22keyword_type%22:%5B%22card_name%22,%22card_ruby%22,%22card_text%22%5D,%22culture_cond%22:%5B%22%E5%8D%98%E8%89%B2%22,%22%E5%A4%9A%E8%89%B2%22%5D,%22pagenum%22:%22{page_num}%22,%22samename%22:%22show%22,%22products%22:%22{booster}%22,%22sort%22:%22release_new%22%7D"

        driver.get(url)
        time.sleep(3)

        card_items = driver.find_elements(By.CSS_SELECTOR, 'div#cardlist li')
        page_data = []

        for card in card_items:
            try:
                img = card.find_element(By.TAG_NAME, 'img')
                image_url = img.get_attribute('src')

                link = card.find_element(By.TAG_NAME, 'a')
                detail_url = link.get_attribute('href')

                card_id = detail_url.split('=')[-1] if detail_url else 'No ID'

                page_data.append([card_id, image_url, detail_url])
            except Exception as e:
                print(f"❌ Error extracting card data: {e}")

        print(f"✅ Page {page_num}: Found {len(page_data)} cards")
        all_card_data.extend(page_data)

        time.sleep(1)
    print(all_card_data)
    return all_card_data

def scrape_card_details(card_data, wikimainurl, wikiscraper:DuelMastersCardWikiScraper):
    """Scrapes the detailed information for each card and processes it."""
    detailed_cards = []
    civilization_mapping = load_mapping_from_github("duelmasterdb/civilization.json")
    type_mapping = load_mapping_from_github("duelmasterdb/type.json")

    card_mapping = wikiscraper.scrape_booster_page(wikimainurl)

    # # Testing: only process first 4 cards
    # card_data = card_data[:4]
    # print(f"⚠️ TEST MODE: Processing only first 4 cards")

    for card in card_data:
        try:
            card = process_card(card)  # Process the card to extract booster, cardUid, and urlimage
            detail_url = card["detailUrl"]
            response = requests.get(detail_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Scraping details
            full_name = soup.find("h3", class_="card-name").text.strip()
            card_name, card_name2 = split_card_name(full_name)

            card_details_divs = soup.find_all("div", class_="cardDetail")
            details_list, abilities_list = [], []
            serial = re.search(r'\(.*?([A-Z]+\d+/[A-Z]+\d+|\d+[A-Z]*/\d+)\)', card_name)  # Extract serial from card name - supports DM25EX4/1 or 1/65 formats
            print(f"🔍 Scraping details for card: {card_name} (Serial: {serial.group(1) if serial else 'N/A'})")
            # Extract all details for awaken array (if multiple forms exist)
            # Skip the first form, only include awakened forms (2nd onwards)
            awaken_list = []
            if len(card_details_divs) > 1:
                for awaken_idx, card_detail in enumerate(card_details_divs[1:]):  # Skip first form
                    awaken_form = {}
                    
                    # Extract card name from this specific detail
                    card_name_elem = card_detail.find("h3", class_="card-name")
                    if card_name_elem:
                        awaken_form["cardName"] = card_name_elem.text.strip().split("(")[0].strip()
                    
                    # Extract image URL from this detail and upload to GCS
                    img_elem = card_detail.find("div", class_="card-img").find("img") if card_detail.find("div", class_="card-img") else None
                    if img_elem and img_elem.get("src"):
                        image_path = img_elem.get("src")
                        if image_path.startswith("/"):
                            full_image_url = "https://dm.takaratomy.co.jp" + image_path
                        else:
                            full_image_url = image_path
                        
                        # Extract filename from awaken form's image path (e.g., dm25ex4-TR07b from /wp-content/card/cardimage/dm25ex4-TR07b.jpg)
                        awaken_image_filename = image_path.split('/')[-1].split('?')[0].replace('.jpg', '').replace('.webp', '')
                        
                        # Upload to GCS
                        booster = card["booster"]
                        gcs_url = upload_image_to_gcs(image_url=full_image_url, filename=awaken_image_filename, filepath=f"DMTCG/{booster}/")
                        awaken_form["urlimage"] = gcs_url
                    
                    # Extract details from tables
                    detail_dict = {}
                    tables = card_detail.find_all("table")
                    for table in tables:
                        rows = table.find_all("tr")
                        for row in rows:
                            cols = row.find_all(["th", "td"])
                            if len(cols) == 2:
                                key = cols[0].text.strip()
                                value = cols[1].text.strip()
                                detail_dict[key] = value
                            elif len(cols) == 4:
                                key1, value1, key2, value2 = [col.text.strip() for col in cols]
                                detail_dict[key1] = value1
                                detail_dict[key2] = value2
                    
                    # Extract abilities
                    ability_section = card_detail.find("td", class_="skills full")
                    abilities = "\n".join([li.text.strip() for li in ability_section.find_all("li")]) if ability_section else ""
                    
                    # Map the fields
                    awaken_form["typeJP"] = detail_dict.get("カードの種類")
                    awaken_form["type"] = match_type(japanese_type=detail_dict.get("カードの種類"), type_mapping=type_mapping)
                    awaken_form["civilizationJP"] = detail_dict.get("文明")
                    awaken_form["civilization"] = match_civilization(japanese_civilization=detail_dict.get("文明"), civilization_mapping=civilization_mapping)
                    awaken_form["power"] = detail_dict.get("パワー")
                    awaken_form["cost"] = detail_dict.get("コスト")
                    awaken_form["mana"] = detail_dict.get("マナ")
                    awaken_form["race"] = split_race(detail_dict.get("種族"))
                    awaken_form["effect"] = abilities
                    
                    # Assign wiki URL with letter suffix (b, c, d, etc.)
                    if serial:
                        letter_suffix = chr(ord('b') + awaken_idx)  # 'b' for 1st awaken, 'c' for 2nd, etc.
                        awaken_serial = f"{serial.group(1).split('/')[0]}{letter_suffix}/{serial.group(1).split('/')[1]}"
                        awaken_form["wikiurl"] = card_mapping.get(awaken_serial, "")
                    
                    awaken_list.append(awaken_form)

            # Extract main details (first and second forms for cardName/cardName2)
            for card_detail in card_details_divs:
                detail = {}
                tables = card_detail.find_all("table")
                for table in tables:
                    rows = table.find_all("tr")
                    for row in rows:
                        cols = row.find_all(["th", "td"])
                        if len(cols) == 2:
                            key = cols[0].text.strip()
                            value = cols[1].text.strip()
                            detail[key] = value
                        elif len(cols) == 4:
                            key1, value1, key2, value2 = [col.text.strip() for col in cols]
                            detail[key1] = value1
                            detail[key2] = value2
                details_list.append(detail)

                ability_section = card_detail.find("td", class_="skills full")
                if ability_section:
                    abilities = "\n".join([li.text.strip() for li in ability_section.find_all("li")])
                else:
                    abilities = ""
                abilities_list.append(abilities)

            main = details_list[0] if len(details_list) > 0 else {}
            alt = details_list[1] if len(details_list) > 1 else {}
            effects_main = abilities_list[0] if len(abilities_list) > 0 else ""
            effects_alt = abilities_list[1] if len(abilities_list) > 1 else ""
            
            card_obj = {
                "cardName": card_name,
                "cardName2": card_name2,
                "booster": card["booster"],  # Use the processed booster here
                "cardUid": card["cardUid"],  # Use the processed cardUid here
                "detailUrl": card["detailUrl"],  # Use the processed detailUrl here
                "urlimage": card["urlimage"],  # Use the processed urlimage here
                "typeJP": main.get("カードの種類"),
                "type": match_type(japanese_type=main.get("カードの種類"),type_mapping=type_mapping),
                "civilizationJP": main.get("文明"),
                "civilization": match_civilization(japanese_civilization=main.get("文明"),civilization_mapping=civilization_mapping),
                "rarity": main.get("レアリティ"),
                "power": main.get("パワー"),
                "cost": main.get("コスト"),
                "mana": main.get("マナ"),
                "race": split_race(main.get("種族")),
                "illustrator": main.get("イラストレーター"),
                "effects": effects_main,
                "type2JP": alt.get("カードの種類"),
                "type2": match_type(japanese_type=alt.get("カードの種類"),type_mapping=type_mapping),
                "civilization2JP": alt.get("文明"),
                "civilization2": match_civilization(japanese_civilization=alt.get("文明"),civilization_mapping=civilization_mapping),
                "rarity2": alt.get("レアリティ"),
                "power2": alt.get("パワー"),
                "cost2": alt.get("コスト"),
                "mana2": alt.get("マナ"),
                "race2": split_race(alt.get("種族")),
                "effects2": effects_alt,
                "wikiurl": card_mapping.get(serial.group(1)) if serial else "ERROR"
            }
            
            # Append awaken array if multiple forms exist
            if awaken_list:
                card_obj["awaken"] = awaken_list
            
            detailed_cards.append(card_obj)
            
        except Exception as e:
            print(f"❌ Error scraping detailed data for card {card['cardUid']}: {e}")

    return detailed_cards

def split_card_name(full_name):
    match = re.match(r"^(.*?)\s*/\s*(.*?)(\([^()]*\))?$", full_name)
    if match and "(" not in match.group(1):
        name1 = f"{match.group(1).strip()} {match.group(3).strip() if match.group(3) else ''}".strip()
        name2 = f"{match.group(2).strip()} {match.group(3).strip() if match.group(3) else ''}".strip()
        return name1, name2
    else:
        return full_name, None

def process_card(card):
    try:
        card_uid = card[0]
        image_url= card[1]
        detail_url = card[2]

        booster = card_uid.split("-")[0]
        new_urlimage = upload_image_to_gcs(image_url=image_url,filename=card_uid,filepath=f"DMTCG/{booster}/")

        card_dict = {
            "cardUid": card_uid,
            "booster": booster,
            "urlimage": new_urlimage,
            "detailUrl": detail_url
        }

    except Exception as e:
        print(f"Error processing card: {e}")
        return card  # Return the original card if there's an error

    return card_dict

def load_mapping_from_github(file_path):
    """Load mapping JSON from GitHub using GitHubService"""
    try:
        mapping, _ = github_service.load_json_file(file_path)
        if mapping is not None:
            print(f"✅ Loaded mapping from GitHub: {file_path}")
            return mapping
        else:
            print(f"⚠️ Mapping file not found on GitHub: {file_path}")
            return {}
    except Exception as e:
        print(f"❌ Error loading mapping file {file_path}: {e}")
        return {}

def match_civilization(japanese_civilization, civilization_mapping):
    return civilization_mapping.get(japanese_civilization, japanese_civilization)

def match_type(japanese_type,type_mapping):
    return type_mapping.get(japanese_type, japanese_type)

def startscraping(booster_list):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
    "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
    )
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    wikiscraper = DuelMastersCardWikiScraper(driver)

    try:
        all_translated_data = []
        wiki_map, _ = github_service.load_json_file("duelmasterdb/wiki_map.json")
        for booster in booster_list:
            print(f"🚀 Processing booster: {booster}")
            card_data = scrape_all_pages(driver, booster)
            wikimainurl = wiki_map.get(booster, '')
            detailed_card_data = scrape_card_details(card_data, wikimainurl, wikiscraper)

            translated_data = translate_data(
                data=detailed_card_data,
                fields_to_translate=['cardName', 'cardName2', 'effects', 'effects2', 'race', 'race2'],
                src_lang='ja',
                dest_lang='en',
                batch_size=100,
                max_retries=3
            )

            all_translated_data.extend(translated_data)
            collection_value = os.getenv("C_DUELMASTERS")

            booster_update = translated_data[0]['booster']  # Ensure booster field is set
            if collection_value:
                try:
                    mongo_service.upload_data(
                        data=all_translated_data,
                        collection_name=collection_value,
                        backup_before_upload=True
                    )
                    # json_obj = mongo_service.find_by_field(collection_name="NewList", field_name="booster", field_value=booster_update)
                    
                    # # Modify category field by splitting on underscore and taking first part
                    # if json_obj and 'category' in json_obj:
                    #     original_category = json_obj['category']
                    #     json_obj['category'] = original_category.split('_')[0]
                    #     mongo_service.update_by_id(collection_name="NewList", object_id=json_obj['_id'], update_data={'category': json_obj['category']})
                    #     print(f"📝 Updated category from '{original_category}' to '{json_obj['category']}'")
                    
                except Exception as e:
                    print(f"❌ MongoDB operation failed: {str(e)}")
            else:
                print("⚠️ MongoDB collection name not found in environment variables")
        
    finally:
        driver.quit()

