import requests
import os
import sys
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

from service.googlecloudservice import upload_image_to_gcs
from service.mongo_service import MongoService
from service.notification_service import NotificationService

mongo_service = MongoService()
notification_service = NotificationService()

SET_MAP = {
    "set1": "TFC",
    "set2": "ROTF",
    "set3": "ITI",
    "set4": "UR",
    "set5": "SS",
    "set6": "AS",
    "set7": "AI",
    "set8": "ROJ",
    "set9": "FAB",
    "set10": "WITW",
    "set11": "WS",
    "set12": "WU",
    "set13": "AOTV",
}

API_URL = "https://cards.disneylorcana.com/en-US/api/cards/en"


def fetch_all_cards():
    print(f"Fetching {API_URL}")
    resp = requests.get(API_URL, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    cards = data.get("cards", [])
    filters = data.get("filters", {})
    set_names = data.get("setNames", {})
    print(f"Received {len(cards)} cards total")
    return cards, filters, set_names


def normalize_card(card, gcs_path=None):
    card_identifier = card.get("card_identifier", "")
    parts = card_identifier.split()
    collector = parts[0] if parts else ""
    lang = parts[1] if len(parts) > 1 else "EN"
    set_code = parts[2] if len(parts) > 2 else ""

    set_id = ""
    card_sets = card.get("card_sets", [])
    if card_sets:
        set_id = card_sets[0].get("id", "")

    booster = SET_MAP.get(set_id, set_id)

    author = card.get("author", "")
    subtitle = card.get("subtitle", "")
    card_type_raw = card.get("card_type", "")
    card_type = card_type_raw.capitalize() if card_type_raw else ""

    subtypes = card.get("subtypes", [])
    display_type = [card_type]
    if subtypes:
        display_type = [card_type] + subtypes

    full_name = f"{card.get('name', '')} - {subtitle}" if subtitle else card.get('name', '')

    variants = card.get("variants", [])
    urlimage = ""
    if variants:
        raw_url = variants[0].get("detail_image_url", "")
        if raw_url:
            img_url = raw_url.rstrip("/") + "/card"
            filename = card_identifier.replace(" ", "_").replace("/", "_")
            if gcs_path:
                try:
                    urlimage = upload_image_to_gcs(img_url, filename, gcs_path)
                except Exception as e:
                    print(f"GCS upload failed: {e}")
                    urlimage = img_url
            else:
                urlimage = img_url

    rarity = card.get("rarity", "")
    if rarity == "SUPER":
        rarity = "Super Rare"
    elif rarity == "LEGENDARY":
        rarity = "Legendary"
    elif rarity == "ENCHANTED":
        rarity = "Enchanted"
    elif rarity == "SPECIAL":
        rarity = "Special Rare"
    else:
        rarity = rarity.capitalize() if rarity else ""

    return {
        "cardName": card.get("name", ""),
        "subtitle": subtitle,
        "fullName": full_name,
        "card_identifier": card_identifier,
        "collectorNumber": collector,
        "lang": lang.lower(),
        "cardId": card_identifier,
        "cardUid": card.get("culture_invariant_id", ""),
        "rarity": rarity,
        "inkColors": card.get("magic_ink_colors", []),
        "inkable": card.get("ink_convertible", False),
        "inkCost": card.get("ink_cost"),
        "cardType": display_type,
        "cardTypeRaw": card_type_raw,
        "subtypes": subtypes,
        "author": author,
        "rulesText": card.get("rules_text", ""),
        "flavorText": card.get("flavor_text", ""),
        "strength": card.get("strength"),
        "willpower": card.get("willpower"),
        "lore": card.get("quest_value"),
        "setId": set_id,
        "setCode": set_code,
        "setName": card_sets[0].get("name", "") if card_sets else "",
        "booster": booster,
        "urlimage": urlimage,
        "variants": [
            {
                "variant_id": v.get("variant_id"),
                "detail_image_url": v.get("detail_image_url", ""),
                "foil_type": v.get("foil_type"),
            }
            for v in variants
        ],
    }


def scrape_lorcana_all():
    gcs_path = os.getenv("GCS_LORCANA")
    collection = os.getenv("C_LORCANA")
    booster_collection = os.getenv("C_BOOSTERLIST") or "BoosterList"

    cards, filters, set_names = fetch_all_cards()

    all_data = []
    for card in cards:
        try:
            all_data.append(normalize_card(card, gcs_path))
        except Exception as e:
            print(f"Error normalizing card: {e}")

    print(f"Normalized {len(all_data)} cards")

    if all_data and collection:
        try:
            from pymongo import MongoClient
            import certifi
            client = MongoClient(
                f"mongodb+srv://{os.getenv('MONGO_USER')}:{os.getenv('MONGO_PASSWORD')}@{os.getenv('MONGO_CLUSTER')}/{os.getenv('MONGO_DATABASE')}?retryWrites=true&w=majority",
                tlsCAFile=certifi.where(),
            )
            db = client[os.getenv("MONGO_DATABASE")]
            sets_in_data = set(c["booster"] for c in all_data)
            for b in sets_in_data:
                result = db[collection].delete_many({"booster": b})
                print(f"Deleted {result.deleted_count} existing docs for {b}")
            mongo_service.upload_data(
                data=all_data,
                collection_name=collection,
                backup_before_upload=True,
            )
            print(f"Uploaded {len(all_data)} cards to {collection}")
        except Exception as e:
            print(f"MongoDB operation failed: {e}")


def scrape_lorcana_set(set_id):
    if not set_id:
        print("No set_id provided")
        return

    gcs_path = os.getenv("GCS_LORCANA")
    booster_mapped = SET_MAP.get(set_id, set_id)
    collection = os.getenv("C_LORCANA")
    booster_collection = os.getenv("C_BOOSTERLIST") or "BoosterList"

    cards, filters, set_names = fetch_all_cards()

    filtered = [c for c in cards if any(s.get("id") == set_id for s in c.get("card_sets", []))]
    print(f"Matching set {set_id}: {len(filtered)} cards")

    json_data = []
    for card in filtered:
        try:
            json_data.append(normalize_card(card, gcs_path))
        except Exception as e:
            print(f"Error normalizing card: {e}")

    if json_data and collection:
        try:
            from pymongo import MongoClient
            import certifi
            client = MongoClient(
                f"mongodb+srv://{os.getenv('MONGO_USER')}:{os.getenv('MONGO_PASSWORD')}@{os.getenv('MONGO_CLUSTER')}/{os.getenv('MONGO_DATABASE')}?retryWrites=true&w=majority",
                tlsCAFile=certifi.where(),
            )
            db = client[os.getenv("MONGO_DATABASE")]
            result = db[collection].delete_many({"booster": booster_mapped})
            print(f"Deleted {result.deleted_count} existing docs for {booster_mapped}")
            mongo_service.upload_data(
                data=json_data,
                collection_name=collection,
                backup_before_upload=True,
            )

            if not mongo_service.validate_field(
                collection_name=booster_collection,
                field_name="pathname",
                field_value=booster_mapped,
            )["exists"]:
                import re as _re
                num_match = _re.search(r'\d+', set_id)
                order = int(num_match.group()) if num_match else 99
                new_booster = {
                    "pathname": booster_mapped,
                    "alt": booster_mapped,
                    "imageSrc": f"https://images.geekstack.dev/boostercover/lorcana_{booster_mapped.lower()}.webp",
                    "tcg": "lorcana",
                    "order": order,
                    "imgWidth": "110%",
                    "category": "expansion_unreleased",
                }
                notification_service.send_email_notification(
                    subject="New Lorcana Booster Detected",
                    message=f"A new set '{booster_mapped}' has been added to the Lorcana collection.",
                )
                mongo_service.upload_data(
                    data=new_booster,
                    collection_name=booster_collection,
                    backup_before_upload=True,
                )
        except Exception as e:
            print(f"MongoDB operation failed: {e}")
