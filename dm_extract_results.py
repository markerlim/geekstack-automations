import json

def extract_results():
    """Extract the results field from wiki_checkpoint.json"""
    try:
        # Load the checkpoint file
        with open('wiki_checkpoint.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Extract results field
        results = data.get('results', [])
        
        # Save extracted results to a new file
        with open('dm_results.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"Successfully extracted {len(results)} results from wiki_checkpoint.json")
        print(f"Results saved to dm_results.json")
        
        return results
    
    except FileNotFoundError:
        print("Error: wiki_checkpoint.json not found")
        return None
    except json.JSONDecodeError:
        print("Error: Invalid JSON format in wiki_checkpoint.json")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def extract_unique_wiki_urls():
    """Extract unique wiki URLs from dm_results.json to avoid duplicate scraping"""
    try:
        # Load the results file
        with open('wiki_results.json', 'r', encoding='utf-8') as f:
            results = json.load(f)
        
        # Extract unique wiki URLs
        wiki_urls = set()
        
        for result in results:
            wiki_url = result.get('wiki_url')
            if wiki_url:
                wiki_urls.add(wiki_url)
        
        # Convert to sorted list for consistent ordering
        unique_urls = sorted(list(wiki_urls))
        
        # Save unique URLs to a new file
        with open('dm_unique_wiki_urls.json', 'w', encoding='utf-8') as f:
            json.dump(unique_urls, f, indent=2, ensure_ascii=False)
        
        print(f"Successfully extracted {len(unique_urls)} unique wiki URLs from {len(results)} results")
        print(f"Unique URLs saved to dm_unique_wiki_urls.json")
        
        return unique_urls
    
    except FileNotFoundError:
        print("Error: dm_results.json not found")
        return []
    except json.JSONDecodeError:
        print("Error: Invalid JSON format in dm_results.json")
        return []
    except Exception as e:
        print(f"Error: {e}")
        return []


def find_objects_by_wiki_urls(wiki_urls):
    """Find all objects in dm_results.json that have the specified wiki URLs
    
    Args:
        wiki_urls: A list of wiki URLs to search for
    
    Returns:
        A dictionary mapping wiki URLs to their matching objects
    """
    try:
        # Load the results file
        with open('wiki_results.json', 'r', encoding='utf-8') as f:
            results = json.load(f)
        
        # Create a dictionary to store wiki_url -> objects mapping
        url_to_objects = {url: [] for url in wiki_urls}
        
        # Search for matching objects
        for result in results:
            wiki_url = result.get('wiki_url')
            if wiki_url in url_to_objects:
                url_to_objects[wiki_url].append(result)
        
        # Save results to file
        with open('dm_wiki_url_objects.json', 'w', encoding='utf-8') as f:
            json.dump(url_to_objects, f, indent=2, ensure_ascii=False)
        
        # Print summary
        total_objects = sum(len(objs) for objs in url_to_objects.values())
        non_empty_urls = sum(1 for objs in url_to_objects.values() if objs)
        
        print(f"Found {total_objects} objects across {non_empty_urls} wiki URLs\n")
        print("Breakdown by URL:")
        print("-" * 80)
        
        # Print detailed breakdown
        for url, objects in url_to_objects.items():
            count = len(objects)
            if count > 0:
                print(f"{count:3d} objects - {url}")
        
        print("-" * 80)
        print(f"Results saved to dm_wiki_url_objects.json")
        
        return url_to_objects
    
    except FileNotFoundError:
        print("Error: dm_results.json not found")
        return {}
    except json.JSONDecodeError:
        print("Error: Invalid JSON format in dm_results.json")
        return {}
    except Exception as e:
        print(f"Error: {e}")
        return {}


if __name__ == "__main__":
    # extract_results()
    extract_unique_wiki_urls()
#     urlarray = [
#   "https://duelmasters.fandom.com/wiki/Duel_Masters_Wiki"
#     ]
    
#     find_objects_by_wiki_urls(urlarray)
