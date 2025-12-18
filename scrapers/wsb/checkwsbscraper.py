import requests
from bs4 import BeautifulSoup
import json
import os
import sys
import time
import re
import base64
from datetime import datetime
from urllib.parse import urljoin
from wsbscraper import scrape_wsb_card

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.mongo_service import MongoService
from service.translationservice import translate_data
from service.googlecloudservice import upload_image_to_gcs
from service.github_service import GitHubService

#Initialize Service Layer
github_service = GitHubService()
mongo_service = MongoService()

# Variables
FILE_PATH = "wsbdb/db.json"

def compare_with_github():
    """Compare local expansions with GitHub version and report differences"""
    try:
        github_data = github_service.load_json_file(file_path=FILE_PATH)[0]
            
        # Get GitHub expansion codes from booster field
        github_codes = set()
        for item in github_data['expansions']:
            # Handle nested list structure
            if isinstance(item, list) and len(item) > 0:
                expansion_obj = item[0]
            elif isinstance(item, dict):
                expansion_obj = item
            else:
                continue
                    
                # Get booster code (preferred) or fallback to expansion_code
            booster_code = expansion_obj.get('booster', expansion_obj.get('expansion_code', ''))
            if booster_code:
                github_codes.add(booster_code)        
            return github_data, github_codes
            
    except Exception as e:
        print(f"⚠️ Error comparing with GitHub: {str(e)}")
        return None, None

def parse_japanese_date(date_str):
    """Convert Japanese date string to ISO format"""
    if not date_str or date_str.strip() == "":
        return None
    
    # Remove day of week in parentheses like （金）
    date_clean = re.sub(r'（[^）]*）', '', date_str).strip()
    
    # Parse format like "2025年10月24日"
    match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_clean)
    if match:
        year, month, day = match.groups()
        try:
            # Create datetime object and return ISO format
            dt = datetime(int(year), int(month), int(day))
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            print(f"⚠️ Invalid date: {date_str}")
            return date_str
    
    # If parsing fails, return original
    return date_str

def upload_expansion_image(expansion_code, image_url):
    """Upload expansion/booster pack image to GCS"""
    try:
        
        if not image_url:
            return None
            
        # Create filename based on expansion code
        filename = f"wsbCover{expansion_code.replace('/', '_')}"
        filepath = "boostercover/"
        
        gcs_url = upload_image_to_gcs(image_url, filename, filepath)
        print(f"✅ Uploaded expansion image for {expansion_code}: {filename}")
        return gcs_url
        
    except Exception as e:
        print(f"⚠️ Failed to upload expansion image for {expansion_code}: {str(e)}")
        return image_url  # Return original URL as fallback

def scrape_cards_for_expansion(expansion_code, expansion_title, max_pages=10):
    """Scrape all cards for a specific expansion"""
    base_url = "https://ws-blau.com/cardlist/cardsearch/"
    cards_data = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    print(f"🔍 Scraping cards for expansion: {expansion_title} (code: {expansion_code})")
    
    page = 1
    while page <= max_pages:
        try:
            url = f"{base_url}?expansion={expansion_code}&page={page}"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find card links
            card_links = soup.find_all('a', href=True)
            card_nos = []
            
            for link in card_links:
                href = link.get('href', '')
                if '/cardlist/?cardno=' in href:
                    # Extract card number from URL, removing any additional parameters
                    card_no_part = href.split('cardno=')[-1]
                    # Split by '&' to remove any additional URL parameters
                    card_no = card_no_part.split('&')[0]
                    # URL decode the card number to handle encoded characters like %2F
                    from urllib.parse import unquote
                    card_no = unquote(card_no)
                    if card_no and card_no not in card_nos:
                        card_nos.append(card_no)
            
            if not card_nos:
                print(f"  📄 No more cards found on page {page}, stopping")
                break
            
            print(f"  📄 Page {page}: Found {len(card_nos)} cards")
            
            # Scrape each card
            for card_no in card_nos:
                try:
                    print(f"    🎴 Scraping card: {card_no}")
                    # Try scraping without translation first to isolate issues
                    card_data = scrape_wsb_card(card_no, expansion_code, translate=True)
                    print(f"📋 Card data: {card_data}")
                    if card_data:
                        card_data['booster'] = expansion_code
                        card_data['expansionTitle'] = expansion_title
                        cards_data.append(card_data)
                    
                    # Small delay to be respectful
                    time.sleep(0.5)
                    
                except Exception as e:
                    print(f"    ❌ Error scraping card {card_no}: {str(e)}")
                    import traceback
                    print(f"    📋 Full error traceback:")
                    traceback.print_exc()
                    continue
            
            page += 1
            time.sleep(1)  # Delay between pages
            
        except Exception as e:
            print(f"❌ Error scraping page {page} for expansion {expansion_title}: {str(e)}")
            break
    
    print(f"✅ Completed scraping {len(cards_data)} cards for {expansion_title}")
    return cards_data

