import requests
from urllib.parse import urljoin, urlparse

def find_missing_values(json_values, website_values):
    json_set = set(json_values)
    website_set = set(website_values)

    print(f"\n🧪 Debug: {len(json_set)} JSON values vs {len(website_set)} website values")
    return sorted(website_set - json_set)

def mimick_click(session, element, base_url="", headers=None):
    """
    Mimick a website click action by following links or submitting forms
    
    Args:
        session: requests.Session object to maintain cookies/state
        element: BeautifulSoup element (a, button, form, etc.)
        base_url: Base URL for relative links
        headers: Optional headers for the request
    
    Returns:
        Response object or None if click couldn't be processed
    """
    
    if headers is None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
    
    try:
        # Handle anchor links (a tags)
        if element.name == 'a':
            href = element.get('href')
            if href:
                # Handle relative URLs
                if href.startswith('/') or not urlparse(href).scheme:
                    url = urljoin(base_url, href)
                else:
                    url = href
                
                print(f"Following link: {url}")
                return session.get(url, headers=headers)
        
        # Handle button clicks (look for parent form or onclick actions)
        elif element.name in ['button', 'input']:
            
            # Check for onclick or data attributes that might indicate an action
            onclick = element.get('onclick', '')
            if 'location.href' in onclick:
                # Extract URL from onclick="location.href='...'"
                import re
                url_match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick)
                if url_match:
                    url = urljoin(base_url, url_match.group(1))
                    print(f"Following onclick redirect: {url}")
                    return session.get(url, headers=headers)
    
        
        # Handle elements with data-href or similar attributes
        data_href = element.get('data-href') or element.get('data-url')
        if data_href:
            url = urljoin(base_url, data_href)
            print(f"Following data-href: {url}")
            return session.get(url, headers=headers)
    
    except Exception as e:
        print(f"Error processing click: {e}")
        return None
    
    print(f"No click action found for element: {element.name}")
    return None
 
def get_anime_english_title(anime_name):
    """
    Get the English title for an anime/manga from the Jikan API (MyAnimeList data).
    Tries anime first, then manga if no anime results found.
    
    Args:
        anime_name: Japanese or any anime/manga name to search for
        
    Returns:
        English title if found, or the original anime_name if not found/error
    """
    def try_endpoint(endpoint_type, name):
        """Helper function to try a specific endpoint"""
        try:
            api_url = f"https://api.jikan.moe/v4/{endpoint_type}?q={name}&limit=1"
            
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Check if we have results
            if data.get('data') and len(data['data']) > 0:
                info = data['data'][0]
                
                # Try to get English title
                english_title = info.get('title_english')
                if english_title:
                    print(f"Found English title for '{name}' in {endpoint_type}: {english_title}")
                    return english_title
                
                # Fallback to default title if no English title
                default_title = info.get('title')
                if default_title:
                    print(f"No English title found in {endpoint_type}, using default: {default_title}")
                    return default_title
            
            return None
            
        except requests.RequestException as e:
            print(f"API request failed for '{name}' on {endpoint_type}: {e}")
            return None
        except Exception as e:
            print(f"Error getting title for '{name}' on {endpoint_type}: {e}")
            return None
    
    try:
        # First try anime endpoint
        result = try_endpoint("anime", anime_name)
        if result:
            return result
        
        # If no anime found, try manga endpoint
        print(f"No anime results for '{anime_name}', trying manga...")
        result = try_endpoint("manga", anime_name)
        if result:
            return result
        
        # If both fail, return original name
        print(f"No results found in anime or manga for: {anime_name}")
        return anime_name
        
    except Exception as e:
        print(f"Error in get_anime_english_title for '{anime_name}': {e}")
        return anime_name 