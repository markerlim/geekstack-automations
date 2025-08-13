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
                    if isinstance(original, list):
                        translated_list = []
                        for text in original:
                            if not text or str(text).strip() == "":
                                translated_list.append("")
                                continue
                            translated = translator.translate(str(text))
                            translated_list.append(translated)
                        item[field] = translated_list
                    # Handle string fields
                    elif str(original).strip() != "":
                        item[field] = translator.translate(str(original))

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