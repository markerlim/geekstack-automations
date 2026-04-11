from pymongo import MongoClient
from pymongo import UpdateOne
import certifi
import os
import json
from bson import ObjectId
from datetime import datetime
from service.googlecloudservice import upload_data_to_gcs


class MongoService:
    """MongoDB service for database operations and data management"""
    
    def __init__(self, database=None):
        """Initialize MongoDB service with configuration"""
        self.mongo_user = os.getenv("MONGO_USER")
        self.mongo_password = os.getenv("MONGO_PASSWORD")
        self.mongo_cluster = os.getenv("MONGO_CLUSTER")
        self.mongo_database = database or os.getenv("MONGO_DATABASE")
        
        print(f"🔧 MongoDB service initialized for database: {self.mongo_database}")
    
    def _validate_mongo_config(self):
        """Validate that all required MongoDB environment variables are set"""
        if not all([self.mongo_user, self.mongo_password, self.mongo_cluster, self.mongo_database]):
            raise ValueError("Missing one or more required MongoDB environment variables: MONGO_USER, MONGO_PASSWORD, MONGO_CLUSTER, MONGO_DATABASE")
    
    def _get_mongo_uri(self):
        """Get MongoDB connection URI"""
        return f"mongodb+srv://{self.mongo_user}:{self.mongo_password}@{self.mongo_cluster}/{self.mongo_database}?retryWrites=true&w=majority"
    
    def _get_collection(self, collection_name):
        """Helper method to get MongoDB collection with connection setup"""
        self._validate_mongo_config()
        
        # Construct the MongoDB URI
        mongo_uri = self._get_mongo_uri()

        # Connect to MongoDB
        client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
        db = client[self.mongo_database]
        collection = db[collection_name]
        
        return collection

    def upload_data(self, data, collection_name, backup_before_upload=False):
        """Upload data to MongoDB collection"""
        try:
            if backup_before_upload:
                # Backup current MongoDB collection before upload
                print("💾 Creating backup before upload...")
                self.backup_collection(collection_name)

            collection = self._get_collection(collection_name)

            # Optional: Clear old data before inserting
            # collection.delete_many({})

            # Insert new data
            result = collection.insert_many(data)
            print(f"✅ Inserted {len(result.inserted_ids)} documents into MongoDB.")
        except Exception as e:
            print(f"❌ MongoDB upload failed: {e}")

    def backup_collection(self, collection_name):
        """Create backup of MongoDB collection and upload to GCS"""
        try:
            collection = self._get_collection(collection_name)

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

    def validate_field(self, collection_name, field_name, field_value):
        """Check if documents with specific field-value combination exist"""
        try:
            collection = self._get_collection(collection_name)

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
        
    def get_unique_values(self, collection_name, field_name):
        """Get all unique values for a specific field"""
        try:
            collection = self._get_collection(collection_name)

            # Fetch all unique values for the specified field
            unique_values = collection.distinct(field_name)
            
            print(f"✅ Found {len(unique_values)} unique values for field '{field_name}'.")
            
            return unique_values
        except Exception as e:
            print(f"❌ MongoDB unique set check failed: {e}")
            return None

    def get_unique_values_scoped(self, collection_name, scope_field, scope_value, field_name):
        """Get all unique values for a specific field within a scoped subset"""
        try:
            collection = self._get_collection(collection_name)

            # Create query to filter by scope first (e.g., anime = "kagurabachi")
            scope_query = {scope_field: scope_value}
            
            # Fetch all unique values for the specified field within the scope
            unique_values = collection.distinct(field_name, scope_query)
            
            print(f"✅ Found {len(unique_values)} unique values for field '{field_name}' where '{scope_field}' = '{scope_value}'.")
            
            return unique_values
        except Exception as e:
            print(f"❌ MongoDB scoped unique set check failed: {e}")
            return None
        
    def find_by_field(self, collection_name, field_name, field_value):
        """Find a specific document by field value"""
        try:
            collection = self._get_collection(collection_name)

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
        
    def find_all_by_field(self, collection_name, field_name, field_value):
        """Find all documents by field value"""
        try:
            collection = self._get_collection(collection_name)

            query = {field_name: field_value}
            cursor = collection.find(query)

            documents = []
            for doc in cursor:
                if '_id' in doc:
                    doc['_id'] = str(doc['_id'])
                documents.append(doc)

            if documents:
                print(f"✅ Found {len(documents)} documents where '{field_name}' = '{field_value}'.")
                return documents
            else:
                print(f"⚠️ No documents found where '{field_name}' = '{field_value}'.")
                return []

        except Exception as e:
            print(f"❌ MongoDB find operation failed: {e}")
            return []

    def find_all_by_field_array(self, collection_name, field_name, field_values):
        """Find all documents where field matches any value in the provided array"""
        try:
            collection = self._get_collection(collection_name)

            # Use $in operator to match any value in the array
            query = {field_name: {"$in": field_values}}
            cursor = collection.find(query)

            documents = []
            for doc in cursor:
                if '_id' in doc:
                    doc['_id'] = str(doc['_id'])
                documents.append(doc)

            if documents:
                print(f"✅ Found {len(documents)} documents where '{field_name}' matches any of {len(field_values)} values.")
                return documents
            else:
                print(f"⚠️ No documents found where '{field_name}' matches any of the {len(field_values)} provided values.")
                return []

        except Exception as e:
            print(f"❌ MongoDB find operation failed: {e}")
            return []

    def update_by_field(self, collection_name, field_name, field_value, update_data):
        """Update document by field value"""
        try:
            collection = self._get_collection(collection_name)

            # Update the specific object
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
    
    def batch_update_by_field(self, collection_name, update_operations, batch_size=1000):
        """Batch update multiple documents by field value
        
        Args:
            collection_name: Name of the collection
            update_operations: List of dicts with format {'field_name': name, 'field_value': value, 'update_data': data}
            batch_size: Max operations per bulk_write call (default 1000 to avoid memory/timeout issues)
        
        Returns:
            Dict with 'success': bool, 'total': int, 'matched': int, 'modified': int
        """
        try:
            collection = self._get_collection(collection_name)
            
            if not update_operations:
                print("⚠️ No update operations provided")
                return {'success': False, 'total': 0, 'matched': 0, 'modified': 0}
            
            total_matched = 0
            total_modified = 0
            num_batches = (len(update_operations) + batch_size - 1) // batch_size
            
            print(f"🔄 Processing {len(update_operations)} updates in {num_batches} batch(es)...")
            
            # Process in chunks to avoid memory/timeout issues
            for batch_num in range(num_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, len(update_operations))
                batch_ops = update_operations[start_idx:end_idx]
                
                operations = []
                for op in batch_ops:
                    field_name = op['field_name']
                    field_value = op['field_value']
                    update_data = op['update_data']
                    
                    query = {field_name: field_value}
                    update = {"$set": update_data}
                    operations.append(UpdateOne(query, update))
                
                # Execute this batch
                result = collection.bulk_write(operations)
                total_matched += result.matched_count
                total_modified += result.modified_count
                
                batch_label = f"Batch {batch_num + 1}/{num_batches}"
                print(f"  ✅ {batch_label}: {result.matched_count} matched, {result.modified_count} modified")
            
            print(f"✅ Batch update complete: {total_matched} total matched, {total_modified} total modified")
            return {
                'success': True,
                'total': len(update_operations),
                'matched': total_matched,
                'modified': total_modified
            }
        except Exception as e:
            print(f"❌ MongoDB batch update operation failed: {e}")
            return {'success': False, 'total': 0, 'matched': 0, 'modified': 0}


    def update_by_id(self, collection_name, object_id, update_data):
        """Update document by ObjectId"""
        try:            
            collection = self._get_collection(collection_name)

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