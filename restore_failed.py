import json

# Load unique wiki URLs
with open('/Users/markerlim/Desktop/geekstack-automations/dm_unique_wiki_urls.json', 'r') as f:
    unique_urls = set(json.load(f))

# Load existing results from copy
with open('/Users/markerlim/Desktop/geekstack-automations/dm_wiki_results copy.json', 'r') as f:
    results = json.load(f)

# Extract scraped URLs
scraped_urls = {item['url'] for item in results if 'url' in item}

# Find missing/failed URLs
failed_urls = unique_urls - scraped_urls

print(f"Total unique URLs: {len(unique_urls)}")
print(f"Successfully scraped: {len(scraped_urls)}")
print(f"Failed/Missing: {len(failed_urls)}")

# Convert to dictionary format matching the original structure
failed_dict = {url: "No cards found" for url in failed_urls}

# Save in proper format
with open('/Users/markerlim/Desktop/geekstack-automations/dm_wiki_results_failed.json', 'w', encoding='utf-8') as f:
    json.dump(failed_dict, f, indent=2, ensure_ascii=False)

print(f"\n✓ Restored dm_wiki_results_failed.json with {len(failed_dict)} failed URLs")
print(f"\nFirst 10 failed URLs:")
for i, url in enumerate(sorted(failed_urls)[:10]):
    print(f"  - {url}")
