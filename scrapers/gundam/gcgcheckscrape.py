import os
from bs4 import BeautifulSoup
import sys

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.github_service import GitHubService
from service.mongo_service import MongoService
from service.api_service import ApiService
from gundamscrape import scrape_gundam_cards

# Variables
FILE_PATH = "gundamtcgdb/series.json"
BASE_URL = "https://www.gundam-gcg.com"
C_GUNDAM = os.getenv('C_GUNDAM')

# Initialize GitHub service
mongo_service = MongoService()
api_service = ApiService(BASE_URL)

def check_for_new_series():
    """Check for new Gundam series by comparing scraped data with mongoDB distinct values"""
    # Step 1: Scrape the current list of series values from the Gundam site
    response = api_service.get("/asia-en/cards")
    soup = BeautifulSoup(response['data'], 'html.parser')

    # Find all package links in the filter list
    package_links = soup.select('.filterListItems.js-add--toggleElem a.js-selectBtn-package')
    scraped_values = [link['data-val'] for link in package_links if link['data-val']]  # Get non-empty data-val values

    # Step 2: Get the existing series.json file from GitHub using GitHubService
    #existing_values, file_sha = github_service.load_json_file(FILE_PATH)
    existing_values = mongo_service.get_unique_values(C_GUNDAM,"package")
    if existing_values is None:
        print(f"Error fetching data from MongoDB collection: {C_GUNDAM}")
        exit()

    # Step 4: Convert both to sets for comparison
    scraped_set = set(scraped_values)
    existing_set = set(existing_values)

    # Step 5: Find differences
    missing_in_json = list(scraped_set - existing_set)

    if missing_in_json:
        print("Missing in series.json:")
        for val in sorted(missing_in_json):
            print(f"  - {val}")
            # Call the scrape_gundam_cards function for each missing value
            scrape_gundam_cards(val)

def check_for_watchlist():
    watchlist = ["619701","619801","619901","619103"]

    for package_value in watchlist:
        print(f"Checking package: {package_value}")
        scrape_gundam_cards(package_value)

if __name__ == "__main__":
    check_for_new_series()
    check_for_watchlist()