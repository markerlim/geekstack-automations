import json
import sys
import time
from pathlib import Path

# Add service and scrapers to path
sys.path.insert(0, str(Path(__file__).parent))

from service.selenium_service import SeleniumService
from scrapers.duelmasters.dmwikiscraper import DuelMastersCardWikiScraper


def load_unique_urls(filepath: str) -> list:
    """Load unique wiki URLs from JSON file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            urls = json.load(f)
        # Filter out invalid URLs (ones starting with 'hh' or without 'https')
        valid_urls = [url for url in urls if url.startswith('https://') or url.startswith('http://')]
        return valid_urls
    except FileNotFoundError:
        print(f"Error: File {filepath} not found")
        return []
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {filepath}")
        return []


def load_existing_results(output_filepath: str) -> tuple:
    """Load existing results and already scraped URLs.
    
    Returns:
        (results_list, scraped_urls_set)
    """
    if not Path(output_filepath).exists():
        return [], set()
    
    try:
        with open(output_filepath, 'r', encoding='utf-8') as f:
            results = json.load(f)
        
        # Extract already scraped URLs
        scraped_urls = {item['url'] for item in results if 'url' in item}
        return results, scraped_urls
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load existing results: {e}")
        return [], set()


def load_failed_urls(output_basename: str) -> dict:
    """Load previously failed URLs from checkpoint file.
    
    Returns:
        Dictionary with URL as key and error info as value
    """
    failed_file = f"{output_basename.replace('.json', '')}_failed.json"
    
    if not Path(failed_file).exists():
        return {}
    
    try:
        with open(failed_file, 'r', encoding='utf-8') as f:
            failed_data = json.load(f)
        return failed_data
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load failed URLs: {e}")
        return {}


def save_failed_urls(failed_urls: dict, output_basename: str):
    """Save failed URLs to checkpoint file for later retry."""
    failed_file = f"{output_basename.replace('.json', '')}_failed.json"
    
    try:
        with open(failed_file, 'w', encoding='utf-8') as f:
            json.dump(failed_urls, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"Warning: Could not save failed URLs: {e}")


def save_progress_checkpoint(output_basename: str, total: int, completed: int, failed: int):
    """Save progress checkpoint for reference."""
    checkpoint_file = f"{output_basename.replace('.json', '')}_progress.json"
    
    checkpoint = {
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "total_urls": total,
        "completed": completed,
        "failed": failed,
        "success_rate": f"{(completed / total * 100) if total > 0 else 0:.1f}%"
    }
    
    try:
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"Warning: Could not save progress checkpoint: {e}")


def save_results_incrementally(results: list, failed_urls: dict, output_filepath: str):
    """Save results and failed URLs after each batch."""
    try:
        # Save successful results
        with open(output_filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        # Save failed URLs
        save_failed_urls(failed_urls, output_filepath)
        
        print(f"💾 Checkpoint saved: {len(results)} results, {len(failed_urls)} failed")
    except IOError as e:
        print(f"⚠️  Warning: Could not save checkpoint: {e}")


def scrape_all_urls(urls: list, output_filepath: str = "dm_wiki_results.json", limit: int = None, delay: float = 2.0, batch_size: int = 10, batch_delay: float = 5.0, resume: bool = False):
    """Scrape wiki URLs and save results to JSON file.
    
    Args:
        urls: List of URLs to scrape
        output_filepath: Output JSON file path
        limit: Maximum number of URLs to scrape (None = no limit)
        delay: Delay in seconds between each URL scrape (default: 2.0)
        batch_size: Number of URLs to scrape before batch delay (default: 10)
        batch_delay: Delay in seconds after scraping batch_size URLs (default: 5.0)
        resume: Resume from previous progress if True (default: False)
    """
    
    # Apply limit if specified
    if limit:
        urls = urls[:limit]
    
    # Load existing results and failed URLs if resuming
    failed_urls = {}
    if resume:
        results, scraped_urls = load_existing_results(output_filepath)
        failed_urls = load_failed_urls(output_filepath)
        urls_to_scrape = [url for url in urls if url not in scraped_urls and url not in failed_urls]
        print(f"\n📋 Resume mode: Found {len(results)} previously scraped URLs")
        print(f"⚠️  Failed URLs from previous runs: {len(failed_urls)}")
        print(f"📝 Remaining to scrape: {len(urls_to_scrape)}/{len(urls)}")
        if not urls_to_scrape:
            print("✓ All URLs already processed!")
            return results
        urls = urls_to_scrape
    else:
        results = []
    
    # Initialize Selenium driver
    selenium = SeleniumService(headless=True)
    driver = selenium.driver
    
    scraper = DuelMastersCardWikiScraper(driver)
    
    try:
        total_urls = len(urls)
        completed_count = 0
        
        for index, url in enumerate(urls, 1):
            try:
                print(f"\nScraping: {url}")
                
                # Scrape the card data
                card_data = scraper.scrape_card(url)
                
                if card_data and card_data.get('cards'):
                    results.append(card_data)
                    print(f"✓ Successfully scraped - {len(card_data['cards'])} card(s)")
                    completed_count += 1
                    # Remove from failed list if it was there
                    if url in failed_urls:
                        del failed_urls[url]
                else:
                    print(f"✗ No cards found or error during scraping")
                    failed_urls[url] = "No cards found"
                
                # Progress indicator
                print(f"Progress: {index}/{total_urls} URLs processed | Success: {completed_count} | Failed: {len(failed_urls)}")
                
                # Apply delay between URLs
                if index < total_urls:  # Don't delay after last URL
                    print(f"⏳ Waiting {delay} seconds...")
                    time.sleep(delay)
                
                # Apply batch delay and save after batch_size URLs
                if index % batch_size == 0:
                    print(f"\n⏰ Batch delay: Waiting {batch_delay} seconds (completed {index} URLs)...")
                    # Save checkpoint before batch delay
                    save_results_incrementally(results, failed_urls, output_filepath)
                    time.sleep(batch_delay)
                
            except Exception as e:
                error_msg = str(e)
                print(f"✗ Error scraping {url}: {error_msg}")
                failed_urls[url] = error_msg
                
                # Check for rate limit errors
                if "429" in error_msg or "rate" in error_msg.lower():
                    print("\n⚠️  RATE LIMIT DETECTED! Increasing batch delay...")
                    batch_delay = min(batch_delay * 2, 60)  # Cap at 60 seconds
                    time.sleep(10)  # Immediate pause for rate limit
                
                continue
    
    finally:
        # Close the driver
        driver.quit()
        # Save one final time in case of shutdown
        save_results_incrementally(results, failed_urls, output_filepath)
    
    # Final save and summary
    with open(output_filepath, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    # Save failed URLs (final)
    save_failed_urls(failed_urls, output_filepath)
    
    # Save progress checkpoint
    save_progress_checkpoint(output_filepath, total_urls, completed_count, len(failed_urls))
    
    print(f"\n{'='*60}")
    print(f"Scraping completed!")
    print(f"Total URLs processed: {total_urls}")
    print(f"Successfully scraped: {completed_count}")
    print(f"Failed: {len(failed_urls)}")
    print(f"Results saved to: {output_filepath}")
    if failed_urls:
        print(f"Failed URLs saved to: {output_filepath.replace('.json', '')}_failed.json")
    print(f"Progress saved to: {output_filepath.replace('.json', '')}_progress.json")
    print(f"{'='*60}")
    
    return results


if __name__ == "__main__":
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Scrape Duel Masters wiki URLs", formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Output files:
  - {output}.json: Successfully scraped card data
  - {output}_failed.json: URLs that failed to scrape (can be retried)
  - {output}_progress.json: Progress checkpoint
        """)
    parser.add_argument("--limit", type=int, default=None, help="Limit number of URLs to scrape (default: no limit)")
    parser.add_argument("--output", type=str, default="dm_wiki_results.json", help="Output JSON file path")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay in seconds between each URL scrape (default: 2.0)")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of URLs before batch delay (default: 10)")
    parser.add_argument("--batch-delay", type=float, default=5.0, help="Delay in seconds after batch (default: 5.0)")
    parser.add_argument("--resume", action="store_true", help="Resume from previous progress instead of starting fresh")
    parser.add_argument("--retry-failed", action="store_true", help="Retry only previously failed URLs")
    args = parser.parse_args()
    
    # Handle retry-failed mode
    if args.retry_failed:
        print("Loading failed URLs from previous run...")
        failed_urls = load_failed_urls(args.output)
        if not failed_urls:
            print("No failed URLs found!")
        else:
            print(f"Found {len(failed_urls)} failed URLs to retry")
            print(f"⚠️  Failed URLs:")
            for url, error in list(failed_urls.items())[:5]:
                print(f"  - {url[:80]}... ({error})")
            if len(failed_urls) > 5:
                print(f"  ... and {len(failed_urls) - 5} more")
            
            urls_to_retry = list(failed_urls.keys())
            
            print(f"\n⚙️  Settings:")
            print(f"  - Retrying {len(urls_to_retry)} failed URLs")
            print(f"  - Delay between URLs: {args.delay}s")
            print(f"  - Batch size: {args.batch_size} URLs")
            print(f"  - Batch delay: {args.batch_delay}s")
            print(f"\n" + "="*60)
            
            # Load existing results to preserve them
            existing_results, _ = load_existing_results(args.output)
            
            # Scrape failed URLs without resume mode (to actually retry them)
            new_results = scrape_all_urls(urls_to_retry, args.output, limit=None, delay=args.delay, batch_size=args.batch_size, batch_delay=args.batch_delay, resume=False)
            
            # Merge with existing results
            merged_results = existing_results + new_results
            
            # Save merged results
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(merged_results, f, indent=2, ensure_ascii=False)
            
            print(f"\n✓ Merged results: {len(existing_results)} existing + {len(new_results)} newly scraped = {len(merged_results)} total")
    else:
        # Load unique URLs
        print("Loading unique wiki URLs...")
        urls = load_unique_urls("dm_unique_wiki_urls.json")
        print(f"Loaded {len(urls)} unique URLs")
        
        if urls:
            # Display settings
            if args.limit:
                print(f"Testing with limit: {args.limit} URLs")
            print(f"\n⚙️  Settings:")
            print(f"  - Mode: {'Resume' if args.resume else 'Fresh start'}")
            print(f"  - Delay between URLs: {args.delay}s")
            print(f"  - Batch size: {args.batch_size} URLs")
            print(f"  - Batch delay: {args.batch_delay}s")
            print(f"\n" + "="*60)
            
            # Scrape URLs with delay parameters
            results = scrape_all_urls(urls, args.output, limit=args.limit, delay=args.delay, batch_size=args.batch_size, batch_delay=args.batch_delay, resume=args.resume)
        else:
            print("No URLs to scrape")
