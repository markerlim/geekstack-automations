import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
import io
import json
from service.googlecredentials import get_google_credentials

# Google Drive API scopes
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_drive_service():
    """Get authenticated Google Drive service"""
    try:
        # Load credentials using centralized service
        credentials = get_google_credentials(scopes=SCOPES)
        
        if not credentials:
            print("⚠️ Google Drive credentials not found")
            return None
        
        drive_service = build('drive', 'v3', credentials=credentials)
        return drive_service
    except Exception as e:
        print(f"❌ Failed to authenticate Google Drive: {e}")
        return None

def upload_file_to_drive(file_path, file_name=None, folder_id=None, mime_type=None):
    """
    Upload a file to Google Drive
    
    Args:
        file_path: Local file path to upload
        file_name: Name for the file in Google Drive (default: original filename)
        folder_id: Google Drive folder ID to upload to (optional)
        mime_type: MIME type of the file (default: auto-detect)
    
    Returns:
        Dictionary with file_id, file_link, and filename, or None if failed
    """
    try:
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            return None
        
        drive_service = get_drive_service()
        if not drive_service:
            print("⚠️ Skipping Google Drive upload - authentication failed")
            return None
        
        # Use original filename if not provided
        if not file_name:
            file_name = os.path.basename(file_path)
        
        # Auto-detect MIME type if not provided
        if not mime_type:
            if file_name.endswith('.json'):
                mime_type = 'application/json'
            elif file_name.endswith('.txt'):
                mime_type = 'text/plain'
            elif file_name.endswith('.pdf'):
                mime_type = 'application/pdf'
            elif file_name.endswith('.csv'):
                mime_type = 'text/csv'
            elif file_name.endswith('.zip'):
                mime_type = 'application/zip'
            else:
                mime_type = 'application/octet-stream'
        
        # Prepare file metadata
        file_metadata = {
            'name': file_name,
            'mimeType': mime_type
        }
        
        # Add to folder if folder_id is provided
        if folder_id:
            file_metadata['parents'] = [folder_id]
        
        # Upload file
        media = MediaFileUpload(file_path, mimetype=mime_type)
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink, name, createdTime'
        ).execute()
        
        file_id = file.get('id')
        file_link = file.get('webViewLink')
        created_time = file.get('createdTime')
        
        print(f"✅ File uploaded to Google Drive: {file_link}")
        return {
            'file_id': file_id,
            'file_link': file_link,
            'filename': file_name,
            'created_time': created_time
        }
    
    except Exception as e:
        print(f"❌ Google Drive upload failed: {e}")
        return None

def upload_data_to_drive(data, file_name, folder_id=None, data_type='json'):
    """
    Upload data directly to Google Drive (without creating a local file)
    
    Args:
        data: Data to upload (dict for JSON, string for text)
        file_name: Name for the file in Google Drive
        folder_id: Google Drive folder ID to upload to (optional)
        data_type: Type of data ('json' or 'text')
    
    Returns:
        Dictionary with file_id, file_link, and filename, or None if failed
    """
    try:
        drive_service = get_drive_service()
        if not drive_service:
            print("⚠️ Skipping Google Drive upload - authentication failed")
            return None
        
        # Determine MIME type
        if data_type == 'json':
            mime_type = 'application/json'
            content = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            mime_type = 'text/plain'
            content = str(data)
        
        # Create file metadata
        file_metadata = {
            'name': file_name,
            'mimeType': mime_type
        }
        
        # Add to folder if folder_id is provided
        if folder_id:
            file_metadata['parents'] = [folder_id]
        
        # Convert content to bytes and upload
        file_content = io.BytesIO(content.encode('utf-8'))
        media = MediaIoBaseUpload(file_content, mimetype=mime_type)
        
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink, name, createdTime'
        ).execute()
        
        file_id = file.get('id')
        file_link = file.get('webViewLink')
        created_time = file.get('createdTime')
        
        print(f"✅ Data uploaded to Google Drive: {file_link}")
        return {
            'file_id': file_id,
            'file_link': file_link,
            'filename': file_name,
            'created_time': created_time
        }
    
    except Exception as e:
        print(f"❌ Google Drive upload failed: {e}")
        return None

