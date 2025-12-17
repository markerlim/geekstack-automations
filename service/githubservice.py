import os
import subprocess
from datetime import datetime
import json
import requests
import base64

# GitHub config - Default values
REPO_OWNER = "markerlim"
REPO_NAME = "geekstack-automations"
FILE_PATH = None
BRANCH = None
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_EMAIL = os.getenv("GITHUB_EMAIL")
GITHUB_API_URL = None  # Will be set by init_github_config()

def _validate_github_config():
    """Validate that all required GitHub environment variables are set"""
    if not all([GITHUB_TOKEN, GITHUB_USERNAME, GITHUB_EMAIL]):
        raise ValueError("Missing one or more required GitHub environment variables: GITHUB_TOKEN, GITHUB_USERNAME, GITHUB_EMAIL")

def init_github_config(repo_owner="markerlim", repo_name="geekstack-automations", file_path=None, branch="main"):
    """Initialize GitHub configuration variables and return API URL"""
    global REPO_OWNER, REPO_NAME, FILE_PATH, BRANCH, GITHUB_API_URL
    
    # Update global variables if provided
    if repo_owner:
        REPO_OWNER = repo_owner
    if repo_name:
        REPO_NAME = repo_name
    if file_path:
        FILE_PATH = file_path
    if branch:
        BRANCH = branch
    
    # Validate required parameters
    if not FILE_PATH or not BRANCH:
        raise ValueError("FILE_PATH and BRANCH must be provided to initialize GitHub config")
    
    # Generate new API URL
    GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}?ref={BRANCH}"
    
    # Return configuration object
    config = {
        'repo_owner': REPO_OWNER,
        'repo_name': REPO_NAME,
        'file_path': FILE_PATH,
        'branch': BRANCH,
        'api_url': GITHUB_API_URL,
        'update_url': f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    }
    
    print(f"🔧 GitHub config initialized:")
    print(f"   Repository: {REPO_OWNER}/{REPO_NAME}")
    print(f"   File: {FILE_PATH}")
    print(f"   Branch: {BRANCH}")
    print(f"   API URL: {GITHUB_API_URL}")
    
    return config

def load_series_json_from_github(api_url=None):
    """Load series JSON from GitHub using configured or provided API URL"""
    if not api_url and not GITHUB_API_URL:
        raise ValueError("No API URL configured. Please call init_github_config() first or provide api_url parameter")
    
    _validate_github_config()
    
    url = api_url or GITHUB_API_URL
    print(f"🔄 Loading JSON values from GitHub: {url}")
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    response = requests.get(url, headers=headers)
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

def update_file_on_github(repo_owner, repo_name, file_path, content, commit_message, file_sha, branch="main"):
    """Update a file directly on GitHub via API"""
    try:
        if not GITHUB_TOKEN:
            print("❌ GITHUB_TOKEN not found in environment variables")
            return False
            
        update_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}"
        
        # Encode content to base64
        content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        
        data = {
            "message": commit_message,
            "content": content_base64,
            "sha": file_sha,
            "branch": branch
        }

        headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
        response = requests.put(update_url, headers=headers, json=data)

        if response.status_code == 200:
            print(f"✅ Successfully updated {file_path} on GitHub")
            return True
        else:
            print(f"❌ Error updating file on GitHub: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error updating file on GitHub: {e}")
        return False
