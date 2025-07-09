import json
import requests
from PIL import Image
import os
from google.oauth2 import service_account
from google.cloud import storage
from service.googlecloudservice import upload_image_to_gcs  # Imported from external module

# Configuration
CARDS_DATA_FILE = 'riftbounddb/riftbound_cards_data.json'
PLACEHOLDER_IMAGE_PATH = 'placeholder.webp'
GCS_BUCKET_NAME = os.environ.get('GCSIMAGE', 'RBTCG/test')

def process_cards():
    if not GCS_BUCKET_NAME:
        print("GCS_BUCKET_NAME environment variable not set. Exiting.")
        return

    try:
        with open(CARDS_DATA_FILE, 'r') as f:
            cards = json.load(f)
    except FileNotFoundError:
        print(f"Error: {CARDS_DATA_FILE} not found.")
        return

    processed_cards_info = []

    for card in cards:
        card_name_slug = card['altText'].replace('Riftbound. ', '').split('.')[0].replace(' ', '_').lower()
        if not card_name_slug:
            card_name_slug = f"placeholder_{len(processed_cards_info)}"

        if card['isComingSoon']:
            print(f"Processing coming soon card: {card['altText']}. Using placeholder.")
            destination_blob_name = f"cards/{card_name_slug}.webp"
            try:
                with open(PLACEHOLDER_IMAGE_PATH, 'rb') as f_placeholder:
                    credentials = None
                    if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
                        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                        credentials = service_account.Credentials.from_service_account_file(credentials_path)
                    elif os.path.exists("credentials/service-accountkey.json"):
                        credentials = service_account.Credentials.from_service_account_file("credentials/service-accountkey.json")
                    else:
                        raise Exception("No GCP credentials found.")

                    client = storage.Client(credentials=credentials)
                    bucket = client.get_bucket(GCS_BUCKET_NAME)
                    blob = bucket.blob(destination_blob_name)
                    blob.upload_from_file(f_placeholder, rewind=True)
                    blob.make_public()

                    processed_cards_info.append({
                        'name': card['altText'],
                        'image_url': blob.public_url,
                        'status': 'placeholder'
                    })
            except FileNotFoundError:
                print(f"Placeholder image not found at {PLACEHOLDER_IMAGE_PATH}. Skipping upload for {card_name_slug}.")
            except Exception as e:
                print(f"Error uploading placeholder for {card_name_slug}: {e}")
        else:
            print(f"Processing available card: {card['altText']}")
            public_url = upload_image_to_gcs(
                image_url=card['src'],
                filename=card_name_slug,
                filepath="cards/",
                bucket_name=GCS_BUCKET_NAME
            )
            if public_url:
                processed_cards_info.append({
                    'name': card['altText'],
                    'image_url': public_url,
                    'status': 'processed'
                })

    with open('processed_cards_info.json', 'w') as f:
        json.dump(processed_cards_info, f, indent=4)
    print("Card processing complete. Summary saved to processed_cards_info.json")

if __name__ == '__main__':
    if not os.path.exists(PLACEHOLDER_IMAGE_PATH):
        try:
            img = Image.new('RGB', (100, 150), color='gray')
            img.save(PLACEHOLDER_IMAGE_PATH, 'WEBP')
            print(f"Created dummy placeholder image at {PLACEHOLDER_IMAGE_PATH}")
        except Exception as e:
            print(f"Could not create dummy placeholder image: {e}")

    process_cards()
