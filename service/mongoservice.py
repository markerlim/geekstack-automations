from pymongo import MongoClient
import certifi
import os
import json
from bson import ObjectId
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

def _get_mongo_collection(collection_name):
    """Helper function to get MongoDB collection with connection setup"""
    _validate_mongo_config()
    
    # Construct the MongoDB URI
    mongo_uri = _get_mongo_uri()

    # Connect to MongoDB
    client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
    db = client[MONGO_DATABASE]
    collection = db[collection_name]
    
    return collection

def upload_to_mongo(data, collection_name, backup_before_upload=False):
    try:
        if backup_before_upload:
            # Backup current MongoDB collection before upload
            print("💾 Creating backup before upload...")
            backup_from_mongo(collection_name)

        collection = _get_mongo_collection(collection_name)

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

def validate_from_mongo(collection_name, field_name, field_value):
    try:
        collection = _get_mongo_collection(collection_name)

        # Check if documents with the specified field-value combination exist
        query = {field_name: field_value}
        count = collection.count_documents(query)
        
        print(f"🔍 Searching for documents where '{field_name}' = '{field_value}'")
        print(f"✅ Found {count} documents matching the criteria.")
        
        return {
            'exists': count > 0,
            'count': count
        }
    except Exception as e:
        print(f"❌ MongoDB validation failed: {e}")
        return None
    
def check_unique_by_field(collection_name,field_name):
    try:
        collection = _get_mongo_collection(collection_name)

        # Fetch all unique values for the specified field
        unique_values = collection.distinct(field_name)
        
        print(f"✅ Found {len(unique_values)} unique values for field '{field_name}'.")
        
        return unique_values
    except Exception as e:
        print(f"❌ MongoDB unique set check failed: {e}")
        return None

def find_specific_object_in_mongo(collection_name, field_name, field_value):
    try:
        collection = _get_mongo_collection(collection_name)

        # Find the specific object
        query = {field_name: field_value}
        document = collection.find_one(query)
        
        if document:
            print(f"✅ Found document where '{field_name}' = '{field_value}'.")
            # Convert ObjectId to string for JSON serialization
            if '_id' in document:
                document['_id'] = str(document['_id'])
            return document
        else:
            print(f"⚠️ No document found where '{field_name}' = '{field_value}'.")
            return None
    except Exception as e:
        print(f"❌ MongoDB find operation failed: {e}")
        return None
    
def modify_specific_object_in_mongo(collection_name, field_name, field_value, update_data):
    try:
        collection = _get_mongo_collection(collection_name)

        query = {field_name: field_value}
        update = {"$set": update_data}
        result = collection.update_one(query, update)
        
        if result.matched_count > 0:
            print(f"✅ Updated document where '{field_name}' = '{field_value}'. Modified count: {result.modified_count}")
            return True
        else:
            print(f"⚠️ No document found to update where '{field_name}' = '{field_value}'.")
            return False
    except Exception as e:
        print(f"❌ MongoDB update operation failed: {e}")
        return False

def modify_object_by_id(collection_name, object_id, update_data):
    try:        
        collection = _get_mongo_collection(collection_name)

        # Convert string ID to ObjectId
        if isinstance(object_id, str):
            object_id = ObjectId(object_id)
        
        # Update the specific object by ObjectId
        query = {"_id": object_id}
        update = {"$set": update_data}
        result = collection.update_one(query, update)
        
        if result.matched_count > 0:
            print(f"✅ Updated document with _id = '{object_id}'. Modified count: {result.modified_count}")
            return True
        else:
            print(f"⚠️ No document found with _id = '{object_id}'.")
            return False
    except Exception as e:
        print(f"❌ MongoDB update by ID operation failed: {e}")
        return False