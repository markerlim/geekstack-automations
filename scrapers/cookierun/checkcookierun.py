import requests
import json
import os
import sys
import base64
from datetime import datetime

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.mongoservice import upload_to_mongo
from service.googlecloudservice import upload_image_to_gcs

# GitHub repository details
REPO_OWNER = "markerlim"
REPO_NAME = "geekstack-automations"
LATEST_DATE_FILE = "cookierundb/latestdate.txt"
BRANCH = "main"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def get_latest_date_local():
    """Get the latest postDate from local file"""
    try:
        latest_file = os.path.join(os.path.dirname(__file__), '..', '..', 'cookierundb', 'latestdate.txt')
        if os.path.exists(latest_file):
            with open(latest_file, 'r') as f:
                content = f.read().strip()
                if content:
                    return int(content)
        return 0  # If file doesn't exist or is empty, start from 0
    except Exception as e:
        print(f"⚠️ Error reading local latest date: {str(e)}")
        return 0

def save_latest_date_local(date_timestamp):
    """Save the latest postDate to local file"""
    try:
        db_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'cookierundb')
        os.makedirs(db_dir, exist_ok=True)
        latest_file = os.path.join(db_dir, 'latestdate.txt')
        
        with open(latest_file, 'w') as f:
            f.write(str(date_timestamp))
        print(f"💾 Updated local latest date: {date_timestamp}")
        return True
    except Exception as e:
        print(f"❌ Error saving local latest date: {str(e)}")
        return False

