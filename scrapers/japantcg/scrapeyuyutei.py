import requests
import re
from bs4 import BeautifulSoup
import os
import sys
import json
from selenium.webdriver.common.by import By
import time
from datetime import datetime
import argparse

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.selenium_service import SeleniumService
from service.mongo_service import MongoService
from cleanup_utils import cleanup_old_backups
from dotenv import load_dotenv

load_dotenv()

class YuyuTeiScraper:
    """Scraper for Yuyu-Tei Union Arena website"""
    
    def __init__(self, headless=True):
        """Initialize the scraper"""
        self.selenium = SeleniumService(headless=headless, window_size="1920,1080", timeout=10)
        self.mongo = MongoService()
        self.base_url = "https://yuyu-tei.jp/top/ua"
        self.all_hrefs = []
        self.cardlist_data = []  # Store cardlist data with rarity, price, etc.
        self.timestamp_ms = int(datetime.now().timestamp() * 1000)  # Current time in milliseconds
    
    def scrape_single_card_links(self):
        """
        Scrape all single card links from Yuyu-Tei
        
        Steps:
        1. Navigate to the website
        2. Click the "シングルカード販売" button
        3. Extract all href links from the expanded menu
        4. Crawl each link and extract card data
        """
        try:
            # Step 1: Navigate to the website
            print(f"🔄 Navigating to {self.base_url}")
            self.selenium.navigate_to(self.base_url)
            self.selenium.sleep(2)  # Wait for page to load
            
            # Step 2: Click the "シングルカード販売" button
            print("🔄 Clicking the 'シングルカード販売' button to expand the menu")
            button_clicked = self.selenium.click_element(
                By.CSS_SELECTOR,
                ".accordion-button.text-primary[data-bs-target='#side-sell-single']"
            )
            
            if not button_clicked:
                print("❌ Failed to click the button, trying alternative selector")
                # Alternative: click by data-bs-target attribute
                self.selenium.click_element(By.CSS_SELECTOR, "[data-bs-target='#side-sell-single']")
            
            self.selenium.sleep(2)  # Wait for menu to expand
            
            # Step 3: Extract all href links from the expanded menu
            print("🔄 Extracting all href links from the expanded menu")
            self.extract_all_links()
            
            # Step 4: Crawl each link and extract card data
            print("🔄 Crawling each category link to extract card data")
            self.scrape_cards_from_links()
            
            print(f"✅ Successfully scraped {len(self.all_hrefs)} links and {len(self.cardlist_data)} cards")
            return self.all_hrefs
            
        except Exception as e:
            print(f"❌ Error during scraping: {str(e)}")
            return []
    
    def extract_all_links(self):
        """
        Extract href links only from the first set of sub-child corners
        """
        try:
            # Get the page source
            page_source = self.selenium.get_page_source()
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Find the side-sell-single container (the expanded menu)
            container = soup.find('div', {'id': 'side-sell-single'})
            
            if not container:
                print("❌ Could not find the expanded menu container")
                return
            
            # Find all sub-child corner divs within the first accordion-item child
            # These are the actual product link buttons
            sub_child_corners = container.find_all('div', {'class': 'accordion-item rounded-0 mb-2 sub-child corner'})
            
            print(f"🔍 Found {len(sub_child_corners)} card sections")
            
            for sub_child in sub_child_corners:
                # Find the button with onclick attribute in this sub-child
                button = sub_child.find('button', {'onclick': True})
                
                if button:
                    onclick = button.get('onclick', '')
                    if 'location.href=' in onclick:
                        # Extract URL from onclick attribute
                        # Pattern: onclick="location.href='URL'"
                        match = re.search(r"location\.href='([^']+)'", onclick)
                        if match:
                            href = match.group(1)
                            self.all_hrefs.append({
                                'href': href,
                                'text': button.get_text(strip=True),
                                'id': button.get('id', '')
                            })
                            print(f"  📌 Found: {button.get_text(strip=True)} -> {href}")
            
        except Exception as e:
            print(f"❌ Error extracting links: {str(e)}")
    
    def scrape_cards_from_links(self):
        """
        Navigate to each extracted link and extract card data
        """
        if not self.all_hrefs:
            print("⚠️ No links to scrape. Extract links first.")
            return
        
        print(f"🔄 Crawling {len(self.all_hrefs)} category links...")
        
        for idx, link_data in enumerate(self.all_hrefs, 1):
            href = link_data.get('href', '')
            category_name = link_data.get('text', 'Unknown')
            
            if not href:
                continue
            
            try:
                print(f"\n  [{idx}/{len(self.all_hrefs)}] 📂 Navigating to: {category_name}")
                self.selenium.navigate_to(href)
                self.selenium.sleep(1.5)  # Wait for page to load
                
                # Extract card data from this page
                self.extract_cardlist_data()
                
            except Exception as e:
                print(f"    ❌ Error scraping {category_name}: {str(e)}")
                continue
    
    def extract_cardlist_data(self):
        """
        Extract cardlist data mapping rarity with card information
        Extracts: rarity, card ID, card name, price, stock status
        """
        try:
            page_source = self.selenium.get_page_source()
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Find all cards-list sections
            cards_list_sections = soup.find_all('div', {'class': 'py-4 cards-list'})
            
            print(f"🔍 Found {len(cards_list_sections)} rarity sections")
            
            for section in cards_list_sections:
                # Extract rarity from the section header
                header = section.find('h3', {'class': 'text-primary fs-4 shadow fw-bold'})
                if not header:
                    continue
                
                # The rarity is in a span with class 'py-2 d-inline-block px-2 me-2 text-white fw-bold'
                rarity_span = header.find('span', {'class': 'py-2 d-inline-block px-2 me-2 text-white fw-bold'})
                rarity = rarity_span.get_text(strip=True) if rarity_span else "Unknown"
                
                print(f"  📋 Processing rarity: {rarity}")
                
                # Find all card products in this section
                row = section.find('div', {'class': 'row mt-2'})
                if not row:
                    continue
                
                # Use a more flexible class selector to handle extra classes like 'sold-out'
                card_divs = row.find_all('div', class_=lambda x: x and 'card-product' in x and 'position-relative' in x and 'mt-4' in x)
                
                for card_div in card_divs:
                    try:
                        # Extract card ID
                        id_span = card_div.find('span', {'class': 'd-block border border-dark p-1 w-100 text-center my-2'})
                        card_id_raw = id_span.get_text(strip=True) if id_span else "Unknown"
                        
                        # Split card_id into cardId and booster by slash
                        if '/' in card_id_raw:
                            booster, card_id = card_id_raw.split('/', 1)
                        else:
                            card_id = card_id_raw
                            booster = "Unknown"
                        
                        # Extract card name and product link
                        name_h4 = card_div.find('h4', {'class': 'text-primary fw-bold'})
                        card_name = name_h4.get_text(strip=True) if name_h4 else "Unknown"
                        
                        # Extract product link (href from the <a> tag containing the card name)
                        product_link = "N/A"
                        if name_h4:
                            link_tag = name_h4.find_parent('a')
                            if link_tag and link_tag.get('href'):
                                product_link = link_tag.get('href')
                        
                        # Extract price
                        price_strong = card_div.find('strong', {'class': 'd-block text-end'})
                        # Get all text content and clean it - extract only the integer
                        if price_strong:
                            price_text = price_strong.get_text(strip=True)
                            # Remove '円' and any whitespace, extract the number
                            price_match = re.search(r'(\d+(?:,\d+)*)', price_text)
                            price = int(price_match.group(1).replace(',', '')) if price_match else 0
                        else:
                            price = 0
                        
                        # Extract stock status
                        stock_label = card_div.find('label', {'class': 'form-check-label fw-bold float-start cart_sell_zaiko'})
                        if stock_label:
                            stock_text = stock_label.get_text(strip=True)
                            # Remove the label "在庫 :" prefix
                            stock_text = stock_text.replace('在庫 :', '').strip()
                            
                            # Parse stock: ◯ = 20, × = 0, otherwise extract number
                            if '◯' in stock_text:
                                stock = 20
                            elif '×' in stock_text:
                                stock = 0
                            else:
                                # Extract the number (e.g., "2 点" → 2)
                                stock_match = re.search(r'(\d+)', stock_text)
                                stock = int(stock_match.group(1)) if stock_match else 0
                        else:
                            stock = 0
                        
                        # Create card entry with price_history nested by timestamp
                        card_entry = {
                            'rarity': rarity,
                            'cardId': card_id,
                            'booster': booster,
                            'card_name': card_name,
                            'product_link': product_link,
                            'price_history': {
                                str(self.timestamp_ms): {
                                    'price': price,
                                    'stock': stock
                                }
                            }
                        }
                        
                        self.cardlist_data.append(card_entry)
                        print(f"    ✓ {rarity} | {card_id}/{booster} | {price}円 | Stock: {stock} | Link: {product_link}")
                        
                    except Exception as e:
                        print(f"    ❌ Error extracting card: {str(e)}")
                        continue
            
            print(f"✅ Extracted {len(self.cardlist_data)} cards with rarity and pricing data")
            
        except Exception as e:
            print(f"❌ Error extracting cardlist data: {str(e)}")

    def save_backup(self, backup_filename=None):
        """Save cardlist data as a backup file"""
        try:
            os.makedirs('yuyuteidb', exist_ok=True)
            
            if not backup_filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_filename = f'yuyutei_cardlist_backup_{timestamp}.json'
            
            backup_filepath = f"yuyuteidb/{backup_filename}"
            
            with open(backup_filepath, 'w', encoding='utf-8') as f:
                json.dump(self.cardlist_data, f, ensure_ascii=False, indent=2)
            
            print(f"💾 Backup saved to {backup_filepath}")
            return backup_filepath
            
        except Exception as e:
            print(f"❌ Error saving backup: {str(e)}")
            return None
    
    def load_from_backup(self, backup_filename=None):
        """Load cardlist data from a backup file"""
        try:
            if not backup_filename:
                # Find the most recent backup file
                backups = [f for f in os.listdir('yuyuteidb') if f.startswith('yuyutei_cardlist_backup_')]
                if not backups:
                    print("❌ No backup files found")
                    return False
                
                backup_filename = sorted(backups)[-1]  # Get most recent
            
            backup_filepath = f"yuyuteidb/{backup_filename}"
            
            with open(backup_filepath, 'r', encoding='utf-8') as f:
                self.cardlist_data = json.load(f)
            
            print(f"✅ Loaded {len(self.cardlist_data)} cards from backup: {backup_filename}")
            return True
            
        except Exception as e:
            print(f"❌ Error loading backup: {str(e)}")
            return False

    def upload_to_mongo(self, db_name='geekstack', collection_name='cardprices_yyt'):
        """Upload cardlist data to MongoDB with bulk operations"""
        try:
            print(f"🔄 Uploading {len(self.cardlist_data)} cards to MongoDB ({db_name}.{collection_name})")
            
            # Get existing cards with price history - fetched ONCE
            existing_cards_map = {}
            try:
                from pymongo import MongoClient
                import certifi
                
                mongo_uri = self.mongo._get_mongo_uri()
                client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
                db = client[db_name]
                collection = db[collection_name]
                
                # Fetch all existing cards with product_link and price_history
                existing_docs = collection.find({}, {'product_link': 1, 'price_history': 1})
                existing_cards_map = {doc.get('product_link'): doc.get('price_history', {}) for doc in existing_docs}
                
            except Exception as e:
                print(f"⚠️ Warning getting existing cards: {str(e)}")
            
            # Separate new and existing cards
            new_cards = []
            update_operations = []
            
            for card in self.cardlist_data:
                product_link = card.get('product_link', 'N/A')
                
                if product_link in existing_cards_map:
                    # This is an update - merge price history
                    existing_history = existing_cards_map[product_link]
                    new_history = card['price_history']
                    merged_history = {**existing_history, **new_history}
                    
                    update_data = {
                        'rarity': card['rarity'],
                        'cardId': card['cardId'],
                        'booster': card['booster'],
                        'card_name': card['card_name'],
                        'product_link': product_link,
                        'price_history': merged_history,
                        'last_updated': self.timestamp_ms
                    }
                    
                    update_operations.append({
                        'field_name': 'product_link',
                        'field_value': product_link,
                        'update_data': update_data
                    })
                else:
                    # This is a new card
                    card['created_at'] = self.timestamp_ms
                    card['last_updated'] = self.timestamp_ms
                    new_cards.append(card)
            
            # Bulk insert new cards
            inserted = 0
            if new_cards:
                try:
                    result = self.mongo.upload_data(new_cards, collection_name, backup_before_upload=False)
                    inserted = len(new_cards)
                    print(f"  ✅ Bulk inserted {inserted} new cards")
                except Exception as e:
                    print(f"  ❌ Error bulk inserting: {str(e)}")
            
            # Bulk update existing cards
            updated = 0
            if update_operations:
                try:
                    result = self.mongo.batch_update_by_field(collection_name, update_operations)
                    if result['success']:
                        updated = result['modified']
                        print(f"  ✅ Batch updated {updated} existing cards ({result['matched']} matched)")
                    else:
                        print(f"  ❌ Error batch updating: Operation failed")
                except Exception as e:
                    print(f"  ❌ Error batch updating: {str(e)}")
            
            print(f"✅ MongoDB upload complete: {inserted} inserted, {updated} updated")
            return True
            
        except Exception as e:
            print(f"❌ Error uploading to MongoDB: {str(e)}")
            print(f"💾 Data is safe in backup. You can retry upload later.")
            return False
    
    def close(self):
        """Close the Selenium driver"""
        try:
            self.selenium.driver.quit()
            print("✅ Selenium driver closed")
        except Exception as e:
            print(f"⚠️ Error closing driver: {str(e)}")


