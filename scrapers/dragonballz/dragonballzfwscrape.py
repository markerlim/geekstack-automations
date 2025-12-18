import requests
from bs4 import BeautifulSoup
import os
import sys
from urllib.parse import urljoin

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.googlecloudservice import upload_image_to_gcs
from service.mongo_service import MongoService

# Initialize Service Layer
mongo_service = MongoService

def map_booster(code):
    if code == '583901':
        return 'PROMO'
    else:
        prefix = code[:4]
        suffix = code[-2:]
        if prefix == '5831':
            return f"FS{suffix}"
        elif prefix == '5830':
            return f"FB{suffix}"
        elif prefix == '5832':
            return f"SD{suffix}"
        else:
            return code
        
def scrape_dragonballzfw_cards(package_value):
    """Scrape Dragonballz cards for a specific value and upload to MongoDB/GCS"""
    if not package_value:
        print("❌ package_value is not provided. Exiting.")
        return
    
    gcs_imgpath_value = f'DBZFW/{package_value}/'
    url = f"https://www.dbs-cardgame.com/fw/en/cardlist/?search=true&category%5B0%5D={package_value}"
    base_url = "https://www.dbs-cardgame.com/fw/en/cardlist/"

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

                img_tag = card_link.find('img')
                alt_text = img_tag.get('alt', '') if img_tag else ''
                card_no = alt_text.split(' ')[0] if alt_text else ''
                card_name = ' '.join(alt_text.split(' ')[1:]) if alt_text else ''

                detail_url = urljoin(base_url, card_link.get('data-src', '')) if card_link.get('data-src') else ''
                # Image handling - initial card image (front side for leaders)
                image_url = img_tag.get('data-src', '') or img_tag.get('src', '')
                full_image_url = urljoin(base_url, image_url) if image_url else ''
                filename = image_url.split('/')[-1].split('?')[0] if image_url else ''
                card_uid = filename.replace('.webp', '')
                urlimage = upload_image_to_gcs(full_image_url, card_uid, gcs_imgpath_value)

                # Initialize base card data structure
                card_data = {
                    "cardNo": card_no,
                    "cardName": card_name,
                    "urlimage": urlimage,
                    "cardUid": card_uid,
                    "detail_url": detail_url,
                    "booster": map_booster(package_value)
                }

                # Get additional details from detail page
                try:
                    detail_response = requests.get(detail_url, headers=headers)
                    detail_soup = BeautifulSoup(detail_response.content, 'html.parser')

                    # Extract common card details
                    card_data['cardNo'] = detail_soup.find('div', class_='cardNo').text.strip() if detail_soup.find('div', class_='cardNo') else ''
                    card_data['rarity'] = detail_soup.find('div', class_='rarity').text.strip() if detail_soup.find('div', class_='rarity') else ''
                    card_data['cardName'] = detail_soup.find('h1', class_='cardName').text.strip() if detail_soup.find('h1', class_='cardName') else ''

                    cardDataRows = detail_soup.find('div', class_='cardData').find_all('div', class_='cardDataRow') if detail_soup.find('div', class_='cardData') else []
                    
                    # Initialize card attributes
                    card_attributes = {
                        'cardType': '',
                        'color': '',
                        'cost': '',
                        'specifiedCost': '',
                        'power': '',
                        'comboPower': '',
                        'features': '',
                        'effect': '',
                        'obtainedFrom': ''
                    }

                    for cardDataRow in cardDataRows:
                        cardDataCells = cardDataRow.find_all('div', class_='cardDataCell')
                        for cardDataCell in cardDataCells:
                            heading = cardDataCell.find('h6').decode_contents().strip() if cardDataCell.find('h6') else ''
                            data = cardDataCell.find('div', class_='data').text.strip() if cardDataCell.find('div', class_='data') else ''
                            
                            if heading == 'Card type':
                                card_attributes['cardType'] = data
                            elif heading == 'Color':
                                card_attributes['color'] = data
                            elif heading == 'Cost':
                                card_attributes['cost'] = data
                            elif heading == 'Specified cost':
                                card_attributes['specifiedCost'] = data
                            elif heading == 'Power':
                                card_attributes['power'] = data
                            elif heading == 'Combo power':
                                card_attributes['comboPower'] = data
                            elif heading == 'Features':
                                card_attributes['features'] = data
                            elif heading == 'Effect':
                                card_attributes['effect'] = data
                            elif heading == 'Where to get it':
                                card_attributes['obtainedFrom'] = data

                    card_data.update(card_attributes)

                    # Check if it's a leader card
                    is_leader = 'LEADER' in card_attributes['cardType'].upper()
                    
                    if is_leader:
                        # Process both front and back sides for leader cards
                        for side in ['front', 'back']:
                            side_class = f'is-{side}'
                            img_div_class = f'img-{side}'
                            side_suffix = '_f' if side == 'front' else '_b'
                            
                            card_data_side = card_data.copy()
                            card_data_side['cardUid'] = f"{card_uid}{side_suffix}"
                            
                            # Get side-specific name
                            card_name_tag = detail_soup.find('h1', class_=f'cardName {side_class}')
                            if card_name_tag:
                                card_data_side['cardName'] = card_name_tag.text.strip()
                            
                            # Get side-specific attributes
                            for attr in ['power', 'features', 'effect']:
                                data_tag = detail_soup.find('div', class_=f'data {side_class}')
                                if data_tag:
                                    card_data_side[attr] = data_tag.text.strip()
                            
                            # Get side-specific image
                            image_div = detail_soup.find('div', class_=img_div_class)
                            if image_div:
                                image_tag = image_div.find('img')
                                if image_tag:
                                    image_url = image_tag.get('data-src', '') or image_tag.get('src', '')
                                    if image_url:
                                        full_image_url = urljoin(base_url, image_url)
                                        filename = f"{card_uid}{side_suffix}"
                                        card_data_side['urlimage'] = upload_image_to_gcs(full_image_url, filename, gcs_imgpath_value)
                            
                            card_data_side['side'] = side
                            json_data.append(card_data_side)
                            print(f"Stored {side} side for leader card: {card_data_side['cardNo']} with UID {card_data_side['cardUid']}")
                    else:
                        # Normal card, store as is
                        json_data.append(card_data)

                except Exception as e:
                    print(f"⚠️ Couldn't fetch details for {card_no}: {str(e)}")

            except Exception as e:
                print(f"❌ Error processing card: {str(e)}")

        # Upload to MongoDB
        collection_value = os.getenv('C_DRAGONBALLZFW')
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