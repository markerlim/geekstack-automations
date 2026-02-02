import requests
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.googlecloudservice import upload_image_to_gcs

def process_card_data(card):
    """Process and clean card data"""
    try:
        # Get card number and transform it for cardId and cardUid
        card_no = card.get("card_no", "")
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
        
        # Extract booster series from card ID (e.g., BS9-001 -> bs9)
        # Special case: if card_grade is "PROMOTION", booster should be "promo"
        booster = ""
        card_grade = card.get("card_grade", "")
        
        if card_grade == "PROMOTION":
            booster = "promo"
        elif card_id:
            parts = card_id.split("-")
            if len(parts) > 0:
                booster = parts[0].lower()  # BS9 -> bs9
        
        # Extract and clean card data
        processed_card = {
            "card_idx": card.get("card_idx"),
            "site_lang": card.get("site_lang"),
            "card_name": card.get("card_name", ""),
            "card_artist_title": card.get("card_artist_title", ""),
            "card_product_title": card.get("card_product_title", ""),
            "card_skill_text": card.get("card_skill_text") or  "-",
            "card_attack_text": card.get("card_attack_text") or "-",
            "card_flip": card.get("card_flip") or "-",
            "card_rare": card.get("card_rare", ""),
            "card_grade": card.get("card_grade", ""),
            "card_hp": card.get("card_hp") or "-",
            "card_level": card.get("card_level") or "-",
            "card_type": card.get("card_type", ""),
            "card_energy_type": card.get("card_energy_type", ""),
            "card_color": card.get("card_color") or "-",
            "cardUid": card_uid,
            "cardId": card_id,
            "booster": booster
        }
        
        # Download and upload image to GCS if URL exists
        card_image_url = card.get("card_image", "")
        if card_image_url:
            try:
                # Use cardUid as filename (e.g., BS9-001_ALT)
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
        api_url = "https://cookierunbraverse.com/data/json/cardList_asia.json"
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        
        api_response = response.json()
        cards_data = api_response.get("cardList", [])
        card = next((c for c in cards_data if c.get("card_idx") == card_id), None)
        
        if not card:
            print(f"❌ Card with ID {card_id} not found")
            return None
        
        return process_card_data(card)
        
    except Exception as e:
        print(f"❌ Error fetching card {card_id}: {str(e)}")
        return None
    