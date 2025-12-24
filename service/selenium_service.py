from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import time
import os

class SeleniumService:
    """Selenium service layer for web automation"""
    
    def __init__(self, headless=True, window_size="1920,1080", timeout=10):
        """
        Initialize Selenium service
        
        Args:
            headless: Run browser in headless mode
            window_size: Browser window size
            timeout: Default wait timeout in seconds
        """
        self.driver = None
        self.wait = None
        self.headless = headless
        self.window_size = window_size
        self.timeout = timeout
        self._setup_driver()
    
    def _setup_driver(self):
        """Setup Chrome driver with optimized options"""
        chrome_options = Options()
        
        if self.headless:
            chrome_options.add_argument("--headless=new")
        
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument(f"--window-size={self.window_size}")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--disable-logging")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # User agent to avoid detection
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.wait = WebDriverWait(self.driver, self.timeout)
            print(f"✅ Selenium driver initialized successfully")
        except Exception as e:
            print(f"❌ Failed to create Chrome driver: {str(e)}")
            print("⚠️ Make sure chromedriver is installed and in PATH")
            raise
    
    def navigate_to(self, url):
        """Navigate to a URL"""
        try:
            self.driver.get(url)
            print(f"✅ Navigated to: {url}")
            return True
        except Exception as e:
            print(f"❌ Failed to navigate to {url}: {str(e)}")
            return False
    
    def find_element(self, by, value, timeout=None):
        """Find single element with wait"""
        try:
            if timeout is None:
                timeout = self.timeout
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return element
        except TimeoutException:
            print(f"❌ Element not found: {by}='{value}' within {timeout} seconds")
            return None
    
    def find_elements(self, by, value, timeout=None):
        """Find multiple elements with wait"""
        try:
            if timeout is None:
                timeout = self.timeout
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return self.driver.find_elements(by, value)
        except TimeoutException:
            print(f"❌ Elements not found: {by}='{value}' within {timeout} seconds")
            return []
    
    def click_element(self, by, value, timeout=None):
        """Click an element"""
        try:
            element = self.wait_for_clickable(by, value, timeout)
            if element:
                element.click()
                print(f"✅ Clicked element: {by}='{value}'")
                return True
            return False
        except Exception as e:
            print(f"❌ Failed to click element {by}='{value}': {str(e)}")
            return False
    
    def wait_for_clickable(self, by, value, timeout=None):
        """Wait for element to be clickable"""
        try:
            if timeout is None:
                timeout = self.timeout
            element = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by, value))
            )
            return element
        except TimeoutException:
            print(f"❌ Element not clickable: {by}='{value}' within {timeout} seconds")
            return None
    
    def wait_for_visible(self, by, value, timeout=None):
        """Wait for element to be visible"""
        try:
            if timeout is None:
                timeout = self.timeout
            element = WebDriverWait(self.driver, timeout).until(
                EC.visibility_of_element_located((by, value))
            )
            return element
        except TimeoutException:
            print(f"❌ Element not visible: {by}='{value}' within {timeout} seconds")
            return None
    
    def send_keys(self, by, value, text, clear_first=True):
        """Send keys to an element"""
        try:
            element = self.find_element(by, value)
            if element:
                if clear_first:
                    element.clear()
                element.send_keys(text)
                print(f"✅ Sent keys '{text}' to element: {by}='{value}'")
                return True
            return False
        except Exception as e:
            print(f"❌ Failed to send keys to element {by}='{value}': {str(e)}")
            return False
    
    def select_dropdown_by_value(self, by, value, option_value):
        """Select dropdown option by value"""
        try:
            dropdown_element = self.find_element(by, value)
            if dropdown_element:
                select = Select(dropdown_element)
                select.select_by_value(option_value)
                print(f"✅ Selected option '{option_value}' in dropdown: {by}='{value}'")
                return True
            return False
        except Exception as e:
            print(f"❌ Failed to select dropdown option: {str(e)}")
            return False
    
    def select_dropdown_by_text(self, by, value, option_text):
        """Select dropdown option by visible text"""
        try:
            dropdown_element = self.find_element(by, value)
            if dropdown_element:
                select = Select(dropdown_element)
                select.select_by_visible_text(option_text)
                print(f"✅ Selected option '{option_text}' in dropdown: {by}='{value}'")
                return True
            return False
        except Exception as e:
            print(f"❌ Failed to select dropdown option: {str(e)}")
            return False
    
    def get_page_source(self):
        """Get current page HTML source"""
        return self.driver.page_source
    
    def get_current_url(self):
        """Get current page URL"""
        return self.driver.current_url
    
    def get_element_text(self, by, value):
        """Get text content of an element"""
        try:
            element = self.find_element(by, value)
            if element:
                return element.text
            return None
        except Exception as e:
            print(f"❌ Failed to get element text: {str(e)}")
            return None
    
    def get_element_attribute(self, by, value, attribute):
        """Get attribute value of an element"""
        try:
            element = self.find_element(by, value)
            if element:
                return element.get_attribute(attribute)
            return None
        except Exception as e:
            print(f"❌ Failed to get element attribute: {str(e)}")
            return None
    
    def execute_script(self, script, *args):
        """Execute JavaScript"""
        try:
            return self.driver.execute_script(script, *args)
        except Exception as e:
            print(f"❌ Failed to execute script: {str(e)}")
            return None
    
    def scroll_to_element(self, by, value):
        """Scroll to an element"""
        try:
            element = self.find_element(by, value)
            if element:
                self.driver.execute_script("arguments[0].scrollIntoView();", element)
                print(f"✅ Scrolled to element: {by}='{value}'")
                return True
            return False
        except Exception as e:
            print(f"❌ Failed to scroll to element: {str(e)}")
            return False
    
    def take_screenshot(self, filename=None):
        """Take a screenshot"""
        try:
            if filename is None:
                filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            self.driver.save_screenshot(filename)
            print(f"✅ Screenshot saved: {filename}")
            return filename
        except Exception as e:
            print(f"❌ Failed to take screenshot: {str(e)}")
            return None
    
    def sleep(self, seconds):
        """Wait for specified seconds"""
        time.sleep(seconds)
        print(f"⏳ Waited {seconds} seconds")
    
    def hover_over_element(self, by, value):
        """Hover over an element"""
        try:
            element = self.find_element(by, value)
            if element:
                ActionChains(self.driver).move_to_element(element).perform()
                print(f"✅ Hovered over element: {by}='{value}'")
                return True
            return False
        except Exception as e:
            print(f"❌ Failed to hover over element: {str(e)}")
            return False
    
    def switch_to_frame(self, frame_locator):
        """Switch to iframe"""
        try:
            if isinstance(frame_locator, tuple):
                frame = self.find_element(*frame_locator)
            else:
                frame = frame_locator
            
            self.driver.switch_to.frame(frame)
            print(f"✅ Switched to frame")
            return True
        except Exception as e:
            print(f"❌ Failed to switch to frame: {str(e)}")
            return False
  
    def switch_to_default_content(self):
        """Switch back to main content from iframe"""
        try:
            self.driver.switch_to.default_content()
            print(f"✅ Switched to default content")
            return True
        except Exception as e:
            print(f"❌ Failed to switch to default content: {str(e)}")
            return False
    
    def refresh_page(self):
        """Refresh the current page"""
        try:
            self.driver.refresh()
            print(f"✅ Page refreshed")
            return True
        except Exception as e:
            print(f"❌ Failed to refresh page: {str(e)}")
            return False
    
    def close(self):
        """Close the browser"""
        try:
            if self.driver:
                self.driver.quit()
                print(f"✅ Browser closed")
        except Exception as e:
            print(f"❌ Error closing browser: {str(e)}")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


def setup_selenium_driver():
    """Legacy function for backward compatibility"""
    return SeleniumService().driver
