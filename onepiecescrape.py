from bs4 import BeautifulSoup 
import requests 
import csv
import json
import re

from googlecloudservice import upload_image_to_gcs
from mongoservice import upload_to_mongo

# Booster mapping function
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

# Master list of URLs
listofall = [
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556001", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556002",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556003", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556004",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556005", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556006",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556007", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556008",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556009", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556010",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556011", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556012",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556013", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556014",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556015", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556016",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556017", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556018",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556019", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556020",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556101", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556102",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556103", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556104",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556105", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556106",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556107", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556108",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556109", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556110",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556111", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556201",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556202", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556301",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556701", "https://asia-en.onepiece-cardgame.com/cardlist/?series=556801",
    "https://asia-en.onepiece-cardgame.com/cardlist/?series=556901",
]
oneurl = ["https://asia-en.onepiece-cardgame.com/cardlist/?series=556701"]
csv_data = [["cardname", "cardid", "rarity", "category", "lifecost", "attribute", "power", "counter", "color", "typing", "effects", "trigger", "urlimage", "cardUid", "booster"]]
json_data = []

for url in oneurl:
    source_id = url[-6:]  # Last 6 characters
    booster_mapped = map_booster(source_id)
    base_url = "https://asia-en.onepiece-cardgame.com"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://asia-en.onepiece-cardgame.com/"
    }

    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Extract image URLs
    image_urls = []
    for a_tag in soup.find_all('a'):
        img_tag = a_tag.find('img')
        if img_tag:
            img_src = img_tag.get('data-src') or img_tag.get('src')
            if img_src and '/images/common' not in img_src:
                full_url = base_url + img_src if img_src.startswith('/') else img_src
                image_urls.append(full_url)

    # Extract card info
    dl_elements = soup.find_all('dl', class_='modalCol')

    if len(image_urls) != len(dl_elements):
        print(f"⚠️  Mismatch in {source_id}: {len(image_urls)} images vs {len(dl_elements)} cards")

    for idx, dl_element in enumerate(dl_elements):
        try:
            raw_url = image_urls[idx] if idx < len(image_urls) else 'none'
            filename = raw_url.split('/')[-1].split('?')[0]
            urlforscraping = f"{base_url}/images/cardlist/card/{filename}"
            card_uid = filename.replace('.png', '')
            urlimage = upload_image_to_gcs(urlforscraping, card_uid, "OPTCG/test/")
            #urlimage = f"https://storage.googleapis.com/geek-stack.appspot.com/OPTCG/card/{filename}.webp"

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
            effect = dl_element.find('div', class_='text').decode_contents().replace('Effect', '').strip()

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

upload_to_mongo(
    data=json_data,
    db_name="geekstack",
    collection_name="CL_onepiece_v3")

