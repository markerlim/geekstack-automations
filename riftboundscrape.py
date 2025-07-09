from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import json
import time

def get_riftbound_cards_selenium(url):
    """Fetches the Riftbound TCG cards page using Selenium and extracts card data."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        driver.get(url)
        # Wait for at least one card image to be present, indicating content has loaded
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "img[alt^=\"Riftbound.\"], img[src$=\"full-desktop.jpg\"]"))
        )
        # Scroll down to load all lazy-loaded images
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2) # Give time for new content to load
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        html_content = driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')
        cards = []

        card_elements = soup.find_all('img', attrs={'alt': lambda x: x and x.startswith('Riftbound.')}) + \
                        soup.find_all('img', src=lambda x: x and x.endswith('full-desktop.jpg'))

        processed_srcs = set()

        for card in card_elements:
            src = card.get('src')
            alt_text = card.get('alt', '')

            if src in processed_srcs:
                continue
            processed_srcs.add(src)

            is_coming_soon = 'full-desktop.jpg' in src or 'Coming Soon' in alt_text

            cards.append({
                'altText': alt_text,
                'src': src,
                'isComingSoon': is_coming_soon
            })
        return cards

    except Exception as e:
        print(f"An error occurred: {e}")
        return []
    finally:
        driver.quit()

if __name__ == '__main__':
    cards_url = "https://riftbound.leagueoflegends.com/en-us/tcg-cards/"
    card_data = get_riftbound_cards_selenium(cards_url)
    if card_data:
        with open('riftbounddb/riftbound_cards_data.json', 'w') as f:
            json.dump(card_data, f, indent=4)
        print(f"Successfully extracted {len(card_data)} cards. Data saved to riftbound_cards_data_selenium.json")
    else:
        print("No card data extracted.")


