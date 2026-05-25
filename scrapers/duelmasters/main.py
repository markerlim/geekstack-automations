import json
import os
import sys
from bs4 import BeautifulSoup
import requests

# Add project root to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from scrapers.duelmasters.pipelines.a_scrape_covers import duelmaster_cover_scrape
from scrapers.duelmasters.pipelines.b_scrape_cards import startscraping
from service.utils_service import find_missing_values
from service.github_service import GitHubService

github_service = GitHubService()
FILE_PATH = "duelmasterdb/series.json"

def scrape_website_values():
    print("🌐 Scraping website values...")
    url = "https://dm.takaratomy.co.jp/card/"
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        select = soup.find('select', {'name': 'products'})
        if not select:
            print("❌ Could not find the 'products' dropdown.")
            return []

        return [opt.get('value').strip() for opt in select.find_all('option') if opt.get('value')]
    except Exception as e:
        print(f"❌ Failed to scrape website: {e}")
        return []

def run_check():
    json_data,file_sha = github_service.load_json_file(FILE_PATH)
    website_values = scrape_website_values()

    if not json_data:
        print("❌ No data loaded from series.json.")
        return
    if not website_values:
        print("❌ No data scraped from website.")
        return

    missing_values = find_missing_values(json_data, website_values)

    print("\n=== 📋 Missing Values Report ===")
    print(f"📦 Total series in JSON: {len(json_data)}")
    print(f"🌍 Total series on website: {len(website_values)}")
    print(f"❓ Missing series count: {len(missing_values)}")

    if missing_values:
        print("\n⚠️ Missing series:")
        for val in missing_values:
            print(f"- {val}")

        # Run scraper for missing boosters
        startscraping(booster_list=missing_values)

        # Step 7: Update series.json with the new scraped values
        updated_series = list(set(json_data) | set(website_values))
        updated_content = json.dumps(updated_series, indent=4)  
        # Step 8: Commit the change to GitHub using GitHubService
        commit_message = "Update series.json with latest Duel Masters series"
        success = github_service.update_file(FILE_PATH, updated_content, commit_message, file_sha)
        if success:
            print("\n🎯 PROCESSING COMPLETE")
            print(f"📊 New series added: {len(missing_values)}")
        else:
            print("Error updating file on GitHub.")

    else:
        print("✅ All series from website already exist in series.json!")


if __name__ == "__main__":
    duelmaster_cover_scrape()
    run_check()
