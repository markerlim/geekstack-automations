import requests
from bs4 import BeautifulSoup
import json
import re
import os
import sys
from datetime import datetime

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.googlecloudservice import upload_image_to_gcs
from service.mongoservice import upload_to_mongo, validate_from_mongo
from service.github_service import GitHubService
import base64

# GitHub config
github_service = GitHubService()
DATE_FILE_PATH = "duelmasterdb/last_pdt_date.json"

# Function to scrape a single page
def scrape_page(url, category_key):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Find all items on the page - use category-specific class
    # deck -> 'itemList01_item deck'
    # expansion -> 'itemList01_item expansion'
    # other -> 'itemList01_item others'
    category_class_map = {
        'deck': 'itemList01_item deck',
        'expansion': 'itemList01_item expansion',
        'other': 'itemList01_item others'
    }
    
    class_selector = category_class_map.get(category_key, 'itemList01_item')
    items = soup.find_all('div', class_=class_selector)

    # Create a list to store the extracted data
    product_data = []

    for item in items:
        # Extract image URL
        img_tag = item.find('div', class_='img')
        img_url = img_tag.find('img')['src'] if img_tag and img_tag.find('img') else 'N/A'

        # Extract product title
        title_tag = item.find('h2', class_='title')
        title = title_tag.get_text(strip=True) if title_tag else 'N/A'

        # Extract release date
        release_date_tag = item.find('dt', string='発売日')
        if release_date_tag:
            raw_date = release_date_tag.find_next('dd').get_text(strip=True)

            # Try to match full date (YYYY年MM月DD日)
            match_full = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", raw_date)
            match_partial = re.match(r"(\d{4})年(\d{1,2})月", raw_date)  # Match only YYYY年MM月

            if match_full:
                year, month, day = map(int, match_full.groups())  # Extract year, month, day
            elif match_partial:
                year, month = map(int, match_partial.groups())  # Extract only year, month
                day = 1  # Default to 1st day of the month
            else:
                year, month, day = None, None, None  # No valid date found

            release_date = datetime(year, month, day) if year and month and day else None
        else:
            release_date = None


        # Extract product details link
        detail_link_tag = item.find('a', class_='btn_basic01')
        detail_link = detail_link_tag['href'] if detail_link_tag else 'N/A'

        # Extract booster code from img_url by finding first 'dm' from the right
        booster = ''
        if img_url != 'N/A':
            # Special handling for playsdeck images - replace playsdeck with dmpcd + formatted number
            if 'playsdeck' in img_url:
                # Extract the playsdeck part and replace with dmpcd
                parts = img_url.strip('/').split('/')
                for part in reversed(parts):
                    part_name = part.split('.')[0] if '.' in part else part
                    if 'playsdeck' in part_name:
                        # Extract number from playsdeck (e.g., playsdeck2 -> 2, playsdeck -> 1)
                        if part_name == 'playsdeck':
                            # No number means it's the first one
                            number = 1
                        else:
                            # Extract number after 'playsdeck'
                            number_str = part_name.replace('playsdeck', '')
                            try:
                                number = int(number_str)
                            except ValueError:
                                number = 1  # Default fallback
                        
                        # Format as dmpcd + zero-padded 2-digit number
                        booster = f"dmpcd{number:02d}"
                        break
            else:
                # Split the URL and iterate from right to left to find first segment starting with 'dm'
                parts = img_url.strip('/').split('/')
                for part in reversed(parts):
                    # Remove file extension if present
                    part_name = part.split('.')[0] if '.' in part else part
                    if part_name.startswith('dm'):
                        booster = part_name
                        break
        
        print(f"DEBUG img_url: '{img_url}'")
        print(f"DEBUG extracted booster: '{booster}'")
        
        # Skip items with no image URL
        if img_url == 'N/A' or not booster:
            print(f"Skipping item with no image: img_url='{img_url}', booster='{booster}'")
            continue

        # Format the product data to match final schema (without uploading image yet)
        product_obj = {
            'img_url': img_url,  # Store original URL for later upload
            'booster': booster,
            'japtext': title,
            'timestamp': release_date if release_date else None,
            'detailLink': detail_link,
            'category': category_key
        }

        # Append the extracted data to the product_data list
        product_data.append(product_obj)

    # --- DYNAMIC PAGINATION PATCH START ---
    # Check if there's a next page link in the pagination
    has_next_page = False
    pagination = soup.find('div', class_='wp-pagenavi')
    if pagination:
        next_link = pagination.find('a', class_='nextpostslink')
        has_next_page = next_link is not None
    print(f"DEBUG pagination: {pagination}")
    print(f"DEBUG next_link: {next_link if pagination else None}")
    print(f"DEBUG has_next_page: {has_next_page}")
    # --- DYNAMIC PAGINATION PATCH END ---

    return product_data, has_next_page

