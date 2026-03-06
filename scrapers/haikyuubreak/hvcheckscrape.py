import json
import os
import sys
from bs4 import BeautifulSoup
import requests
from dotenv import load_dotenv
from datetime import datetime
from pymongo import MongoClient
import certifi
import re

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from service.utils_service import find_missing_values
from service.mongo_service import MongoService
from service.googlecloudservice import upload_image_to_gcs
from scrapers.haikyuubreak.haikyuuscrape import start_scraping

load_dotenv()

mongo_service = MongoService()
BOOSTERDB = os.getenv("BT_HAIKYUUBREAK")
BASE_URL = "https://www.takaratomy.co.jp/products/haikyuvobacabreak"

def parse_japanese_date(date_string):
    """Parse Japanese date format (e.g., '2026年2月28日') to datetime"""
    try:
        # Extract numbers from Japanese date format
        match = re.search(r'(\d+)年(\d+)月(\d+)日', date_string)
        if match:
            year, month, day = match.groups()
            return datetime(int(year), int(month), int(day))
    except Exception as e:
        print(f"Warning: Could not parse date '{date_string}': {e}")
    return datetime.now()

def scrape_detailed_products():
    """Scrape detailed product information from Takara Tomy Haikyuu BREAK website"""
    print("🌐 Scraping detailed Haikyuu BREAK product information...")
    url = f"{BASE_URL}/product/"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all product items
        product_list = soup.find('div', class_='product_list')
        if not product_list:
            print("❌ Could not find the product list.")
            return []
        
        # Extract only pack and deck items (skip peripherals/sleeves)
        products = []
        items = product_list.find_all('a', class_='item')
        
        for item in items:
            category = item.get('data-category', '')
            # Only include packs and decks
            if category in ['pack', 'deck']:
                try:
                    # Extract href/detail link
                    href = item.get('href', '')
                    if not href:
                        continue
                    
                    # Extract product code
                    product_code = href.split('.')[0].upper()
                    
                    # Extract Japanese text (product name/description)
                    subject_tag = item.find('div', class_='subject')
                    japtext = subject_tag.get_text(strip=True) if subject_tag else ""
                    
                    # Extract release date
                    date_div = item.find('div', class_='date')
                    release_date = None
                    if date_div:
                        date_text = date_div.get_text(strip=True)
                        # Clean up the text (remove "発売日" label)
                        date_match = re.search(r'(\d+年\d+月\d+日)', date_text)
                        if date_match:
                            release_date = parse_japanese_date(date_match.group(1))
                    
                    # Extract price
                    price_div = item.find('div', class_='price')
                    price = ""
                    if price_div:
                        price_text = price_div.get_text(strip=True)
                        # Extract price value (remove "希望小売価格" label)
                        price_match = re.search(r'([\d,]+円)', price_text)
                        if price_match:
                            price = price_match.group(1)
                    
                    # Fetch detail page to get main image
                    print(f"  📄 Fetching detail page: {href}")
                    detail_url = f"{BASE_URL}/product/{href}"
                    detail_response = requests.get(detail_url)
                    detail_response.raise_for_status()
                    detail_soup = BeautifulSoup(detail_response.text, 'html.parser')
                    
                    # Extract main image from detail page
                    main_img = detail_soup.find('img', class_='mainImage')
                    image_url = ""
                    if main_img:
                        img_src = main_img.get('src', '')
                        if img_src:
                            # Convert relative URL to absolute URL
                            if img_src.startswith('./'):
                                image_url = f"{BASE_URL}/product/{img_src[2:]}"
                            elif img_src.startswith('/'):
                                image_url = f"https://www.takaratomy.co.jp{img_src}"
                            else:
                                image_url = f"{BASE_URL}/product/{img_src}"
                            
                            print(f"    ✓ Main image URL: {image_url}")
                    
                    # Upload image to GCS and get the stored URL
                    stored_image_url = image_url
                    if image_url:
                        try:
                            stored_image_url = upload_image_to_gcs(image_url,product_code,"boostercover/")
                            print(f"    ✓ Image uploaded to GCS")
                        except Exception as e:
                            print(f"    ⚠️ Failed to upload image to GCS: {e}, using original URL")
                    
                    # Create product object
                    # Map category: pack -> expansion
                    mapped_category = "expansion" if category == "pack" else category
                    
                    product = {
                        "booster": product_code,
                        "japtext": japtext,
                        "category": f"{mapped_category}_unreleased",
                        "urlimage": stored_image_url,
                        "detailLink": f"/product/{href}",
                        "price": price,
                        "timestamp": release_date or datetime.now(),
                    }
                    
                    products.append(product)
                    print(f"  ✓ Found {category.upper()}: {product_code}")
                    
                except Exception as e:
                    print(f"  ⚠️ Error parsing product item: {e}")
                    continue
        
        return products
        
    except Exception as e:
        print(f"❌ Failed to scrape website: {e}")
        return []

