from bs4 import BeautifulSoup
import requests
import re
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.googlecloudservice import upload_image_to_gcs
from service.mongoservice import backup_from_mongo, upload_to_mongo

def map_booster(code):
    if code == '556701':
        return 'FDS'
    elif code == '556801':
        return 'LIMITED'
    elif code == '556901':
        return 'PROMO'
    else:
        prefix = code[:4]
        suffix = code[-2:]
        if prefix == '5560':
            return f"ST{suffix}"
        elif prefix == '5561':
            return f"OP{suffix}"
        elif prefix == '5562':
            return f"EB{suffix}"
        elif prefix == '5563':
            return f"PRB{suffix}"
        else:
            return code

def scrape_onepiece_cards(series_value):
    if not series_value:
        print("❌ series_value is not provided. Exiting.")
        return
    
    gcs_imgpath_value = os.getenv('GCSIMAGE', 'OPTCG/test/')
    url = f"https://asia-en.onepiece-cardgame.com/cardlist/?series={series_value}"
    source_id = series_value
    booster_mapped = map_booster(source_id)
    base_url = "https://asia-en.onepiece-cardgame.com"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": base_url + "/"
    }

    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')

    image_urls = []
    for a_tag in soup.find_all('a'):
        img_tag = a_tag.find('img')
        if img_tag:
            img_src = img_tag.get('data-src') or img_tag.get('src')
            if img_src and '/images/common' not in img_src:
                full_url = base_url + img_src if img_src.startswith('/') else img_src
                image_urls.append(full_url)

    dl_elements = soup.find_all('dl', class_='modalCol')
    if len(image_urls) != len(dl_elements):
        print(f"⚠️  Mismatch in {source_id}: {len(image_urls)} images vs {len(dl_elements)} cards")

    csv_data = [["cardname", "cardid", "rarity", "category", "lifecost", "attribute", "power", "counter", "color", "typing", "effects", "trigger", "urlimage", "cardUid", "booster"]]
    json_data = []

    for idx, dl_element in enumerate(dl_elements):
        try:
            raw_url = image_urls[idx] if idx < len(image_urls) else 'none'
            filename = raw_url.split('/')[-1].split('?')[0]
            urlforscraping = f"{base_url}/images/cardlist/card/{filename}"
            card_uid = filename.replace('.png', '')
            urlimage = upload_image_to_gcs(urlforscraping, card_uid, gcs_imgpath_value)

            cardname = dl_element.find('div', class_='cardName').text.strip()

            try:
                card3span = dl_element.find('div', class_="infoCol").find_all('span')
                cardid = card3span[0].text.strip()
                rarity = card3span[1].text.strip()
                category = card3span[2].text.strip()
            except:
                cardid = rarity = category = "none"

            cost_text = dl_element.find('div', class_='cost').text
            cost_match = re.search(r'\d+', cost_text)
            cost = cost_match.group() if cost_match else "none"

            try:
                attribute = dl_element.find('div', class_='attribute').find('img').get('alt', '')
            except:
                attribute = "none"

            power = dl_element.find('div', class_='power').text.replace('Power', '').strip()
            counter = dl_element.find('div', class_='counter').text.replace('Counter', '').strip()
            color = dl_element.find('div', class_='color').text.replace('Color', '').strip()
            typing = dl_element.find('div', class_='feature').text.replace('Type', '').strip()
            effect = dl_element.find('div', class_='text').get_text().replace('Effect', '').strip()
            try:
                trigger = dl_element.find('div', class_='trigger').text.replace('Trigger', '').strip()
            except:
                trigger = "none"

            csv_data.append([
                cardname, cardid, rarity, category, cost, attribute, power, counter,
                color, typing, effect, trigger, urlimage, card_uid, booster_mapped
            ])

            json_data.append({
                "cardName": cardname,
                "cardId": cardid,
                "rarity": rarity,
                "category": category,
                "lifecost": cost,
                "attribute": attribute,
                "power": power,
                "counter": counter,
                "color": color,
                "typing": typing,
                "effects": effect,
                "trigger": trigger,
                "urlimage": urlimage,
                "cardUid": card_uid,
                "booster": booster_mapped
            })

            print(f"{booster_mapped} ✅ Parsed: {cardname}")

        except Exception as e:
            print(f"❌ Error parsing card in {booster_mapped}: {e}")


    collection_value = os.getenv('C_ONEPIECE')
    if collection_value:
        try:
            upload_to_mongo(
                data=json_data,
                collection_name=collection_value,
                backup_before_upload=True
            )
        except Exception as e:
                    print(f"❌ MongoDB operation failed: {str(e)}")
    else:
        print("⚠️ MongoDB collection name not found in environment variables")