# Main scraping loop for multiple pages
def duelmaster_cover_scrape():
    product_categories = [
        {'path': '/product/deck/page/', 'key': 'deck', 'name': 'Deck Products'},
        {'path': '/product/expansion/page/', 'key': 'expansion', 'name': 'Expansion Products'},
        {'path': '/product/others/page/', 'key': 'others', 'name': 'Other Products'}
    ]

    total_new_products = 0
    json_object, file_sha = github_service.load_json_file(DATE_FILE_PATH)

    for category in product_categories:
        # Get last processed date for this category from GitHubService loaded data
        last_date = None
        if json_object and category['key'] in json_object:
            date_str = json_object[category['key']].get('last_date')
            # Handle empty strings
            if date_str and date_str.strip():
                last_date = datetime.fromisoformat(date_str)
        
        category_latest_date = last_date
        category_new_products = []
        
        base_url = f'https://dm.takaratomy.co.jp{category["path"]}'
        print(f"\n🔍 Scraping {category['name']}...")
        if last_date:
            print(f"   Last processed date: {last_date.isoformat()}")
        else:
            print(f"   Last processed date: None (will scrape ALL products)")
        
        # Loop through pages 1 to 6 (you can adjust this if more pages are needed)
        page_num = 1
        while True:
            url = base_url + str(page_num)
            print(f"  Scraping page {page_num}: {url}")
            try:
                page_data, has_next_page = scrape_page(url, category['key'])
                # Filter products by date - only add products with timestamp after last_date for this category
                # If last_date is None, scrape all products
                new_products = []
                print(f"  DEBUG: last_date for {category['key']}: {last_date}")
                for product in page_data:
                    # Get the release date from the product (it's already a datetime object)
                    release_date = product.get('timestamp')
                    booster_name = product.get('booster', 'Unknown')
                    
                    # If no release date, add product if this is first run (last_date is None)
                    if release_date is None:
                        if last_date is None:
                            new_products.append(product)
                            print(f"    DEBUG: Added {booster_name} (no date, first run)")
                        else:
                            print(f"    DEBUG: Skipped {booster_name} (no date, not first run)")
                        continue
                    
                    print(f"    DEBUG: Product {booster_name} date: {release_date}, last_date: {last_date}")
                    
                    # Add product if it's newer than last processed date (or first run)
                    if last_date is None or release_date > last_date:

                        collection_value = os.getenv("C_DUELMASTERS")
                        if not validate_from_mongo(collection_value, "booster", booster_name)['exists']:
                            print(f"DEBUG booster '{booster_name}' not found in MongoDB, marking as unreleased")
                            product['category'] = f"{category['key']}_unreleased"
                        # Upload image to GCS now that we know this product is new
                        img_url = product.get('img_url')
                        if img_url != 'N/A':
                            gcs_url = upload_image_to_gcs(
                                image_url=f"https://dm.takaratomy.co.jp{img_url}", 
                                filename=booster_name, 
                                filepath="boostercover/duelmaster/")
                            product['urlimage'] = gcs_url
                        else:
                            product['urlimage'] = 'N/A'
                        # Remove the temporary img_url field
                        del product['img_url']
                        new_products.append(product)
                        print(f"    DEBUG: Added {booster_name} (newer than last date)")
                        # Track the latest date in this category
                        if category_latest_date is None or release_date > category_latest_date:
                            category_latest_date = release_date
                    else:
                        print(f"    DEBUG: Skipped {booster_name} (older than last date)")
                        # If we hit an older product, we can stop processing this page since products should be in reverse chronological order
                        if len(new_products) == 0:
                            print(f"    DEBUG: No new products found and hit older product, stopping page processing")
                            break
                category_new_products.extend(new_products)
                print(f"  ✅ Found {len(new_products)} new products (out of {len(page_data)} total)")
                if len(new_products) == 0 and last_date is not None:
                    print(f"  ⏭️ No new products on page {page_num}, skipping remaining pages for {category['name']}")
                    break
                if not has_next_page:
                    print(f"  ✅ Reached last page (no next page link)")
                    break
                page_num += 1
            except Exception as e:
                print(f"  ⚠️ Error scraping page {page_num}: {str(e)}")
                break
        # --- DYNAMIC PAGINATION PATCH END ---
        
        # Combine new data with existing data for this category
        if category_new_products:
            upload_to_mongo(category_new_products, "NewList", backup_before_upload=True)
            
            # Update last date for this category
            if category_latest_date and category_latest_date != last_date:
                # Update json_object with new date
                if json_object is None:
                    json_object = {}
                if category['key'] not in json_object:
                    json_object[category['key']] = {}
                json_object[category['key']]['last_date'] = category_latest_date.isoformat()
                
                # Convert to JSON string and update via GitHubService
                updated_content = json.dumps(json_object, indent=2)
                commit_message = f"feat(dm): Update last processed date for {category['key']} to {category_latest_date.isoformat()}"
                github_service.update_file(DATE_FILE_PATH, updated_content, commit_message, file_sha)
            
            print(f"  📈 Total products for {category['name']}: {len(category_new_products)}")
            
            total_new_products += len(category_new_products)
        else:
            print(f"  ⏭️ No new products found for {category['name']}")

    print(f"\n{'='*60}")
    print(f"✅ Scraping Complete!")
    print(f"📊 Total new products: {total_new_products}")
    print(f"{'='*60}")
