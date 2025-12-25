import requests
import time
from urllib.parse import urljoin, urlparse
from service.translationservice import translate_text


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