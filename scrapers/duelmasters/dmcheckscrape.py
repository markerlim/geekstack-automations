import json
import os
import sys
from bs4 import BeautifulSoup
import requests

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from duelmasterscrape import startscraping
from scrapers.duelmasters.dmcovercheckscrape import duelmaster_cover_scrape
from service.utils_service import find_missing_values
from service.mongoservice import check_unique_sets

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
    # Get unique boosters from MongoDB (source of truth)
    collection_name = os.getenv("C_DUELMASTERS")
    if not collection_name:
        print("❌ MongoDB collection name not found in environment variables")
        return
        
    mongo_values = check_unique_sets(collection_name, "booster")
    website_values = scrape_website_values()

    if not mongo_values:
        print("❌ No data loaded from MongoDB.")
        return
    if not website_values:
        print("❌ No data scraped from website.")
        return

    missing_values = find_missing_values(mongo_values, website_values)

    print("\n=== 📋 Missing Values Report ===")
    print(f"📦 Total series in MongoDB: {len(mongo_values)}")
    print(f"🌍 Total series on website: {len(website_values)}")
    print(f"❓ Missing series count: {len(missing_values)}")

    if missing_values:
        print("\n⚠️ Missing series:")
        for val in missing_values:
            print(f"- {val}")

        # Run scraper for missing boosters
        startscraping(booster_list=missing_values)


    else:
        print("✅ All series from website already exist in MongoDB!")


if __name__ == "__main__":
    duelmaster_cover_scrape()
    run_check()
