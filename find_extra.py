import json
from collections import Counter

# Load both JSON files
with open('wiki_results.json', 'r', encoding='utf-8') as f:
    wiki_results = json.load(f)

with open('dmfull.json', 'r', encoding='utf-8') as f:
    dmfull = json.load(f)

# Check for duplicate IDs
wiki_ids = [card["_id"]["$oid"] for card in wiki_results]
dmfull_ids = [card["_id"]["$oid"] for card in dmfull]

# Count duplicates
wiki_duplicates = [id for id, count in Counter(wiki_ids).items() if count > 1]
dmfull_duplicates = [id for id, count in Counter(dmfull_ids).items() if count > 1]

print(f"Wiki Results Count: {len(wiki_results)}")
print(f"DM Full Count: {len(dmfull)}")
print(f"\nDuplicate IDs in wiki_results: {len(wiki_duplicates)}")
if wiki_duplicates:
    print(f"Duplicate IDs: {wiki_duplicates}")
    for dup_id in wiki_duplicates:
        indices = [i for i, card in enumerate(wiki_results) if card["_id"]["$oid"] == dup_id]
        print(f"\n  ID {dup_id} appears at indices: {indices}")
        for idx in indices:
            card = wiki_results[idx]
            print(f"    [{idx}] {card.get('cardName', 'N/A')} - {card.get('cardId', 'N/A')}")

print(f"\nDuplicate IDs in dmfull: {len(dmfull_duplicates)}")
if dmfull_duplicates:
    print(f"Duplicate IDs: {dmfull_duplicates}")
