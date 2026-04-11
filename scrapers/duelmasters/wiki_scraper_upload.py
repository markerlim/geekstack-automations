import sys
import random
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from dmwikiscraper import DuelMastersCardWikiScraper

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
from dotenv import load_dotenv
from service.mongo_service import MongoService

load_dotenv()

WIKI_COLLECTION = "CL_duelmasters_wiki"

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.85 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.94 Safari/537.36",
    "Mozilla/5.0 (Macintosh; ARM Mac OS X 13_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.94 Safari/537.36",
]

def create_driver():
    """Create and configure a new Chrome WebDriver instance"""
    chrome_options = Options()  

    chrome_options.add_argument(
        f"--user-agent={random.choice(USER_AGENTS)}"
    )
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )

def get_existing_urls(mongo_service):
    """Fetch all existing URLs from MongoDB to avoid duplicate scraping."""
    existing = mongo_service.get_unique_values(WIKI_COLLECTION, "url")
    if existing:
        return set(existing)
    return set()

def scrape_and_upload_wiki(booster_url):
    """
    Scrape wiki cards from a booster page and upload to MongoDB.
    
    Flow:
    1. scrape_booster_page() - Gets all wiki links from booster page
    2. Deduplicate against existing URLs in CL_duelmasters_wiki
    3. Scrape each new card page
    4. Upload new card objects to MongoDB
    """
    mongo_service = MongoService()
    
    # Step 1: Scrape booster page for all wiki links
    driver = create_driver()
    try:
        scraper = DuelMastersCardWikiScraper(driver)
        
        print(f"🚀 Step 1: Scraping booster page for all wiki links")
        print(f"   URL: {booster_url}\n")
        
        card_mapping = scraper.scrape_booster_page(booster_url)
        
        print(f"✅ Step 1 Complete!")
        print(f"📊 Found {len(card_mapping)} cards with wiki links\n")
    finally:
        driver.quit()
    
    # Step 2: Deduplicate - get unique wiki URLs and check against MongoDB
    unique_urls = set(card_mapping.values())
    print(f"📊 Unique wiki URLs from booster: {len(unique_urls)}")
    
    existing_urls = get_existing_urls(mongo_service)
    print(f"📊 Existing URLs in MongoDB: {len(existing_urls)}")
    
    urls_to_scrape = [url for url in unique_urls if url not in existing_urls]
    skipped = len(unique_urls) - len(urls_to_scrape)
    
    print(f"📊 URLs to scrape: {len(urls_to_scrape)} (skipping {skipped} already in DB)\n")
    
    if not urls_to_scrape:
        print("✅ All cards already exist in MongoDB. Nothing to scrape.")
        return
    
    # Step 3: Scrape individual card pages
    print(f"🚀 Step 2: Scraping {len(urls_to_scrape)} new card pages")
    print("=" * 80)
    
    card_objects = []
    upload_batch_size = 10
    
    for idx, wiki_url in enumerate(urls_to_scrape, 1):
        card_driver = create_driver()
        try:
            print(f"\n📖 Scraping card {idx}/{len(urls_to_scrape)}")
            print(f"   From: {wiki_url}")
            
            card_scraper = DuelMastersCardWikiScraper(card_driver)
            card_obj = card_scraper.scrape_card(wiki_url)
            
            if card_obj:
                card_objects.append(card_obj)
                print(f"   ✅ Card object created with {len(card_obj.get('cards', []))} form(s)")
                for i, card in enumerate(card_obj.get('cards', []), 1):
                    print(f"      Form {i}: {card.get('name', 'N/A')}")
            else:
                print(f"   ⚠️ Could not scrape card details")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        finally:
            card_driver.quit()
        
        # Upload in batches to avoid losing progress
        if len(card_objects) >= upload_batch_size:
            print(f"\n💾 Uploading batch of {len(card_objects)} cards to MongoDB...")
            mongo_service.upload_data(card_objects, WIKI_COLLECTION)
            card_objects = []
    
    # Upload remaining cards
    if card_objects:
        print(f"\n💾 Uploading final batch of {len(card_objects)} cards to MongoDB...")
        mongo_service.upload_data(card_objects, WIKI_COLLECTION)
    
    print(f"\n✅ Scrape Complete!")
    print("=" * 80)
    print(f"📋 SUMMARY:")
    print(f"   Total cards in booster: {len(card_mapping)}")
    print(f"   Unique wiki URLs: {len(unique_urls)}")
    print(f"   Skipped (already in DB): {skipped}")
    print(f"   Newly scraped & uploaded: {len(urls_to_scrape)}")

if __name__ == "__main__":
    booster_urls = ["https://duelmasters.fandom.com/wiki/DM26-RP1_Garde_of_Bolmeteus"]
    for booster_url in booster_urls:
        scrape_and_upload_wiki(booster_url)
