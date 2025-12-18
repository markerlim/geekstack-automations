import requests
import json
import os
from bs4 import BeautifulSoup
import sys

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.github_service import GitHubService
from gundamscrape import scrape_gundam_cards

# Initialize GitHub service
github_service = GitHubService()
FILE_PATH = "gundamtcgdb/series.json"

# Step 1: Scrape the current list of series values from the Gundam site
series_url = "https://www.gundam-gcg.com/asia-en/cards"
response = requests.get(series_url)
soup = BeautifulSoup(response.content, 'html.parser')

# Find all package links in the filter list
package_links = soup.select('.filterListItems.js-add--toggleElem a.js-selectBtn-package')
scraped_values = [link['data-val'] for link in package_links if link['data-val']]  # Get non-empty data-val values

# Step 2: Get the existing series.json file from GitHub using GitHubService
existing_values, file_sha = github_service.load_json_file(FILE_PATH)

if existing_values is None:
    print(f"Error fetching file from GitHub: {FILE_PATH}")
    exit()

# Step 4: Convert both to sets for comparison
scraped_set = set(scraped_values)
existing_set = set(existing_values)

# Step 5: Find differences
missing_in_json = list(scraped_set - existing_set)
extra_in_json = list(existing_set - scraped_set)

# Step 6: Report results
if not missing_in_json and not extra_in_json:
    print("same")
else:
    print("different")
    if missing_in_json:
        print("Missing in series.json:")
        for val in sorted(missing_in_json):
            print(f"  - {val}")
            # Call the scrape_gundam_cards function for each missing value
            scrape_gundam_cards(val)

    if extra_in_json:
        print("Extra in series.json:")
        for val in sorted(extra_in_json):
            print(f"  - {val}")

    # Step 7: Update series.json with the new scraped values
    updated_series = list(scraped_set)
    updated_content = json.dumps(updated_series, indent=4)

    # Step 8: Commit the change to GitHub using GitHubService
    commit_message = "Update series.json with new Gundam series"
    success = github_service.update_file(FILE_PATH, updated_content, commit_message, file_sha)

    if success:
        print("\nseries.json has been updated on GitHub.")
    else:
        print("Error updating file on GitHub.")