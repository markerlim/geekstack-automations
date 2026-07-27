"""
One-time job: build the lean global `All_cards` search collection.

Each output doc = { _id (from source), tcg, cardName, cardId, rarity }

HOW TO USE:
  - Edit the GAMES table below. For each game set which SOURCE field maps to
    cardName / cardId / rarity. Use None if the game has no such field.
  - `id_fallback` is an optional second field used only when the primary
    cardId field is missing/empty (e.g. duelmasters falls back to cardUid).
  - Run:  venv/bin/python build_all_cards.py
  - It is idempotent: clears All_cards and rebuilds every run.
"""
import os
from dotenv import load_dotenv
from pymongo import MongoClient, InsertOne
import certifi

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
uri = (f"mongodb+srv://{os.getenv('MONGO_USER')}:{os.getenv('MONGO_PASSWORD')}"
       f"@{os.getenv('MONGO_CLUSTER')}/{os.getenv('MONGO_DATABASE')}?retryWrites=true&w=majority")
db = MongoClient(uri, tlsCAFile=certifi.where())[os.getenv("MONGO_DATABASE")]

# ─── EDIT THIS TABLE ────────────────────────────────────────────────────────
# collection name : per-game field mapping
GAMES = {
    "CL_unionarena_v2":     {"tcg": "unionarena",        "cardName": "cardName", "cardId": "cardId", "rarity": "rarity"},
    "CL_dragonballzfw":     {"tcg": "dragonballzfw",     "cardName": "cardName", "cardId": "cardNo", "rarity": "rarity"},
    "CL_duelmasters":       {"tcg": "duelmasters",       "cardName": "cardName", "cardId": "cardId", "rarity": "rarity", "id_fallback": "cardUid"},
    "CL_gundamcardgame":    {"tcg": "gundam",    "cardName": "cardName", "cardId": "cardId", "rarity": "rarity"},
    "CL_onepiece_v2":       {"tcg": "onepiece",          "cardName": "cardName", "cardId": "cardId", "rarity": "rarity"},
    "CL_riftbound":         {"tcg": "riftbound",         "cardName": "title",    "cardId": "cardId", "rarity": "rarity"},
    "CL_haikyuubreak":      {"tcg": "haikyuubreak",      "cardName": "cardName", "cardId": "cardId", "rarity": "voba_detail"},
    "CL_wsblau":            {"tcg": "wsblau",            "cardName": "cardName", "cardId": "cardId", "rarity": "rarity"},
    "CL_lorcana":           {"tcg": "lorcana",           "cardName": "cardName", "cardId": "cardId", "rarity": "rarity"},
}
# ────────────────────────────────────────────────────────────────────────────

TARGET = "All_cards"
target = db[TARGET]


def get(doc, field):
    if not field:
        return None
    v = doc.get(field)
    return v if v not in (None, "") else None


def main():
    deleted = target.delete_many({}).deleted_count
    print(f"Cleared {deleted} existing docs from {TARGET}\n")

    total = 0
    for col, m in GAMES.items():
        src = db[col]
        ops = []
        n = 0
        for doc in src.find({}):
            card_id = get(doc, m["cardId"]) or get(doc, m.get("id_fallback"))
            ops.append(InsertOne({
                "_id":      doc["_id"],            # preserve source _id for join-back
                "tcg":      m["tcg"],
                "cardName": get(doc, m["cardName"]),
                "cardId":   card_id,
                "rarity":   get(doc, m["rarity"]),
            }))
            n += 1
            if len(ops) >= 2000:
                target.bulk_write(ops, ordered=False)
                ops = []
        if ops:
            target.bulk_write(ops, ordered=False)
        print(f"  {col:24s} -> {m['tcg']:18s} {n:6d} docs")
        total += n

    print(f"\nTotal inserted: {total}")
    target.create_index("tcg")
    target.create_index("cardId")
    target.create_index("cardName")
    print("Indexes created: tcg, cardId, cardName")
    print(f"Final {TARGET} count: {target.estimated_document_count()}")


if __name__ == "__main__":
    main()
