from pymongo import MongoClient
import certifi
import os

def upload_to_mongo(data, db_name, collection_name):
    try:
        # Retrieve MongoDB connection details from environment variables
        mongo_user = os.getenv("MONGO_USER")
        mongo_password = os.getenv("MONGO_PASSWORD")
        mongo_cluster = os.getenv("MONGO_CLUSTER")
        mongo_database = os.getenv("MONGO_DATABASE")

        # Check if all required environment variables are available
        if not all([mongo_user, mongo_password, mongo_cluster, mongo_database]):
            raise ValueError("Missing one or more required environment variables.")

        # Construct the MongoDB URI dynamically
        mongo_uri = f"mongodb+srv://{mongo_user}:{mongo_password}@{mongo_cluster}/{mongo_database}?retryWrites=true&w=majority"

        # Connect to MongoDB
        client = MongoClient(mongo_uri,tlsCAFile=certifi.where())
        db = client[db_name]
        collection = db[collection_name]

        # Optional: Clear old data before inserting
        # collection.delete_many({})

        # Insert new data
        result = collection.insert_many(data)
        print(f"✅ Inserted {len(result.inserted_ids)} documents into MongoDB.")
    except Exception as e:
        print(f"❌ MongoDB upload failed: {e}")

