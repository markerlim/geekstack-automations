from bs4 import BeautifulSoup
from typing import Dict, Any
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time


class DuelMastersCardWikiScraper:
    """Scrapes card information from Duel Masters wiki pages."""
    
    def __init__(self, driver):
        """Initialize scraper with a Selenium WebDriver instance.
        
        Args:
            driver: A Selenium WebDriver instance to use for fetching pages.
        """
        self.driver = driver
    
    def extract_text_content(self, element) -> str:
        """Extract clean text from an element, preserving proper spacing."""
        if not element:
            return ""
        
        # Get all text nodes and join with spaces
        text_parts = []
        for string in element.stripped_strings:
            text_parts.append(string)
        
        return ' '.join(text_parts)
    
    def clean_text(self, text: str) -> str:
        """Clean extracted text by removing extra symbols and normalizing whitespace."""
        # Remove shield trigger symbol prefix if present
        text = text.replace('Shield trigger', 'Shield Trigger').strip()
        # Normalize multiple spaces to single space
        text = ' '.join(text.split())
        # Clean up common wiki artifacts
        text = text.replace('[ citation needed ]', '').strip()
        return text
    
    def fetch_page(self, url: str) -> str:
        """Fetch the wiki page content using Selenium and wait for AJAX content."""
        try:
            self.driver.get(url)
            # Wait for the wikitable to be present (max 15 seconds)
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CLASS_NAME, "wikitable"))
            )
            # Extra wait to ensure all AJAX content is loaded
            time.sleep(2)
            return self.driver.page_source
        except Exception as e:
            print(f"Error fetching page with Selenium: {e}")
            return None
    
    def is_twinpact_card(self, soup: BeautifulSoup) -> bool:
        """Check if the card is a twinpact (dual) card by counting major sections."""
        # Look for multiple card name sections (indicated by header rows)
        header_divs = soup.find_all('div', style=lambda x: x and 'color: white' in x)
        card_name_headers = [div for div in header_divs if div and 'br' in str(div)]
        return len(card_name_headers) >= 2
    
    def extract_card_section(self, soup: BeautifulSoup, start_index: int = 0) -> Dict[str, Any]:
        """Extract a single card section from the table."""
        card_info = {}
        
        # Find all table rows
        rows = soup.find_all('tr')
        
        if start_index >= len(rows):
            return None
        
        # Find the next major section header (card name)
        section_header = None
        for i in range(start_index, len(rows)):
            header_div = rows[i].find('div', style=lambda x: x and 'color: white' in x if x else False)
            if header_div and 'br' in str(header_div):
                section_header = rows[i]
                start_row = i + 1
                break
        
        if not section_header:
            return None
        
        # Extract card name
        name_text = ' '.join(section_header.stripped_strings)
        # Remove Japanese text in small tags
        small_tags = section_header.find_all('small')
        for small in small_tags:
            name_text = name_text.replace(small.get_text(strip=True), '').strip()
        card_info['name'] = name_text
        
        # Extract properties until next major section
        current_row = start_row
        while current_row < len(rows):
            row = rows[current_row]
            
            # Check if this is another major section header
            next_header = row.find('div', style=lambda x: x and 'color: white' in x if x else False)
            if next_header and 'br' in str(next_header) and row != section_header:
                break
            
            cells = row.find_all('td')
            if len(cells) >= 2:
                label = self.extract_text_content(cells[0])
                value = cells[1]
                
                # Extract relevant fields
                if 'Civilization' in label:
                    card_info['civilization'] = value.find('a').get_text(strip=True) if value.find('a') else self.extract_text_content(value)
                elif 'Card Type' in label:
                    card_info['card_type'] = self.extract_text_content(value)
                elif 'Mana Cost' in label:
                    card_info['mana_cost'] = self.extract_text_content(value)
                elif 'Race' in label:
                    card_info['race'] = self.extract_text_content(value)
                elif 'Power' in label:
                    card_info['power'] = self.extract_text_content(value)
                elif 'Mana Number' in label:
                    card_info['mana_number'] = self.extract_text_content(value)
                elif 'English Text' in label:
                    card_info['english_text'] = self.clean_text(self.extract_text_content(value))
                elif 'Japanese Text' in label:
                    card_info['japanese_text'] = self.clean_text(self.extract_text_content(value))
                elif 'Illustrator' in label:
                    card_info['illustrator'] = self.extract_text_content(value)
            
            current_row += 1
        
        return card_info if card_info else None
    
    def scrape_card(self, url: str) -> Dict[str, Any]:
        """Scrape a card from the wiki URL."""
        html_content = self.fetch_page(url)
        if not html_content:
            return None
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find the main card info table
        card_table = soup.find('table', {'class': 'wikitable'})
        
        # Debug output
        print(f"HTML length: {len(html_content)}")
        print(f"Table found: {card_table is not None}")
        
        if card_table:
            rows = card_table.find_all('tr')
            print(f"Rows found: {len(rows)}")
        else:
            # Try to find any table
            all_tables = soup.find_all('table')
            print(f"Total tables on page: {len(all_tables)}")
            if all_tables:
                for i, table in enumerate(all_tables[:3]):
                    print(f"Table {i}: classes={table.get('class')}")
            # Save HTML for inspection
            with open('debug_page.html', 'w') as f:
                f.write(html_content[:5000])
            print("Saved first 5000 chars to debug_page.html")
            return None
        
        result = {
            'url': url,
            'is_twinpact': self.is_twinpact_card(card_table),
            'cards': []
        }
        
        # Extract all card sections
        rows = card_table.find_all('tr')
        current_index = 0
        
        while current_index < len(rows):
            card_data = self.extract_card_section(card_table, current_index)
            if card_data:
                result['cards'].append(card_data)
                # Move to next section (rough estimate - refine based on actual structure)
                current_index += 10  # Approximate rows per card section
            else:
                current_index += 1
        
        return result
