#!/usr/bin/env python3
"""
Duel Masters Card Wiki Fetcher (dcw.py)
Step 1: Extract card name from cardnameJP
Step 2: Search Google for card + Duelmaster Fandom
Step 3: Extract first wiki link
Step 4: Fetch card data from wiki
"""

import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

def extract_card_name(cardname):
    """
    Extract card name, removing set/number info in parentheses
    
    Example:
        Input:  "強瀾怒闘 キューブリック(DM24EX4 35/100)"
        Output: "強瀾怒闘 キューブリック"
    """
    if not cardname:
        return None
    
    # Remove everything from the first ( onwards
    clean_name = cardname.split("(")[0].strip()
    return clean_name


def search_google_for_wiki(card_name, debug=False, driver=None):
    """
    Search Google for card name + Duelmaster Fandom and get first wiki link using Selenium
    Handles AJAX-loaded content.
    
    Example:
        Input:  "グレイト"Ｓ-駆"
        Output: "https://duelmasters.fandom.com/wiki/Great_Sonic"
    """
    try:
        should_close_driver = False
        
        # Create driver if not provided
        if driver is None:
            options = Options()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-plugins")
            options.add_argument("start-maximized")
            # Uncomment for headless mode:
            # options.add_argument("--headless")
            
            driver = webdriver.Chrome(options=options)
            should_close_driver = True
        
        # Build search query
        search_query = f"{card_name} Duelmasters Fandom"
        search_url = f"https://www.google.com/search?q={quote(search_query)}"
        
        print(f"  🔍 Searching Google: {search_query}")
        if debug:
            print(f"     URL: {search_url}")
        
        # Navigate to search
        driver.get(search_url)
        
        # Wait for search results to load (AJAX content)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.TAG_NAME, "a"))
            )
        except:
            if debug:
                print("     Warning: Timeout waiting for results, trying anyway")
        
        # Give AJAX a moment to settle
        time.sleep(2)
        
        # Check for CAPTCHA or rate limit
        page_source = driver.page_source
        if "detected unusual traffic" in page_source or "Please try again later" in page_source:
            print(f"\n  ⚠️  RATE LIMIT DETECTED! Google is blocking requests.")
            print(f"     Consider increasing --delay and --batch-delay")
            print(f"     Browser window is open - you can:")
            print(f"     1. Solve the CAPTCHA manually in the browser")
            print(f"     2. Wait for Google to unblock you")
            print(f"     3. Change your IP/proxy if needed")
            
            # Pause and wait for user to handle
            response = input("\n     Press ENTER once you've resolved the issue (or type 'skip' to skip this card): ").strip().lower()
            if response == "skip":
                return None, "rate_limit"
            # Try the search again after user has resolved it
            time.sleep(3)
            driver.get(search_url)
            time.sleep(2)
            page_source = driver.page_source
            # Check if still blocked
            if "detected unusual traffic" in page_source or "Please try again later" in page_source:
                print(f"  ⚠️  Still rate limited. Skipping...")
                return None, "rate_limit"
        
        if "recaptcha" in page_source.lower() or "captcha" in page_source.lower():
            print(f"\n  ⚠️  CAPTCHA DETECTED! Google requires human verification.")
            print(f"     Browser window is open - please solve the CAPTCHA manually")
            print(f"     The page will continue automatically once solved")
            
            # Pause and wait for user to solve CAPTCHA
            response = input("\n     Press ENTER once you've solved the CAPTCHA (or type 'skip' to skip this card): ").strip().lower()
            if response == "skip":
                return None, "captcha_detected"
            # Try again after user has solved CAPTCHA
            time.sleep(3)
            driver.get(search_url)
            time.sleep(2)
            page_source = driver.page_source
            # Check if CAPTCHA is gone
            if "recaptcha" in page_source.lower() or "captcha" in page_source.lower():
                print(f"  ⚠️  CAPTCHA still present. Skipping...")
                return None, "captcha_detected"
        
        # Get page source and parse with BeautifulSoup
        soup = BeautifulSoup(page_source, "html.parser")
        
        # Find all links
        all_links = soup.find_all("a", href=True)
        
        if debug:
            print(f"     Found {len(all_links)} total links")
        
        wiki_urls = []
        
        # Extract wiki links - return FIRST one found
        for link in all_links:
            href = link.get("href", "")
            
            # Check for Duelmaster wiki links (various formats)
            if "duelmasters.fandom.com" in href:
                wiki_url = href
                
                # Clean up Google redirect format if present
                if href.startswith("/url?q="):
                    wiki_url = href.replace("/url?q=", "").split("&")[0]
                
                # Return immediately on first wiki page found
                if "/wiki/" in wiki_url:
                    print(f"  ✅ Found wiki link: {wiki_url}")
                    return wiki_url
        
        if debug:
            print(f"     Checked {len(all_links)} links, no duelmasters.fandom.com/wiki/ found")
            # Show first few links for debugging
            print("     Sample links found:")
            for link in all_links[:10]:
                href = link.get("href", "")[:80]
                if href:
                    print(f"       - {href}")
        
        print(f"  ⚠️ No Duelmaster Fandom wiki link found")
        return None
    
    except Exception as e:
        print(f"  ❌ Search failed: {str(e)}")
        return None
    
    finally:
        if should_close_driver and driver:
            driver.quit()


