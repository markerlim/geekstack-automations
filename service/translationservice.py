import json
from deep_translator import GoogleTranslator
import time
from tqdm import tqdm

def translate_data(data, 
                                   fields_to_translate,
                                   src_lang='ja',
                                   dest_lang='en',
                                   batch_size=100,
                                   max_retries=3):
    """
    Translates specified fields in a list of JSON objects together per entry, preserving originals.

    Args:
        data: JSON data (list of objects) to translate.
        fields_to_translate: List of keys to translate.
        src_lang: Source language code.
        dest_lang: Target language code.
        batch_size: Rate limit batch size.
        max_retries: Retry attempts per translation.

    Returns:
        Translated JSON data.
    """
    translator = GoogleTranslator(source=src_lang, target=dest_lang)

    print(f"🔁 Translating fields: {fields_to_translate}")
    print(f"Total entries: {len(data)}")

    for idx, item in enumerate(tqdm(data, desc="Translating entries")):
        retry_count = 0
        while retry_count < max_retries:
            try:
                for field in fields_to_translate:
                    original = item.get(field, "")
                    if not original or str(original).strip() == "":
                        continue

                    # Backup original
                    item[f"{field}JP"] = original

                    # Translate and assign
                    translated = translator.translate(str(original))
                    item[field] = translated

                break  # Success, break retry loop
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(2 ** retry_count)
                else:
                    print(f"\n⚠️ Failed to translate entry {idx+1}: {e}")
                    # Optional: Keep original for failed fields

        # Optional: Simple throttle
        if (idx + 1) % batch_size == 0:
            time.sleep(1)

    return data  # Return translated data


# Example usage
if __name__ == "__main__":
    # Example input JSON data (can be loaded from anywhere, e.g., a database or API)
    input_data = [
        {"cardName": "カード1", "cardName2": "カード2", "effects": "効果1", "effects2": "効果2"},
        {"cardName": "カード3", "cardName2": "カード4", "effects": "効果3", "effects2": "効果4"}
    ]

    # Translate the data
    translated_data = translate_data(
        data=input_data,
        fields_to_translate=['cardName', 'cardName2', 'effects', 'effects2'],
        src_lang='ja',
        dest_lang='en',
        batch_size=100,
        max_retries=3
    )

    # Print the translated data
    print(json.dumps(translated_data, ensure_ascii=False, indent=2))
