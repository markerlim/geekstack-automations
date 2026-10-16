"""One-off patch for CL_riftbound's RAD (Radiance) set.

  venv/bin/python3 riftbounddb/patch_rad.py           # dry run: prints what would change
  venv/bin/python3 riftbounddb/patch_rad.py --apply   # backs up, then writes

Fixes:
  A. domain on RAD 001-138: every set is numbered in equal blocks of 23 per
     domain (Fury, Calm, Mind, Body, Chaos, Order); 25 cards broke that
     (wrong domain, or none). Checked against VEN (156/156 follow it).
  B. card_type on 9 cards that had none (read off each card image / rules text).
  C. VEN-192/166 duplicates filed under booster UNL and OGN (deleted only if
     identical to the real VEN document).

Every update is compare-and-set: it only applies if the field still holds the
value it had when read. Originals are saved to riftbounddb/backup_*.json first.
Single domain / type values stay plain strings (the live convention).
"""
import json
import os
import re
import sys
from datetime import datetime

import certifi
from bson import json_util
from dotenv import load_dotenv
from pymongo import MongoClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))
uri = (f"mongodb+srv://{os.getenv('MONGO_USER')}:{os.getenv('MONGO_PASSWORD')}"
       f"@{os.getenv('MONGO_CLUSTER')}/{os.getenv('MONGO_DATABASE')}?retryWrites=true&w=majority")
col = MongoClient(uri, tlsCAFile=certifi.where())[os.getenv("MONGO_DATABASE")]["CL_riftbound"]

APPLY = "--apply" in sys.argv
ORDER = ["Fury", "Calm", "Mind", "Body", "Chaos", "Order"]
TYPES = {  # cardUid -> card_type
    "RAD-034/167": "Spell", "RAD-127/167": "Spell", "RAD-006/167": "Spell",
    "RAD-009/167": "Unit",  "RAD-026/167": "Unit",  "RAD-041/167": "Spell",
    "RAD-047/167": "Spell", "RAD-049/167": "Unit",  "RAD-121/167": "Spell",
}


def as_list(v):
    return [] if v is None else (v if isinstance(v, list) else [v])


dom_fix, type_fix = [], []
for d in col.find({"booster": "RAD"}):
    m = re.match(r"^RAD-(\d{3})a?/", d["cardUid"])
    if m and 1 <= int(m.group(1)) <= 138:
        want = ORDER[(int(m.group(1)) - 1) // 23]
        if as_list(d.get("domain")) != [want]:
            dom_fix.append((d, want))
    if d["cardUid"] in TYPES and not d.get("card_type"):
        type_fix.append((d, TYPES[d["cardUid"]]))

strays = list(col.find({"cardUid": "VEN-192/166", "booster": {"$ne": "VEN"}}))
real = col.find_one({"cardUid": "VEN-192/166", "booster": "VEN"})
same = bool(real) and all(
    s.get(k) == real.get(k) for s in strays
    for k in ("title", "cardId", "domain", "card_type", "rarity", "urlimage"))

print(f"A. domain   : {len(dom_fix)} card(s)")
for d, w in dom_fix:
    print(f"     {d['cardUid']:14s} {d['title'][:28]:28s} {d.get('domain')!r} -> {w!r}")
print(f"B. card_type: {len(type_fix)} card(s)")
for d, t in type_fix:
    print(f"     {d['cardUid']:14s} {d['title'][:28]:28s} None -> {t!r}")
print(f"C. strays   : {len(strays)} VEN-192/166 under {[s['booster'] for s in strays]}; "
      f"identical to real VEN doc: {same}")

if not APPLY:
    print("\nDRY RUN -- nothing written. Re-run with --apply to patch.")
    sys.exit(0)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = os.path.join(ROOT, "riftbounddb", f"backup_riftbound_patch_{stamp}.json")
with open(backup, "w", encoding="utf-8") as f:
    json.dump([d for d, _ in dom_fix] + [d for d, _ in type_fix] + strays,
              f, default=json_util.default, ensure_ascii=False, indent=1)
print(f"\nbackup -> {backup}")

nd = nt = nx = 0
for d, w in dom_fix:
    nd += col.update_one({"_id": d["_id"], "domain": d.get("domain")}, {"$set": {"domain": w}}).modified_count
for d, t in type_fix:
    nt += col.update_one({"_id": d["_id"], "card_type": d.get("card_type")}, {"$set": {"card_type": t}}).modified_count
if same:
    for s in strays:
        nx += col.delete_one({"_id": s["_id"]}).deleted_count
print(f"domain fixed {nd}/{len(dom_fix)} | card_type fixed {nt}/{len(type_fix)} | "
      f"stray dupes deleted {nx}/{len(strays)}")
print("Then re-run build_all_cards.py so All_cards drops the deleted duplicates.")
