import requests
import json
import os
from bs4 import BeautifulSoup
import sys

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.github_service import GitHubService
from service.api_service import ApiService
from service.translationservice import translate_text
from scrapers.unionarena.unionarenascrape import scrape_unionarena_cards

# Initialize GitHub service
github_service = GitHubService()
api_service = ApiService("https://www.unionarena-tcg.com")
FILE_PATH = "unionarenadb/series.json"

def translate_new_series(series_name):
    """Translate Japanese series name to English"""
    try:
        english_name = translate_text(series_name, src_lang="ja", dest_lang="en")
        print(f"Translated: '{series_name}' -> '{english_name}'")
        return english_name
    except Exception as e:
        print(f"Failed to translate '{series_name}': {e}")
        return series_name  # Fallback to original name

# Main execution logic wrapped in a function
def main():
    try:
        # Step 1: Scrape the current list of series values from the Union Arena site
        response = api_service.get("/jp/cardlist/")
        soup = BeautifulSoup(response['data'], 'html.parser')
        
        # Find all series options in the filter list
        series_options = soup.select('div.selectTitleCol option[value]')
        scraped_series_list = [option['value'] for option in series_options if option['value']]  # Japanese series names
        
        print(f"Scraped {len(scraped_series_list)} series from website")
        
        # Step 2: Get the existing series.json file from GitHub (now as key-value pairs)
        github_content, file_sha = github_service.load_json_file(FILE_PATH)
        
        if github_content is None:
            print(f"Error fetching file from GitHub: {FILE_PATH}")
            return
        
        # Parse existing series mapping (Japanese -> English)
        try:
            existing_series_map = json.loads(github_content)
        except json.JSONDecodeError:
            print("Error: Existing series.json is not valid JSON, treating as empty")
            existing_series_map = {}
        
        print(f"Current series mapping has {len(existing_series_map)} entries")
        
        # Step 3: Find new series not in current mapping
        new_series = [series for series in scraped_series_list if series not in existing_series_map.keys()]
        
        if new_series:
            print(f"Found {len(new_series)} new series:")
            
            # Create updated mapping with translations
            updated_series_map = existing_series_map.copy()
            
            for japanese_series in new_series:
                print(f"  - Processing: {japanese_series}")
                # Translate to English
                english_series = translate_new_series(japanese_series)
                updated_series_map[japanese_series] = english_series
                print(f"    Added mapping: '{japanese_series}' -> '{english_series}'")
            
            # Step 4: Update the GitHub file with new mappings
            updated_content = json.dumps(updated_series_map, ensure_ascii=False, indent=2)
            
            commit_message = f"Add {len(new_series)} new series mappings: {', '.join([f'{jp}->{updated_series_map[jp]}' for jp in new_series[:2]])}{'...' if len(new_series) > 2 else ''}"
            
            success = github_service.update_file(FILE_PATH, updated_content, commit_message)
            
            if success:
                print("\n✓ Successfully updated series.json on GitHub with new mappings")
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

if __name__ == "__main__":
    main()