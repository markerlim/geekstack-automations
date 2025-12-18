import requests
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.googlecloudservice import upload_image_to_gcs

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
        # Special case: if field_grade is "PROMOTION", booster should be "promo"
        booster = ""
        field_grade = card.get("field_grade", "")
        
        if field_grade == "PROMOTION":
            booster = "promo"
        elif card_id:
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
    