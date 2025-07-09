from google.cloud import storage
from google.oauth2 import service_account
import requests
import tempfile
import os
from PIL import Image

def upload_image_to_gcs(image_url, filename, filepath, bucket_name="geek-stack.appspot.com"):
    try:
        print(f"Attempting to download image from: {image_url}")
        
        response = requests.get(image_url, stream=True)
        if response.status_code != 200:
            raise Exception(f"Image not accessible: {image_url}")
        
        # Save original image temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
            for chunk in response.iter_content(1024):
                temp_file.write(chunk)
            temp_file_path = temp_file.name
        
        print(f"Temporary original image saved at: {temp_file_path}")

        # Convert to WebP
        image = Image.open(temp_file_path).convert("RGBA")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webp") as webp_file:
            image.save(webp_file.name, format="WEBP")
            webp_file_path = webp_file.name

        print(f"Converted WebP image saved at: {webp_file_path}")
        os.remove(temp_file_path)  # Clean up original PNG

        # Determine credentials source (file or environment variable)
        credentials = None
        if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            # Use credentials from environment variable (GCP service account file path)
            credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            print(f"Using GCP credentials from environment variable: {credentials_path}")
            credentials = service_account.Credentials.from_service_account_file(credentials_path)
        elif os.path.exists("credentials/service-accountkey.json"):
            # Fallback to credentials file in the project directory
            print(f"Using GCP credentials from file: credentials/service-accountkey.json")
            credentials = service_account.Credentials.from_service_account_file("credentials/service-accountkey.json")
        else:
            raise Exception("No GCP credentials found. Set GOOGLE_APPLICATION_CREDENTIALS environment variable or provide a credentials file.")

        # Upload to GCS
        client = storage.Client(credentials=credentials)
        bucket = client.get_bucket(bucket_name)
        blob = bucket.blob(f"{filepath}{filename}.webp")
        print(f"Uploading to GCS at: {filepath}{filename}.webp")
        blob.upload_from_filename(webp_file_path)
        blob.make_public()

        os.remove(webp_file_path)  # Clean up WebP temp file

        print(f"✅ File uploaded successfully. Public URL: {blob.public_url}")
        return blob.public_url
    except Exception as e:
        print(f"❌ Failed to upload {filename} to GCS: {e}")
        return image_url  # fallback to original
