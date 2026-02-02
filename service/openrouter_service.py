import os
import json
import requests
import time
from typing import Dict, Any, List, Union
from dotenv import load_dotenv
load_dotenv()

def batch_data_for_translation(data: List[Dict], batch_size: int = 12) -> List[List[Dict]]:
    """
    Split a list of card data into batches for efficient API processing.
    
    Args:
        data: List of card dicts to batch
        batch_size: Number of cards per batch (default 12)
    
    Returns:
        List of batches (each a list of card dicts)
    """
    if not data:
        return []
    return [data[i:i+batch_size] for i in range(0, len(data), batch_size)]

class OpenRouterService:
    def __init__(self, api_key=None, model=None, site_url=None, site_name=None):
        """
        Initialize OpenRouter service for AI-powered translations
        
        Args:
            api_key: OpenRouter API key. If None, will try to get from environment
            model: OpenRouter model to use. If None, will try to get from environment
            site_url: Optional site URL for rankings on openrouter.ai
            site_name: Optional site title for rankings on openrouter.ai
        """
        self.api_key = api_key or os.getenv('OPENROUTER_API_KEY')
        if self.api_key:
            print("✓ OpenRouter API key loaded")
            print(self.api_key)
        else:
            raise ValueError("OpenRouter API key is required. Set OPENROUTER_API_KEY environment variable or pass api_key parameter.")
        
        self.model = model or os.getenv('OPENROUTER_MODEL')
        if self.model:
            print("✓ OpenRouter model loaded")
            print(self.model)
        else:
            raise ValueError("OpenRouter model is required. Set OPENROUTER_MODEL environment variable or pass model parameter.")
        
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
                              source_lang: str = "Japanese",
                              target_lang: str = "English",
                              max_retries: int = 3) -> Dict:
        """
        Translate a batch of titles and return the raw response
        
        Args:
            titles: List of titles to translate
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
                response = self._make_request(prompt)
                
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

    def translate_fields(self,
                    data: List[Dict],
                    fields_to_translate: List[str],
                    source_lang: str = "Japanese", 
                    target_lang: str = "English",
                    keep_original: bool = True,
                    max_retries: int = 3) -> Dict:
        """
        Translate specified fields in a list of JSON objects in one API call
    
        Args:
            data: List of objects to translate
            fields_to_translate: List of field names to translate
            source_lang: Source language
            target_lang: Target language  
            keep_original: If True, keeps original in fieldJP format
            max_retries: Number of retry attempts
        
        Returns:
            Dict with success status and translated data
        """
        if not data or not fields_to_translate:
            return {
                'success': True,
                'translated_data': data,
                'message': 'No data or fields to translate'
            }
        
        # Extract only the fields that need translation from each object
        translation_batch = []
        for i, item in enumerate(data):
            item_translations = {}
            for field in fields_to_translate:
                if field in item and item[field] and str(item[field]).strip():
                    item_translations[f"item_{i}_{field}"] = item[field]
            if item_translations:
                translation_batch.append(item_translations)
        
        # Flatten all translations into one dict for single API call
        all_translations = {}
        for batch in translation_batch:
            all_translations.update(batch)
        
        if not all_translations:
            return {
                'success': True, 
                'translated_data': data,
                'message': 'No content found to translate'
            }
        
        prompt = f"""Translate the following {source_lang} text fields to {target_lang}.
    Return ONLY a JSON object with the same keys but translated values.
    Preserve the exact key format (item_X_fieldname).
    Use natural, accurate translations appropriate for anime/manga/games.

    Input JSON to translate:
    {json.dumps(all_translations, ensure_ascii=False, indent=2)}

    Translated JSON:"""
        
        # Make API request with retries
        for attempt in range(max_retries):
            try:
                response = self._make_request(prompt)
                
                if response and 'choices' in response and len(response['choices']) > 0:
                    translated_text = response['choices'][0]['message']['content'].strip()
                    
                    # Clean up response
                    if translated_text.startswith('```json'):
                        translated_text = translated_text.replace('```json', '').replace('```', '')
                    elif translated_text.startswith('```'):
                        translated_text = translated_text.replace('```', '')
                    
                    try:
                        translated_dict = json.loads(translated_text.strip())
                        
                        # Apply translations back to original data
                        translated_data = []
                        for i, item in enumerate(data):
                            new_item = item.copy()
                            
                            for field in fields_to_translate:
                                key = f"item_{i}_{field}"
                                if key in translated_dict:
                                    # Backup original if requested
                                    if keep_original and field in item:
                                        new_item[f"{field}JP"] = item[field]
                                    
                                    # Set translated value
                                    new_item[field] = translated_dict[key]
                            
                            translated_data.append(new_item)
                        
                        print(f"✓ Successfully translated {len(all_translations)} fields across {len(data)} objects")
                        return {
                            'success': True,
                            'translated_data': translated_data,
                            'original_data': data,
                            'fields_translated': fields_to_translate,
                            'raw_response': translated_text
                        }
                        
                    except json.JSONDecodeError as e:
                        print(f"Failed to parse translation response: {e}")
                        if attempt == max_retries - 1:
                            return {
                                'success': False,
                                'error': f'JSON parse error: {e}',
                                'translated_data': data,  # Return original on failure
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
                        'translated_data': data,  # Return original on failure
                        'raw_response': None
                    }
        
        return {
            'success': False,
            'error': 'Max retries exceeded',
            'translated_data': data,
            'raw_response': None
        }

    def translate_fields_unionarena(self,
                    data: List[Dict],
                    fields_to_translate: List[str],
                    source_lang: str = "Japanese", 
                    target_lang: str = "English",
                    keep_original: bool = True,
                    context: str = None,
                    max_retries: int = 3,
                    batch_size: int = 12) -> Dict:
        """
        Translate specified fields in a list of JSON objects using batch processing.
        Splits data into batches and makes multiple API calls if needed.
    
        Args:
            data: List of objects to translate
            fields_to_translate: List of field names to translate
            source_lang: Source language
            target_lang: Target language  
            keep_original: If True, keeps original in fieldJP format
            context: Context for translation (e.g., anime/game name)
            max_retries: Number of retry attempts per batch
            batch_size: Number of cards per API call (default 12)
        
        Returns:
            Dict with success status and combined translated data
        """
        if not data or not fields_to_translate:
            return {
                'success': True,
                'translated_data': data,
                'message': 'No data or fields to translate'
            }
        if context is None or context.strip() == "":
            raise ValueError("Context for translation (e.g., anime/game name) must be provided and non-empty.")
        
        # Split data into batches
        batches = batch_data_for_translation(data, batch_size)
        print(f"[Batch Processing] Processing {len(data)} cards in {len(batches)} batch(es) (batch size: {batch_size})")
        
        all_translated_data = []
        total_token_usage = {
            'total_tokens': 0,
            'prompt_tokens': 0,
            'completion_tokens': 0
        }
        
        for batch_idx, batch in enumerate(batches, 1):
            print(f"[Batch {batch_idx}/{len(batches)}] Translating {len(batch)} cards...")
            
            # Process this batch
            batch_result = self._translate_batch_unionarena(
                batch,
                fields_to_translate,
                source_lang,
                target_lang,
                keep_original,
                context,
                max_retries
            )
            
            if not batch_result['success']:
                print(f"[Batch {batch_idx}] Failed: {batch_result.get('error', 'Unknown error')}")
                return batch_result  # Return failure immediately
            
            all_translated_data.extend(batch_result['translated_data'])
            
            # Accumulate token usage
            if batch_result.get('token_usage'):
                total_token_usage['total_tokens'] += batch_result['token_usage'].get('total_tokens', 0)
                total_token_usage['prompt_tokens'] += batch_result['token_usage'].get('prompt_tokens', 0)
                total_token_usage['completion_tokens'] += batch_result['token_usage'].get('completion_tokens', 0)
            
            print(f"[Batch {batch_idx}] ✓ Completed")
        
        print(f"\n[Summary] Successfully translated {len(all_translated_data)} cards total")
        print(f"[Batches] Processed {len(batches)} batch(es)")
        print(f"[Token Usage] Total: {total_token_usage['total_tokens']}, Prompt: {total_token_usage['prompt_tokens']}, Completion: {total_token_usage['completion_tokens']}")
        
        return {
            'success': True,
            'translated_data': all_translated_data,
            'original_data': data,
            'fields_translated': fields_to_translate,
            'raw_response': None
        }
    
    def _translate_batch_unionarena(self,
                    data: List[Dict],
                    fields_to_translate: List[str],
                    source_lang: str,
                    target_lang: str,
                    keep_original: bool,
                    context: str,
                    max_retries: int) -> Dict:
        """
        Internal method to translate a single batch of cards.
        
        Args:
            data: List of objects in this batch
            fields_to_translate: Fields to translate
            source_lang: Source language
            target_lang: Target language
            keep_original: Keep original field
            context: Translation context
            max_retries: Retry attempts
        
        Returns:
            Dict with success status and translated batch data
        """
        # Extract only the fields that need translation from each object
        translation_batch = []
        for i, item in enumerate(data):
            item_translations = {}
            for field in fields_to_translate:
                if field in item and item[field] and str(item[field]).strip():
                    item_translations[f"item_{i}_{field}"] = item[field]
            if item_translations:
                translation_batch.append(item_translations)
        
        # Flatten all translations into one dict for single API call
        all_translations = {}
        for batch in translation_batch:
            all_translations.update(batch)
        
        if not all_translations:
            return {
                'success': True, 
                'translated_data': data,
                'message': 'No content found to translate'
            }
        
        prompt = f"""
    You are translating trading card game effects.

    Context:
    - Anime/Manga/Game universe: {context}
    - This is official card effect text.
    - Translation must sound natural and professional for anime TCGs.
    - Source language: {source_lang}
    - Target language: {target_lang}
    - Fields to translate: {', '.join(fields_to_translate)}


    CONTEXT AUTHORITY RULE (CRITICAL):
    - The provided context defines the official canon for names, terminology, and romanization.
    - Use the naming and romanization conventions implied by the context.
    - Do NOT default to literal translation or pinyin/kunrei/hepburn unless the context clearly implies it.
    - If multiple romanizations exist, choose the one most commonly used in official anime/game localizations for this context.
    - Name Mapping Example: 龐煖 should always be romanized as "Hou Ken" (not "Pang Nuan") in the Kingdom context.

    STRICT RULES (must follow all):
    1. REMOVE all HTML tags completely (e.g. <dd>, <br>, etc).
    2. For any <img> tag, REPLACE it with its alt text. If the alt value matches the following mapping, use the mapped English tag instead (otherwise, use the alt value in square brackets):
    Alt Text to English Tag Mapping:
      'インパクト（1）': '[Impact 1]',
      'インパクト（2）': '[Impact 2]',
      'インパクト（3）': '[Impact 3]',
      'インパクト（4）': '[Impact 4]',
      'インパクト': '[Impact]',
      '2回ブロック': '[Block x2]',
      '2回アタック': '[Attack x2]',
      '狙い撃ち': '[Snipe]',
      'インパクト（+1）': '[Impact +1]',
      'ステップ': '[Step]',
      'ダメージ': '[Damage]',
      'ダメージ（+1）': '[Damage +1]',
      'ダメージ（2）': '[Damage 2]',
      'ダメージ（3）': '[Damage 3]',
      'ダメージ（4）': '[Damage 4]',
      'ダメージ（5）': '[Damage 5]',
      'ダメージ（6）': '[Damage 6]',
      'ダメージ（7）': '[Damage 7]',
      'インパクト無効': '[Impact Negate]',
      'ターン1': '[Once Per Turn]',
      'レストにする': '[Rest this card]',
      'このカードを退場させる': '[Retire this card]',
      '手札を1枚場外に置く': '[Place 1 card from hand to Outside Area]',
      '手札を2枚場外に置く': '[Place 2 cards from hand to Outside Area]',
      '手札を3枚場外に置く': '[Place 3 cards from hand to Outside Area]',
      'フロントLにある場合': '[When In Front Line]',
      'エナジーLにある場合': '[When In Energy Line]',
      '場外にある場合': '[When In Outside Area]',
      '除外エリアにある場合': '[When In Remove Area]',
      'APを1支払う': '[Pay 1 AP]',
      'レイド': '[Raid]',
      '登場時': '[On Play]',
      '退場時': '[On Retire]',
      'ブロック時': '[When Blocking]',
      '起動メイン': '[Activate Main]',
      'アタック時': '[When Attacking]',
      '自分のターン中': '[Your Turn]',
      '相手のターン中': "[Opponent's Turn]",
      'トリガー': '[Trigger]',

    If the alt value is not in the mapping, use the alt value in square brackets, e.g. [alt value].
    3. Preserve line breaks where effects are logically separated.
    4. Do NOT add explanations, notes, or commentary.
    5. Do NOT summarize or paraphrase — translate faithfully with TCG-style wording.
    6. Use consistent card-game terminology (e.g. "BP", "AP", "draw a card") and preserve effect headers such as [On Attack], [On Appearance], [When in Front L], [When Removed].
    7. Output ONLY valid JSON.
    8. Preserve the exact key names (item_X_fieldname).
    9. Values must be strings.

    Input JSON:
    {json.dumps(all_translations, ensure_ascii=False, indent=2)}

    Output JSON:
    """

        
        # Make API request with retries
        for attempt in range(max_retries):
            try:
                response = self._make_request(prompt)
                # Track token usage if available
                usage_info = response.get('usage', {}) if response else {}
                total_tokens = usage_info.get('total_tokens')
                prompt_tokens = usage_info.get('prompt_tokens')
                completion_tokens = usage_info.get('completion_tokens')
                if total_tokens is not None:
                    print(f"[OpenRouter] Token usage: total={total_tokens}, prompt={prompt_tokens}, completion={completion_tokens}")
                
                if response and 'choices' in response and len(response['choices']) > 0:
                    translated_text = response['choices'][0]['message']['content'].strip()
                    # Clean up response
                    if translated_text.startswith('```json'):
                        translated_text = translated_text.replace('```json', '').replace('```', '')
                    elif translated_text.startswith('```'):
                        translated_text = translated_text.replace('```', '')
                    try:
                        translated_dict = json.loads(translated_text.strip())
                        # Apply translations back to original data
                        translated_data = []
                        for i, item in enumerate(data):
                            new_item = item.copy()
                            for field in fields_to_translate:
                                key = f"item_{i}_{field}"
                                if key in translated_dict:
                                    # Backup original if requested
                                    if keep_original and field in item:
                                        new_item[f"{field}JP"] = item[field]
                                    # Set translated value
                                    new_item[field] = translated_dict[key]
                            translated_data.append(new_item)
                        print(f"✓ Successfully translated {len(all_translations)} fields across {len(data)} objects")
                        return {
                            'success': True,
                            'translated_data': translated_data,
                            'original_data': data,
                            'fields_translated': fields_to_translate,
                            'raw_response': translated_text,
                            'token_usage': usage_info
                        }
                    except json.JSONDecodeError as e:
                        print(f"Failed to parse translation response: {e}")
                        if attempt == max_retries - 1:
                            return {
                                'success': False,
                                'error': f'JSON parse error: {e}',
                                'translated_data': data,  # Return original on failure
                                'raw_response': translated_text,
                                'token_usage': usage_info
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
                        'translated_data': data,  # Return original on failure
                        'raw_response': None,
                        'token_usage': None
                    }
        
        return {
            'success': False,
            'error': 'Max retries exceeded',
            'translated_data': data,
            'raw_response': None
        }

    def _make_request(self, prompt: str) -> Dict:
        """
        Make request to OpenRouter API
        """
        payload = {
            "model": self.model,
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