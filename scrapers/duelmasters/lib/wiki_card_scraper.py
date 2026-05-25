from bs4 import BeautifulSoup
from typing import Dict, Any
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import re


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
    
    def extract_text_with_newlines(self, element) -> str:
        """Extract text while preserving intentional newlines from <br> and <p> tags."""
        if not element:
            return ""
        
        # Recursively extract text, treating <p> and <br> as separators
        parts = []
        for child in element.children:
            if isinstance(child, str):
                text = child.strip()
                if text:
                    parts.append(text)
            elif getattr(child, 'name', None) == 'br':
                parts.append('\n')
            elif getattr(child, 'name', None) == 'p':
                # Extract text from paragraph, add newline after
                p_text = child.get_text(separator=' ').strip()
                if p_text:
                    parts.append(p_text)
                    parts.append('\n')
            else:
                # Recurse into child elements, joining with space
                inner_text = child.get_text(separator=' ').strip()
                if inner_text:
                    parts.append(inner_text)
        
        # Join parts
        text = ''.join(parts)
        
        # Clean up excessive spaces within lines, but preserve newlines
        lines = text.split('\n')
        cleaned_lines = [' '.join(line.split()) for line in lines]  # Normalize spaces per line
        text = '\n'.join(cleaned_lines)
        
        # Remove leading/trailing newlines
        text = text.strip()
        
        return text
    
    def extract_english_and_japanese_name_from_header(self, header_div):
        """
        Extract English and Japanese names from header div.
        Returns (english_name, japanese_name)
        """
        if not header_div:
            return ("", "")

        english_parts = []
        japanese_name = ""
        found_br = False
        for element in header_div.children:
            if isinstance(element, str):
                text = element.strip()
                if text and not found_br:
                    english_parts.append(text)
            elif element.name == 'br':
                found_br = True
            elif element.name == 'small':
                # Robust Japanese name extraction
                small = element
                jp_parts = []
                for child in small.children:
                    if getattr(child, 'name', None) == 'ruby':
                        # Only take <rb> text (kanji), skip <rt>/<rp>
                        for rb in child.find_all('rb'):
                            jp_parts.append(rb.get_text(strip=True))
                    elif isinstance(child, str):
                        # Plain text directly in <small>
                        jp_parts.append(child.strip())
                    elif getattr(child, 'name', None):
                        # Any other tag in <small>
                        jp_parts.append(child.get_text(strip=True))
                japanese_name = ''.join([s for s in jp_parts if s])
            else:
                text = element.get_text(strip=True)
                if text:
                    english_parts.append(text)
        english_name = ' '.join(english_parts).strip()
        return (english_name, japanese_name)
    
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
        
        # Extract card name (English and Japanese) from the header div
        header_div = section_header.find('div', style=lambda x: x and 'color: white' in x if x else False)
        if header_div:
            english_name, japanese_name = self.extract_english_and_japanese_name_from_header(header_div)
            card_info['name'] = english_name
            card_info['name_jp'] = japanese_name
        else:
            # Fallback if div structure is different
            name_text = ' '.join(section_header.stripped_strings)
            small_tags = section_header.find_all('small')
            japanese_name = ''
            for small in small_tags:
                small_text = small.get_text(strip=True)
                name_text = name_text.replace(small_text, '').strip()
                if not japanese_name:
                    japanese_name = small_text
            card_info['name'] = name_text
            card_info['name_jp'] = japanese_name
        
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
                    card_info['english_text'] = self.extract_text_with_newlines(value)
                elif 'Japanese Text' in label:
                    card_info['japanese_text'] = self.extract_text_with_newlines(value)
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
    
    def scrape_booster_page(self, url: str) -> Dict[str, str]:
        """Scrape a booster set wiki page and extract card ID to URL mappings.
        Only scrapes content between "Contents" h2 section and "Cycles" h2 section.
        Handles multiple <p> and <ul> tags in between.
        
        Structure:
        - h2 with span id="Contents"
        - p (empty or with text)
        - ul (with card list items)
        - p (empty or with text)
        - ul (with more card list items)
        - ... more p and ul combinations ...
        - h2 with span id="Cycles"
        
        Args:
            url: The URL of the booster set wiki page
            
        Returns:
            A dictionary mapping card IDs to their wiki URLs
            
        Example:
            {"SSP1/SSP1": "https://duelmasters.fandom.com/wiki/Mendelssohn"}
        """
        try:
            self.driver.get(url)
            # Wait for the page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "ul"))
            )
            time.sleep(1)  # Extra wait for any dynamic content
            
            html_content = self.driver.page_source
        except Exception as e:
            print(f"Error fetching booster page: {e}")
            return {}
        
        soup = BeautifulSoup(html_content, 'html.parser')
        card_mapping = {}
        
        # Find the "Contents" h2 section - look for span with id="Contents"
        contents_h2 = None
        end_h2 = None
        
        h2_elements = soup.find_all('h2')
        found_contents = False
        for h2 in h2_elements:
            span = h2.find('span', {'id': 'Contents'})
            if span:
                contents_h2 = h2
                found_contents = True
                continue
            
            # Use the first h2 after Contents as the end boundary
            # (could be "Cycles", "Gallery", or anything else)
            if found_contents and not end_h2:
                end_h2 = h2
        
        if not contents_h2:
            print("Warning: 'Contents' h2 section not found")
            return {}
        
        if not end_h2:
            print("Warning: No h2 section found after 'Contents'")
            return {}
        
        # Iterate through all siblings between Contents and the next h2
        current = contents_h2.find_next_sibling()
        
        while current and current != end_h2:
            # Look for all ul tags
            if current.name == 'ul':
                # Extract all li items from this ul
                list_items = current.find_all('li', recursive=False)
                
                for li in list_items:
                    # Get the HTML content of the li to split by <br> tags
                    li_html = str(li)
                    
                    # Split by <br> tags to handle multiple cards in one <li>
                    segments = li_html.split('<br')
                    
                    # Process each segment
                    for segment in segments:
                        # Parse this segment
                        soup_segment = BeautifulSoup(segment, 'html.parser')
                        link = soup_segment.find('a', href=True)
                        
                        if link:
                            href = link['href']
                            
                            # Get the full URL
                            if href.startswith('/'):
                                full_url = "https://duelmasters.fandom.com" + href
                            elif href.startswith('http'):
                                full_url = href
                            else:
                                full_url = "https://duelmasters.fandom.com/wiki/" + href
                            
                            # Use URL slug as the identifier
                            url_slug = full_url.split('/wiki/')[-1] if '/wiki/' in full_url else full_url
                            card_mapping[url_slug] = full_url
            
            current = current.find_next_sibling()
        
        return card_mapping
