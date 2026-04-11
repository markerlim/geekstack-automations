import json
from datetime import datetime

# Get current timestamp in milliseconds
current_timestamp = int(datetime.now().timestamp() * 1000)

# Read the backup file
backup_file = '/Users/markerlim/Desktop/geekstack-automations/fullaheaddb/fullahead_cardlist_backup_20260316_214437.json'

with open(backup_file, 'r', encoding='utf-8') as f:
    cards = json.load(f)

print(f"📋 Processing {len(cards)} cards...")
print(f"⏰ Adding timestamp: {current_timestamp}\n")

# Add created_at and last_updated to each card
for card in cards:
    card['created_at'] = current_timestamp
    card['last_updated'] = current_timestamp

# Write back to the file
with open(backup_file, 'w', encoding='utf-8') as f:
    json.dump(cards, f, ensure_ascii=False, indent=2)

print(f"✅ Updated all {len(cards)} cards with:")
print(f"   - created_at: {current_timestamp}")
print(f"   - last_updated: {current_timestamp}")
print(f"\n💾 Saved back to: {backup_file}")
