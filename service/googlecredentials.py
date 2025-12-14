import os
import json
from google.oauth2 import service_account

def get_google_credentials(scopes=None):
    """
    Get Google service account credentials from environment or file
    
    Args:
        scopes: List of OAuth scopes (optional)
    
    Returns:
        Credentials object, or None if failed
    """
    try:
        credentials = None
        
        # Try to load from GOOGLE_APPLICATION_CREDENTIALS environment variable (file path)
        if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            print(f"Loading Google credentials from environment variable path: {credentials_path}")
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=scopes
            )
        # Try to load from GOOGLE_SERVICE_ACCOUNT_JSON environment variable (JSON string)
        elif "GOOGLE_SERVICE_ACCOUNT_JSON" in os.environ:
            creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            print("Loading Google credentials from GOOGLE_SERVICE_ACCOUNT_JSON environment variable")
            creds_dict = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=scopes
            )
        # Fallback to credentials file in project directory
        elif os.path.exists("credentials/service-accountkey.json"):
            print("Loading Google credentials from file: credentials/service-accountkey.json")
            credentials = service_account.Credentials.from_service_account_file(
                "credentials/service-accountkey.json",
                scopes=scopes
            )
        else:
            print("⚠️ No Google credentials found")
            return None
        
        print("✅ Google credentials loaded successfully")
        return credentials
    
    except Exception as e:
        print(f"❌ Failed to load Google credentials: {e}")
        return None