def check_and_scrape_new_expansions():
    """Check for new expansions and scrape cards for missing ones"""
    # First get current expansions list from the item list
    url = "https://ws-blau.com/cardlist/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all items in the item list
        item_list_items = soup.find_all('li', class_='item_List_Item')
        if not item_list_items:
            print("❌ Could not find item list items")
            return
        
        current_expansions = []
        
        for item in item_list_items:
            link = item.find('a')
            if not link:
                continue
                
            href = link.get('href', '')
            if '/cardlist/cardsearch/?expansion=' not in href:
                continue
            
            # Extract expansion code from URL
            expansion_code = href.split('expansion=')[1].split('&')[0]
            
            # Extract title
            title_div = item.find('div', class_='ttl')
            title = title_div.text.strip() if title_div else ''
            
            # Extract expansion/booster pack image
            thumb_div = item.find('div', class_='thumb')
            expansion_image = ''
            expansion_image_alt = ''
            if thumb_div:
                img_tag = thumb_div.find('img')
                if img_tag:
                    expansion_image = img_tag.get('src', '')
                    expansion_image_alt = img_tag.get('alt', '')
                    # Convert relative URL to absolute
                    if expansion_image and not expansion_image.startswith('http'):
                        base_url = "https://ws-blau.com"
                        expansion_image = urljoin(base_url, expansion_image)
                        print(f"  🖼️  Found expansion image: {expansion_image}")
                else:
                    print(f"  ⚠️  No image tag found in thumb div for {expansion_code}")
            else:
                print(f"  ⚠️  No thumb div found for {expansion_code}")
            
            # Extract category
            cat_item = item.find('div', class_='cat-item')
            category = cat_item.text.strip() if cat_item else ''
            
            # Extract release date
            release_detail = item.find('div', class_='release-detail')
            release_date_raw = release_detail.text.strip() if release_detail else ''
            # Parse Japanese date to ISO format
            release_date = parse_japanese_date(release_date_raw) or release_date_raw
            if(category == 'デッキ商品'):
                category = 'deck'
            elif(category == 'パック商品'):
                category = 'expansion'
            else:
                category = 'extra'
            # Prepare expansion data
            expansion_data = {
                "booster": expansion_code,
                "title": title,
                "category": category,
                "release_date": release_date,
                "url": href,
                "alt": expansion_image_alt
            }
            
            # Store expansion image URL for later processing (don't upload yet)
            if expansion_image:
                expansion_data["expansion_image"] = expansion_image
                expansion_data["expansion_image_alt"] = expansion_image_alt
            
            # Don't translate yet - defer until we know it's new
            current_expansions.append(expansion_data)
        
        print(f"🔍 Found {len(current_expansions)} expansions on website")
        
    except Exception as e:
        print(f"❌ Error fetching current expansions list: {str(e)}")
        return
    
    # Compare with GitHub and local data
    current_codes = {exp['booster'] for exp in current_expansions}
    github_data, github_codes = compare_with_github()
    existing_data,file_sha = github_service.load_json_file(file_path=FILE_PATH)
    
    # Determine what expansions need scraping
    if existing_data is None and github_codes is None:
        # No existing data anywhere, scrape all expansions
        expansions_to_scrape = current_expansions
        print(f"📚 No existing data found. Will scrape all {len(expansions_to_scrape)} expansions.")
    else:
        # Combine existing sources
        known_codes = set()
        if existing_data:
            # Handle db.json structure: get expansions field and extract booster codes
            expansions_list = existing_data.get('expansions', [])
            for item in expansions_list:
                # Handle nested list structure (each expansion is wrapped in a list)
                if isinstance(item, list) and len(item) > 0:
                    expansion_obj = item[0]  # Get the actual expansion object
                elif isinstance(item, dict):
                    expansion_obj = item  # Direct object
                else:
                    continue
                
                # Get booster code from the expansion object
                booster_code = expansion_obj.get('booster', '')
                if booster_code:
                    known_codes.add(str(booster_code))
                    
        if github_codes:
            known_codes.update(github_codes)
        
        # Find new expansions (using 'booster' field which is the actual field name)
        expansions_to_scrape = [e for e in current_expansions if e['booster'] not in known_codes]
        
        if expansions_to_scrape:
            print(f"📚 Found {len(expansions_to_scrape)} new expansions to scrape:")
            for expansion in expansions_to_scrape:
                print(f"  - {expansion['title']} (code: {expansion['booster']})")
        else:
            # Check if we need to update GitHub even without new expansions
            if github_codes and current_codes != github_codes:
                print("🔄 No new expansions, but updating GitHub with current data...")
                expansions_db = {
                    "expansions": current_expansions,
                    "total_count": len(current_expansions)
                }
                updated_content = json.dumps(expansions_db, indent=2, ensure_ascii=False)
                commit_message = "Update db.json with current expansions list"
                success = github_service.update_file(FILE_PATH, updated_content, commit_message, file_sha)
                if success:
                    print("✅ GitHub db.json has been updated.")
                else:
                    print("❌ Error updating db.json on GitHub.")
            else:
                print("✅ No new expansions found. Database is up to date.")
            return []
    
    # Merge existing urlimage data with current expansions to preserve urlimage fields
    if github_data and 'expansions' in github_data:
        existing_expansions = {}
        # Handle nested list structure in GitHub data
        for item in github_data['expansions']:
            if isinstance(item, list) and len(item) > 0:
                exp = item[0]  # Get the actual expansion object from nested list
            elif isinstance(item, dict):
                exp = item  # Direct object
            else:
                continue
            
            # Get booster code as key
            booster_key = exp.get('booster', exp.get('expansion_code', ''))
            if booster_key:
                existing_expansions[booster_key] = exp
        
        # Preserve existing urlimage fields
        for i, expansion in enumerate(current_expansions):
            booster_code = expansion['booster']
            if booster_code in existing_expansions and 'urlimage' in existing_expansions[booster_code]:
                # Preserve existing urlimage if new expansion doesn't have one
                if 'urlimage' not in expansion:
                    current_expansions[i]['urlimage'] = existing_expansions[booster_code]['urlimage']
    
    # Process and scrape cards for each new expansion
    all_cards_data = []
    for expansion in expansions_to_scrape:
        print(f"\n🎴 Processing new expansion: {expansion['title']} (code: {expansion['booster']})")
        
        # Now translate and upload expansion metadata for new expansions only
        print(f"🔄 Translating expansion metadata...")
        translated_expansion = translate_data([expansion], fields_to_translate=['title', 'category', 'alt'])[0]
        
        # Upload expansion image for new expansions only
        expansion_image = expansion.get('expansion_image')
        if expansion_image:
            print(f"📤 Uploading expansion image...")
            gcs_url = upload_expansion_image(expansion['booster'], expansion_image)
            if gcs_url:
                translated_expansion["urlimage"] = gcs_url
        
        # Update the expansion in current_expansions with translated data and urlimage
        for i, exp in enumerate(current_expansions):
            if exp['booster'] == expansion['booster']:
                current_expansions[i] = translated_expansion
                break
        
        print(f"🎴 Scraping cards for: {translated_expansion['title']}")
        cards_data = scrape_cards_for_expansion(expansion['booster'], translated_expansion['title'])
        all_cards_data.extend(cards_data)
        
        # Display sample data for review
        if cards_data:
            print(f"✅ Found {len(cards_data)} cards in {expansion['title']}")
            print(f"📋 Sample card data:")
            sample_card = cards_data[0] if cards_data else {}
            for key, value in list(sample_card.items())[:5]:  # Show first 5 fields
                print(f"   {key}: {value}")
            if len(sample_card) > 5:
                print(f"   ... and {len(sample_card) - 5} more fields")
            print()
    
    # Save the complete expansions list both locally and to GitHub AFTER image uploads
    expansions_db = {
        "expansions": current_expansions,
        "total_count": len(current_expansions)
    }

    # Update GitHub with complete data including urlimage fields
    if expansions_to_scrape:  # Only update GitHub if there were new expansions
        updated_content = json.dumps(expansions_db, indent=2, ensure_ascii=False)
        commit_message = "Update db.json with current expansions list"
        success = github_service.update_file(FILE_PATH, updated_content, commit_message, file_sha)
        if success:
            print("✅ GitHub db.json has been updated.")
        else:
            print("❌ Error updating db.json on GitHub.")
    
    # Show summary but don't upload yet
    if all_cards_data:
        print(f"🎯 SCRAPING COMPLETE - REVIEW DATA")
        print(f"📊 Total cards scraped: {len(all_cards_data)}")
        print(f"📦 From {len(expansions_to_scrape)} expansions")
        print(f"💾 Data ready for upload (currently disabled for review)")
        collection_value = os.getenv('C_WSB')
        if collection_value:
            mongo_service.upload_data(
                 data=all_cards_data,
                 collection_name=collection_value,
                 backup_before_upload=True
             )
            print(f"📤 Uploaded {len(all_cards_data)} cards to MongoDB")
        else:
             print("⚠️ MongoDB collection name not found in environment variables")
    
    # Final status report
    if expansions_to_scrape:
        print(f"\n🎯 SCRAPING SESSION COMPLETE")
        print(f"📊 New expansions processed: {len(expansions_to_scrape)}")
        print(f"🎴 Total cards scraped: {len(all_cards_data)}")
        print(f"💾 Local database updated: ✅")
    
    return all_cards_data

if __name__ == "__main__":
    check_and_scrape_new_expansions()