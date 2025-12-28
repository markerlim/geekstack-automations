import requests
from bs4 import BeautifulSoup
import os
import sys
import re
from urllib.parse import urljoin

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.mongo_service import MongoService
from service.api_service import ApiService

# Environment Variables
C_GUNDAM = 'test'
BASE_URL = "https://www.gundam-gcg.com"

# Initialize Service Layer
mongo_service = MongoService()
api_service = ApiService(BASE_URL)

def extract_card_id_from_uid(card_uid):
    """Extract the base card ID from cardUid (e.g., GD02-001_p1 -> GD02-001)"""
    if '_p' in card_uid:
        return card_uid.split('_p')[0]
    return card_uid

def extract_effect_from_detail_page(card_id):
    """Scrape effect text from Gundam card detail page"""
    try:
        detail_url = f"detail.php?detailSearch={card_id}"
        print(f"🔍 Fetching effect for {card_id} from {detail_url}")
        
        detail_response = api_service.get(f"/asia-en/cards/{detail_url}")
        detail_soup = BeautifulSoup(detail_response['data'], 'html.parser')
        
        # Extract overview/effect text
        overview_element = detail_soup.select_one('.cardDataRow.overview .dataTxt')
        if overview_element:
            # Get the HTML content and process it
            effect_html = str(overview_element)
            
            # Replace <br> with \n, but not when followed by whitespace and </div>
            # This regex matches <br> that is NOT followed by optional whitespace and </div>
            effect_html = re.sub(r'<br/>(?!\s*</div>)', '\n', effect_html)
            
            # Parse the modified HTML and get text
            effect_soup = BeautifulSoup(effect_html, 'html.parser')
            effect = effect_soup.get_text(strip=True)
            
            # Clean up any remaining HTML entities
            effect = effect.replace('&lt;', '<').replace('&gt;', '>')
            
            return effect
        else:
            print(f"❌ No effect element found for {card_id}")
            return None
            
    except Exception as e:
        print(f"❌ Error fetching effect for {card_id}: {str(e)}")
        return None

def update_all_card_effects():
    """Update effect text for all cards in MongoDB"""
    if not C_GUNDAM:
        print("❌ C_GUNDAM environment variable not found")
        return
    
    try:
        # Get all cardUIDs from MongoDB
        print("📊 Fetching all cardUIDs from MongoDB...")
        all_card_uids = mongo_service.get_unique_values(C_GUNDAM, "cardUid")
        print(f"Found {len(all_card_uids)} cards in database")
        
        success_count = 0
        error_count = 0
        
        for i, card_uid in enumerate(all_card_uids, 1):
            try:
                # Extract base card ID for detail page lookup
                card_id = extract_card_id_from_uid(card_uid)
                
                print(f"\n[{i}/{len(all_card_uids)}] Processing {card_uid} (ID: {card_id})")
                
                # Scrape effect from detail page
                effect = extract_effect_from_detail_page(card_id)
                
                if effect:
                    # Update MongoDB document
                    update_result = mongo_service.update_by_field(
                        C_GUNDAM,
                        "cardUid", 
                        card_uid,
                        update_data={"effect": effect}
                    )
                    
                    if update_result:
                        print(f"✅ Updated effect for {card_uid}")
                        print(f"📝 Effect: {effect[:100]}...")
                        success_count += 1
                    else:
                        print(f"❌ Failed to update {card_uid} in database")
                        error_count += 1
                else:
                    print(f"⚠️ No effect found for {card_uid}")
                    error_count += 1
                    
            except Exception as e:
                print(f"❌ Error processing {card_uid}: {str(e)}")
                error_count += 1
        
        print(f"\n🎉 Update complete!")
        print(f"✅ Successfully updated: {success_count} cards")
        print(f"❌ Errors: {error_count} cards")
        
    except Exception as e:
        print(f"❌ Fatal error in update process: {str(e)}")

if __name__ == "__main__":
    print("🚀 Starting Gundam card effect update process...")
    update_all_card_effects()