def main():
    """Main execution function with CLI support"""
    parser = argparse.ArgumentParser(
        description='Yuyu-Tei Union Arena scraper with backup/upload support'
    )
    parser.add_argument(
        '--upload-backup',
        type=str,
        metavar='FILENAME',
        help='Load cards from backup file and upload to MongoDB (skip scraping)'
    )
    parser.add_argument(
        '--use-latest-backup',
        action='store_true',
        help='Load from most recent backup file and upload to MongoDB'
    )
    
    args = parser.parse_args()
    
    # Handle backup upload mode
    if args.upload_backup or args.use_latest_backup:
        backup_filename = args.upload_backup if args.upload_backup else None
        retry_upload_from_backup(backup_filename)
        return
    
    # Normal scrape mode
    scraper = YuyuTeiScraper(headless=False)  # Set to False to see the browser
    
    try:
        # Scrape the links and cardlist data
        links = scraper.scrape_single_card_links()
        
        # Save backup before uploading (so we don't lose data on upload failure)
        backup_file = scraper.save_backup()
        
        # Cleanup old backups (keep only last 7 days)
        print("\n🔧 Cleaning up old backups...")
        cleanup_old_backups('yuyuteidb', 'yuyutei_cardlist_backup_', days=7)
        
        # Upload directly to MongoDB
        upload_success = scraper.upload_to_mongo(db_name='geekstack', collection_name='cardprices_yyt')
        
        if not upload_success and backup_file:
            print(f"⚠️ Upload failed, but your data is saved in: {backup_file}")
            print(f"You can retry the upload without re-scraping using:")
            print(f"  python3 scrapers/japantcg/scrapeyuyutei.py --upload-backup={os.path.basename(backup_file)}")
        
        # Print summary
        print(f"\n📊 Summary:")
        print(f"  Total links found: {len(links)}")
        if links:
            print(f"  First link: {links[0]}")
            print(f"  Last link: {links[-1]}")
        
        print(f"\n  Total cards with rarity data: {len(scraper.cardlist_data)}")
        if scraper.cardlist_data:
            print(f"\n  Sample cards (with price_history):")
            for card in scraper.cardlist_data[:5]:
                # Get the first price history entry
                price_data = list(card['price_history'].values())[0] if card['price_history'] else {}
                timestamp_key = list(card['price_history'].keys())[0] if card['price_history'] else "N/A"
                print(f"    {card['rarity']:8} | {card['cardId']:18} | {price_data.get('price', 'N/A'):10} | Stock: {price_data.get('stock', 'N/A'):5}")
                print(f"      └─ Recorded: {timestamp_key} (ms)")
            print(f"    ... and {len(scraper.cardlist_data) - 5} more cards")
        
        
    finally:
        scraper.close()


def retry_upload_from_backup(backup_filename=None):
    """Retry MongoDB upload from a backup file without re-scraping
    
    Args:
        backup_filename: Optional specific backup file to load (e.g., 'yuyutei_cardlist_backup_20260317_120000.json')
                        If None, loads the most recent backup file
    
    Usage:
        python3 scrapers/japantcg/scrapeyuyutei.py --upload-backup=yuyutei_cardlist_backup_20260317_120000.json
    """
    print("🔄 Retrying upload from backup...")
    
    scraper = YuyuTeiScraper(headless=True)  # Headless since we're not scraping
    
    try:
        # Load data from backup
        loaded = scraper.load_from_backup(backup_filename)
        
        if not loaded:
            print("❌ Failed to load backup")
            return False
        
        # Try uploading again
        upload_success = scraper.upload_to_mongo(db_name='geekstack', collection_name='cardprices_yyt')
        
        if upload_success:
            print("✅ Backup upload successful!")
        else:
            print(f"❌ Upload still failed. Check MongoDB connection.")
        
        return upload_success
        
    finally:
        # No need to close selenium driver in headless mode for backup upload
        pass


if __name__ == "__main__":
    main()