def scrape_website_values():
    """Scrape product codes from Takara Tomy Haikyuu BREAK website"""
    print("🌐 Scraping Haikyuu BREAK website for new series...")
    url = f"{BASE_URL}/product/"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all product items
        product_list = soup.find('div', class_='product_list')
        if not product_list:
            print("❌ Could not find the product list.")
            return []
        
        # Extract only pack and deck items (skip peripherals/sleeves)
        products = []
        items = product_list.find_all('a', class_='item')
        
        for item in items:
            category = item.get('data-category', '')
            # Only include packs and decks
            if category in ['pack', 'deck']:
                href = item.get('href', '')
                # Extract product code from href (e.g., "HV-P02.html" -> "HV-P02")
                if href:
                    product_code = href.split('.')[0].upper()
                    # Normalize format (remove hyphens for consistency)
                    product_code = product_code.replace('-', '')
                    products.append(product_code)
                    print(f"  ✓ Found {category.upper()}: {product_code}")
        
        return products
        
    except Exception as e:
        print(f"❌ Failed to scrape website: {e}")
        return []

def run_check():
    """Check for new series and update MongoDB"""
    print(f"📚 Querying MongoDB collection: {BOOSTERDB}")
    
    # Get existing series codes from MongoDB
    existing_series = mongo_service.get_unique_values(BOOSTERDB, "booster")
    
    if existing_series is None:
        existing_series = []
    
    # Normalize existing series (remove hyphens for comparison)
    normalized_existing = [code.replace('-', '') for code in existing_series]
    
    website_values = scrape_website_values()
    
    if not website_values:
        print("❌ No data scraped from website.")
        return
    
    missing_values = find_missing_values(normalized_existing, website_values)
    
    print("\n=== 📋 Missing Values Report ===")
    print(f"📦 Total series in MongoDB: {len(existing_series)}")
    print(f"🌍 Total series on website: {len(website_values)}")
    print(f"❓ Missing series count: {len(missing_values)}")
    
    if missing_values:
        print("\n⚠️ New Series Found:")
        for val in missing_values:
            print(f"  - {val}")
        
        # Scrape detailed product information
        print("\n📋 Scraping detailed product information...")
        all_products = scrape_detailed_products()
        
        # Filter for only missing products
        formatted_missing = [val[:2] + '-' + val[2:] if len(val) > 2 else val for val in missing_values]
        print(f"📍 Looking for products with booster in: {formatted_missing}")
        print(f"📍 All scraped products: {[p['booster'] for p in all_products]}")
        
        missing_products = [p for p in all_products if p['booster'] in formatted_missing]
        print(f"📍 Filtered missing products: {[p['booster'] for p in missing_products]}")
        
        if not missing_products:
            print("⚠️ No products to insert after filtering!")
        else:
            # Insert new series into MongoDB
            try:
                # Get MongoDB collection directly
                mongo_uri = f"mongodb+srv://{os.getenv('MONGO_USER')}:{os.getenv('MONGO_PASSWORD')}@{os.getenv('MONGO_CLUSTER')}/{os.getenv('MONGO_DATABASE')}?retryWrites=true&w=majority"
                print(f"🔗 Connecting to MongoDB...")
                client = MongoClient(mongo_uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
                
                # Test connection
                client.admin.command('ping')
                print(f"✅ MongoDB connection successful")
                
                db = client[os.getenv('MONGO_DATABASE')]
                collection = db[BOOSTERDB]
                
                # Check which products already exist to avoid re-upload
                existing_boosters = {p['booster'] for p in collection.find({}, {'booster': 1})}
                print(f"📚 Existing boosters in DB: {existing_boosters if existing_boosters else 'None'}")
                
                products_to_insert = [p for p in missing_products if p['booster'] not in existing_boosters]
                already_exists = [p for p in missing_products if p['booster'] in existing_boosters]
                
                if already_exists:
                    print(f"⏭️  Skipping {len(already_exists)} booster(s) already in DB: {[p['booster'] for p in already_exists]}")
                
                for product in products_to_insert:
                    result = collection.insert_one(product)
                    print(f"  ✓ Added to MongoDB: {product['booster']} - {product['japtext']} (ID: {result.inserted_id})")
                
                if products_to_insert:
                    print(f"✅ Successfully inserted {len(products_to_insert)} new products into MongoDB")
                else:
                    print(f"⏭️  No new products to insert (all already exist)")
                client.close()
            except Exception as e:
                print(f"  ❌ Error adding to MongoDB: {e}")
                import traceback
                traceback.print_exc()
        
        print("\n🎯 PROCESSING COMPLETE")
        print(f"📊 New series added: {', '.join(formatted_missing)}")
    
    else:
        print("✅ All series from website already exist in MongoDB!")


def scrape_cardlist_dropdown():
    """Scrape booster codes from the cardlist dropdown menu using Selenium"""
    print("🔍 Scraping cardlist dropdown with Selenium...")
    cardlist_url = f"{BASE_URL}/cardlist/"
    
    try:
        # Initialize Selenium
        from service.selenium_service import SeleniumService
        from selenium.webdriver.common.by import By
        import time
        
        selenium = SeleniumService(headless=False, window_size="1920,1080", timeout=10)
        
        print(f"  📄 Navigating to: {cardlist_url}")
        selenium.driver.get(cardlist_url)
        time.sleep(2)  # Wait for page to load
        
        # Find the select dropdown
        select_element = selenium.driver.find_element(By.CSS_SELECTOR, 'select')
        if not select_element:
            print("❌ Could not find dropdown in cardlist page")
            selenium.close()
            return []
        
        # Extract all option values
        booster_codes = []
        options = select_element.find_elements(By.TAG_NAME, 'option')
        
        for option in options:
            value = option.get_attribute('value').strip()
            text = option.text.strip()
            
            # Skip empty option
            if value and value != '':
                booster_codes.append(value)
                print(f"  ✓ Found: {value} - {text}")
        
        selenium.close()
        return booster_codes
        
    except Exception as e:
        print(f"❌ Failed to scrape cardlist dropdown: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_existing_boosters_in_cards():
    """Get list of booster codes that already have cards scraped in CL_haikyuubreak"""
    try:
        existing = mongo_service.get_unique_values("CL_haikyuubreak", "booster")
        return set(existing) if existing else set()
    except Exception as e:
        print(f"⚠️ Error fetching existing boosters: {e}")
        return set()

def get_booster_category(booster_code):
    """Get category of a booster from BT_haikyuuvobacca"""
    try:
        mongo_uri = f"mongodb+srv://{os.getenv('MONGO_USER')}:{os.getenv('MONGO_PASSWORD')}@{os.getenv('MONGO_CLUSTER')}/{os.getenv('MONGO_DATABASE')}?retryWrites=true&w=majority"
        client = MongoClient(mongo_uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
        db = client[os.getenv('MONGO_DATABASE')]
        collection = db["BT_haikyuuvobacca"]
        
        product = collection.find_one({"booster": booster_code})
        client.close()
        
        if product:
            return product.get("category", None)
        return None
    except Exception as e:
        print(f"⚠️ Error getting booster category: {e}")
        return None

def trigger_scrape_for_booster(booster_code):
    """Trigger scraping for a specific booster"""
    print(f"\n📊 Triggering scrape for booster: {booster_code}")
    
    try:
        start_scraping([booster_code])
        print(f"✅ Scrape completed for {booster_code}")
        return True
    except Exception as e:
        print(f"❌ Error triggering scrape: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_and_scrape_released_boosters():
    """Check dropdown for released boosters and scrape unscraped ones"""
    print("\n" + "="*60)
    print("🎯 CARDLIST DROPDOWN CHECK")
    print("="*60)
    
    # Get boosters from dropdown (these are RELEASED)
    dropdown_boosters = scrape_cardlist_dropdown()
    if not dropdown_boosters:
        print("⚠️ No boosters found in dropdown")
        return
    
    print(f"🌐 In dropdown (released): {set(dropdown_boosters)}")
    
    # Get MongoDB connection
    try:
        mongo_uri = f"mongodb+srv://{os.getenv('MONGO_USER')}:{os.getenv('MONGO_PASSWORD')}@{os.getenv('MONGO_CLUSTER')}/{os.getenv('MONGO_DATABASE')}?retryWrites=true&w=majority"
        client = MongoClient(mongo_uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
        db = client[os.getenv('MONGO_DATABASE')]
        bt_collection = db["BT_haikyuuvobacca"]
        cl_collection = db["CL_haikyuubreak"]
        
        # For each dropdown booster, check if it needs scraping
        boosters_to_scrape = []
        
        for booster in dropdown_boosters:
            # Check if booster exists in BT_haikyuuvobacca
            product = bt_collection.find_one({"booster": booster})
            
            if not product:
                print(f"  📌 {booster}: Not in product list (BT_haikyuuvobacca) - skipping")
                continue
            
            category = product.get("category", "")
            
            # Check if it has _unreleased suffix (newly released)
            if category.endswith("_unreleased"):
                print(f"  📌 {booster}: NEWLY RELEASED (category: {category}) - will scrape")
                boosters_to_scrape.append((booster, category))
            else:
                # Check if already scraped in CL_haikyuubreak
                cards_count = cl_collection.count_documents({"booster": booster})
                if cards_count > 0:
                    print(f"  📌 {booster}: Already scraped ({cards_count} cards) - skipping")
                else:
                    print(f"  📌 {booster}: Released but not yet scraped (category: {category}) - will scrape")
                    boosters_to_scrape.append((booster, category))
        
        # Scrape all new/unreleased boosters
        if boosters_to_scrape:
            print(f"\n🔄 Scraping {len(boosters_to_scrape)} booster(s)...")
            for booster, original_category in boosters_to_scrape:
                print(f"\n  📌 {booster} ({original_category})")
                trigger_scrape_for_booster(booster)
                
                # Update category to remove _unreleased suffix if it had one
                if original_category.endswith("_unreleased"):
                    new_category = original_category.replace("_unreleased", "")
                    bt_collection.update_one(
                        {"booster": booster},
                        {"$set": {"category": new_category}}
                    )
                    print(f"     ✅ Updated category: {original_category} → {new_category}")
        else:
            print(f"\n✅ All dropdown boosters are either already scraped or not yet in product list")
        
        client.close()
        
    except Exception as e:
        print(f"⚠️ Error checking boosters: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_check()
    check_and_scrape_released_boosters()
