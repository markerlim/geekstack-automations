import requests
from bs4 import BeautifulSoup
import os
import sys
from urllib.parse import urljoin

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.googlecloudservice import upload_image_to_gcs
from service.translationservice import translate_data

def process_effect_with_icons(detail_div):
    """Process the effect div to convert icon images to bracketed alt text"""
    # Clone the div to avoid modifying the original
    div_copy = BeautifulSoup(str(detail_div), 'html.parser')
    
    # Find all icon images in the detail div
    icon_imgs = div_copy.find_all('img', class_='icon-img')
    
    # Replace each icon image with its alt text in brackets
    for img in icon_imgs:
        alt_text = img.get('alt', '')
        if alt_text:
            bracketed_text = f"[{alt_text}]"
            # Replace the img tag with bracketed text
            img.replace_with(bracketed_text)
    
    # Get the processed text content
    effect_text = div_copy.get_text(separator=' ', strip=True)
    
    # Clean up any extra whitespace
    import re
    effect_text = re.sub(r'\s+', ' ', effect_text)
    
    return effect_text

def scrape_wsb_card(cardno, expansion_code, translate=True):
    """Scrape WSB card data for a specific card number with optional translation"""
    if not cardno:
        print("❌ cardno is not provided. Exiting.")
        return
    
    base_url = "https://ws-blau.com"
    url = f"{base_url}/cardlist/?cardno={cardno}"
    gcs_imgpath_value = f'WSB/{expansion_code}/'

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # Find the main card detail box
        detail_box = soup.find('div', class_='cardlist-Detail_Box')
        if not detail_box:
            print(f"❌ Card {cardno} not found")
            return None

        # Initialize card data
        card_data = {
            "cardId": cardno,
            "detail_url": url
        }

        # Extract card image
        img_box = detail_box.find('div', class_='img_Box')
        if img_box:
            img_tag = img_box.find('img')
            if img_tag:
                image_url = img_tag.get('src', '')
                if image_url:
                    full_image_url = urljoin(base_url, image_url)
                    filename = image_url.split('/')[-1].split('.')[0]
                    card_data['cardUid'] = filename
                    try:
                        card_data['urlimage'] = upload_image_to_gcs(image_url=full_image_url, filename=filename, filepath=gcs_imgpath_value)
                    except Exception as e:
                        print(f"⚠️ Image upload failed for {cardno}: {str(e)}")
                        card_data['urlimage'] = full_image_url

        # Extract card name
        title_tag = detail_box.find('h1', class_='ttl')
        if title_tag:
            card_data['cardName'] = title_tag.text.strip()

        # Extract spec icons (rarity, foil, hologram, drawing)
        spec_div = detail_box.find('div', class_='spec')
        spec_icons = []
        if spec_div:
            current_specs = spec_div.find_all('div', class_='icon-spec current')
            for spec in current_specs:
                img = spec.find('img')
                if img:
                    spec_icons.append(img.get('alt', ''))
        card_data['specifications'] = spec_icons

        # Extract info fields
        info_div = detail_box.find('div', class_='info')
        if info_div:
            dl_elements = info_div.find_all('dl')
            for dl in dl_elements:
                dt = dl.find('dt')
                dd = dl.find('dd')
                if dt and dd:
                    field_name = dt.text.strip()
                    
                    if field_name == '収録商品':
                        card_data['product'] = dd.text.strip()
                    elif field_name == '作品区分':
                        card_data['series'] = dd.text.strip()
                    elif field_name == 'カード種類':
                        card_data['cardType'] = dd.text.strip()
                    elif field_name == 'レアリティ':
                        card_data['rarity'] = dd.text.strip()
                    elif field_name == '色':
                        # Extract color from icon
                        color_img = dd.find('img')
                        if color_img:
                            card_data['color'] = color_img.get('alt', '')
                    elif field_name == '特徴':
                        card_data['features'] = dd.text.strip()

        # Extract status information
        status_div = detail_box.find('div', class_='status')
        if status_div:
            status_items = status_div.find_all('span', class_='status-Item')
            for item in status_items:
                heading = item.find('span', class_='heading')
                if heading:
                    field = heading.text.strip()
                    value = item.text.replace(heading.text, '').strip()
                    
                    if field == 'レベル':
                        card_data['level'] = value
                    elif field == 'コスト':
                        card_data['cost'] = value
                    elif field == 'パワー':
                        card_data['power'] = value
                    elif field == 'ソウル':
                        card_data['soul'] = value
                    elif field == 'トリガー':
                        card_data['trigger'] = value

        # Extract card effect/detail
        detail_div = detail_box.find('div', class_='detail')
        if detail_div:
            # Process the detail div to convert icon images to bracketed alt text
            effect_text = process_effect_with_icons(detail_div)
            card_data['effect'] = effect_text
            print(f"🎯 Effect with icons: {effect_text[:100]}..." if len(effect_text) > 100 else f"🎯 Effect with icons: {effect_text}")

        # Extract supplementary info
        sup_div = detail_box.find('div', class_='sup')
        if sup_div:
            sup_texts = sup_div.find_all('p', class_='sup-txt')
            if len(sup_texts) >= 2:
                card_data['cardNo'] = sup_texts[0].text.strip()  # Override with accurate card number
                card_data['pronunciation'] = sup_texts[1].text.strip()

        print(f"Scraped card: {card_data.get('cardName', cardno)}")
        
        # Apply translation if requested
        if translate:
            print(f"🔄 Translating card data...")
            fields_to_translate = [
                'cardName', 'booster', 'series', 'cardType', 
                'color', 'features', 'effect', 'specifications'
            ]
            translated_data = translate_data([card_data], fields_to_translate)
            card_data = translated_data[0] if translated_data else card_data
            print(f"✅ Translation completed")
        
        return card_data

    except Exception as e:
        print(f"❌ Error scraping card {cardno}: {str(e)}")
        return None
    