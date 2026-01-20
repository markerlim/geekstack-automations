import json
import re
from bs4 import BeautifulSoup
import os
import sys
from urllib.parse import urljoin

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.googlecloudservice import upload_image_to_gcs
from service.mongo_service import MongoService
from service.api_service import ApiService

# Environment Variables
C_GUNDAM = os.getenv('C_GUNDAM')
GCS_GUNDAM = os.getenv('GCS_GUNDAM')
BASE_URL = "https://www.gundam-gcg.com"

# Initialize Service Layer
mongo_service = MongoService()
api_service = ApiService(BASE_URL)

def scrape_gundam_cards(package_value):
    """Scrape Gundam cards for a specific package value and upload to MongoDB/GCS"""
    if not package_value:
        print("❌ package_value is not provided. Exiting.")
        return
    
    gcs_imgpath_value = f'{GCS_GUNDAM}{package_value}/'

    try:
        response = api_service.get(f"/asia-en/cards/?package={package_value}")
        soup = BeautifulSoup(response['data'], 'html.parser')

        card_items = [item for item in soup.select('.cardCol .cardItem') 
                     if 'display: none' not in item.get('style', '')]

        json_data = []
        carduid_from_mongo = set(mongo_service.get_unique_values_scoped(C_GUNDAM,"package",package_value,"cardUid"))
        for item in card_items:
            try:
                card_link = item.find('a', class_='cardStr')
                if not card_link:
                    continue

                base_url = BASE_URL
                # Extract basic card info
                detail_url = card_link.get('data-src', '')
                card_id = detail_url.split('detailSearch=')[-1] if 'detailSearch=' in detail_url else ''
                image_url = card_link.find('img').get('data-src', '') or card_link.find('img').get('src', '')
                alt_text = card_link.find('img').get('alt', '')

                # Process image
                full_image_url = urljoin(base_url, image_url) if image_url else ''
                filename = image_url.split('/')[-1].split('?')[0] if image_url else ''
                card_uid = filename.replace('.webp', '')
                if card_uid in carduid_from_mongo:
                    print(f"⚠️ Skipping existing cardUid: {card_uid}")
                    continue
                urlimage = upload_image_to_gcs(full_image_url, card_uid, gcs_imgpath_value)

                # Initialize card data structure
                card_data = {
                    "cardName": alt_text,
                    "package": package_value,
                    "series": card_id.split('-')[0] if '-' in card_id else '',
                    "urlimage": urlimage,
                    "cardUid": card_uid,
                    "detail_url": urljoin(base_url, f"/asia-en/cards/{detail_url}") if detail_url else ''
                }

                # Get additional details from detail page if available
                if detail_url:
                    try:
                        print(f"Fetching details for card ID: {card_uid} from {detail_url}")
                        detail_response = api_service.get(f"/asia-en/cards/{detail_url}")
                        detail_soup = BeautifulSoup(detail_response['data'], 'html.parser')
                        
                        # Extract card number and rarity
                        card_no_element = detail_soup.select_one('.cardNoCol .cardNo')
                        if card_no_element:
                            card_data['cardId'] = card_no_element.get_text(strip=True)
                        
                        rarity_element = detail_soup.select_one('.cardNoCol .rarity')
                        if rarity_element:
                            card_data['rarity'] = rarity_element.get_text(strip=True)
                        
                        # Extract level, cost, color, type
                        side_data = detail_soup.select('.cardDataRow.side .dataBox')
                        for data in side_data:
                            label = data.select_one('.dataTit').get_text(strip=True) if data.select_one('.dataTit') else ''
                            value = data.select_one('.dataTxt').get_text(strip=True) if data.select_one('.dataTxt') else ''
                            
                            if label == 'Lv.':
                                card_data['level'] = value
                            elif label == 'COST':
                                card_data['cost'] = value
                            elif label == 'COLOR':
                                card_data['color'] = value
                            elif label == 'TYPE':
                                card_data['cardType'] = value
                        
                        # Extract overview/effect text
                        overview_element = detail_soup.select_one('.cardDataRow.overview .dataTxt')
                        print(overview_element)
                        if overview_element:
                            # Get the HTML content and process it
                            effect_html = str(overview_element)
                            # This regex matches <br> that is NOT followed by optional whitespace and </div>
                            effect_html = re.sub(r'<br/>(?!\s*</div>)', '\n', effect_html)
                            
                            # Parse the modified HTML and get text
                            effect_soup = BeautifulSoup(effect_html, 'html.parser')
                            effect = effect_soup.get_text(strip=True)
                            
                            # Clean up any remaining HTML entities
                            effect = effect.replace('&lt;', '<').replace('&gt;', '>')
                            
                            card_data['effect'] = effect
                        
                        # Extract zone, trait, link
                        other_data = detail_soup.select('.cardDataRow:not(.side) .dataBox')
                        for data in other_data:
                            label = data.select_one('.dataTit').get_text(strip=True) if data.select_one('.dataTit') else ''
                            value = data.select_one('.dataTxt').get_text(strip=True) if data.select_one('.dataTxt') else ''
                            
                            if label == 'Zone':
                                card_data['zone'] = value
                            elif label == 'Trait':
                                card_data['trait'] = value
                            elif label == 'Link':
                                card_data['link'] = value
                        
                        # Extract AP and HP if available
                        ap_hp_data = detail_soup.select('.cardDataRow.side .dataBox')
                        for data in ap_hp_data:
                            label = data.select_one('.dataTit').get_text(strip=True) if data.select_one('.dataTit') else ''
                            value = data.select_one('.dataTxt').get_text(strip=True) if data.select_one('.dataTxt') else ''
                            
                            if label == 'AP':
                                card_data['attackPower'] = value
                            elif label == 'HP':
                                card_data['hitPoints'] = value
                        
                        # Extract source title
                        source_element = detail_soup.select_one('.cardDataRow dl:has(.dataTit:contains("Source Title")) .dataTxt')
                        if source_element:
                            card_data['sourceTitle'] = source_element.get_text(strip=True)
                        
                        # Extract where to get it
                        where_element = detail_soup.select_one('.cardDataRow dl:has(.dataTit:contains("Where to get it")) .dataTxt')
                        if where_element:
                            card_data['obtainedFrom'] = where_element.get_text(strip=True)

                    except Exception as e:
                        print(f"⚠️ Couldn't fetch details for {card_id}: {str(e)}")

                json_data.append(card_data)
                print(json.dumps(card_data, indent=2, ensure_ascii=False))
                print(f"✅ Success: {card_data['cardName']} ({card_id})")

            except Exception as e:
                print(f"❌ Error processing card: {str(e)}")

        # Upload to MongoDB
        collection_value = C_GUNDAM # Default collection name
        if collection_value:
            try:
                mongo_service.upload_data(
                    data=json_data,
                    collection_name=collection_value,
                    backup_before_upload=True
                )
            except Exception as e:
                print(f"❌ MongoDB operation failed: {str(e)}")
        else:
            print("⚠️ MongoDB collection name not found in environment variables")        

        return json_data

    except Exception as e:
        print(f"❌ Fatal error scraping package {package_value}: {str(e)}")
        return []