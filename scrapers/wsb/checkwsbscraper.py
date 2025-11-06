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

# Import the WSB card scraper
sys.path.append(os.path.dirname(__file__))
from wsbscraper import scrape_wsb_card

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.mongoservice import upload_to_mongo

# GitHub repository details
REPO_OWNER = "markerlim"
REPO_NAME = "geekstack-automations"
FILE_PATH = "wsbdb/db.json"
BRANCH = "main"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def update_github_db(expansions_data):
    """Update the WSB database on GitHub with new expansions data"""
    if not GITHUB_TOKEN:
        print("⚠️ GITHUB_TOKEN not found, skipping GitHub update")
        return False
    
    # GitHub API URL for file content
    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}?ref={BRANCH}"
    
    try:
        # Get current file from GitHub
        response = requests.get(api_url, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"})
        
        if response.status_code == 200:
            file_data = response.json()
            
            # Prepare updated content
            updated_content = json.dumps(expansions_data, indent=2, ensure_ascii=False)
            
            # Update file on GitHub
            update_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
            data = {
                "message": "Update WSB expansions database with new data",
                "content": base64.b64encode(updated_content.encode('utf-8')).decode('utf-8'),
                "sha": file_data['sha'],
                "branch": BRANCH
            }
            
            response = requests.put(update_url, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"}, json=data)
            
            if response.status_code == 200:
                print("✅ Successfully updated WSB database on GitHub")
                return True
            else:
                print(f"❌ Error updating GitHub file: {response.status_code}")
                print(response.text)
                return False
        else:
            print(f"❌ Error fetching file from GitHub: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error with GitHub update: {str(e)}")
        return False

def compare_with_github():
    """Compare local expansions with GitHub version and report differences"""
    if not GITHUB_TOKEN:
        print("⚠️ GITHUB_TOKEN not found, skipping GitHub comparison")
        return None, None
    
    # GitHub API URL for file content
    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}?ref={BRANCH}"
    
    try:
        response = requests.get(api_url, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"})
        
        if response.status_code == 200:
            file_data = response.json()
            content_base64 = file_data['content']
            decoded_content = base64.b64decode(content_base64).decode('utf-8')
            github_data = json.loads(decoded_content)
            
            # Get GitHub expansion codes
            github_codes = set()
            if 'expansions' in github_data:
                github_codes = {exp.get('expansion_code', '') for exp in github_data['expansions']}
            
            return github_data, github_codes
        else:
            print(f"⚠️ Could not fetch GitHub data: {response.status_code}")
            return None, None
            
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

def scrape_wsb_series():
    """Scrape WSB series list and save to db.json"""
    url = "https://ws-blau.com/cardlist/"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the select element with series options
        select_element = soup.find('select', {'name': 'title', 'class': 'saerchform-Select'})
        
        if not select_element:
            print("❌ Could not find series select element")
            return
        
        series_data = []
        options = select_element.find_all('option')
        
        for option in options:
            value = option.get('value', '').strip()
            text = option.text.strip()
            
            # Skip empty "すべて" option
            if not value:
                continue
                
            series_data.append({
                "value": value,
                "name": text
            })
        
        # Create wsbdb directory if it doesn't exist
        db_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'wsbdb')
        os.makedirs(db_dir, exist_ok=True)
        
        # Save to db.json
        db_file = os.path.join(db_dir, 'db.json')
        with open(db_file, 'w', encoding='utf-8') as f:
            json.dump({
                "series": series_data,
                "total_count": len(series_data)
            }, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Scraped {len(series_data)} series and saved to {db_file}")
        
        # Print summary
        for series in series_data:
            print(f"Value: {series['value']} - Name: {series['name']}")
            
        return series_data
        
    except Exception as e:
        print(f"❌ Error scraping WSB series: {str(e)}")
        return None

def load_series_db():
    """Load series data from db.json"""
    db_file = os.path.join(os.path.dirname(__file__), '..', '..', 'wsbdb', 'db.json')
    
    if not os.path.exists(db_file):
        print("❌ db.json not found. Run scrape_wsb_series() first.")
        return None
        
    try:
        with open(db_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Error loading db.json: {str(e)}")
        return None

def scrape_cards_for_series(series_value, series_name, max_pages=10):
    """Scrape all cards for a specific series (legacy function)"""
    base_url = "https://ws-blau.com/cardlist/cardsearch/"
    cards_data = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    print(f"🔍 Scraping cards for series: {series_name} (value: {series_value})")
    
    page = 1
    while page <= max_pages:
        try:
            url = f"{base_url}?title={series_value}&page={page}"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find card links
            card_links = soup.find_all('a', href=True)
            card_nos = []
            
            for link in card_links:
                href = link.get('href', '')
                if '/cardlist/?cardno=' in href:
                    # Extract card number from URL
                    card_no = href.split('cardno=')[-1]
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
                    card_data = scrape_wsb_card(card_no)
                    if card_data:
                        card_data['seriesValue'] = series_value
                        card_data['seriesName'] = series_name
                        cards_data.append(card_data)
                    
                    # Small delay to be respectful
                    time.sleep(0.5)
                    
                except Exception as e:
                    print(f"    ❌ Error scraping card {card_no}: {str(e)}")
                    continue
            
            page += 1
            time.sleep(1)  # Delay between pages
            
        except Exception as e:
            print(f"❌ Error scraping page {page} for series {series_name}: {str(e)}")
            break
    
    print(f"✅ Completed scraping {len(cards_data)} cards for {series_name}")
    return cards_data

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
                    card_data = scrape_wsb_card(card_no, expansion_code, translate=True)
                    print(f"📋 Card data: {card_data}")
                    if card_data:
                        card_data['expansionCode'] = expansion_code
                        card_data['expansionTitle'] = expansion_title
                        cards_data.append(card_data)
                    
                    # Small delay to be respectful
                    time.sleep(0.5)
                    
                except Exception as e:
                    print(f"    ❌ Error scraping card {card_no}: {str(e)}")
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
            
            # Extract category
            cat_item = item.find('div', class_='cat-item')
            category = cat_item.text.strip() if cat_item else ''
            
            # Extract release date
            release_detail = item.find('div', class_='release-detail')
            release_date_raw = release_detail.text.strip() if release_detail else ''
            # Parse Japanese date to ISO format
            release_date = parse_japanese_date(release_date_raw) or release_date_raw
            
            current_expansions.append({
                "expansion_code": expansion_code,
                "title": title,
                "category": category,
                "release_date": release_date,
                "url": href
            })
        
        print(f"🔍 Found {len(current_expansions)} expansions on website")
        
    except Exception as e:
        print(f"❌ Error fetching current expansions list: {str(e)}")
        return
    
    # Compare with GitHub and local data
    current_codes = {exp['expansion_code'] for exp in current_expansions}
    github_data, github_codes = compare_with_github()
    existing_data = load_series_db()
    
    # Determine what expansions need scraping
    if existing_data is None and github_codes is None:
        # No existing data anywhere, scrape all expansions
        expansions_to_scrape = current_expansions
        print(f"📚 No existing data found. Will scrape all {len(expansions_to_scrape)} expansions.")
    else:
        # Combine existing sources
        known_codes = set()
        if existing_data:
            known_codes.update(str(s.get('expansion_code', s.get('value', ''))) for s in existing_data.get('expansions', existing_data.get('series', [])))
        if github_codes:
            known_codes.update(github_codes)
        
        # Find new expansions
        expansions_to_scrape = [e for e in current_expansions if e['expansion_code'] not in known_codes]
        
        if expansions_to_scrape:
            print(f"📚 Found {len(expansions_to_scrape)} new expansions to scrape:")
            for expansion in expansions_to_scrape:
                print(f"  - {expansion['title']} (code: {expansion['expansion_code']})")
        else:
            # Check if we need to update GitHub even without new expansions
            if github_codes and current_codes != github_codes:
                print("🔄 No new expansions, but updating GitHub with current data...")
                expansions_db = {
                    "expansions": current_expansions,
                    "total_count": len(current_expansions)
                }
                update_github_db(expansions_db)
            else:
                print("✅ No new expansions found. Database is up to date.")
            return []
    
    # Save the complete expansions list both locally and to GitHub
    expansions_db = {
        "expansions": current_expansions,
        "total_count": len(current_expansions)
    }
    
    # Save locally
    db_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'wsbdb')
    os.makedirs(db_dir, exist_ok=True)
    db_file = os.path.join(db_dir, 'db.json')
    
    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(expansions_db, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Updated local expansions database with {len(current_expansions)} total expansions")
    
    # Update GitHub
    if expansions_to_scrape:  # Only update GitHub if there were new expansions
        update_github_db(expansions_db)
    
    # Scrape cards for each new expansion
    all_cards_data = []
    for expansion in expansions_to_scrape:
        print(f"\n🎴 Scraping expansion: {expansion['title']} (code: {expansion['expansion_code']})")
        cards_data = scrape_cards_for_expansion(expansion['expansion_code'], expansion['title'])
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
    
    # Show summary but don't upload yet
    if all_cards_data:
        print(f"🎯 SCRAPING COMPLETE - REVIEW DATA")
        print(f"📊 Total cards scraped: {len(all_cards_data)}")
        print(f"📦 From {len(expansions_to_scrape)} expansions")
        print(f"💾 Data ready for upload (currently disabled for review)")
        collection_value = os.getenv('C_WSB')
        if collection_value:
             upload_to_mongo(
                 data=all_cards_data,
                 collection_name=collection_value
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
        print(f"🔄 GitHub updated: ✅" if GITHUB_TOKEN else "🔄 GitHub update: ⚠️ (No token)")
    
    return all_cards_data

def scrape_specific_expansion(expansion_code):
    """Scrape cards for a specific expansion by code"""
    expansion_data = load_series_db()
    if not expansion_data:
        print("❌ Expansion data not found. Run check_and_scrape_new_expansions() first.")
        return
    
    # Find the expansion
    expansion_info = None
    expansions = expansion_data.get('expansions', expansion_data.get('series', []))
    for expansion in expansions:
        exp_code = expansion.get('expansion_code', expansion.get('value', ''))
        if str(exp_code) == str(expansion_code):
            expansion_info = expansion
            break
    
    if not expansion_info:
        print(f"❌ Expansion with code {expansion_code} not found")
        return
    
    # Scrape cards for this expansion
    cards_data = scrape_cards_for_expansion(
        expansion_info.get('expansion_code', expansion_info.get('value', '')), 
        expansion_info.get('title', expansion_info.get('name', ''))
    )
    
    # Show data for review (upload disabled)
    if cards_data:
        print(f"🎯 SCRAPING COMPLETE - REVIEW DATA")
        print(f"📊 Total cards scraped: {len(cards_data)}")
        print(f"📋 Sample card data:")
        sample_card = cards_data[0] if cards_data else {}
        for key, value in list(sample_card.items())[:8]:  # Show first 8 fields
            print(f"   {key}: {value}")
        if len(sample_card) > 8:
            print(f"   ... and {len(sample_card) - 8} more fields")
        print(f"💾 Data ready for upload (currently disabled for review)")
        collection_value = os.getenv('C_WSB')
        if collection_value:
             upload_to_mongo(
                 data=cards_data,
                 collection_name=collection_value
             )
             print(f"📤 Uploaded {len(cards_data)} cards to MongoDB")
    
    return cards_data

def scrape_specific_series(series_value):
    """Scrape cards for a specific series by value (legacy function for backward compatibility)"""
    series_data = load_series_db()
    if not series_data:
        print("❌ Series data not found. Run check_and_scrape_new_expansions() first.")
        return
    
    # Find the series
    series_info = None
    for series in series_data.get('series', []):
        if str(series['value']) == str(series_value):
            series_info = series
            break
    
    if not series_info:
        print(f"❌ Series with value {series_value} not found")
        return
    
    # Scrape cards for this series
    cards_data = scrape_cards_for_series(series_info['value'], series_info['name'])
    
    # Upload to MongoDB
    if cards_data:
        collection_value = os.getenv('C_WSB')
        if collection_value:
            upload_to_mongo(
                data=cards_data,
                collection_name=collection_value
            )
            print(f"📤 Uploaded {len(cards_data)} cards to MongoDB")
    
    return cards_data

if __name__ == "__main__":
    check_and_scrape_new_expansions()