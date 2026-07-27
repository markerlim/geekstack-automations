import json
import os
import sys
import requests
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
from service.github_service import GitHubService
from service.mongo_service import MongoService
from lcscrape import scrape_lorcana_set

github_service = GitHubService()
mongo_service = MongoService()

FILE_PATH = "lorcanadb/series.json"

existing_data, file_sha = github_service.load_json_file(FILE_PATH, local_fallback=True)

if existing_data is None:
    print("Error fetching series.json from GitHub")
    exit()

existing_standard = set(existing_data.get("standard", []))
existing_special = set(existing_data.get("special", []))

API_URL = "https://cards.disneylorcana.com/en-US/api/cards/en"
resp = requests.get(API_URL, timeout=60)
resp.raise_for_status()
data = resp.json()
filters = data.get("filters", {})

scraped_standard = set()
scraped_special = set()

set_filter = filters.get("set", {})
options = set_filter.get("options", [])
for group in options:
    group_type = group.get("type", "")
    sets = group.get("sets", [])
    for s in sets:
        sid = s.get("id", "")
        if group_type == "special":
            scraped_special.add(sid)
        else:
            scraped_standard.add(sid)

print(f"Scraped standard sets: {sorted(scraped_standard)}")
print(f"Scraped special sets: {sorted(scraped_special)}")

missing_standard = scraped_standard - existing_standard
extra_standard = existing_standard - scraped_standard
missing_special = scraped_special - existing_special
extra_special = existing_special - scraped_special

missing = missing_standard | missing_special
extra = extra_standard | extra_special

if not missing and not extra:
    print("same")
else:
    print("different")
    for set_id in sorted(missing):
        print(f"New set: {set_id}")
        scrape_lorcana_set(set_id)

    if extra:
        print("Extra in series.json:")
        for set_id in sorted(extra):
            print(f"  - {set_id}")

    updated = {
        "standard": sorted(scraped_standard),
        "special": sorted(scraped_special),
    }
    updated_content = json.dumps(updated, indent=2)
    success = github_service.update_file(
        FILE_PATH,
        updated_content,
        "Update series.json with new Lorcana sets",
        file_sha,
    )
    if success:
        print("series.json updated on GitHub")
    else:
        print("Error updating series.json")

if not missing:
    print("No new sets detected.")
