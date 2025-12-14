from pymongo import MongoClient
import certifi
import os
import json
from datetime import datetime
from service.googledriveservice import upload_data_to_drive, get_drive_service

# Global MongoDB environment variables
MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_CLUSTER = os.getenv("MONGO_CLUSTER")
MONGO_DATABASE = os.getenv("MONGO_DATABASE")

def _validate_mongo_config():
    """Validate that all required MongoDB environment variables are set"""
    if not all([MONGO_USER, MONGO_PASSWORD, MONGO_CLUSTER, MONGO_DATABASE]):
        raise ValueError("Missing one or more required MongoDB environment variables: MONGO_USER, MONGO_PASSWORD, MONGO_CLUSTER, MONGO_DATABASE")

def _get_mongo_uri():
    """Get MongoDB connection URI"""
    return f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_CLUSTER}/{MONGO_DATABASE}?retryWrites=true&w=majority"

def upload_to_mongo(data, collection_name):
    try:
        _validate_mongo_config()
        
        # Construct the MongoDB URI
        mongo_uri = _get_mongo_uri()

        # Connect to MongoDB
        client = MongoClient(mongo_uri,tlsCAFile=certifi.where())
        db = client[MONGO_DATABASE]
        collection = db[collection_name]

        # Optional: Clear old data before inserting
        # collection.delete_many({})

        # Insert new data
        result = collection.insert_many(data)
        print(f"✅ Inserted {len(result.inserted_ids)} documents into MongoDB.")
    except Exception as e:
        print(f"❌ MongoDB upload failed: {e}")

def get_or_create_backup_folder():
    """Get or create the 'Geekstack_Backup' folder in Google Drive"""
    try:
        drive_service = get_drive_service()
        if not drive_service:
            print("⚠️ Could not get Google Drive service")
            return None
        
        # Search for existing 'Geekstack_Backup' folder
        results = drive_service.files().list(
            q="name='Geekstack_Backup' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces='drive',
            fields='files(id, name)',
            pageSize=1
        ).execute()
        
        files = results.get('files', [])
        
        if files:
            folder_id = files[0]['id']
            print(f"✅ Found existing 'Geekstack_Backup' folder: {folder_id}")
            return folder_id
        else:
            # Create folder if it doesn't exist
            print("Creating 'Geekstack_Backup' folder...")
            file_metadata = {
                'name': 'Geekstack_Backup',
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = drive_service.files().create(body=file_metadata, fields='id').execute()
            folder_id = folder.get('id')
            print(f"✅ Created 'Geekstack_Backup' folder: {folder_id}")
            return folder_id
    except Exception as e:
        print(f"❌ Failed to get or create backup folder: {e}")
        return None

def backup_from_mongo(collection_name):
    try:
        _validate_mongo_config()
        
        # Construct the MongoDB URI
        mongo_uri = _get_mongo_uri()

        # Connect to MongoDB
        client = MongoClient(mongo_uri,tlsCAFile=certifi.where())
        db = client[MONGO_DATABASE]
        collection = db[collection_name]

        # Fetch all documents from the collection
        data = list(collection.find({}))
        print(f"✅ Fetched {len(data)} documents from MongoDB.")

        # Convert ObjectId to string for JSON serialization
        serializable_data = []
        for doc in data:
            doc_copy = doc.copy()
            if '_id' in doc_copy:
                doc_copy['_id'] = str(doc_copy['_id'])
            serializable_data.append(doc_copy)

        # Get or create Geekstack_Backup folder
        folder_id = get_or_create_backup_folder()
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{collection_name}_backup_{timestamp}.json"
        
        # Upload data to Google Drive
        if folder_id:
            result = upload_data_to_drive(serializable_data, file_name, folder_id=folder_id, data_type='json')
            if result:
                print(f"✅ Backup uploaded to Google Drive: {result.get('file_link')}")
                return {
                    'data': serializable_data,
                    'drive_info': result
                }
        
        return {'data': serializable_data, 'drive_info': None}
    except Exception as e:
        print(f"❌ MongoDB backup failed: {e}")
        return {'data': [], 'drive_info': None}
