import requests
from bs4 import BeautifulSoup
import os
import sys
from urllib.parse import urljoin

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.googlecloudservice import upload_image_to_gcs
from service.mongoservice import upload_to_mongo

def map_booster(code):
    if code == '595901':
        return 'PROMO'
    else:
        prefix = code[:4]
        suffix = code[-2:]
        if prefix == '5951':
            return f"ST{suffix}"
        elif prefix == '5950':
            return f"FB{suffix}"
        elif prefix == '5952':
            return f"SD{suffix}"
        else:
            return code
        
def scrape_dragonballzfw_cards(package_value):
    """Scrape Dragonballz cards for a specific value and upload to MongoDB/GCS"""
    if not package_value:
        print("❌ package_value is not provided. Exiting.")
        return
    
    gcs_imgpath_value = f'DBZFW/{package_value}/'
    url = f"https://www.dbs-cardgame.com/fw/asia-en/cardlist/?search=true&category%5B0%5D={package_value}"
    base_url = "https://www.dbs-cardgame.com/fw/asia-en/cardlist/"

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

                # Extract card number from alt text or data-src
                img_tag = card_link.find('img')
                alt_text = img_tag.get('alt', '') if img_tag else ''
                # Example alt_text: "FS01-01 Son Goku"
                card_no = alt_text.split(' ')[0] if alt_text else ''
                card_name = ' '.join(alt_text.split(' ')[1:]) if alt_text else ''

                # Build detail URL
                detail_url = f"https://dbs-cardgame.com/fw/en/cardlist/detail.php?card_no={card_no}"

                # Image handling
                image_url = img_tag.get('data-src', '') or img_tag.get('src', '')
                full_image_url = urljoin(base_url, image_url) if image_url else ''
                filename = image_url.split('/')[-1].split('?')[0] if image_url else ''
                card_uid = filename.replace('.webp', '')
                urlimage = upload_image_to_gcs(full_image_url, card_uid, gcs_imgpath_value)

                # Initialize card data structure
                card_data = {
                    "cardNo": card_no,
                    "cardName": card_name,
                    "urlimage": urlimage,
                    "cardUid": card_uid,
                    "detail_url": detail_url,
                    "package": package_value
                }

                # Get additional details from new detail page
                try:
                    detail_response = requests.get(detail_url, headers=headers)
                    detail_soup = BeautifulSoup(detail_response.content, 'html.parser')

                    card_data['cardNo'] = detail_soup.find('div', class_='cardNo').text.strip() if detail_soup.find('div', class_='cardNo') else ''
                    card_data['rarity'] = detail_soup.find('div', class_='rarity').text.strip() if detail_soup.find('div', class_='rarity') else ''
                    card_data['cardName'] = detail_soup.find('h1', class_='cardName').text.strip() if detail_soup.find('h1', class_='cardName') else ''

                    cardDataRows = detail_soup.find('div', class_='cardData').find_all('div', class_='cardDataRow') if detail_soup.find('div', class_='cardData') else []
                    # Initialize variables
                    cardtype = color = cost = specifiedcost = power = combopower = features = effects = setFrom = ''

                    for cardDataRow in cardDataRows:
                        cardDataCells = cardDataRow.find_all('div', class_='cardDataCell')
                        for cardDataCell in cardDataCells:
                            heading = cardDataCell.find('h6').decode_contents().strip() if cardDataCell.find('h6') else ''
                            data = cardDataCell.find('div', class_='data').text.strip() if cardDataCell.find('div', class_='data') else ''
                            if heading == 'Card type':
                                cardtype = data
                            elif heading == 'Color':
                                color = data
                            elif heading == 'Cost':
                                cost = data
                            elif heading == 'Specified cost':
                                specifiedcost = data
                            elif heading == 'Power':
                                power = data
                            elif heading == 'Combo power':
                                combopower = data
                            elif heading == 'Features':
                                features = data
                            elif heading == 'Effect':
                                effects = data
                            elif heading == 'Where to get it':
                                setFrom = data

                    # Add extracted fields to card_data
                    card_data.update({
                        "cardType": cardtype,
                        "color": color,
                        "cost": cost,
                        "specifiedCost": specifiedcost,
                        "power": power,
                        "comboPower": combopower,
                        "features": features,
                        "effect": effects,
                        "obtainedFrom": setFrom
                    })

                    print([
                        card_data.get('cardNo', ''), card_data.get('rarity', ''), card_data.get('cardName', ''),
                        cardtype, color, cost, specifiedcost, power, combopower, features, effects, setFrom
                    ])
                    print(detail_url, "completed")

                except Exception as e:
                    print(f"⚠️ Couldn't fetch details for {card_no}: {str(e)}")

                json_data.append(card_data)
                print(f"✅ Success: {card_data['cardName']} ({card_no})")

            except Exception as e:
                print(f"❌ Error processing card: {str(e)}")

        # Upload to MongoDB
        collection_value = os.getenv('C_DRAGONBALLZ')  # Default collection name
        upload_to_mongo(
            data=json_data,
            collection_name=collection_value
        )

        return json_data

    except Exception as e:
        print(f"❌ Fatal error scraping package {package_value}: {str(e)}")
        return []