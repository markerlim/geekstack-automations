import requests

import os
import sys

from cookierunscrape import process_card_data
from service.github_service import GitHubService
from datetime import datetime

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.mongoservice import upload_to_mongo

# Initialize GitHub service
github_service = GitHubService()
FILE_PATH = "cookierundb/latestdate.json"

existing_values, file_sha = github_service.load_json_file(FILE_PATH)
latest_date = existing_values.get("latestDate", 0)
    
# Step 1: Fetch card data from API
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
    
# Step 2: Filter for cards with postDate AFTER the latest recorded date
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
    
print(f"🆕 Total new cards to process: {len(new_cards)}")
    
# Step 3: Sort by postDate to process oldest first
new_cards.sort(key=lambda x: x.get("postDate", 0))
print("📊 Processing cards in chronological order...")
    
processed_cards = []
latest_post_date = latest_date

# Step 4: Process each new card    
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
    
# Step 5: Upload processed cards to MongoDB
if processed_cards:
    collection_value = os.getenv('C_COOKIERUN')
    if collection_value:
        try:
        # Upload new cards to MongoDB
            upload_to_mongo(
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

    

