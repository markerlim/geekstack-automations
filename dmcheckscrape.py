import json
import requests
import base64
import os
from bs4 import BeautifulSoup
from duelmasterscrape import startscraping

# GitHub configuration
REPO_OWNER = "markerlim"
REPO_NAME = "geekstack-automations"
FILE_PATH = "duelmasterdb/seriesdm.json"
BRANCH = "main"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# GitHub API URL for content
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}?ref={BRANCH}"

def load_json_values_from_github():
    """Load values from seriesdm.json on GitHub"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.raw"
    }

    try:
        response = requests.get(GITHUB_API_URL, headers=headers)
        response.raise_for_status()
        content_json = response.json()

        # Decode content
        content = base64.b64decode(content_json['content']).decode('utf-8')
        data = json.loads(content)

        # Normalize
        if isinstance(data, list):
            if all(isinstance(item, dict) and 'value' in item for item in data):
                return [item['value'].strip() for item in data], content_json['sha']
            elif all(isinstance(item, str) for item in data):
                return [item.strip() for item in data], content_json['sha']

        print("[Warning] JSON format not recognized.")
        return [], content_json['sha']
    except Exception as e:
        print(f"[Error] Failed to load JSON from GitHub: {e}")
        return [], None

def scrape_website_values():
    """Scrape series values from the official Duel Masters site"""
    url = "https://dm.takaratomy.co.jp/card/"
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        select = soup.find('select', {'name': 'products'})
        if not select:
            print("[Error] Could not find 'products' dropdown.")
            return []

        options = [opt.get('value').strip() for opt in select.find_all('option') if opt.get('value')]
        return options
    except Exception as e:
        print(f"[Error] Failed to scrape website: {e}")
        return []

def find_missing_values(json_values, website_values):
    json_set = set(json_values)
    website_set = set(website_values)
    print(f"\n🧪 Debug: {len(json_set)} JSON values vs {len(website_set)} website values")
    return sorted(website_set - json_set)

def update_json_and_commit(missing_values, existing_values, sha):
    updated_data = [{"value": val} for val in sorted(existing_values + missing_values)]

    payload = {
        "message": "🔄 Auto-update seriesdm.json with new booster series",
        "content": base64.b64encode(json.dumps(updated_data, indent=2, ensure_ascii=False).encode('utf-8')).decode('utf-8'),
        "branch": BRANCH,
        "sha": sha
    }

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        res = requests.put(GITHUB_API_URL, headers=headers, json=payload)
        res.raise_for_status()
        print("✅ Successfully updated seriesdm.json on GitHub.")
    except Exception as e:
        print(f"❌ Failed to update GitHub file: {e}")
        print("Response:", res.text)

def run_scraper_and_update():
    print("🔄 Loading JSON values from GitHub...")
    json_values, sha = load_json_values_from_github()

    print("🌐 Scraping website values...")
    website_values = scrape_website_values()

    if not json_values:
        print("❌ No data loaded from GitHub.")
        return
    if not website_values:
        print("❌ No data scraped from website.")
        return

    print("🔍 Finding missing values...")
    missing_values = find_missing_values(json_values, website_values)

    print(f"\n📋 JSON total: {len(json_values)} | Website total: {len(website_values)} | Missing: {len(missing_values)}")
    if missing_values:
        print("\n⚠️ Missing booster series:")
        for val in missing_values:
            print(f"- {val}")
        
        collection = os.getenv('C_DUELMASTERS')

        # ✅ Scrape missing data
        startscraping(booster_list=missing_values, collection_name=collection)

        # ✅ Update and commit JSON to GitHub
        update_json_and_commit(missing_values, json_values, sha)

    else:
        print("✅ All booster series from the site are already in the JSON!")

if __name__ == "__main__":
    run_scraper_and_update()
