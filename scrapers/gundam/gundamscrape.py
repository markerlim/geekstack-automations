import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin
from service.googlecloudservice import upload_image_to_gcs
from service.mongoservice import upload_to_mongo

def scrape_gundam_cards(package_value):
    """Scrape Gundam cards for a specific package value and upload to MongoDB/GCS"""
    if not package_value:
        print("❌ package_value is not provided. Exiting.")
        return
    
    gcs_imgpath_value = os.getenv('GCSIMAGE', 'GUNDAM/test/')
    url = f"https://www.gundam-gcg.com/asia-en/cards/?package={package_value}"
    base_url = "https://www.gundam-gcg.com"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        card_items = [item for item in soup.select('.cardCol .cardItem') 
                     if 'display: none' not in item.get('style', '')]

        json_data = []

        for item in card_items:
            try:
                card_link = item.find('a', class_='cardStr')
                if not card_link:
                    continue

                # Extract basic card info
                detail_url = card_link.get('data-src', '')
                card_id = detail_url.split('detailSearch=')[-1] if 'detailSearch=' in detail_url else ''
                image_url = card_link.find('img').get('data-src', '')
                alt_text = card_link.find('img').get('alt', '')

                # Process image
                full_image_url = urljoin(base_url, image_url) if image_url else ''
                filename = image_url.split('/')[-1].split('?')[0] if image_url else ''
                card_uid = filename.replace('.webp', '')
                urlimage = upload_image_to_gcs(full_image_url, card_uid, gcs_imgpath_value)

                # Initialize card data structure
                card_data = {
                    "cardName": alt_text,
                    "cardId": card_id,
                    "package": package_value,
                    "series": card_id.split('-')[0] if '-' in card_id else '',
                    "urlimage": urlimage,
                    "cardUid": card_uid,
                    "detail_url": urljoin(base_url, detail_url) if detail_url else ''
                }

                # Get additional details from detail page if available
                if detail_url:
                    try:
                        detail_response = requests.get(urljoin(base_url, detail_url), headers=headers)
                        detail_soup = BeautifulSoup(detail_response.content, 'html.parser')
                        
                        # Extract card stats - adjust selectors based on actual page structure
                        stats = detail_soup.select('.cardInfo .infoRow')
                        for stat in stats:
                            label = stat.find(class_='infoLabel').text.strip() if stat.find(class_='infoLabel') else ''
                            value = stat.find(class_='infoValue').text.strip() if stat.find(class_='infoValue') else ''
                            
                            if 'Rarity' in label:
                                card_data['rarity'] = value
                            elif 'Type' in label:
                                card_data['cardType'] = value
                            elif 'Cost' in label:
                                card_data['cost'] = value
                            elif 'Power' in label:
                                card_data['power'] = value
                            elif 'Armor' in label:
                                card_data['armor'] = value
                            elif 'Effect' in label:
                                card_data['effects'] = value
                    except Exception as e:
                        print(f"⚠️ Couldn't fetch details for {card_id}: {str(e)}")

                json_data.append(card_data)
                print(f"✅ Success: {card_data['cardName']} ({card_id})")

            except Exception as e:
                print(f"❌ Error processing card: {str(e)}")

        # Upload to MongoDB
        collection_value = os.getenv('C_GUNDAM', 'gundam_cards')  # Default collection name
        upload_to_mongo(
            data=json_data,
            collection_name=collection_value
        )

        return json_data

    except Exception as e:
        print(f"❌ Fatal error scraping package {package_value}: {str(e)}")
        return []