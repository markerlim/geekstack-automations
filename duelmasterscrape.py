import requests
from bs4 import BeautifulSoup
import time
import re
import json
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

from googlecloudservice import upload_image_to_gcs
from mongoservice import upload_to_mongo
from translationservice import translate_data

def get_total_pages(driver, booster):
    url = f"https://dm.takaratomy.co.jp/card/?v=%7B%22suggest%22:%22on%22,%22keyword_type%22:%5B%22card_name%22,%22card_ruby%22,%22card_text%22%5D,%22culture_cond%22:%5B%22%E5%8D%98%E8%89%B2%22,%22%E5%A4%9A%E8%89%B2%22%5D,%22pagenum%22:%221%22,%22samename%22:%22show%22,%22products%22:%22{booster}%22,%22sort%22:%22release_new%22%7D"
    
    driver.get(url)
    time.sleep(3)

    try:
        pagination = driver.find_elements(By.CSS_SELECTOR, "ul.pagination li a")
        page_numbers = [int(p.text) for p in pagination if p.text.isdigit()]
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

def scrape_card_details(card_data):
    """Scrapes the detailed information for each card and processes it."""
    detailed_cards = []
    civilization_mapping = load_mapping("duelmasterdb/civilization.json")
    type_mapping = load_mapping("duelmasterdb/type.json")
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
            card_image = soup.find("div", class_="card-img").find("img")["src"]

            card_details_divs = soup.find_all("div", class_="cardDetail")
            details_list, abilities_list = [], []

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

            detailed_cards.append({
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
                "race": main.get("種族"),
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
                "race2": alt.get("種族"),
                "effects2": effects_alt
            })
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
        # Extract cardUid and detailUrl from the card list
        card_uid = card[0]
        image_url= card[1]
        detail_url = card[2]  # The third element is the detail URL

        # Extract booster from cardUid
        booster = card_uid.split("-")[0]
        new_urlimage = upload_image_to_gcs(image_url=image_url,filename=card_uid,filepath=f"DMTCG/test/{booster}/")

        # Add new fields and update
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

def save_to_json(detailed_cards, filename="duelmasters_cards_data.json"):
    """Save the detailed card data to a JSON file."""
    import json
    with open(filename, mode='w', encoding='utf-8') as file:
        json.dump(detailed_cards, file, ensure_ascii=False, indent=2)
    print(f"Saved {len(detailed_cards)} detailed cards to {filename}")

def load_mapping(json_file):
    try:
        with open(json_file, 'r', encoding='utf-8') as file:
            mapping = json.load(file)
        return mapping
    except Exception as e:
        print(f"❌ Error loading JSON file: {e}")
        return {}

def match_civilization(japanese_civilization, civilization_mapping):
    return civilization_mapping.get(japanese_civilization, japanese_civilization)

def match_type(japanese_type,type_mapping):
    return type_mapping.get(japanese_type, japanese_type)

def startscraping(booster_list, collection_name):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    try:
        all_translated_data = []

        for booster in booster_list:
            print(f"🚀 Processing booster: {booster}")
            card_data = scrape_all_pages(driver, booster)
            detailed_card_data = scrape_card_details(card_data)

            translated_data = translate_data(
                data=detailed_card_data,
                fields_to_translate=['cardName', 'cardName2', 'effects', 'effects2'],
                src_lang='ja',
                dest_lang='en',
                batch_size=100,
                max_retries=3
            )

            all_translated_data.extend(translated_data)

        # Upload all collected data
        upload_to_mongo(
            data=all_translated_data,
            collection_name=collection_name
        )
    finally:
        driver.quit()

