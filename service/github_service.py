import os
import subprocess
from datetime import datetime
import json
import requests
import base64


class GitHubService:
    """GitHub API service for file operations and repository management"""
    
    def __init__(self, repo_owner="markerlim", repo_name="geekstack-automations", branch="main"):
        """Initialize GitHub service with repository details"""
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.branch = branch
        
        # Load environment variables
        self.github_token = os.getenv("GITHUB_TOKEN")
        #self.github_username = os.getenv("GITHUB_USERNAME")
        #self.github_email = os.getenv("GITHUB_EMAIL")
        
        print(f"🔧 GitHub service initialized for {repo_owner}/{repo_name}")
    
    def _validate_github_config(self):
        """Validate that all required GitHub environment variables are set"""
        if not all([self.github_token, self.github_username, self.github_email]):
            raise ValueError("Missing one or more required GitHub environment variables: GITHUB_TOKEN, GITHUB_USERNAME, GITHUB_EMAIL")
    
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
    
    def load_json_file(self, file_path=None, api_url=None):
        """Load JSON file from GitHub using configured or provided file path/API URL"""
        if file_path:
            self.set_file_path(file_path)
        
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
                
                print(f"✅ Successfully loaded JSON file")
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
    
    def load_series_json(self, file_path=None, api_url=None):
        """Load series JSON from GitHub (backward compatibility method)"""
        json_data, file_sha = self.load_json_file(file_path, api_url)
        
        if json_data is None:
            return [], None
        
        if isinstance(json_data, list):
            return [item.strip() for item in json_data if isinstance(item, str)], file_sha
        else:
            print("[Warning] JSON content is not a list.")
            return [], file_sha
    
    def update_file(self, file_path, content, commit_message, file_sha=None, branch=None):
        """Update a file directly on GitHub via API"""
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
    
    def load_mapping(self, file_path):
        """Load mapping JSON from GitHub - useful for configuration files"""
        json_data, _ = self.load_json_file(file_path)
        return json_data if json_data is not None else {}


# Backward compatibility functions
def init_github_config(repo_owner="markerlim", repo_name="geekstack-automations", file_path=None, branch="main"):
    """Backward compatibility function - creates and returns GitHubService instance"""
    service = GitHubService(repo_owner, repo_name, branch)
    if file_path:
        return service.set_file_path(file_path)
    return service

def load_series_json_from_github(api_url=None):
    """Backward compatibility function"""
    # This requires a global service instance, which isn't ideal
    # Users should migrate to using GitHubService class directly
    raise NotImplementedError("Please use GitHubService class directly: service = GitHubService(); service.load_series_json()")

def update_file_on_github(repo_owner, repo_name, file_path, content, commit_message, file_sha, branch="main"):
    """Backward compatibility function"""
    service = GitHubService(repo_owner, repo_name, branch)
    return service.update_file(file_path, content, commit_message, file_sha, branch)
