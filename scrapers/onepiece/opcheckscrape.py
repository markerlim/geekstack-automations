import requests
import json
import os
import base64
from bs4 import BeautifulSoup

from onepiecescrape import scrape_onepiece_cards

# GitHub repository details
REPO_OWNER = "markerlim"
REPO_NAME = "geekstack-automations"
FILE_PATH = "onepiecedb/series.json"
BRANCH = "main"  # Replace with your branch name
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # Ensure GITHUB_TOKEN is set as an environment variable

# GitHub API URL for file content (raw URL will not work directly for API requests)
url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}?ref={BRANCH}"

# Step 1: Scrape the current list of series values from the site
series_url = "https://asia-en.onepiece-cardgame.com/cardlist/"
response = requests.get(series_url)
soup = BeautifulSoup(response.content, 'html.parser')

select = soup.find('select', {'name': 'series'})
scraped_values = [option.get('value') for option in select.find_all('option') if option.get('value')]

# Step 2: Get the existing series.json file from GitHub via API
response = requests.get(url, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"})

if response.status_code == 200:
    file_data = response.json()
    print(file_data)  # Debugging: Check the returned content
else:
    print(f"Error fetching file from GitHub: {response.status_code}")
    print(response.text)
    exit()  # Exit if the response is not valid

# Step 3: Decode the base64 content of the existing file
content_base64 = file_data['content']
decoded_content = base64.b64decode(content_base64).decode('utf-8')

# Load the decoded content as JSON
existing_values = json.loads(decoded_content)

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
            # Call the scrape_onepiece_cards function for each missing value (if needed)
            scrape_onepiece_cards(val)  # This will trigger the scraping for the missing series value

    if extra_in_json:
        print("Extra in series.json:")
        for val in sorted(extra_in_json):
            print(f"  - {val}")

    # Step 7: Update series.json with the new scraped values
    updated_series = list(scraped_set)
    updated_content = json.dumps(updated_series, indent=4)

    # Step 8: Commit the change to GitHub using the API
    update_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    data = {
        "message": "Update series.json with new series",
        "content": base64.b64encode(updated_content.encode('utf-8')).decode('utf-8'),  # encode to base64
        "sha": file_data['sha'],  # Provide the sha to update the file
        "branch": BRANCH
    }

    response = requests.put(update_url, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"}, json=data)

    if response.status_code == 200:
        print("\nseries.json has been updated on GitHub.")
    else:
        print(f"Error updating file: {response.content}")
