import requests
import os
import pandas as pd

# --- CONFIG ---
set_code = "OGN"  # Change this (e.g., OGS, OGN)
base_url = f"https://cdn.rgpub.io/public/live/map/riftbound/latest/{set_code}/metadata.json"
image_url_pattern = f"https://cdn.rgpub.io/public/live/map/riftbound/latest/{set_code}/cards/{{id}}/full-desktop.jpg"

# --- FOLDERS ---
os.makedirs(f"riftbound_{set_code}_images", exist_ok=True)

# --- FETCH JSON ---
response = requests.get(base_url)
if response.status_code != 200:
    raise Exception(f"Failed to fetch data. Status code: {response.status_code}")

data = response.json()

# --- PARSE CARDS ---
cards = []
for item in data.get("items", []):
    card_id = item.get("id")
    card_title = item.get("title")

    # build image url
    img_url = image_url_pattern.format(id=card_id)

    # download image
    img_path = f"riftbound_{set_code}_images/{card_id}.avif"
    try:
        img_data = requests.get(img_url)
        if img_data.status_code == 200:
            with open(img_path, "wb") as f:
                f.write(img_data.content)
            print(f"✅ Downloaded {card_id} - {card_title}")
        else:
            print(f"⚠️ Failed to download {card_id}: {img_data.status_code}")
    except Exception as e:
        print(f"❌ Error downloading {card_id}: {e}")

    # collect metadata
    card = {
        "number": item.get("number"),
        "id": card_id,
        "title": card_title,
        "altText": item.get("altText"),
        "orientation": item.get("orientation"),
        "flags": item.get("flags"),
        "image": img_path,
    }
    cards.append(card)

# --- SAVE METADATA TO CSV ---
df = pd.DataFrame(cards)
df.to_csv(f"riftbound_{set_code}.csv", index=False)
print(f"\n🎉 Done! Saved {len(cards)} cards to riftbound_{set_code}.csv and downloaded images.")
