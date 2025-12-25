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