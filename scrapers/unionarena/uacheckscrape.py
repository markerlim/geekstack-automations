import requests
import json
import os
from bs4 import BeautifulSoup
import sys

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.github_service import GitHubService
from service.api_service import ApiService
from service.openrouter_service import OpenRouterService
from service.notification_service import NotificationService
from service.mongo_service import MongoService
from scrapers.unionarena.unionarenascrape import scrape_unionarena_cards,navigate_to_selected_cardlist,clean_out_AP
from dotenv import load_dotenv
load_dotenv()

# Initialize services
github_service = GitHubService()
api_service = ApiService("https://www.unionarena-tcg.com")
openrouter_service = OpenRouterService()
notification_service = NotificationService()
mongo_service = MongoService()

# Variables
FILE_PATH = "unionarenadb/series.json"
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

# Main execution logic wrapped in a function
def check_for_new_series():
    try:
        # Step 1: Scrape the current list of series values from the Union Arena site
        response = api_service.get("/jp/cardlist/")
        soup = BeautifulSoup(response['data'], 'html.parser')
        
        # Find all series options in the filter list
        series_options = soup.select('div.selectTitleCol option[value]')
        scraped_series_list = [option['value'] for option in series_options if option['value']]  # Japanese series names
        
        print(f"Scraped {len(scraped_series_list)} series from website")
        
        # Step 2: Get the existing series.json file from GitHub
        github_content, file_sha = github_service.load_json_file(FILE_PATH)
        
        if github_content is None:
            print(f"Error fetching file from GitHub: {FILE_PATH}")
            return
        
        # Handle both array and object formats
        if isinstance(github_content, list):
            # Convert array to mapping format (all titles map to themselves initially)
            existing_series_map = {title: title for title in github_content}
            print(f"Converted array of {len(github_content)} series to mapping format")
        else:
            # Already in mapping format
            existing_series_map = github_content
            print(f"Current series mapping has {len(existing_series_map)} entries")
        
        # Step 3: Find new series not in current mapping
        new_series = [series for series in scraped_series_list if series not in existing_series_map.keys()]
        
        if new_series:
            print(f"Found {len(new_series)} new series:")
            for series in new_series:
                print(f"  - {series}")
            
            # Translate new series using OpenRouter batch translation
            print("\nTranslating new series using OpenRouter...")
            new_translations = translate_new_series_batch(new_series)
            
            # Create updated mapping
            updated_series_map = existing_series_map.copy()
            updated_series_map.update(new_translations)
            
            # Step 4: Update the GitHub file with new mappings
            updated_content = json.dumps(updated_series_map, ensure_ascii=False, indent=2)
            
            commit_message = f"Add {len(new_series)} new series via OpenRouter: {', '.join(new_series[:2])}{'...' if len(new_series) > 2 else ''}"
            
            success = github_service.update_file(FILE_PATH, updated_content, commit_message, file_sha)
            
            if success:
                print(f"\n✓ Successfully updated series.json on GitHub")
                print(f"Added {len(new_series)} new series translations")
                notification_service.send_email_notification(
                    subject="Union Arena Series.json Updated",
                    message=f"Added {len(new_series)} new series translations to series.json on GitHub."
                )
                print(f"Total series mappings: {len(updated_series_map)}")
            else:
                print("✗ Error updating series.json on GitHub")
                
        else:
            print("No new series found. Series mapping is up to date.")
            
        # Optional: Check for removed series
        existing_keys = set(existing_series_map.keys())
        scraped_keys = set(scraped_series_list)
        removed_series = existing_keys - scraped_keys
        
        if removed_series:
            print(f"\nWarning: {len(removed_series)} series exist in mapping but not on website:")
            for series in sorted(removed_series):
                print(f"  - {series} -> {existing_series_map[series]}")
                
    except Exception as e:
        print(f"Error in main execution: {e}")
        import traceback
        traceback.print_exc()

def check_for_watchlist_updates():
    try:
        # Load watchlist from GitHub
        watchlist, _ = github_service.load_json_file("unionarenadb/watchlist.json")
        if not watchlist:
            print("Watchlist is empty or could not be loaded.")
            return
        for jp_title, en_title in watchlist.items():
            print(f"Watchlist entry: {jp_title} -> {en_title}")
            card_numbers_with_AP = navigate_to_selected_cardlist(jp_title)
            card_numbers = clean_out_AP(card_numbers_with_AP)
            validation_result = mongo_service.validate_field(C_UNIONARENA,"anime",en_title)
            exists = validation_result['exists']
            count = validation_result['count']
            if( int(count) < len(card_numbers)) or (not exists):
                print(f"Discrepancy found for '{jp_title}' ({en_title}): MongoDB has {count} cards, scraped {len(card_numbers)} cards.")
                scrape_unionarena_cards(jp_title)
        else:
            print("No updates found in watchlist.")
            
    except Exception as e:
        print(f"Error checking watchlist updates: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_for_new_series()
    check_for_watchlist_updates()