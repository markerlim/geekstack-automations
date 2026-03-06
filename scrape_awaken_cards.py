import requests
from bs4 import BeautifulSoup
import json
import re
import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from service.github_service import GitHubService

github_service = GitHubService()

def split_race(race_string):
    """Splits a race string by '/' and returns a list of cleaned race names."""
    if not race_string:
        return []
    return [r.strip() for r in race_string.split("/") if r.strip()]

def split_civilization(civilization_string):
    """Splits a civilization string by '/' and returns a list of cleaned civilization names."""
    if not civilization_string:
        return []
    return [c.strip() for c in civilization_string.split("/") if c.strip()]

def split_card_name(full_name):
    """Split card name into main and twinpact form."""
    match = re.match(r"^(.*?)\s*/\s*(.*?)(\([^()]*\))?$", full_name)
    if match and "(" not in match.group(1):
        name1 = f"{match.group(1).strip()} {match.group(3).strip() if match.group(3) else ''}".strip()
        name2 = f"{match.group(2).strip()} {match.group(3).strip() if match.group(3) else ''}".strip()
        return name1, name2
    else:
        return full_name, None

def scrape_card_details_for_awaken(detail_url, card_uid):
    """
    Scrapes detailed card information from a detail URL.
    Returns the same detailed structure as scrape_card_details().
    """
    
    with open("duelmasterdb/civilization.json", "r", encoding="utf-8") as file:
        civilization_mapping = json.load(file)

    with open("duelmasterdb/type.json", "r", encoding="utf-8") as file:
        type_mapping = json.load(file)
    
    with open("duelmasterdb/backup_dm25ex4.json", "r", encoding="utf-8") as file:
        card_mapping = json.load(file)

    try:
        response = requests.get(detail_url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Scraping details
        full_name = soup.find("h3", class_="card-name").text.strip()
        card_name, card_name2 = split_card_name(full_name)
        
        card_details_divs = soup.find_all("div", class_="cardDetail")
        details_list, abilities_list = [], []
        serial = re.search(r'\(.*?([A-Z]+\d+/[A-Z]+\d+|\d+[A-Z]*/\d+)\)', card_name)
        
        # Count images to verify it's an awaken card
        # Only count card-img divs that have actual image sources (non-empty src)
        num_images = 0
        for card_detail in card_details_divs:
            img_elem = card_detail.find("div", class_="card-img")
            if img_elem:
                img_tag = img_elem.find("img")
                # Only count if img exists and has a non-empty src attribute
                if img_tag and img_tag.get("src") and img_tag.get("src").strip():
                    num_images += 1
        
        num_details = len(card_details_divs)
        print(f"   🔍 Found {num_details} detail sections and {num_images} images for {card_name}")
        is_awaken_card = num_details > 1 and num_images == num_details
        
        if not is_awaken_card:
            return None
        
        # Extract awaken forms (skip first form)
        awaken_list = []
        if is_awaken_card:
            for awaken_idx, card_detail in enumerate(card_details_divs[1:]):
                awaken_form = {}
                
                # Extract card name
                card_name_elem = card_detail.find("h3", class_="card-name")
                if card_name_elem:
                    awaken_form["cardName"] = card_name_elem.text.strip().split("(")[0].strip()
                
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
                awaken_form["civilizationJP"] = split_civilization(detail_dict.get("文明"))
                awaken_form["civilization"] = [match_civilization(japanese_civilization=c, civilization_mapping=civilization_mapping) for c in split_civilization(detail_dict.get("文明"))]
                awaken_form["power"] = detail_dict.get("パワー")
                awaken_form["powerInt"] = convert_power_to_int(detail_dict.get("パワー"))
                awaken_form["cost"] = detail_dict.get("コスト")
                awaken_form["mana"] = detail_dict.get("マナ")
                awaken_form["race"] = split_race(detail_dict.get("種族"))
                awaken_form["effects"] = abilities
                
                # Assign wiki URL with letter suffix
                if serial:
                    letter_suffix = chr(ord('b') + awaken_idx)
                    awaken_serial = f"{serial.group(1).split('/')[0]}{letter_suffix}/{serial.group(1).split('/')[1]}"
                    awaken_form["wikiurl"] = card_mapping.get(awaken_serial, "")
                
                awaken_list.append(awaken_form)
        
        # Extract main details (first form only for awaken cards)
        main = {}
        if card_details_divs:
            card_detail = card_details_divs[0]
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
            
            ability_section = card_detail.find("td", class_="skills full")
            abilities = "\n".join([li.text.strip() for li in ability_section.find_all("li")]) if ability_section else ""
            main = detail_dict
        
        effects_main = abilities
        
        # Build card object with full details
        card_obj = {
            "cardName": card_name,
            "cardName2": card_name2,
            "cardUid": card_uid,
            "detailUrl": detail_url,
            "typeJP": main.get("カードの種類"),
            "type": match_type(japanese_type=main.get("カードの種類"), type_mapping=type_mapping),
            "civilizationJP": split_civilization(main.get("文明")),
            "civilization": [match_civilization(japanese_civilization=c, civilization_mapping=civilization_mapping) for c in split_civilization(main.get("文明"))],
            "rarity": main.get("レアリティ"),
            "power": main.get("パワー"),
            "powerInt": convert_power_to_int(main.get("パワー")),
            "cost": main.get("コスト"),
            "mana": main.get("マナ"),
            "race": split_race(main.get("種族")),
            "illustrator": main.get("イラストレーター"),
            "effects": effects_main,
            "wikiurl": card_mapping.get(serial.group(1)) if serial else ""
        }
        
        # Append awaken array
        if awaken_list:
            card_obj["awaken"] = awaken_list
        
        return card_obj
        
    except Exception as e:
        print(f"   ❌ Error scraping details: {e}")
        return None

def match_civilization(japanese_civilization, civilization_mapping):
    return civilization_mapping.get(japanese_civilization, japanese_civilization)

def match_type(japanese_type, type_mapping):
    return type_mapping.get(japanese_type, japanese_type)

def convert_power_to_int(power_str):
    """Converts power string to integer. Infinity symbols become max int value."""
    if not power_str:
        return None
    
    power_str = str(power_str).strip()
    
    if power_str in ["∞", "infinity", "無制限"]:
        return 2147483647
    
    try:
        return int(power_str)
    except (ValueError, TypeError):
        return None

def scrape_and_filter_awaken_cards(input_file, output_file):
    """
    Scrapes each detailUrl from the input JSON and keeps only awaken cards.
    Records all the same details as scrape_card_details().
    Saves when 5 awaken cards are accumulated (not periodic).
    Supports robust resuming from where it left off.
    """
    
    # Load input JSON
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            cards = json.load(f)
        print(f"✅ Loaded {len(cards)} cards from {input_file}\n")
    except Exception as e:
        print(f"❌ Error loading file: {e}")
        return
    
    # Track progress separately from results
    progress_file = output_file.replace('.json', '_progress.json')
    
    # Load or initialize progress tracking
    processed_uids = set()
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                processed_uids = set(json.load(f))
            print(f"✅ Resumed: {len(processed_uids)} cards already processed\n")
        except Exception as e:
            print(f"⚠️  Could not load progress file, starting fresh: {e}\n")
    
    # Load or initialize awaken cards
    awaken_cards = []
    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                awaken_cards = json.load(f)
            print(f"✅ Loaded {len(awaken_cards)} existing awaken cards\n")
        except Exception as e:
            print(f"⚠️  Could not load existing output file: {e}\n")
    
    awaken_accumulator = []
    save_threshold = 5
    
    for idx, card in enumerate(cards, 1):
        try:
            detail_url = card.get("detailUrl")
            card_id = card.get("_id", {}).get("$oid", "Unknown") if isinstance(card.get("_id"), dict) else str(card.get("_id", "Unknown"))
            card_name = card.get("cardName", "Unknown")
            
            # Skip if already processed
            if card_id in processed_uids:
                print(f"⏭️  [{idx}/{len(cards)}] {card_name} - Already processed, skipping")
                continue
            
            if not detail_url:
                print(f"⏭️  [{idx}/{len(cards)}] {card_name} - No detailUrl, skipping")
                processed_uids.add(card_id)
                continue
            
            print(f"📍 [{idx}/{len(cards)}] Scraping: {card_name}")
            
            # Scrape and get detailed card object (only if it's an awaken card)
            detailed_card = scrape_card_details_for_awaken(detail_url, card.get("cardUid", "Unknown"))
            
            # Mark as processed regardless of whether it's awaken
            processed_uids.add(card_id)
            
            if detailed_card:
                awaken_accumulator.append(detailed_card)
                print(f"   ✅ AWAKEN CARD - Added to accumulator ({len(awaken_accumulator)}/{save_threshold})")
                
                # Save when accumulator reaches threshold
                if len(awaken_accumulator) >= save_threshold:
                    awaken_cards.extend(awaken_accumulator)
                    try:
                        with open(output_file, 'w', encoding='utf-8') as f:
                            json.dump(awaken_cards, f, indent=2, ensure_ascii=False)
                        with open(progress_file, 'w', encoding='utf-8') as f:
                            json.dump(list(processed_uids), f)
                        print(f"   💾 Saved batch: {len(awaken_cards)} total awaken cards")
                        awaken_accumulator = []
                    except Exception as e:
                        print(f"   ⚠️  Error during save: {e}")
            else:
                print(f"   ❌ Skipping (not an awaken card or error)")
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            # Still mark as processed even on error to avoid re-processing
            card_id = card.get("_id", {}).get("$oid", "Unknown") if isinstance(card.get("_id"), dict) else str(card.get("_id", "Unknown"))
            processed_uids.add(card_id)
    
    # Final save for remaining cards in accumulator
    if awaken_accumulator:
        awaken_cards.extend(awaken_accumulator)
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(awaken_cards, f, indent=2, ensure_ascii=False)
            print(f"\n💾 Final save: {len(awaken_cards)} total awaken cards")
        except Exception as e:
            print(f"❌ Error during final save: {e}")
    
    # Final progress save
    try:
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(list(processed_uids), f)
    except Exception as e:
        print(f"⚠️  Error saving progress: {e}")
    
    print(f"📊 Total cards processed: {len(processed_uids)}/{len(cards)}")

if __name__ == "__main__":
    input_file = "DM_16FEB2026_1020.json"  # Change to your input JSON
    output_file = "DM_16FEB2026_1020_AWAKEN.json"  # Output file
    
    scrape_and_filter_awaken_cards(input_file, output_file)