def delete_file_from_drive(file_id):
    """
    Delete a file from Google Drive
    
    Args:
        file_id: Google Drive file ID to delete
    
    Returns:
        True if successful, False otherwise
    """
    try:
        drive_service = get_drive_service()
        if not drive_service:
            print("⚠️ Skipping Google Drive delete - authentication failed")
            return False
        
        # Delete the file
        drive_service.files().delete(fileId=file_id).execute()
        print(f"✅ File deleted from Google Drive: {file_id}")
        return True
    
    except Exception as e:
        print(f"❌ Google Drive delete failed: {e}")
        return False

def delete_files_by_name(file_name, folder_id=None):
    """
    Delete all files with a specific name from Google Drive
    
    Args:
        file_name: Name of files to delete
        folder_id: Search within specific folder (optional)
    
    Returns:
        List of deleted file IDs, or empty list if none found
    """
    try:
        drive_service = get_drive_service()
        if not drive_service:
            print("⚠️ Skipping Google Drive delete - authentication failed")
            return []
        
        # Build query
        query = f"name='{file_name}' and trashed=false"
        if folder_id:
            query += f" and '{folder_id}' in parents"
        
        # Find files
        results = drive_service.files().list(
            q=query,
            fields='files(id, name)',
            pageSize=100
        ).execute()
        
        files = results.get('files', [])
        deleted_ids = []
        
        if not files:
            print(f"⚠️ No files found with name: {file_name}")
            return deleted_ids
        
        # Delete all found files
        for file in files:
            file_id = file.get('id')
            drive_service.files().delete(fileId=file_id).execute()
            deleted_ids.append(file_id)
            print(f"✅ Deleted: {file.get('name')} ({file_id})")
        
        return deleted_ids
    
    except Exception as e:
        print(f"❌ Google Drive delete failed: {e}")
        return []

def list_files_in_folder(folder_id, page_size=100):
    """
    List all files in a Google Drive folder
    
    Args:
        folder_id: Google Drive folder ID
        page_size: Number of files to return (default: 100)
    
    Returns:
        List of files with id, name, and createdTime
    """
    try:
        drive_service = get_drive_service()
        if not drive_service:
            print("⚠️ Skipping Google Drive list - authentication failed")
            return []
        
        # Build query to find files in folder
        query = f"'{folder_id}' in parents and trashed=false"
        
        # List files
        results = drive_service.files().list(
            q=query,
            fields='files(id, name, createdTime, mimeType, size)',
            pageSize=page_size,
            orderBy='createdTime desc'
        ).execute()
        
        files = results.get('files', [])
        
        if not files:
            print(f"ℹ️ No files found in folder: {folder_id}")
            return files
        
        print(f"✅ Found {len(files)} files in folder")
        return files
    
    except Exception as e:
        print(f"❌ Google Drive list failed: {e}")
        return []

def get_file_info(file_id):
    """
    Get information about a file in Google Drive
    
    Args:
        file_id: Google Drive file ID
    
    Returns:
        Dictionary with file information, or None if not found
    """
    try:
        drive_service = get_drive_service()
        if not drive_service:
            print("⚠️ Skipping Google Drive get - authentication failed")
            return None
        
        # Get file info
        file = drive_service.files().get(
            fileId=file_id,
            fields='id, name, createdTime, modifiedTime, mimeType, size, webViewLink'
        ).execute()
        
        print(f"✅ Retrieved file info: {file.get('name')}")
        return file
    
    except Exception as e:
        print(f"❌ Google Drive get failed: {e}")
        return None

def create_folder_in_drive(folder_name, parent_folder_id=None):
    """
    Create a new folder in Google Drive
    
    Args:
        folder_name: Name for the new folder
        parent_folder_id: Parent folder ID (optional)
    
    Returns:
        Dictionary with folder_id and folder_link, or None if failed
    """
    try:
        drive_service = get_drive_service()
        if not drive_service:
            print("⚠️ Skipping Google Drive folder creation - authentication failed")
            return None
        
        # Create folder metadata
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        
        # Add parent folder if provided
        if parent_folder_id:
            folder_metadata['parents'] = [parent_folder_id]
        
        # Create folder
        folder = drive_service.files().create(
            body=folder_metadata,
            fields='id, webViewLink, name'
        ).execute()
        
        folder_id = folder.get('id')
        folder_link = folder.get('webViewLink')
        
        print(f"✅ Folder created in Google Drive: {folder_link}")
        return {
            'folder_id': folder_id,
            'folder_link': folder_link,
            'folder_name': folder_name
        }
    
    except Exception as e:
        print(f"❌ Google Drive folder creation failed: {e}")
        return None
