import requests
import json
import os
from bs4 import BeautifulSoup
import sys

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.api_service import ApiService
from service.openrouter_service import OpenRouterService
from service.notification_service import NotificationService
from service.mongo_service import MongoService
from scrapers.unionarena.unionarenascrape import scrape_unionarena_cards,navigate_to_selected_cardlist,clean_out_AP
from dotenv import load_dotenv
load_dotenv()

api_service = ApiService("https://www.unionarena-tcg.com")
openrouter_service = OpenRouterService()
notification_service = NotificationService()
mongo_service = MongoService()

C_UNIONARENA = os.getenv('C_UNIONARENA')

def translate_new_series_batch(series_list):
    """Translate a list of Japanese series names to English using OpenRouter"""
    try:
        response = openrouter_service.translate_titles_batch(
            titles=series_list,
            source_lang="Japanese",
            target_lang="English"
        )
        
        if response.get('success'):
            translated_data = response.get('translated_data', {})
            # Convert the response format to a mapping
            mapping = {}
            for i, original_title in enumerate(series_list):
                key = f"title_{i}"
                translated = translated_data.get(key, original_title)
                mapping[original_title] = translated
                print(f"Translated: '{original_title}' -> '{translated}'")
            return mapping
        else:
            print(f"OpenRouter translation failed: {response.get('error')}")
            return {title: title for title in series_list}  # Fallback to originals
            
    except Exception as e:
        print(f"Failed to translate series batch: {e}")
        return {title: title for title in series_list}  # Fallback to originals

def check_for_watchlist_updates():
    try:
        # Hardcoded watchlist for local testing
        watchlist = {
    "キングダム": "Kingdom"
        }
        
        discrepancies_found = False
        
        for jp_title, en_title in watchlist.items():
            print(f"Watchlist entry: {jp_title} -> {en_title}")
            card_numbers_with_AP = navigate_to_selected_cardlist(jp_title)
            card_numbers = clean_out_AP(card_numbers_with_AP)
            
            # Get existing cards from database
            existing_cards = mongo_service.get_unique_values_scoped(C_UNIONARENA, "anime", en_title, "cardcode")
            if existing_cards is None:
                existing_cards = []
            existing_cards_set = set(existing_cards)
            scraped_cards_set = set(card_numbers)
            
            # Check for missing cards (cards in scraped data but not in database)
            missing_cards = scraped_cards_set - existing_cards_set
            extra_cards = existing_cards_set - scraped_cards_set
            
            validation_result = mongo_service.validate_field(C_UNIONARENA,"anime",en_title)
            exists = 0 #validation_result['exists']
            count = 0 #validation_result['count']
            if( int(count) < len(card_numbers)) or (not exists) or missing_cards:
                discrepancies_found = True
                print(f"Discrepancy found for '{jp_title}' ({en_title}): MongoDB has {count} cards, scraped {len(card_numbers)} cards.")
                if missing_cards:
                    print(f"  Missing cards in database: {sorted(list(missing_cards))[:10]}")
                    if len(missing_cards) > 10:
                        print(f"  ... and {len(missing_cards) - 10} more missing cards")
                if extra_cards:
                    print(f"  Extra cards in database: {sorted(list(extra_cards))[:10]}")
                    if len(extra_cards) > 10:
                        print(f"  ... and {len(extra_cards) - 10} more extra cards")
                scrape_unionarena_cards(jp_title)
        
        if not discrepancies_found:
            print("No updates found in watchlist.")
            
    except Exception as e:
        print(f"Error checking watchlist updates: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_for_watchlist_updates()