def fetch_wiki_data(wiki_url, debug=False, driver=None):
    """
    Fetch card data from the Duelmaster Fandom wiki page using Selenium
    Extracts: name, race, and english text/effect
    """
    try:
        should_close_driver = False
        
        # Create driver if not provided
        if driver is None:
            options = Options()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-plugins")
            options.add_argument("--headless")
            driver = webdriver.Chrome(options=options)
            should_close_driver = True
        
        print(f"  📖 Fetching wiki page: {wiki_url}")
        
        # Navigate to wiki page
        driver.get(wiki_url)
        
        # Wait for table to load
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CLASS_NAME, "wikitable"))
            )
        except:
            if debug:
                print("     Warning: Timeout waiting for table, trying anyway")
        
        # Give page a moment to fully render
        time.sleep(1)
        
        # Get page source and parse with BeautifulSoup
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # Debug: Save HTML to file
        if debug:
            with open("wiki_page_debug.html", "w", encoding="utf-8") as f:
                f.write(soup.prettify())
            print(f"     📄 Saved HTML to wiki_page_debug.html")
        
        # Extract main content
        wiki_data = {
            "wiki_url": wiki_url,
            "name": None,
            "race": None,
            "english_text": None,
            "sets_rarity": []
        }
        
        # Extract card name from title
        title_elem = soup.find("h1", class_="page-header__title")
        if title_elem:
            wiki_data["name"] = title_elem.get_text(strip=True)
            if debug:
                print(f"     ✓ Found name: {wiki_data['name']}")
        else:
            if debug:
                print(f"     ✗ No title found")
        
        # Find the wikitable
        table = soup.find("table", class_="wikitable")
        if debug:
            print(f"     Table found: {table is not None}")
        
        if table:
            rows = table.find_all("tr")
            if debug:
                print(f"     Found {len(rows)} rows")
                print(f"     First 5 rows structure:")
            
            for idx, row in enumerate(rows[:5]):
                cells = row.find_all("td")
                if debug and cells:
                    first_cell = cells[0].get_text(strip=True)[:50]
                    print(f"       Row {idx}: '{first_cell}' ({len(cells)} cells)")
            
            for row in rows:
                cells = row.find_all("td")
                if not cells or len(cells) < 2:
                    continue
                
                # Get text from first cell (header)
                first_cell_text = cells[0].get_text(strip=True)
                second_cell = cells[1]
                
                if debug and ("Race" in first_cell_text or "English" in first_cell_text):
                    print(f"     Processing row: {first_cell_text[:50]}")
                
                # Look for Race row
                if "Race" in first_cell_text:
                    if debug:
                        print(f"     Found Race row: {first_cell_text}")
                    race_link = second_cell.find("a")
                    if race_link:
                        wiki_data["race"] = race_link.get_text(strip=True)
                    else:
                        wiki_data["race"] = second_cell.get_text(strip=True)
                    if debug:
                        print(f"     ✓ Found race: {wiki_data['race']}")
                
                # Look for English Text row
                elif "English Text" in first_cell_text:
                    if debug:
                        print(f"     Found English Text row: {first_cell_text}")
                    # Get all paragraph text
                    paragraphs = second_cell.find_all("p")
                    if paragraphs:
                        text_parts = []
                        for p in paragraphs:
                            text = p.get_text(strip=True)
                            if text:
                                text_parts.append(text)
                        wiki_data["english_text"] = "\n".join(text_parts)
                    else:
                        wiki_data["english_text"] = second_cell.get_text(strip=True)
                    if debug:
                        print(f"     ✓ Found english_text: {wiki_data['english_text'][:50]}...")

        if wiki_data["name"]:
            print(f"  ✅ Fetched: {wiki_data['name']}")
        
        return wiki_data
    
    except Exception as e:
        print(f"  ❌ Wiki fetch failed: {str(e)}")
        return None
    
    finally:
        if should_close_driver and driver:
            driver.quit()