def get_latest_date_github():
    """Get the latest postDate from GitHub"""
    if not GITHUB_TOKEN:
        return None
    
    try:
        api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{LATEST_DATE_FILE}?ref={BRANCH}"
        response = requests.get(api_url, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"})
        
        if response.status_code == 200:
            file_data = response.json()
            content_base64 = file_data['content']
            decoded_content = base64.b64decode(content_base64).decode('utf-8').strip()
            if decoded_content:
                return int(decoded_content)
        return 0
    except Exception as e:
        print(f"⚠️ Error getting GitHub latest date: {str(e)}")
        return None

def update_latest_date_github(date_timestamp):
    """Update the latest postDate on GitHub"""
    if not GITHUB_TOKEN:
        print("⚠️ GITHUB_TOKEN not found, skipping GitHub update")
        return False
    
    try:
        # Get current file from GitHub
        api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{LATEST_DATE_FILE}?ref={BRANCH}"
        response = requests.get(api_url, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"})
        
        # Prepare update data
        content = str(date_timestamp)
        data = {
            "message": f"Update Cookie Run latest date to {date_timestamp}",
            "content": base64.b64encode(content.encode('utf-8')).decode('utf-8'),
            "branch": BRANCH
        }
        
        # Add SHA if file exists
        if response.status_code == 200:
            file_data = response.json()
            data["sha"] = file_data['sha']
        
        # Update file on GitHub
        update_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{LATEST_DATE_FILE}"
        response = requests.put(update_url, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"}, json=data)
        
        if response.status_code in [200, 201]:
            print("✅ Successfully updated latest date on GitHub")
            return True
        else:
            print(f"❌ Error updating GitHub: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error with GitHub update: {str(e)}")
        return False

def process_card_data(card):
    """Process and clean card data"""
    try:
        # Get card number and transform it for cardId and cardUid
        card_no = card.get("field_cardNo_suyeowsc", "")
        card_id = ""
        card_uid = ""
        
        if card_no:
            # Extract base card ID (everything before @)
            if "@" in card_no:
                card_id = card_no.split("@")[0]
                # Transform @1 to _ALT, @2 to _ALT2, etc.
                variant = card_no.split("@")[1]
                if variant == "1":
                    card_uid = f"{card_id}_ALT"
                else:
                    card_uid = f"{card_id}_ALT{variant}"
            else:
                card_id = card_no
                card_uid = card_no
        
        # Extract booster series from card ID (e.g., BS4-012 -> bs4)
        booster = ""
        if card_id:
            parts = card_id.split("-")
            if len(parts) > 0:
                booster = parts[0].lower()  # BS4 -> bs4
        
        # Extract and clean card data
        processed_card = {
            "id": card.get("id"),
            "elementId": card.get("elementId"),
            "title": card.get("title", ""),
            "field_artistTitle": card.get("field_artistTitle", ""),
            "field_productTitle": card.get("field_productTitle", ""),
            "field_cardDesc": card.get("field_cardDesc", ""),
            "field_rare_tzsrperf": card.get("field_rare_tzsrperf", ""),
            "field_hp_zbxcocvx": card.get("field_hp_zbxcocvx", ""),
            "field_grade": card.get("field_grade", ""),
            "cardType": card.get("cardType", ""),
            "cardTypeTitle": card.get("cardTypeTitle", ""),
            "energyType": card.get("energyType", ""),
            "energyTypeTitle": card.get("energyTypeTitle", ""),
            "cardLevel": card.get("cardLevel", ""),
            "cardLevelTitle": card.get("cardLevelTitle", ""),
            "cardUid": card_uid,
            "cardId": card_id,
            "booster": booster
        }
        
        # Clean HTML from description
        if processed_card["field_cardDesc"]:
            # Basic HTML tag removal (you might want to use BeautifulSoup for better cleaning)
            import re
            processed_card["field_cardDesc"] = re.sub(r'<[^>]+>', '', processed_card["field_cardDesc"])
            processed_card["field_cardDesc"] = processed_card["field_cardDesc"].strip()
        
        # Download and upload image to GCS if URL exists
        card_image_url = card.get("cardImage", "")
        if card_image_url:
            try:
                # Use cardUid as filename (e.g., BS4-012_ALT)
                filename = processed_card["cardUid"]
                filepath = f"CRBTCG/"  # Cookie Run Braverse TCG
                processed_card["urlimage"] = upload_image_to_gcs(
                    image_url=card_image_url, 
                    filename=filename, 
                    filepath=filepath
                )
                print(f"✅ Image uploaded: {filename}")
            except Exception as e:
                print(f"⚠️ Image upload failed for {processed_card['cardUid']}: {str(e)}")
                processed_card["urlimage"] = card_image_url
        
        return processed_card
        
    except Exception as e:
        print(f"❌ Error processing card: {str(e)}")
        return None

def check_and_scrape_new_cards(upload_to_db=True):
    """Check for new Cookie Run cards and scrape them"""
    print("🍪 Starting Cookie Run card check...")
    
    # Get latest dates from both sources
    local_latest = get_latest_date_local()
    github_latest = get_latest_date_github()
    
    # Use the most recent date available
    latest_date = max(local_latest, github_latest or 0)
    print(f"📅 Date comparison:")
    print(f"   Local latest: {local_latest} ({datetime.fromtimestamp(local_latest).strftime('%Y-%m-%d %H:%M:%S') if local_latest > 0 else 'None'})")
    print(f"   GitHub latest: {github_latest} ({datetime.fromtimestamp(github_latest).strftime('%Y-%m-%d %H:%M:%S') if github_latest and github_latest > 0 else 'None'})")
    print(f"   Using latest: {latest_date} ({datetime.fromtimestamp(latest_date).strftime('%Y-%m-%d %H:%M:%S') if latest_date > 0 else 'None'})")
    print(f"   Will process cards with postDate > {latest_date}")
    
    # Fetch card data from API
    try:
        print("🔍 Fetching cards from Cookie Run API...")
        api_url = "https://cookierunbraverse.com/en/cardList/card.json"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        cards_data = response.json()
        print(f"📦 Retrieved {len(cards_data)} total cards from API")
        
    except Exception as e:
        print(f"❌ Error fetching cards: {str(e)}")
        return []
    
    # Filter for cards with postDate AFTER the latest recorded date
    print(f"🔍 Filtering cards with postDate > {latest_date}...")
    new_cards = []
    
    for card in cards_data:
        card_post_date = card.get("postDate", 0)
        if card_post_date > latest_date:
            new_cards.append(card)
            card_title = card.get("title", "Unknown")
            card_no = card.get("field_cardNo_suyeowsc", "Unknown")
            readable_date = datetime.fromtimestamp(card_post_date).strftime('%Y-%m-%d %H:%M:%S')
            print(f"  ✅ New card found: {card_title} ({card_no}) - {readable_date} (postDate: {card_post_date})")
    
    if not new_cards:
        print("✅ No new cards found. Database is up to date.")
        print(f"   All cards have postDate <= {latest_date}")
        return []
    
    print(f"🆕 Total new cards to process: {len(new_cards)}")
    
    # Sort by postDate to process oldest first
    new_cards.sort(key=lambda x: x.get("postDate", 0))
    print("📊 Processing cards in chronological order...")
    
    processed_cards = []
    latest_post_date = latest_date
    
    for i, card in enumerate(new_cards, 1):
        card_no = card.get("field_cardNo_suyeowsc", "Unknown")
        card_title = card.get("title", "Unknown")
        post_date = card.get("postDate", 0)
        
        print(f"  🎴 Processing ({i}/{len(new_cards)}): {card_title} ({card_no})")
        print(f"      postDate: {post_date} ({datetime.fromtimestamp(post_date).strftime('%Y-%m-%d %H:%M:%S')})")
        
        processed_card = process_card_data(card)
        if processed_card:
            processed_cards.append(processed_card)
            # Update latest_post_date with the newest card processed
            if post_date > latest_post_date:
                latest_post_date = post_date
                print(f"      📅 Updated latest date to: {latest_post_date}")
    
    # Upload to MongoDB if requested
    if upload_to_db and processed_cards:
        collection_value = os.getenv('C_COOKIERUN')
        if collection_value:
            try:
                upload_to_mongo(
                    data=processed_cards,
                    collection_name=collection_value
                )
                print(f"📤 Uploaded {len(processed_cards)} cards to MongoDB")
            except Exception as e:
                print(f"❌ MongoDB upload failed: {str(e)}")
        else:
            print("⚠️ MongoDB collection name not found in environment variables")
    
    # Update latest date in both local and GitHub
    if processed_cards:
        save_latest_date_local(latest_post_date)
        update_latest_date_github(latest_post_date)
        
        print(f"\n🎯 PROCESSING COMPLETE")
        print(f"📊 New cards processed: {len(processed_cards)}")
        print(f"📅 Updated latest date: {latest_post_date} ({datetime.fromtimestamp(latest_post_date).strftime('%Y-%m-%d %H:%M:%S')})")
        print(f"💾 Database upload: {'✅' if upload_to_db else '⚠️ (Disabled)'}")
    
    return processed_cards

def scrape_specific_card(card_id):
    """Scrape a specific card by ID"""
    try:
        api_url = "https://cookierunbraverse.com/en/cardList/card.json"
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        
        cards_data = response.json()
        card = next((c for c in cards_data if c.get("id") == card_id), None)
        
        if not card:
            print(f"❌ Card with ID {card_id} not found")
            return None
        
        return process_card_data(card)
        
    except Exception as e:
        print(f"❌ Error fetching card {card_id}: {str(e)}")
        return None
if __name__ == "__main__":
    print("🍪 Cookie Run Card Scraper Initialized")
    # Run the actual check with upload disabled for review
    check_and_scrape_new_cards()
