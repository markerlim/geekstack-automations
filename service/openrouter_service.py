import os
import json
import requests
import time
import re
from typing import Dict, Any, List, Union
from dotenv import load_dotenv

from service.mappings.haikyuu_mappings import (
    apply_terminology_mappings,
    apply_cardname_consistency_for_translation,
)
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

def repair_json_string(text: str) -> Dict:
    """
    Attempt to repair and parse JSON that may have unescaped quotes or newlines.
    
    Args:
        text: Potentially malformed JSON string
    
    Returns:
        Parsed JSON dict or None if repair fails
    """
    # First attempt: direct parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Second attempt: Remove incomplete trailing structures
    try:
        # Try removing trailing incomplete JSON structures
        text_trimmed = re.sub(r',\s*[}\]]*\s*$', '}', text)  # Remove trailing commas before closing braces
        return json.loads(text_trimmed)
    except json.JSONDecodeError:
        pass
    
    # Third attempt: Extract valid JSON objects from the text
    try:
        # Find the first { and last } and extract content
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            json_str = match.group(0)
            return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    
    return None

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
    - Fields to translate: {' | '.join(fields_to_translate)}


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
                        translated_dict = repair_json_string(translated_text.strip())
                        
                        if translated_dict is None:
                            raise json.JSONDecodeError("Could not repair JSON", translated_text, 0)
                        
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
            "max_tokens": 4500,
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

    def translate_haikyuu(self, json_file_path: str = None, data: List[Dict] = None, fields_to_translate: List[tuple] = None, output_file_path: str = None, batch_size: int = 20) -> Dict:
        """
        Translate Haikyuu card game data from Japanese to English with consistency checking.
        
        Handles cardName translations first, then uses them for consistency in effects/notes translations.
        Pre-applies Haikyuu terminology mappings to ensure known terms are correct.
        
        Can work with either a JSON file path or in-memory data.
        
        Args:
            json_file_path (str): Path to the input JSON file containing card data. Optional if data is provided.
            data (list): In-memory list of card dictionaries. If provided, json_file_path is ignored for loading.
            fields_to_translate (list): List of tuples (source_field, target_field) to translate.
                                       Default: [('cardNameJP', 'cardName'), ('effectsJP', 'effects'), ('notesJP', 'notes')]
            output_file_path (str): Path to save the output JSON file. Only used if json_file_path is provided.
            batch_size (int): Number of translations per API call (default 20)
        
        Returns:
            dict: Result containing:
                - success (bool): Whether translation completed successfully
                - message (str): Status message
                - data (list): Translated card data (if input was in-memory)
                - cardnames_translated (int): Number of unique cardNames translated
                - effects_translated (int): Number of unique effects translated
                - notes_translated (int): Number of unique notes translated
                - output_file (str): Path to saved output file (if file-based)
        """
        if fields_to_translate is None:
            fields_to_translate = [
                ('cardNameJP', 'cardName'),
                ('effectsJP', 'effects'),
                ('notesJP', 'notes')
            ]
        
        try:
            # Load data from file or use provided data
            if data is not None:
                # Use in-memory data
                card_data = data if isinstance(data, list) else [data]
                is_file_based = False
            elif json_file_path:
                # Load from file
                with open(json_file_path, 'r', encoding='utf-8') as f:
                    card_data = json.load(f)
                is_file_based = True
                if output_file_path is None:
                    output_file_path = json_file_path
            else:
                error_msg = "Either json_file_path or data must be provided"
                print(f"❌ {error_msg}")
                return {'success': False, 'error': error_msg}
            
            print("=" * 80)
            print("HAIKYUU CARD TRANSLATION - WITH CONSISTENCY CHECKING")
            print("=" * 80)
            
            # ========================
            # STAGE 1: Translate cardNames
            # ========================
            cardname_translation_map = {}
            cardnames_translated = 0
            
            # Check if cardName translation is needed
            if any(source == 'cardNameJP' for source, _ in fields_to_translate):
                print(f"\n[Stage 1] Extracting and translating cardNameJP...")
                
                # Extract all unique cardNameJP values
                cardname_jp_values = list(dict.fromkeys([
                    card.get('cardNameJP', '')
                    for card in card_data
                    if 'cardNameJP' in card and card['cardNameJP']
                ]))
                
                if cardname_jp_values:
                    print(f"Found {len(cardname_jp_values)} unique cardNameJP values")
                    
                    # Translate cardNameJP values in batches
                    for batch_start in range(0, len(cardname_jp_values), batch_size):
                        batch_end = min(batch_start + batch_size, len(cardname_jp_values))
                        batch_texts = cardname_jp_values[batch_start:batch_end]
                        
                        try:
                            print(f"  [{batch_start + 1}/{len(cardname_jp_values)}] Translating batch of {len(batch_texts)} cardNames...")
                            translations = self._translate_batch_haikyuu(batch_texts)
                            
                            for i, original_value in enumerate(batch_texts):
                                if i < len(translations):
                                    cardname_translation_map[original_value] = translations[i]
                                    print(f"    ✓ {original_value} → {translations[i]}")
                        except Exception as e:
                            print(f"  ⚠️  Warning: Failed to translate batch: {str(e)}")
                            continue
                    
                    # Apply cardName translations
                    for card in card_data:
                        if 'cardNameJP' in card and card['cardNameJP'] in cardname_translation_map:
                            card['cardName'] = cardname_translation_map[card['cardNameJP']]
                            cardnames_translated += 1
                    
                    print(f"✓ CardNames translated: {len(cardname_translation_map)} unique values")
            
            # ========================
            # STAGE 2: Translate effects and notes with cardName consistency
            # ========================
            effects_translated = 0
            notes_translated = 0
            
            # Group remaining fields by type (effects and notes)
            all_translation_maps = {}
            
            for source_field, target_field in fields_to_translate:
                if source_field == 'cardNameJP':
                    continue  # Already processed
                
                print(f"\n[Stage 2] Translating {source_field}...")
                
                # Extract all unique original values
                jp_values = list(dict.fromkeys([
                    card.get(source_field, '')
                    for card in card_data
                    if source_field in card and card[source_field]
                ]))
                
                if not jp_values:
                    print(f"  No {source_field} values found")
                    continue
                
                # Create mapping from treated (with English cardNames) -> original
                treated_to_original = {}
                treated_values = []
                
                for original_value in jp_values:
                    # Apply cardName consistency for translation (creates a modified copy)
                    treated_value = apply_cardname_consistency_for_translation(
                        original_value,
                        cardname_translation_map
                    )
                    treated_values.append(treated_value)
                    treated_to_original[treated_value] = original_value
                
                print(f"  Found {len(jp_values)} unique {source_field} values")
                if cardname_translation_map:
                    print(f"    (applying cardName consistency for translation purposes only)")
                
                # Translate treated values in batches
                translation_map = {}
                for batch_start in range(0, len(treated_values), batch_size):
                    batch_end = min(batch_start + batch_size, len(treated_values))
                    batch_texts = treated_values[batch_start:batch_end]
                    
                    try:
                        print(f"  [{batch_start + 1}/{len(treated_values)}] Translating batch of {len(batch_texts)} items...")
                        translations = self._translate_batch_haikyuu(batch_texts)
                        
                        for i, treated_value in enumerate(batch_texts):
                            if i < len(translations):
                                # Store mapping from ORIGINAL value to translation
                                original_value = treated_to_original[treated_value]
                                translation_map[original_value] = translations[i]
                                print(f"    ✓ Translated")
                    except Exception as e:
                        print(f"  ⚠️  Warning: Failed to translate batch: {str(e)}")
                        continue
                
                # Apply translations to cards
                for card in card_data:
                    if source_field in card and card[source_field] in translation_map:
                        card[target_field] = translation_map[card[source_field]]
                        if source_field == 'effectsJP':
                            effects_translated += 1
                        elif source_field == 'notesJP':
                            notes_translated += 1
                
                all_translation_maps[source_field] = translation_map
                print(f"✓ {source_field} translated: {len(translation_map)} unique values")
            
            # ========================
            # STAGE 3: Save output (if file-based)
            # ========================
            result = {
                'success': True,
                'message': 'Haikyuu translation completed successfully',
                'cardnames_translated': cardnames_translated,
                'effects_translated': effects_translated,
                'notes_translated': notes_translated,
            }
            
            if is_file_based and output_file_path:
                print(f"\n[Stage 3] Saving output...")
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    json.dump(card_data, f, ensure_ascii=False, indent=2)
                result['output_file'] = output_file_path
                print(f"✓ Output saved to: {output_file_path}")
            else:
                # Return in-memory data
                result['data'] = card_data
            
            print("\n" + "=" * 80)
            print("✅ TRANSLATION COMPLETE!")
            print("=" * 80)
            
            return result
        
        except FileNotFoundError:
            error_msg = f"Error: File not found - {json_file_path}"
            print(f"❌ {error_msg}")
            return {'success': False, 'error': error_msg}
        except json.JSONDecodeError:
            error_msg = f"Error: Invalid JSON format in {json_file_path}"
            print(f"❌ {error_msg}")
            return {'success': False, 'error': error_msg}
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': error_msg}

    def _translate_batch_haikyuu(self, texts: List[str]) -> List[str]:
        """
        Translate a batch of Japanese Haikyuu card texts to English.
        Pre-applies known terminology mappings to ensure consistency.
        
        Args:
            texts (list): List of Japanese text strings to translate
            
        Returns:
            list: List of translated English texts in the same order
        """
        if not texts:
            return []
        
        # Apply terminology mappings first to ensure known terms are correct
        processed_texts = [apply_terminology_mappings(text) for text in texts]
        
        # Create a numbered list for easy parsing
        input_text = "\n".join([f"{i+1}. {text}" for i, text in enumerate(processed_texts)])
        
        system_prompt = """You are an expert TCG translator for the Haikyu!! Volleyball Card Game.
The card effects have already had standard terminology replaced with English equivalents.
Your job is to translate the remaining Japanese text while maintaining a professional TCG rulebook tone.
Ensure the final translation is clear and follows card game conventions."""
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": f"""Translate these {len(texts)} Japanese card texts to English.
Return ONLY the translations, numbered 1-{len(texts)}.
Maintain a professional TCG rulebook tone.

{input_text}"""
                }
            ],
            "max_tokens": 4000,
            "temperature": 0.2  # Lower temperature ensures consistent wording
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            response_text = result['choices'][0]['message']['content'].strip()
            
            # Parse the numbered translations - handle multi-line translations
            translations = []
            
            # Use regex to find all numbered items (1. 2. 3. etc.)
            # This handles multi-line translations correctly
            import re
            
            # Pattern to match "N. " at the start of a line
            pattern = r'^(\d+)\.\s+'
            
            lines = response_text.split('\n')
            current_translation = None
            
            for line in lines:
                match = re.match(pattern, line)
                if match:
                    # This line starts a new numbered item
                    # Save the previous translation if it exists
                    if current_translation is not None:
                        translations.append(current_translation.strip())
                    
                    # Start the new translation (remove the number and period)
                    current_translation = line[match.end():]
                elif current_translation is not None:
                    # This is a continuation of the current translation
                    current_translation += '\n' + line
                else:
                    # Discard lines that don't belong to any numbered item
                    pass
            
            # Don't forget to add the last translation
            if current_translation is not None:
                translations.append(current_translation.strip())
            
            return translations
        except Exception as e:
            raise Exception(f"Translation API error: {str(e)}")