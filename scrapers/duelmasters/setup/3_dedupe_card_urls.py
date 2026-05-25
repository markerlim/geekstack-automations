"""Deduplicate card URLs from wiki_set_cards.json into wiki_unique_cards.json.

Run after setup/2_scrape_card_links.py. Re-run any time wiki_set_cards.json updates.
"""
import json
import os

HERE = os.path.dirname(__file__)
INPUT_PATH = os.path.join(HERE, '..', '..', '..', 'duelmasterdb', 'wiki_set_cards.json')
OUTPUT_PATH = os.path.join(HERE, '..', '..', '..', 'duelmasterdb', 'wiki_unique_cards.json')


def main():
    with open(INPUT_PATH) as f:
        data = json.load(f)
    all_urls = sorted({url for v in data.values() for url in v.get('cards', [])})
    with open(OUTPUT_PATH, 'w') as f:
        json.dump({'total': len(all_urls), 'urls': all_urls}, f, indent=2)
    print(f'{len(all_urls)} unique URLs → {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
