"""
Update a booster's cards in the Union Arena collection with the community
(Discord card_list) translations: cardName, effect and traits only.

The flow for a new set:
    1. scrape the set          -> cards land with a rough AI translation
    2. a few days later, export the Discord posts and import them
       (service/discord_translation_service.py, `make ua-discord-export`)
    3. this script rewrites cardName / effect / traits for that booster

Safety:
    - scoped to ONE booster (`--booster EX17BT`); other boosters sharing a cardId
      (e.g. UAPR promo ALT prints) are never touched
    - dry run unless --apply; --apply first writes the booster's docs to backup/
    - updates by document _id, and only the fields that actually differ
    - an empty Discord effect/traits never overwrites what is in the DB

    python scrapers/unionarena/apply_discord_translations.py --booster EX17BT           # preview
    python scrapers/unionarena/apply_discord_translations.py --booster EX17BT --apply
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from service.discord_translation_service import load_cache  # noqa: E402
from service.mongo_service import MongoService  # noqa: E402

FIELDS = ("cardName", "effect", "traits")   # the only fields Discord may edit


def _norm(v):
    return " ".join(str(v).split()) if v is not None else None


def plan_updates(docs, cache):
    """-> (updates, unchanged, no_discord). updates = [(doc, {field: new})]."""
    updates, unchanged, no_discord = [], [], []
    for doc in docs:
        entry = cache.get(doc.get("cardId"))
        if not entry:
            no_discord.append(doc)
            continue
        change = {}
        for f in FIELDS:
            new = entry.get(f)
            if not new or new == "-":
                continue                      # Discord has nothing for this field: keep the DB value
            if _norm(new) != _norm(doc.get(f)):
                change[f] = new
        (updates if change else unchanged).append((doc, change) if change else doc)
    return updates, unchanged, no_discord


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--booster", required=True, help="booster code as stored in the DB, e.g. EX17BT")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: preview only)")
    ap.add_argument("--show", type=int, default=3, help="example diffs to print (default 3)")
    args = ap.parse_args()
    booster = args.booster.strip()

    col_name = os.getenv("C_UNIONARENA")
    if not col_name:
        sys.exit("C_UNIONARENA is not set (.env)")
    mongo = MongoService()
    col = mongo._get_collection(col_name)

    cache = load_cache()
    in_cache = {k: v for k, v in cache.items() if (v.get("booster") or "").upper() == booster.upper()}
    docs = list(col.find({"booster": booster}))
    if not docs:
        sys.exit(f"no cards with booster={booster!r} in {col_name}")
    if not in_cache:
        sys.exit(f"no Discord translations for {booster} in the cache -- run `make ua-discord-export` first")

    updates, unchanged, no_discord = plan_updates(docs, cache)
    db_ids = {d["cardId"] for d in docs}
    discord_only = sorted(set(in_cache) - db_ids)

    print(f"{col_name} / {booster}: {len(docs)} cards in DB, {len(in_cache)} Discord translations")
    print(f"  to update : {len(updates)}   already matching: {len(unchanged)}   "
          f"no Discord post: {len(no_discord)}   Discord-only (not in DB): {len(discord_only)}")
    if no_discord:
        print("  no Discord post yet:", ", ".join(sorted({d['cardId'] for d in no_discord})))
    if discord_only:
        print("  in Discord but not in DB:", ", ".join(discord_only))
    for doc, change in updates[: args.show]:
        print(f"\n  {doc['cardUid']}")
        for f, new in change.items():
            print(f"    {f}\n      DB     : {doc.get(f)!r}\n      Discord: {new!r}")

    if not updates:
        print("\nnothing to update")
        return
    if not args.apply:
        print("\npreview only -- re-run with --apply to write")
        return

    os.makedirs(os.path.join(ROOT, "backup"), exist_ok=True)
    bk = os.path.join(ROOT, "backup", f"{col_name}_{booster}_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(bk, "w", encoding="utf-8") as f:
        json.dump([{**d, "_id": str(d["_id"])} for d in docs], f, ensure_ascii=False, indent=1)
    print(f"\nbackup of {len(docs)} {booster} docs -> {bk}")

    result = mongo.batch_update_by_field(
        col_name,
        [{"field_name": "_id", "field_value": d["_id"], "update_data": change} for d, change in updates],
    )
    if not result.get("success") or result.get("modified") != len(updates):
        sys.exit(f"!! expected {len(updates)} modified, got {result}")
    print(f"updated {result['modified']} cards")


if __name__ == "__main__":
    main()
