import requests
from bs4 import BeautifulSoup
import re
import json

# Test the Fulla Ahead scraper parsing logic
url = "https://fullahead-tcg-shop.com/shopbrand/ua"

print("🔄 Fetching page...")
response = requests.get(url, timeout=10)
response.encoding = 'utf-8'

if response.status_code != 200:
    print(f"❌ Failed to fetch: {response.status_code}")
    exit(1)

print("✅ Page fetched successfully\n")

soup = BeautifulSoup(response.text, 'html.parser')
main_container = soup.find('div', {'class': 'indexItemBox cf'})

if not main_container:
    print("❌ Could not find main container")
    exit(1)

# Get all item divs
item_divs = main_container.find_all('div', recursive=False)
card_items = [div for div in item_divs if div.find('a', {'href': True})]

print(f"📊 Found {len(card_items)} card items\n")
print("=" * 100)

# Test parsing on first 5 cards
test_cards = card_items[:5]

for idx, item_div in enumerate(test_cards, 1):
    print(f"\n🃏 CARD #{idx}")
    print("-" * 100)
    
    # Extract raw name
    name_span = item_div.find('span', {'class': 'itemName'})
    card_name_raw = name_span.get_text(strip=True) if name_span else "N/A"
    print(f"Raw Name: {card_name_raw}")
    
    # Parse components
    if '/' in card_name_raw:
        booster, rest = card_name_raw.split('/', 1)
        parts = rest.split()
        
        if len(parts) >= 2:
            cardId = parts[0]
            rarity = parts[-1]
            card_name = ' '.join(parts[1:-1])
            
            print(f"  ├─ Booster: '{booster.strip()}'")
            print(f"  ├─ CardId: '{cardId.strip()}'")
            print(f"  ├─ Card Name: '{card_name.strip()}'")
            print(f"  └─ Rarity: '{rarity.strip()}'")
    
    # Extract link
    link_tag = item_div.find('a', {'href': True})
    product_link = link_tag.get('href') if link_tag else 'N/A'
    print(f"Link: {product_link}")
    
    # Extract price
    price_span = item_div.find('span', {'class': 'itemPrice'})
    price = 0
    price_raw = "N/A"
    if price_span:
        price_strong = price_span.find('strong')
        if price_strong:
            price_raw = price_strong.get_text(strip=True)
            price_match = re.search(r'(\d+(?:,\d+)*)', price_raw)
            price = int(price_match.group(1).replace(',', '')) if price_match else 0
    
    print(f"Price Raw: {price_raw}")
    print(f"Price (int): {price}")
    
    # Extract stock
    stock = 0
    stock_raw = "N/A"
    stock_span = item_div.find('span', {'class': 'M_item-stock-smallstock'})
    
    if stock_span:
        stock_raw = stock_span.get_text(strip=True)
        stock_match = re.search(r'(\d+)', stock_raw)
        stock = int(stock_match.group(1)) if stock_match else 0
    
    print(f"Stock Raw: {stock_raw}")
    print(f"Stock (int): {stock}")
    
    print("-" * 100)

print("\n" + "=" * 100)
print(f"✅ Test complete! Parsed {min(5, len(card_items))} cards")
