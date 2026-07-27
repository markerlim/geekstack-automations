import requests
from bs4 import BeautifulSoup
import os
import sys
import re
from urllib.parse import urljoin

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.googlecloudservice import upload_image_to_gcs


def parse_color_icon(dd):
    color_img = dd.find('img')
    if color_img:
        alt = color_img.get('alt', '')
        color_map = {
            '白': 'White', '緑': 'Green', '赤': 'Red',
            '青': 'Blue', '紫': 'Purple', '黄': 'Yellow', '無': 'Colorless'
        }
        return color_map.get(alt, alt)
    return dd.text.strip()


def scrape_hololive_card(card_id, translate=True):
    """Scrape a single hololive OCG card by its global ID"""
    if not card_id:
        return None

    base_url = "https://hololive-official-cardgame.com"
    url = f"{base_url}/cardlist/?id={card_id}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "ja,en;q=0.9"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        card_data = {
            "cardId": str(card_id),
            "detail_url": url
        }

        detail_box = soup.find('div', class_='cardlist-Detail_Box_Inner')
        if not detail_box:
            detail_box = soup.find('div', class_='cardlist-Detail_Box')
        if not detail_box:
            return None

        # --- Image ---
        img_div = detail_box.find('div', class_='img')
        if img_div:
            img_tag = img_div.find('img')
            if img_tag:
                image_url = img_tag.get('src', '')
                if image_url:
                    full_image_url = urljoin(base_url, image_url)
                    filename = image_url.split('/')[-1].split('.')[0]
                    card_data['cardUid'] = filename
                    folder = image_url.split('/')[-2] if '/cardlist/' in image_url else ''
                    gcs_path = f'hOCG/{folder}/'
                    try:
                        card_data['urlimage'] = upload_image_to_gcs(
                            image_url=full_image_url,
                            filename=filename,
                            filepath=gcs_path
                        )
                    except Exception:
                        card_data['urlimage'] = full_image_url

        # --- Card Name ---
        name_tag = detail_box.find('h1', class_='name')
        if name_tag:
            card_data['cardName'] = name_tag.get_text(strip=True)

        # --- Info fields (type, rarity, color, HP, etc.) ---
        info_div = detail_box.find('div', class_='info')
        if info_div:
            dts = info_div.find_all('dt')
            dds = info_div.find_all('dd')
            for dt, dd in zip(dts, dds):
                field = dt.get_text(strip=True)
                field_map = {
                    'カードタイプ': 'cardType',
                    'レアリティ': 'rarity',
                    '収録商品': 'product',
                    '色': 'color',
                    'HP': 'hp',
                    'Bloomレベル': 'bloomLevel',
                    'バトンタッチ': 'batonTouch',
                    'LIFE': 'life',
                    'タグ': 'tags',
                }
                key = field_map.get(field)
                if key == 'color':
                    card_data[key] = parse_color_icon(dd)
                elif key == 'batonTouch':
                    icons = dd.find_all('img')
                    card_data[key] = [img.get('alt', '') for img in icons]
                elif key:
                    card_data[key] = dd.get_text(strip=True)

        card_type = card_data.get('cardType', '')

        # --- Oshi Skills (only for oshi type cards) ---
        if '推し' in card_type:
            oshi_skill_div = detail_box.find('div', class_='oshi')
            if oshi_skill_div:
                skill_ps = oshi_skill_div.find_all('p')
                if len(skill_ps) >= 2:
                    card_data['oshiSkill'] = skill_ps[1].get_text(strip=True)

            sp_skill_div = detail_box.find('div', class_='sp')
            if sp_skill_div:
                skill_ps = sp_skill_div.find_all('p')
                if len(skill_ps) >= 2:
                    card_data['spOshiSkill'] = skill_ps[1].get_text(strip=True)

        # --- Illustrator & Card Number ---
        illustrator_div = detail_box.find('div', class_='illustrator')
        if illustrator_div:
            ill_name_p = illustrator_div.find('p', class_='ill-name')
            if ill_name_p:
                ill_span = ill_name_p.find('span')
                if ill_span:
                    card_data['illustrator'] = ill_span.get_text(strip=True)
                else:
                    card_data['illustrator'] = ill_name_p.get_text(strip=True).replace('イラストレーター名：', '').strip()

            number_p = illustrator_div.find('p', class_='number')
            if number_p:
                num_span = number_p.find('span')
                if num_span:
                    card_data['cardNo'] = num_span.get_text(strip=True)

        # --- Keyword/Arts/Extra via text fallback ---
        txt_inner = detail_box.find('div', class_='txt-Inner')
        if txt_inner:
            all_text = txt_inner.get_text(separator='\n', strip=True)
        else:
            all_text = detail_box.get_text(separator='\n', strip=True)

        # Keyword
        kw_match = re.search(r'キーワード\s*(.*?)(?:アーツ|$)', all_text, re.DOTALL)
        if kw_match:
            card_data['keyword'] = kw_match.group(1).strip()

        # Arts (only for non-oshi cards which have an arts section)
        if '推し' not in card_type:
            arts_match = re.search(r'アーツ\s*(.*?)(?:エクストラ|イラストレーター|$)', all_text, re.DOTALL)
            if arts_match:
                card_data['arts'] = arts_match.group(1).strip()

        # Extra
        extra_match = re.search(r'エクストラ\s*(.*?)(?:イラストレーター|$)', all_text, re.DOTALL)
        if extra_match:
            card_data['extra'] = extra_match.group(1).strip()

        # Ability text (for Yell/Support cards)
        ab_match = re.search(r'能力テキスト\s*(.*?)(?:色|イラストレーター|$)', all_text, re.DOTALL)
        if ab_match:
            card_data['abilityText'] = ab_match.group(1).strip()

        # --- Fallback regex extraction for missed fields ---
        if 'cardType' not in card_data:
            m = re.search(r'カードタイプ\s*(.*?)(?:\n|$)', all_text)
            if m:
                card_data['cardType'] = m.group(1).strip()

        if 'rarity' not in card_data:
            m = re.search(r'レアリティ\s*(.*?)(?:\n|$)', all_text)
            if m:
                card_data['rarity'] = m.group(1).strip()

        if '推し' not in card_type:
            if 'hp' not in card_data:
                m = re.search(r'HP\s*(\d+)', all_text)
                if m:
                    card_data['hp'] = m.group(1)

            if 'bloomLevel' not in card_data:
                m = re.search(r'Bloomレベル\s*(Debut|1st|2nd|Spot)', all_text)
                if m:
                    card_data['bloomLevel'] = m.group(1)

        if 'cardNo' not in card_data:
            m = re.search(r'カードナンバー[：:]\s*(\S+)', all_text)
            if m:
                card_data['cardNo'] = m.group(1).strip()

        if 'illustrator' not in card_data:
            m = re.search(r'イラストレーター名[：:]\s*(.*?)(?:\n|$)', all_text)
            if m:
                candidate = m.group(1).strip()
                if candidate and not re.match(r'^h\w{2,}', candidate):
                    card_data['illustrator'] = candidate

        if 'tags' not in card_data:
            m = re.search(r'タグ\s*(.*?)(?:\n|$)', all_text)
            if m:
                card_data['tags'] = m.group(1).strip()

        # Oshi skills fallback (only for oshi cards)
        if '推し' in card_type:
            if 'oshiSkill' not in card_data:
                m = re.search(r'推しスキル\s*(.*?)(?:SP推しスキル|キーワード|アーツ|イラストレーター|$)', all_text, re.DOTALL)
                if m:
                    card_data['oshiSkill'] = m.group(1).strip()

            if 'spOshiSkill' not in card_data:
                m = re.search(r'SP推しスキル\s*(.*?)(?:キーワード|アーツ|イラストレーター|$)', all_text, re.DOTALL)
                if m:
                    card_data['spOshiSkill'] = m.group(1).strip()

        if 'cardName' in card_data:
            print(f"  Scraped: {card_data['cardName']} ({card_data.get('cardNo', card_id)})")

        return card_data

    except requests.RequestException:
        return None
    except Exception as e:
        print(f"  Error scraping card {card_id}: {e}")
        return None
