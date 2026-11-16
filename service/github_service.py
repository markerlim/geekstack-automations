import os
import subprocess
from datetime import datetime
import json
import requests
import base64

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class GitHubService:
    """GitHub API service for file operations and repository management"""
    
    def __init__(self, repo_owner="markerlim", repo_name="geekstack-automations", branch="main"):
        """Initialize GitHub service with repository details"""
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.branch = branch
        
        # Load environment variables
        self.github_token = os.getenv("GITHUB_TOKEN")
        # Local mode: read/write the repo's own files instead of the GitHub API.
        # On when LOCAL_FILES=1, or automatically when there is no GITHUB_TOKEN
        # (running a scraper on your machine). You commit the changes yourself.
        self.local = os.getenv("LOCAL_FILES") == "1" or not self.github_token
        if self.local:
            print(f"🔧 GitHub service in LOCAL mode (files under {REPO_ROOT}; no GitHub API)")
        else:
            print(f"🔧 GitHub service initialized for {repo_owner}/{repo_name}")

    def _local_path(self, file_path):
        """Repo-relative path -> absolute path under the repo root (independent of cwd)."""
        return file_path if os.path.isabs(file_path) else os.path.join(REPO_ROOT, file_path)
    
    def _validate_github_config(self):
        """Validate that all required GitHub environment variables are set"""
        if not all([self.github_token]):
            raise ValueError("Missing GitHub environment variables: GITHUB_TOKEN")
    
    def set_file_path(self, file_path):
        """Set the file path and generate API URL"""
        self.file_path = file_path
        self.api_url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/contents/{self.file_path}?ref={self.branch}"
        
        print(f"📁 File path set: {file_path}")
        print(f"🔗 API URL: {self.api_url}")
        
        return {
            'repo_owner': self.repo_owner,
            'repo_name': self.repo_name,
            'file_path': self.file_path,
            'branch': self.branch,
            'api_url': self.api_url,
            'update_url': f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/contents/{self.file_path}"
        }
    
    def load_json_file(self, file_path=None, api_url=None, local_fallback=False):
        """Load JSON file from GitHub or local filesystem"""
        if file_path:
            self.set_file_path(file_path)

        if self.local and file_path:
            path = self._local_path(file_path)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
                print(f"📂 Loaded JSON from local file: {path}")
                return json_data, None
            except FileNotFoundError:
                print(f"📄 Local file not found: {path}")
                return None, None
            except Exception as e:
                print(f"❌ Error loading local file {path}: {e}")
                return None, None
        
        # Check if file exists locally first
        if file_path and local_fallback and os.path.exists(file_path):
            try:
                print(f"📂 Loading JSON from local file: {file_path}")
                with open(file_path, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
                print(f"✅ Successfully loaded JSON from local file")
                return json_data, None  # No SHA for local files
            except Exception as e:
                print(f"❌ Error loading local file: {e}")
                print("🔄 Falling back to GitHub...")
        
        if not api_url and not self.api_url:
            raise ValueError("No API URL configured. Please call set_file_path() first or provide api_url parameter")
        
        self._validate_github_config()
        
        url = api_url or self.api_url
        print(f"🔄 Loading JSON from GitHub: {url}")
        
        headers = {
            "Authorization": f"Bearer {self.github_token}",
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
                json_data = json.loads(decoded_content)
                
                print(f"✅ Successfully loaded JSON file from GitHub")
                return json_data, file_data['sha']
            except Exception as e:
                print(f"❌ Error decoding file content: {e}")
                return None, None
        elif response.status_code == 404:
            print(f"📄 File not found: {url}")
            return None, None
        else:
            print(f"❌ Error fetching file from GitHub: {response.status_code}")
            print(response.text)
            return None, None
    
    def load_series_json(self, file_path=None, api_url=None, local_fallback=True):
        """Load series JSON from GitHub or local filesystem (backward compatibility method)"""
        json_data, file_sha = self.load_json_file(file_path, api_url, local_fallback)
        
        if json_data is None:
            return [], None
        
        if isinstance(json_data, list):
            return [item.strip() for item in json_data if isinstance(item, str)], file_sha
        else:
            print("[Warning] JSON content is not a list.")
            return [], file_sha
    
    def get_file_content(self, file_path, local_fallback=False):
        """Get raw file content from GitHub or local filesystem"""
        if self.local:
            try:
                with open(self._local_path(file_path), 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                print(f"❌ Error reading local file {file_path}: {e}")
                return None

        # Check if file exists locally first
        if local_fallback and os.path.exists(file_path):
            try:
                print(f"📂 Reading content from local file: {file_path}")
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                print(f"✅ Successfully read content from local file")
                return content
            except Exception as e:
                print(f"❌ Error reading local file: {e}")
                print("🔄 Falling back to GitHub...")
        
        # GitHub API fallback
        self.set_file_path(file_path)
        self._validate_github_config()
        
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github.v3+json"
        }

        response = requests.get(self.api_url, headers=headers)
        if response.status_code == 200:
            file_data = response.json()
            try:
                content_base64 = file_data['content']
                decoded_content = base64.b64decode(content_base64).decode('utf-8')
                print(f"✅ Successfully retrieved content from GitHub")
                return decoded_content
            except Exception as e:
                print(f"❌ Error decoding GitHub file content: {e}")
                return None
        else:
            print(f"❌ Error fetching file from GitHub: {response.status_code}")
            return None
    
    def update_file(self, file_path, content, commit_message, file_sha=None, branch=None):
        """Update a file directly on GitHub via API (or on disk in local mode)"""
        if self.local:
            try:
                path = self._local_path(file_path)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"✅ Wrote {path} locally (not pushed) -- commit it when you're happy: {commit_message}")
                return True
            except Exception as e:
                print(f"❌ Error writing local file {file_path}: {e}")
                return False
        try:
            if not self.github_token:
                print("❌ GITHUB_TOKEN not found in environment variables")
                return False
                
            branch = branch or self.branch
            update_url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/contents/{file_path}"
            
            # Encode content to base64
            content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            
            data = {
                "message": commit_message,
                "content": content_base64,
                "branch": branch
            }
            
            if file_sha:
                data["sha"] = file_sha

            headers = {"Authorization": f"Bearer {self.github_token}"}
            response = requests.put(update_url, headers=headers, json=data)

            if response.status_code in [200, 201]:
                print(f"✅ Successfully updated {file_path} on GitHub")
                return True
            else:
                print(f"❌ Error updating file on GitHub: {response.status_code}")
                print(f"Response: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Error updating file on GitHub: {e}")
            return False
    
    def load_mapping(self, file_path, local_fallback=True):
        """Load mapping JSON from GitHub or local filesystem - useful for configuration files"""
        json_data, _ = self.load_json_file(file_path, local_fallback=local_fallback)
        return json_data if json_data is not None else {}

