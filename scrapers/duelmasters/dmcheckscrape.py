import json
import os
import base64
import requests
from bs4 import BeautifulSoup
from duelmasterscrape import startscraping

# GitHub config
REPO_OWNER = "markerlim"
REPO_NAME = "geekstack-automations"
FILE_PATH = "duelmasterdb/seriesdm.json"
BRANCH = "main"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}?ref={BRANCH}"


def load_series_json_from_github():
    print("🔄 Loading JSON values from GitHub...")
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    response = requests.get(GITHUB_API_URL, headers=headers)
    if response.status_code == 200:
        file_data = response.json()

        if isinstance(file_data, list):
            print("❌ GitHub path is a directory, not a file.")
            return [], None

        try:
            content_base64 = file_data['content']
            decoded_content = base64.b64decode(content_base64).decode('utf-8')
            existing_values = json.loads(decoded_content)

            if isinstance(existing_values, list):
                return [item.strip() for item in existing_values if isinstance(item, str)], file_data['sha']
            else:
                print("[Warning] JSON content is not a list.")
                return [], file_data['sha']
        except Exception as e:
            print(f"❌ Error decoding file content: {e}")
            return [], None
    else:
        print(f"❌ Error fetching file from GitHub: {response.status_code}")
        print(response.text)
        return [], None


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


def find_missing_values(json_values, website_values):
    json_set = set(json_values)
    website_set = set(website_values)

    print(f"\n🧪 Debug: {len(json_set)} JSON values vs {len(website_set)} website values")
    return sorted(website_set - json_set)


def commit_missing_values_to_github(missing_values, current_values, sha):
    print("🚀 Committing updated JSON to GitHub...")

    updated_values = sorted(current_values + missing_values)

    updated_json_str = json.dumps(updated_values, ensure_ascii=False, indent=2)
    updated_base64 = base64.b64encode(updated_json_str.encode('utf-8')).decode('utf-8')

    commit_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    commit_message = "🔁 Update seriesdm.json with new series from website"
    payload = {
        "message": commit_message,
        "content": updated_base64,
        "sha": sha,
        "branch": BRANCH
    }

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    response = requests.put(commit_url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        print("✅ Successfully committed updated JSON to GitHub!")
    else:
        print(f"❌ Failed to commit file: {response.status_code}")
        print(response.text)


def run_check():
    json_values, sha = load_series_json_from_github()
    website_values = scrape_website_values()

    if not json_values:
        print("❌ No data loaded from GitHub.")
        return
    if not website_values:
        print("❌ No data scraped from website.")
        return

    missing_values = find_missing_values(json_values, website_values)

    print("\n=== 📋 Missing Values Report ===")
    print(f"📦 Total series in GitHub JSON: {len(json_values)}")
    print(f"🌍 Total series on website: {len(website_values)}")
    print(f"❓ Missing series count: {len(missing_values)}")

    if missing_values:
        print("\n⚠️ Missing series:")
        for val in missing_values:
            print(f"- {val}")

        # Run scraper
        collectionval = os.getenv("C_DUELMASTERS")
        startscraping(booster_list=missing_values, collection_name=collectionval)

        # Commit updated list to GitHub
        commit_missing_values_to_github(missing_values, json_values, sha)

        # Save locally
        try:
            with open('missing_series.json', 'w', encoding='utf-8') as f:
                json.dump(missing_values, f, indent=2, ensure_ascii=False)
            print("\n💾 Saved missing series to 'missing_series.json'")
        except Exception as e:
            print(f"[Error] Could not save locally: {e}")
    else:
        print("✅ All series in JSON exist on the website!")


if __name__ == "__main__":
    run_check()
