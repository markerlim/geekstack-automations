import json
import random
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from dmwikiscraper import DuelMastersCardWikiScraper


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
    chrome_options.add_argument("--headless=new")  # Use new headless mode for better compatibility      
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

def test_wiki_scraper_interaction():
    """
    Test the interaction between scrape_booster_page and card scraping.
    
    Flow:
    1. scrape_booster_page() - Gets all wiki links from booster page
    2. For each link, scrape individual card page to form card objects
    """
    
    booster_url = "https://duelmasters.fandom.com/wiki/DM25-EX4_Episode_4:_Pandora_Wars"
    
    # Create driver for booster page
    driver = create_driver()
    
    try:
        # Initialize scraper
        scraper = DuelMastersCardWikiScraper(driver)
        
        print(f"🚀 Step 1: Scraping booster page for all wiki links")
        print(f"   URL: {booster_url}\n")
        
        # Step 1: Scrape booster page to get all card ID → wiki URL mappings
        card_mapping = scraper.scrape_booster_page(booster_url)
        
        print(f"✅ Step 1 Complete!")
        print(f"📊 Found {len(card_mapping)} cards with wiki links\n")
        
        # Display first 5 mappings
        print("Sample Card ID → Wiki URL Mappings (first 5):")
        print("=" * 80)
        for i, (card_id, wiki_url) in enumerate(list(card_mapping.items())[:5], 1):
            print(f"{i}. Card ID: {card_id}")
            print(f"   Wiki URL: {wiki_url}\n")
        
        # Close the booster page driver
        driver.quit()
        
        # Step 2: Now use these wiki links to scrape individual card pages
        print("\n🚀 Step 2: Scraping individual card pages from wiki links")
        print("=" * 80)
        
        card_objects = []
        
        # Scrape all cards
        test_cards = list(card_mapping.items())
        db_path = "../../duelmasterdb/db.json"
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        
        save_interval = 10  # Save progress every 10 cards
        
        for idx, (card_id, wiki_url) in enumerate(test_cards, 1):
            # Create a new driver for each card
            card_driver = create_driver()
            
            try:
                print(f"\n📖 Scraping card {idx}/{len(test_cards)}: {card_id}")
                print(f"   From: {wiki_url}")
                
                # Create scraper with the new driver
                card_scraper = DuelMastersCardWikiScraper(card_driver)
                
                # Actually scrape the card from the wiki link
                card_obj = card_scraper.scrape_card(wiki_url)
                
                if card_obj:
                    card_objects.append(card_obj)
                    print(f"   ✅ Card object created with {len(card_obj.get('cards', []))} form(s)")
                    
                    # Display card details
                    if card_obj.get('cards'):
                        for i, card in enumerate(card_obj['cards'], 1):
                            print(f"      Form {i}: {card.get('name', 'N/A')}")
                else:
                    print(f"   ⚠️ Could not scrape card details")
                
            except Exception as e:
                print(f"   ❌ Error: {e}")
            
            finally:
                # Close the card driver after use
                card_driver.quit()
            
            # Save progress every N cards
            if idx % save_interval == 0 or idx == len(test_cards):
                results = {
                    "booster_url": booster_url,
                    "total_cards_found": len(card_mapping),
                    "total_cards_scraped": len(card_objects),
                    "progress": f"{idx}/{len(test_cards)}",
                    "card_mappings": card_mapping,
                    "scraped_card_objects": card_objects
                }
                
                with open(db_path, 'w', encoding='utf-8') as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
                
                print(f"\n💾 Progress saved: {idx}/{len(test_cards)} cards scraped")
        
        print(f"\n✅ Step 2 Complete!")
        print(f"📊 Scraped {len(card_objects)} card object(s)\n")
        
        print("=" * 80)
        print("📋 SCRAPE SUMMARY:")
        print("=" * 80)
        print(f"Total cards found: {len(card_mapping)}")
        print(f"Total cards scraped: {len(card_objects)}")
        print(f"✅ Full database saved to: {db_path}")
        
        print(f"✅ Full results saved to: wiki_scraper_interaction_test.json")
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Ensure driver is closed if test fails before manual quit
        try:
            driver.quit()
        except:
            pass

if __name__ == "__main__":
    test_wiki_scraper_interaction()
