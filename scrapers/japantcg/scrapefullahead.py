import requests
import re
from bs4 import BeautifulSoup
import os
import sys
import json
from datetime import datetime
import argparse

# Add parent directories to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from service.mongo_service import MongoService
from cleanup_utils import cleanup_old_backups
from dotenv import load_dotenv

load_dotenv()

class FullaheadScraper:
    """Scraper for Fulla Ahead Union Arena shop"""
    
    def __init__(self):
        """Initialize the scraper"""
        self.mongo = MongoService()
        self.base_url = "https://fullahead-tcg-shop.com/shopbrand/ua"
        self.cardlist_data = []
        self.timestamp_ms = int(datetime.now().timestamp() * 1000)
    
    def scrape_cards(self):
        """
        Scrape all Union Arena cards from Fulla Ahead with pagination
        
        Steps:
        1. Fetch the webpage
        2. Parse card items from the HTML
        3. Extract card data (name, price, stock, link)
        4. Check for next page link
        5. Repeat until no next page exists
        """
        try:
            current_url = self.base_url
            page_num = 1
            
            while current_url:
                print(f"\n🔄 Fetching page {page_num}: {current_url}")
                response = requests.get(current_url, timeout=10)
                response.encoding = 'utf-8'
                
                if response.status_code != 200:
                    print(f"❌ Failed to fetch page: Status {response.status_code}")
                    break
                
                print(f"🔄 Parsing HTML and extracting card data from page {page_num}")
                self.extract_cardlist_data(response.text)
                
                # Check for next page link - specifically look for "次の50件" (next 50 items)
                soup = BeautifulSoup(response.text, 'html.parser')
                next_link = None
                
                # Find all <li class="next"> elements
                next_lis = soup.find_all('li', {'class': 'next'})
                
                for li in next_lis:
                    a_tag = li.find('a', {'href': True})
                    if a_tag:
                        link_text = a_tag.get_text(strip=True)
                        # Look for the "next 50 items" link (not the previous link)
                        if '次の50件' in link_text or '次へ' in link_text or '»' in link_text:
                            next_href = a_tag.get('href')
                            # Build absolute URL if relative
                            if next_href.startswith('/'):
                                current_url = 'https://fullahead-tcg-shop.com' + next_href
                            else:
                                current_url = next_href
                            next_link = True
                            page_num += 1
                            break
                
                if not next_link:
                    print("✅ Reached last page - no more pages to scrape")
                    current_url = None
            
            print(f"\n✅ Successfully scraped {len(self.cardlist_data)} cards from all pages")
            return self.cardlist_data
            
        except Exception as e:
            print(f"❌ Error during scraping: {str(e)}")
            return []
    
    def extract_cardlist_data(self, html_content):
        """
        Extract card data from HTML content
        
        Card name format: UA01ST/CGH-1-015 ルルーシュ・ランペルージ U
        - booster: UA01ST (before /)
        - cardId: CGH-1-015
        - card_name: ルルーシュ・ランペルージ
        - rarity: U (last character)
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find the main container with all items
            main_container = soup.find('div', {'class': 'indexItemBox cf'})
            
            if not main_container:
                print("❌ Could not find the main item container")
                return
            
            # Find all item divs (direct children that contain card info)
            item_divs = main_container.find_all('div', recursive=False)
            
            # Filter to only those that have card information (have an <a> tag with href)
            card_items = [div for div in item_divs if div.find('a', {'href': True})]
            
            print(f"🔍 Found {len(card_items)} card items")
            
            for item_div in card_items:
                try:
                    # Extract card name from span.itemName
                    name_span = item_div.find('span', {'class': 'itemName'})
                    if not name_span:
                        continue
                    
                    card_name_raw = name_span.get_text(strip=True)
                    
                    # Parse card name format: "UA01ST/CGH-1-015 ルルーシュ・ランペルージ U"
                    if '/' not in card_name_raw:
                        continue
                    
                    # Split by "/" to separate booster and the rest
                    booster, rest = card_name_raw.split('/', 1)
                    
                    # Split the rest by spaces to get cardId and remaining parts
                    parts = rest.split()
                    if len(parts) < 2:
                        continue
                    
                    cardId = parts[0]  # CGH-1-015
                    rarity = parts[-1]  # Last part is rarity (U, R, SR, etc.)
                    
                    # Everything between cardId and rarity is the card name
                    card_name = ' '.join(parts[1:-1])  # ルルーシュ・ランペルージ
                    
                    # Extract product link and normalize it (remove page/recommend parameters)
                    link_tag = item_div.find('a', {'href': True})
                    product_link = link_tag.get('href') if link_tag else 'N/A'
                    
                    # Normalize: keep only /shopdetail/{id}/ua, remove /page{X}/recommend/ etc
                    if product_link != 'N/A':
                        match = re.search(r'(/shopdetail/[^/]+/ua)', product_link)
                        if match:
                            product_link = match.group(1)
                    
                    # Extract price from span.itemPrice > strong
                    price_span = item_div.find('span', {'class': 'itemPrice'})
                    price = 0
                    if price_span:
                        price_strong = price_span.find('strong')
                        if price_strong:
                            price_text = price_strong.get_text(strip=True)
                            # Extract number from "80円"
                            price_match = re.search(r'(\d+(?:,\d+)*)', price_text)
                            price = int(price_match.group(1).replace(',', '')) if price_match else 0
                    
                    # Extract stock from span.M_item-stock-smallstock
                    stock = 0
                    stock_span = item_div.find('span', {'class': 'M_item-stock-smallstock'})
                    
                    # Extract quantity from "残りあと17個"
                    if stock_span:
                        stock_text = stock_span.get_text(strip=True)
                        # Extract number from stock text (e.g., "残りあと17個" → 17)
                        stock_match = re.search(r'(\d+)', stock_text)
                        stock = int(stock_match.group(1)) if stock_match else 0
                    
                    # Create card entry with price_history nested by timestamp
                    card_entry = {
                        'booster': booster.strip(),
                        'cardId': cardId.strip(),
                        'card_name': card_name.strip(),
                        'rarity': rarity.strip(),
                        'product_link': product_link.strip(),
                        'price_history': {
                            str(self.timestamp_ms): {
                                'price': price,
                                'stock': stock
                            }
                        }
                    }
                    
                    self.cardlist_data.append(card_entry)
                    print(f"    ✓ {booster} | {cardId} | {card_name} | {rarity} | {price}円 | Stock: {stock}")
                    
                except Exception as e:
                    print(f"    ❌ Error extracting card: {str(e)}")
                    continue
            
            print(f"✅ Extracted {len(self.cardlist_data)} cards with pricing data")
            
        except Exception as e:
            print(f"❌ Error extracting cardlist data: {str(e)}")
    
    def save_backup(self, backup_filename=None):
        """Save cardlist data as a backup file"""
        try:
            os.makedirs('fullaheaddb', exist_ok=True)
            
            if not backup_filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_filename = f'fullahead_cardlist_backup_{timestamp}.json'
            
            backup_filepath = f"fullaheaddb/{backup_filename}"
            
            with open(backup_filepath, 'w', encoding='utf-8') as f:
                json.dump(self.cardlist_data, f, ensure_ascii=False, indent=2)
            
            print(f"💾 Backup saved to {backup_filepath}")
            return backup_filepath
        
        except Exception as e:
            print(f"❌ Error saving backup: {str(e)}")
    
    def load_from_backup(self, backup_filename=None):
        """Load cardlist data from a backup file
        
        Args:
            backup_filename: Optional specific backup file to load.
                           If None, loads the most recent backup file
        """
        try:
            if not backup_filename:
                # Find the most recent backup file
                backups = [f for f in os.listdir('fullaheaddb') if f.startswith('fullahead_cardlist_backup_')]
                if not backups:
                    print("❌ No backup files found")
                    return False
                
                backup_filename = sorted(backups)[-1]  # Get most recent
            
            backup_filepath = f"fullaheaddb/{backup_filename}"
            
            with open(backup_filepath, 'r', encoding='utf-8') as f:
                self.cardlist_data = json.load(f)
            
            print(f"✅ Loaded {len(self.cardlist_data)} cards from backup: {backup_filename}")
            return True
        
        except Exception as e:
            print(f"❌ Error loading backup: {str(e)}")
            return False
    
    def upload_to_mongo(self, db_name='geekstack', collection_name='cardprices_fulla'):
        """Upload cardlist data to MongoDB with smart upsert (like yuyutei)"""
        try:
            if not self.cardlist_data:
                print("⚠️ No cardlist data to upload")
                return False
            
            print(f"🔄 Uploading {len(self.cardlist_data)} cards to MongoDB ({db_name}.{collection_name})")
            
            # Get existing cards from MongoDB to identify new vs existing
            existing_cards = {}
            try:
                from pymongo import MongoClient
                import certifi
                
                mongo_uri = self.mongo._get_mongo_uri()
                client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
                db = client[db_name]
                collection = db[collection_name]
                
                # Fetch all existing cards by product_link
                existing_docs = collection.find({}, {'product_link': 1, 'price_history': 1})
                for doc in existing_docs:
                    key = doc.get('product_link', '')
                    existing_cards[key] = doc.get('price_history', {})
                
            except Exception as e:
                print(f"⚠️ Warning getting existing cards: {str(e)}")
            
            # Separate new and existing cards
            new_cards = []
            update_operations = []
            
            for card in self.cardlist_data:
                card_key = card['product_link']
                
                if card_key in existing_cards:
                    # This is an update - merge price history
                    existing_history = existing_cards[card_key]
                    new_history = card['price_history']
                    merged_history = {**existing_history, **new_history}
                    
                    update_data = {
                        'booster': card['booster'],
                        'cardId': card['cardId'],
                        'rarity': card['rarity'],
                        'card_name': card['card_name'],
                        'product_link': card['product_link'],
                        'price_history': merged_history,
                        'last_updated': self.timestamp_ms
                    }
                    
                    update_operations.append({
                        'field_name': 'product_link',
                        'field_value': card['product_link'],
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
                    self.mongo.upload_data(new_cards, collection_name, backup_before_upload=False)
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
            
            print(f"✅ Upload complete: {inserted} new + {updated} updated = {inserted + updated} total")
            return True
        
        except Exception as e:
            print(f"❌ Error uploading to MongoDB: {str(e)}")
            return False
    
    def run(self):
        """Run the complete scraping pipeline"""
        try:
            print("=" * 60)
            print("🚀 Starting Fulla Ahead Union Arena Card Scraper")
            print("=" * 60)
            
            # Scrape cards
            self.scrape_cards()
            
            backup_file = None
            if self.cardlist_data:
                # Save backup
                backup_file = self.save_backup()
                
                # Cleanup old backups (keep only last 7 days)
                print("\n🔧 Cleaning up old backups...")
                cleanup_old_backups('fullaheaddb', 'fullahead_cardlist_backup_', days=7)
                
                # Upload to MongoDB
                upload_success = self.upload_to_mongo()
                
                if not upload_success and backup_file:
                    print(f"⚠️ Upload failed, but your data is saved in: {backup_file}")
                    print(f"You can retry the upload without re-scraping using:")
                    print(f"  python3 scrapers/japantcg/scrapefullahead.py --upload-backup={os.path.basename(backup_file)}")
            
            print("=" * 60)
            print("✅ Scraping complete!")
            print("=" * 60)
        
        except Exception as e:
            print(f"❌ Error in scraping pipeline: {str(e)}")


def retry_upload_from_backup(backup_filename=None):
    """Retry MongoDB upload from a backup file without re-scraping
    
    Args:
        backup_filename: Optional specific backup file to load (e.g., 'fullahead_cardlist_backup_20260317_120000.json')
                        If None, loads the most recent backup file
    
    Usage:
        python3 scrapers/japantcg/scrapefullahead.py --use-latest-backup
        python3 scrapers/japantcg/scrapefullahead.py --upload-backup=fullahead_cardlist_backup_20260317_120000.json
    """
    print("🔄 Retrying upload from backup...")
    
    scraper = FullaheadScraper()
    
    try:
        # Load data from backup
        if backup_filename:
            loaded = scraper.load_from_backup(backup_filename)
        else:
            # Load most recent
            loaded = scraper.load_from_backup(None)
        
        if not loaded:
            print("❌ Failed to load backup")
            return False
        
        # Try uploading again
        upload_success = scraper.upload_to_mongo(db_name='geekstack', collection_name='cardprices_fulla')
        
        if upload_success:
            print("✅ Backup upload successful!")
        else:
            print(f"❌ Upload still failed. Check MongoDB connection.")
        
        return upload_success
        
    except Exception as e:
        print(f"❌ Error during retry upload: {str(e)}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Fulla Ahead Union Arena scraper with backup/upload support'
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
    else:
        # Normal scrape mode
        scraper = FullaheadScraper()
        scraper.run()
