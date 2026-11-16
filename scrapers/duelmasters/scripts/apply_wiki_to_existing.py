"""
Fill in wiki English data for cards of an already-scraped booster that have no
`wikiurl` (the wiki page didn't exist / wasn't scraped yet when the booster was).

Matching is the same as the live scrape (pipelines/b_scrape_cards.py): the JP name
with its "(DM26EX5 ㊙1/㊙5)" serial stripped, normalised with normalize_jp_name(),
looked up against CL_duelmasters_wiki; a hit is applied with apply_wiki_data().

    python scrapers/duelmasters/scripts/apply_wiki_to_existing.py dm26ex5 --fetch   # pull the fandom set page into the wiki DB first
    python scrapers/duelmasters/scripts/apply_wiki_to_existing.py dm26ex5            # preview (writes nothing)
    python scrapers/duelmasters/scripts/apply_wiki_to_existing.py dm26ex5 --apply    # write (backs the booster up to backup/ first)

Only cards WITHOUT a wikiurl are touched; cards already matched are left alone. Cards
still unmatched afterwards keep their machine-translated text and are listed.
"""
import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from scrapers.duelmasters.pipelines.b_scrape_cards import (  # noqa: E402
    apply_wiki_data, backup_jp_fields, normalize_jp_name)
from scrapers.duelmasters.pipelines.c_scrape_wiki_cards import ensure_wiki_for_booster  # noqa: E402
from service.mongo_service import MongoService  # noqa: E402

_SERIAL_RE = re.compile(r"\s*\([^)]*\)\s*$")     # "(DM26EX5 ㊙1/㊙5)"


def fallback_key(norm):
    """Second-chance key for names the wiki spells differently from takaratomy:
    "...Play's(プレイス)" -> "...ps" (takaratomy writes the P'S prints as "...P’S"), and a
    trailing English note "幻想妖精カチュア(Kachua, Fantasy Faerie)" -> "幻想妖精カチュア"."""
    norm = norm.replace("plays(プレイス)", "ps")
    return re.sub(r"\([^)]*[a-z][^)]*\)$", "", norm)


def build_lookup(wiki_collection):
    """-> (exact, fallback): normalised JP name -> wiki doc, and fallback_key() -> wiki doc."""
    exact, fallback = {}, {}
    for doc in wiki_collection.find({}):
        for wc in doc.get("cards", []):
            if wc.get("name_jp"):
                n = normalize_jp_name(wc["name_jp"])
                exact.setdefault(n, doc)
                fallback.setdefault(fallback_key(n), doc)
    return exact, fallback


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("booster", help="DB booster code, e.g. dm26ex5")
    ap.add_argument("--fetch", action="store_true",
                    help="first scrape the booster's fandom set page into CL_duelmasters_wiki (needs Chrome)")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: preview only)")
    args = ap.parse_args()
    booster = args.booster.strip().lower()

    col_name = os.getenv("C_DUELMASTERS")
    if not col_name:
        sys.exit("C_DUELMASTERS is not set (.env)")
    mongo = MongoService()
    col = mongo._get_collection(col_name)
    wiki = mongo._get_collection("CL_duelmasters_wiki")

    if args.fetch:
        print(f"fetching the fandom set page for {booster} into CL_duelmasters_wiki ...")
        print(ensure_wiki_for_booster(booster, mongo))

    docs = list(col.find({"booster": booster}))
    if not docs:
        sys.exit(f"no cards with booster={booster!r} in {col_name}")
    todo = [d for d in docs if not d.get("wikiurl")]
    lookup, fallback = build_lookup(wiki)
    print(f"{col_name} / {booster}: {len(docs)} cards, {len(todo)} without wikiurl "
          f"(wiki DB holds {len(lookup)} JP names)")

    changes, unmatched = [], []
    for doc in todo:
        jp = _SERIAL_RE.sub("", doc.get("cardNameJP") or doc.get("cardName") or "")
        key = normalize_jp_name(jp)
        wdoc = lookup.get(key) or fallback.get(fallback_key(key))
        if not wdoc:
            unmatched.append(doc)
            continue
        new = json.loads(json.dumps(doc, default=str))      # deep copy (ObjectId -> str, dropped below)
        new.pop("_id", None)
        backup_jp_fields(new)
        if not apply_wiki_data(new, wdoc):
            unmatched.append(doc)
            continue
        new["wikiurl"] = wdoc.get("url", "")
        for aw in new.get("awaken", []) or []:
            akey = normalize_jp_name(aw.get("cardName", ""))
            awdoc = lookup.get(akey) or fallback.get(fallback_key(akey))
            if awdoc:
                aw["wikiurl"] = awdoc.get("url", "")
        diff = {k: v for k, v in new.items() if k != "_id" and v != json.loads(json.dumps(doc.get(k), default=str))}
        changes.append((doc, diff))

    print(f"  matched: {len(changes)}   still unmatched: {len(unmatched)}")
    for doc, diff in changes[:3]:
        print(f"\n  {doc['cardUid']}  {doc.get('cardNameJP') or doc.get('cardName')}")
        for k in ("cardName", "type", "effects", "wikiurl"):
            if k in diff:
                print(f"    {k}: {str(doc.get(k))[:70]!r} -> {str(diff[k])[:70]!r}")
    if unmatched:
        print("\n  unmatched (no wiki page found; keep machine translation):")
        for d in unmatched:
            print(f"    {d['cardUid']}  {d.get('cardNameJP') or d.get('cardName')}")

    if not changes:
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
        col_name, [{"field_name": "_id", "field_value": d["_id"], "update_data": diff} for d, diff in changes])
    if not result.get("success") or result.get("modified") != len(changes):
        sys.exit(f"!! expected {len(changes)} modified, got {result}")
    print(f"updated {result['modified']} cards")


if __name__ == "__main__":
    main()
