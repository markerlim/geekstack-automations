import os
import json
import requests
import time
from typing import Dict, Any, List, Union

class OpenRouterService:
    def __init__(self, api_key=None, site_url=None, site_name=None):
        """
        Initialize OpenRouter service for AI-powered translations
        
        Args:
            api_key: OpenRouter API key. If None, will try to get from environment
            site_url: Optional site URL for rankings on openrouter.ai
            site_name: Optional site title for rankings on openrouter.ai
        """
        self.api_key = api_key or os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("OpenRouter API key is required. Set OPENROUTER_API_KEY environment variable or pass api_key parameter.")
        
        self.base_url = "https://openrouter.ai/api/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Optional headers for site rankings
        if site_url:
            self.headers["HTTP-Referer"] = site_url
        if site_name:
            self.headers["X-Title"] = site_name
        
    def translate_titles_batch(self, 
                              titles: List[str], 
                              model: str = "nex-agi/deepseek-v3.1-nex-n1:free",
                              source_lang: str = "Japanese",
                              target_lang: str = "English",
                              max_retries: int = 3) -> Dict:
        """
        Translate a batch of titles and return the raw response
        
        Args:
            titles: List of titles to translate
            model: OpenRouter model to use for translation
            source_lang: Source language (e.g., "Japanese")
            target_lang: Target language (e.g., "English") 
            max_retries: Number of retry attempts for failed requests
            
        Returns:
            Raw translation response payload
        """
        
        # Create JSON structure for the batch
        titles_dict = {f"title_{i}": title for i, title in enumerate(titles)}
        
        prompt = f"""Translate the following {source_lang} anime/manga/game titles to their official {target_lang} titles.
        Return the result as a JSON object with the same keys but translated values.
        Use the most commonly known and official English titles.
        If a title is already in English or mixed languages, keep it as is or make minimal adjustments.
        
        Input:
        {json.dumps(titles_dict, ensure_ascii=False, indent=2)}
        
        Translated JSON:"""
        
        # Make API request with retries
        for attempt in range(max_retries):
            try:
                response = self._make_request(prompt, model)
                
                if response and 'choices' in response and len(response['choices']) > 0:
                    translated_text = response['choices'][0]['message']['content'].strip()
                    
                    # Clean up the response
                    if translated_text.startswith('```json'):
                        translated_text = translated_text.replace('```json', '').replace('```', '')
                    elif translated_text.startswith('```'):
                        translated_text = translated_text.replace('```', '')
                    
                    try:
                        translated_dict = json.loads(translated_text.strip())
                        print(f"✓ Successfully translated batch of {len(titles)} titles")
                        return {
                            'success': True,
                            'original_titles': titles,
                            'translated_data': translated_dict,
                            'raw_response': translated_text
                        }
                        
                    except json.JSONDecodeError as e:
                        print(f"Failed to parse translation response: {e}")
                        if attempt == max_retries - 1:
                            return {
                                'success': False,
                                'error': f'JSON parse error: {e}',
                                'original_titles': titles,
                                'raw_response': translated_text
                            }
                            
                else:
                    print(f"Invalid response from OpenRouter: {response}")
                    
            except Exception as e:
                print(f"Translation attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return {
                        'success': False,
                        'error': str(e),
                        'original_titles': titles,
                        'raw_response': None
                    }
        
        return {
            'success': False,
            'error': 'Max retries exceeded',
            'original_titles': titles,
            'raw_response': None
        }

    def translate_json_titles(self, 
                             data: Union[Dict, List], 
                             model: str = None,
                             source_lang: str = "Japanese",
                             target_lang: str = "English",
                             title_fields: List[str] = ["title", "name", "serie"],
                             max_retries: int = 3) -> Union[Dict, List]:
        """
        Translate specified fields in JSON data using OpenRouter AI models
        
        Args:
            data: JSON data (dict or list) to translate
            model: OpenRouter model to use for translation (uses OPENROUTER_MODEL env var if None)
            source_lang: Source language (e.g., "Japanese") 
            target_lang: Target language (e.g., "English")
            title_fields: List of field names to translate
            max_retries: Number of retry attempts for failed requests
            
        Returns:
            Translated JSON data with same structure
        """
        
        # Use environment variable for model if not provided
        if model is None:
            model = os.getenv('OPENROUTER_MODEL', 'nex-agi/deepseek-v3.1-nex-n1:free')
        
        # Handle single dictionary
        if isinstance(data, dict):
            return self._translate_single_item(data, model, source_lang, target_lang, title_fields, max_retries)
        
        # Handle list of dictionaries
        elif isinstance(data, list):
            translated_items = []
            total_items = len(data)
            
            print(f"Translating {total_items} items using OpenRouter...")
            
            for idx, item in enumerate(data):
                if isinstance(item, dict):
                    translated_item = self._translate_single_item(item, model, source_lang, target_lang, title_fields, max_retries)
                    translated_items.append(translated_item)
                else:
                    translated_items.append(item)  # Keep non-dict items as-is
                
                # Progress feedback
                if (idx + 1) % 10 == 0 or (idx + 1) == total_items:
                    print(f"Progress: {idx + 1}/{total_items} items translated")
                
                # Rate limiting - small delay between requests
                time.sleep(0.5)
            
            return translated_items
        
        else:
            return data  # Return unchanged if not dict or list
    
    def _translate_single_item(self, 
                              item: Dict, 
                              model: str, 
                              source_lang: str, 
                              target_lang: str, 
                              title_fields: List[str], 
                              max_retries: int) -> Dict:
        """
        Translate a single dictionary item
        """
        translated_item = item.copy()
        
        # Find fields to translate
        fields_to_translate = []
        for field in title_fields:
            if field in item and isinstance(item[field], str) and item[field].strip():
                fields_to_translate.append(field)
        
        if not fields_to_translate:
            return translated_item  # Nothing to translate
        
        # Create translation prompt
        translation_data = {field: item[field] for field in fields_to_translate}
        
        prompt = f"""Translate the following {source_lang} text fields to {target_lang}. 
        Maintain the same JSON structure and field names. Only translate the values, not the keys.
        Return only valid JSON with the same structure.
        
        Input JSON:
        {json.dumps(translation_data, ensure_ascii=False, indent=2)}
        
        Translated JSON:"""
        
        # Make API request with retries
        for attempt in range(max_retries):
            try:
                response = self._make_request(prompt, model)
                
                if response and 'choices' in response and len(response['choices']) > 0:
                    translated_text = response['choices'][0]['message']['content'].strip()
                    
                    # Try to parse the response as JSON
                    try:
                        # Clean up the response (remove markdown code blocks if present)
                        if translated_text.startswith('```json'):
                            translated_text = translated_text.replace('```json', '').replace('```', '')
                        elif translated_text.startswith('```'):
                            translated_text = translated_text.replace('```', '')
                        
                        translated_data = json.loads(translated_text.strip())
                        
                        # Update the original item with translated values
                        for field, translated_value in translated_data.items():
                            if field in fields_to_translate and isinstance(translated_value, str):
                                translated_item[field] = translated_value
                                
                        print(f"✓ Translated {fields_to_translate}")
                        return translated_item
                        
                    except json.JSONDecodeError as e:
                        print(f"Failed to parse translation response as JSON: {e}")
                        if attempt == max_retries - 1:
                            print(f"Raw response: {translated_text}")
                        
                else:
                    print(f"Invalid response from OpenRouter: {response}")
                    
            except Exception as e:
                print(f"Translation attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
        
        print(f"⚠️ Failed to translate after {max_retries} attempts, keeping original values")
        return translated_item
    
    def _make_request(self, prompt: str, model: str) -> Dict:
        """
        Make request to OpenRouter API
        """
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 2000,
            "temperature": 0.1  # Low temperature for consistent translations
        }
        
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self.headers,
            json=payload,
            timeout=30
        )
        
        response.raise_for_status()
        return response.json()

# Convenience function for easy usage
def translate_json_with_openrouter(data: Union[Dict, List], 
                                  api_key: str = None,
                                  model: str = None,
                                  source_lang: str = "Japanese",
                                  target_lang: str = "English",
                                  title_fields: List[str] = ["title", "name", "serie"],
                                  site_url: str = None,
                                  site_name: str = None) -> Union[Dict, List]:
    """
    Convenience function to translate JSON data using OpenRouter
    
    Args:
        data: JSON data to translate
        api_key: OpenRouter API key (optional, uses environment variable if not provided)
        model: AI model to use (uses OPENROUTER_MODEL env var if None)
        source_lang: Source language
        target_lang: Target language  
        title_fields: Fields to translate
        site_url: Optional site URL for rankings on openrouter.ai
        site_name: Optional site title for rankings on openrouter.ai
        
    Returns:
        Translated JSON data
    """
    # Use environment variable for model if not provided
    if model is None:
        model = os.getenv('OPENROUTER_MODEL', 'nex-agi/deepseek-v3.1-nex-n1:free')
        
    service = OpenRouterService(api_key, site_url, site_name)
    return service.translate_json_titles(data, model, source_lang, target_lang, title_fields)