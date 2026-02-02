import requests

import os
import sys
from cookierunscrape import process_card_data
from datetime import datetime

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.github_service import GitHubService
from service.mongo_service import MongoService

# Initialize Service Layer
github_service = GitHubService()
mongo_service = MongoService()

# Variables
FILE_PATH = "cookierundb/latestdate.json"

existing_values, file_sha = github_service.load_json_file(FILE_PATH)
latest_date = existing_values.get("latestDate", 0)

# Step 1: Fetch card data from API
try:
    print("🔍 Fetching cards from Cookie Run API...")
    api_url = "https://cookierunbraverse.com/data/json/cardList_asia.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    }
        
    response = requests.get(api_url, headers=headers, timeout=30)
    response.raise_for_status()
        
    api_response = response.json()
    cards_data = api_response.get("cardList", [])
    print(f"📦 Retrieved {len(cards_data)} total cards from API")
        
except Exception as e:
    print(f"❌ Error fetching cards: {str(e)}")
    
# Step 2: Filter for cards with update_dt AFTER the latest recorded date
print(f"🔍 Filtering cards with update_dt > {latest_date}...")
new_cards = []
    
for card in cards_data:
    # Parse ISO 8601 timestamp and convert to epoch
    update_dt_str = card.get("update_dt", "")
    if update_dt_str:
        try:
            card_update_date = int(datetime.fromisoformat(update_dt_str.replace('Z', '+00:00')).timestamp())
        except:
            card_update_date = 0
    else:
        card_update_date = 0
    
    if card_update_date > latest_date:
        new_cards.append(card)
        card_title = card.get("card_name", "Unknown")
        card_no = card.get("card_no", "Unknown")
        readable_date = datetime.fromtimestamp(card_update_date).strftime('%Y-%m-%d %H:%M:%S')
        print(f"  ✅ New card found: {card_title} ({card_no}) - {readable_date} (update_dt: {card_update_date})")
    
if not new_cards:
    print("✅ No new cards found. Database is up to date.")
    print(f"   All cards have update_dt <= {latest_date}")
    
print(f"🆕 Total new cards to process: {len(new_cards)}")
    
# Step 3: Sort by update_dt to process oldest first
def get_update_timestamp(card):
    try:
        update_dt_str = card.get("update_dt", "")
        return int(datetime.fromisoformat(update_dt_str.replace('Z', '+00:00')).timestamp())
    except:
        return 0

new_cards.sort(key=get_update_timestamp)
print("📊 Processing cards in chronological order...")

# Ask for confirmation before processing
if len(new_cards) > 0:
    print("\n" + "="*60)
    print(f"⚠️  About to process {len(new_cards)} card(s)")
    print("="*60)
    response = input("Proceed with processing? (yes/no): ").strip().lower()
    if response not in ["yes", "y"]:
        print("❌ Processing cancelled by user")
        sys.exit(0)
    print("✅ Proceeding with processing...\n")
    
processed_cards = []
latest_post_date = latest_date

# Step 4: Process each new card    
for i, card in enumerate(new_cards, 1):
    card_no = card.get("card_no", "Unknown")
    card_title = card.get("card_name", "Unknown")
    
    # Parse ISO 8601 timestamp
    update_dt_str = card.get("update_dt", "")
    if update_dt_str:
        try:
            update_date = int(datetime.fromisoformat(update_dt_str.replace('Z', '+00:00')).timestamp())
        except:
            update_date = 0
    else:
        update_date = 0
        
    print(f"  🎴 Processing ({i}/{len(new_cards)}): {card_title} ({card_no})")
    print(f"      update_dt: {update_date} ({datetime.fromtimestamp(update_date).strftime('%Y-%m-%d %H:%M:%S')})")
        
    processed_card = process_card_data(card)
    if processed_card:
        processed_cards.append(processed_card)
        # Update latest_post_date with the newest card processed
        if update_date > latest_post_date:
            latest_post_date = update_date
            print(f"      📅 Updated latest date to: {latest_post_date}")
    
# Step 5: Upload processed cards to MongoDB
if processed_cards:
    collection_value = os.getenv('C_COOKIERUN')
    if collection_value:
        try:
        # Upload new cards to MongoDB
            mongo_service.upload_data(
                data=processed_cards,
                collection_name=collection_value,
                backup_before_upload=True
                )
            # Step 6: Report results
            print(f"📤 Uploaded {len(processed_cards)} cards to MongoDB")
        except Exception as e:
                print(f"❌ MongoDB operation failed: {str(e)}")
        else:
            print("⚠️ MongoDB collection name not found in environment variables")
    
if processed_cards:
    # Step 7: Update series.json with the new scraped values
    updated_content = {"latestDate": latest_post_date}
    # Step 8: Commit the change to GitHub using GitHubService
    commit_message = "Update {} with latest postDate after scraping".format(FILE_PATH)
    success = github_service.update_file(FILE_PATH, updated_content, commit_message, file_sha)

    if success:
        print(f"\n🎯 PROCESSING COMPLETE")
        print(f"📊 New cards processed: {len(processed_cards)}")
        print(f"📅 Updated latest date: {latest_post_date} ({datetime.fromtimestamp(latest_post_date).strftime('%Y-%m-%d %H:%M:%S')})")
    else:
        print("Error updating file on GitHub.")

    