def process_duel_masters_card(card, driver, debug=False):
    """
    Simple pipeline: Extract name → Search Google → Get wiki link
    Returns: (result_dict, error_type) where error_type is None or a string describing the error
    """
    try:
        # Use cardNameJP for searching (Japanese name)
        card_name_jp_with_set = card.get("cardNameJP", "")
        
        if not card_name_jp_with_set:
            print("  ⚠️ No cardNameJP found")
            return None, "no_cardnamejp"
        
        # Step 1: Extract clean card name from Japanese
        card_name_jp = extract_card_name(card_name_jp_with_set)
        print(f"\n📌 Processing: {card_name_jp_with_set}")
        print(f"   Cleaned name (JP): {card_name_jp}")
        
        # Step 2: Search Google for wiki using Japanese name (pass driver to reuse)
        result = search_google_for_wiki(card_name_jp, debug=debug, driver=driver)
        # Handle both None and (None, error_type) returns
        if isinstance(result, tuple):
            wiki_url, error_type = result
            if not wiki_url:
                return None, error_type
        else:
            wiki_url = result
            if not wiki_url:
                return None, "wiki_not_found"
        
        # Keep original card object and add wiki URL
        result = card.copy()
        result["wiki_url"] = wiki_url
        
        return result, None
    
    except Exception as e:
        print(f"  ❌ Processing failed: {str(e)}")
        return None, "processing_exception"


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    
    parser = argparse.ArgumentParser(description="Duel Masters Card Wiki Fetcher")
    parser.add_argument("--limit", type=int, default=-1, help="Limit number of cards to process (-1 = all remaining, default: -1)")
    parser.add_argument("--delay", type=float, default=30, help="Delay between requests in seconds (default: 30)")
    parser.add_argument("--batch-delay", type=float, default=300, help="Delay after every 10 cards in seconds (default: 300 = 5 min)")
    parser.add_argument("--output", type=str, default="wiki_results.json", help="Output JSON file")
    parser.add_argument("--checkpoint", type=str, default="wiki_checkpoint.json", help="Checkpoint file for resuming")
    parser.add_argument("--fresh", action="store_true", help="Start fresh (ignore checkpoint)")
    parser.add_argument("--debug", action="store_true", help="Enable debug output to see search details")
    
    args = parser.parse_args()
    
    print("🚀 Duel Masters Card Wiki Fetcher")
    print("="*60)
    
    driver = None
    start_index = 0
    results = []
    
    try:
        # Load dmfull.json
        with open("dmfull.json", "r", encoding="utf-8") as f:
            cards = json.load(f)
        
        print(f"📦 Loaded {len(cards)} cards from dmfull.json")
        
        # Check for checkpoint - AUTO RESUME unless --fresh flag
        checkpoint_path = Path(args.checkpoint)
        if checkpoint_path.exists() and not args.fresh:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
            start_index = checkpoint.get("last_index", 0)
            results = checkpoint.get("results", [])
            print(f"📋 AUTO-RESUMING from card {start_index + 1} (found {len(results)} existing results)")
            print(f"   (Use --fresh to start over)\n")
        elif checkpoint_path.exists() and args.fresh:
            print(f"🗑️  Ignoring checkpoint - starting fresh\n")
        elif not checkpoint_path.exists() and args.fresh:
            print(f"⚠️  No checkpoint to ignore, starting fresh\n")
        
        # Calculate end index
        if args.limit == -1:
            # Process all remaining cards
            end_index = len(cards)
            print(f"📌 Processing all remaining cards (from {start_index + 1} to {len(cards)})")
        else:
            # Process specified limit
            end_index = min(start_index + args.limit, len(cards))
            print(f"📌 Processing {args.limit} cards (from {start_index + 1} to {end_index})")
        
        total_to_process = end_index - start_index
        
        print(f"⏳ Processing cards {start_index + 1}-{end_index} ({total_to_process} cards)")
        print(f"   Delay between cards: {args.delay}s")
        print(f"   Delay after every 10 cards: {args.batch_delay}s\n")
        
        # Create reusable Selenium driver
        print("🌐 Starting Selenium browser...\n")
        options = Options()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        driver = webdriver.Chrome(options=options)
        error_counts = {}
        error_details = {}
        
        for i, card in enumerate(cards[start_index:end_index], 1):
            current_index = start_index + i
            print(f"\n[{i}/{total_to_process}] (Card #{current_index}/{len(cards)})")
            result, error = process_duel_masters_card(card, driver, debug=args.debug)
            
            if result:
                results.append(result)
            else:
                # Track error type
                error_counts[error] = error_counts.get(error, 0) + 1
                # Track which card failed
                if error not in error_details:
                    error_details[error] = []
                error_details[error].append({
                    "index": current_index,
                    "cardNameJP": card.get("cardNameJP", "Unknown"),
                    "cardId": card.get("cardId", "Unknown")
                })
            
            # Save checkpoint after each card
            checkpoint_data = {
                "last_index": current_index,
                "results": results,
                "timestamp": time.time(),
                "errors": error_counts,
                "error_details": error_details
            }
            with open(args.checkpoint, "w", encoding="utf-8") as f:
                json.dump(checkpoint_data, f, ensure_ascii=False)
            
            # Regular delay between cards
            if i < total_to_process:
                time.sleep(args.delay)
            
            # Extra delay after every 10 cards
            if i % 10 == 0 and i < total_to_process:
                print(f"\n⏸️  Batch delay ({args.batch_delay}s) to avoid rate limiting...")
                time.sleep(args.batch_delay)
        
        # Save final results
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        # Delete checkpoint after successful completion
        if checkpoint_path.exists():
            checkpoint_path.unlink()
        
        print(f"\n" + "="*60)
        print(f"✅ COMPLETE")
        print(f"📊 Processed: {len(results)} cards successfully")
        if error_counts:
            print(f"\n⚠️  Error Summary:")
            for error_type, count in error_counts.items():
                print(f"   - {error_type}: {count}")
                if error_type in error_details:
                    print(f"     Details:")
                    for detail in error_details[error_type]:
                        print(f"       - Card #{detail['index']}: {detail['cardNameJP']} ({detail['cardId']})")
        print(f"💾 Results saved to: {args.output}")
        print("="*60)
    
    except FileNotFoundError:
        print("❌ dmfull.json not found in current directory")
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        print(f"💾 Checkpoint saved - resume with: python dcw.py --resume --limit {args.limit}")
    
    finally:
        if driver:
            print("\n🔒 Closing browser...")
            driver.quit()
