from google.cloud import storage
import requests
import tempfile
import os
from PIL import Image
from service.googlecredentials import get_google_credentials

def upload_image_to_gcs(image_url, filename, filepath, bucket_name="images.geekstack.dev"):

    try:
        print(f"Attempting to download image from: {image_url}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        
        response = requests.get(image_url, stream=True, headers=headers, timeout=30)
        print(f"Response status code: {response.status_code}")
        
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

        # Get credentials using centralized service
        credentials = get_google_credentials()
        if not credentials:
            raise Exception("No GCP credentials found. Set GOOGLE_APPLICATION_CREDENTIALS environment variable or provide a credentials file.")

        # Upload to GCS
        client = storage.Client(credentials=credentials)
        bucket = client.get_bucket(bucket_name)
        blob = bucket.blob(f"{filepath}{filename}.webp")
        print(f"Uploading to GCS at: {filepath}{filename}.webp")
        blob.upload_from_filename(webp_file_path)

        os.remove(webp_file_path)  # Clean up WebP temp file

        gcs_url = blob.public_url
        custom_url = gcs_url.replace(
            f"https://storage.googleapis.com/{bucket_name}/",
            f"https://{bucket_name}/"
        )

        print(f"✅ File uploaded successfully. Public URL: {custom_url}")
        return custom_url
    except Exception as e:
        print(f"❌ Failed to upload {filename} to GCS: {e}")
        return image_url  # fallback to original