import requests
import json
from bs4 import BeautifulSoup

# --- SCRAPE SERIES VALUES FROM WEBSITE ---
series_url = "https://www.dbs-cardgame.com/fw/en/cardlist"
response = requests.get(series_url)
soup = BeautifulSoup(response.content, 'html.parser')

# Use a specific selector to get only the real series values (skip empty)
package_links = soup.select('ul.filterListItems.js-add--toggleElem.js-toggle--selectBox a[data-val]')
scraped_values = [link['data-val'] for link in package_links if link['data-val'].strip()]

print("Scraped values from site:")
print(scraped_values)
print(f"Total scraped: {len(scraped_values)}\n")

# --- LOAD EXISTING series.json FROM LOCAL FILE ---
local_json_path = "dragonballzdb/series.json"
with open(local_json_path, "r") as f:
    existing_values = json.load(f)

print("Existing values from series.json:")
print(existing_values)
print(f"Total in series.json: {len(existing_values)}\n")

# --- COMPARE ---
scraped_set = set(scraped_values)
existing_set = set(existing_values)

missing_in_json = list(scraped_set - existing_set)
extra_in_json = list(existing_set - scraped_set)

print("Missing in series.json (on site but not in file):")
for val in sorted(missing_in_json):
    print(f"  - {val}")
print(f"Total missing: {len(missing_in_json)}\n")

print("Extra in series.json (in file but not on site):")
for val in sorted(extra_in_json):
    print(f"  - {val}")
print(f"Total extra: {len(extra_in_json)}\n")