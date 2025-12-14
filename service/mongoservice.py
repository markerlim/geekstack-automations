from pymongo import MongoClient
import certifi
import os
import json
from datetime import datetime
from service.googlecloudservice import upload_data_to_gcs

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
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{collection_name}_backup_{timestamp}.json"
        
        # Upload to Google Cloud Storage
        gcs_result = upload_data_to_gcs(
            data=serializable_data,
            file_name=file_name,
            folder_path=f"backups/{collection_name}",
            data_type='json'
        )
        
        if gcs_result:
            print(f"✅ Backup uploaded to GCS: {gcs_result.get('public_url')}")
        
        return {
            'data': serializable_data,
            'gcs_info': gcs_result
        }
    except Exception as e:
        print(f"❌ MongoDB backup failed: {e}")
        return {'data': [], 'gcs_info': None}
