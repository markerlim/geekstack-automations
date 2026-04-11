import requests
from bs4 import BeautifulSoup
import re

url = "https://fullahead-tcg-shop.com/shopbrand/ua"

print("🔄 Fetching page...")
response = requests.get(url, timeout=10)
response.encoding = 'utf-8'

soup = BeautifulSoup(response.text, 'html.parser')
main_container = soup.find('div', {'class': 'indexItemBox cf'})
item_divs = main_container.find_all('div', recursive=False)
card_items = [div for div in item_divs if div.find('a', {'href': True})]

print(f"\n📊 Testing first card's basket div structure:\n")

item_div = card_items[0]

# Get basket div
basket_div = item_div.find('div', {'class': 'item-add-basket'})
print(f"Basket div found: {basket_div is not None}")

if basket_div:
    # Print raw attributes
    print(f"Basket class attribute: {basket_div.get('class')}")
    print(f"Basket class type: {type(basket_div.get('class'))}")
    
    # Check different ways to get stock
    print(f"\n✓ Checking for 'instock': {'instock' in basket_div.get('class', [])}")
    print(f"✓ Checking for 'outofstock': {'outofstock' in basket_div.get('class', [])}")
    
    # Find stock span
    stock_span = item_div.find('span', {'class': 'M_item-stock-smallstock'})
    print(f"\nStock span found: {stock_span is not None}")
    
    if stock_span:
        stock_text = stock_span.get_text(strip=True)
        print(f"Stock text: '{stock_text}'")
        stock_match = re.search(r'(\d+)', stock_text)
        if stock_match:
            print(f"Stock number extracted: {stock_match.group(1)}")

print("\n" + "="*80)
print("Checking all basketDiv classes in the page:")
print("="*80 + "\n")

basket_divs = soup.find_all('div', {'class': 'item-add-basket'})
print(f"Total basket divs found: {len(basket_divs)}\n")

# Sample a few to see their classes
for i, basket in enumerate(basket_divs[:5]):
    classes = basket.get('class', [])
    print(f"Basket #{i+1} classes: {classes}")
