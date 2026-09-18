#!/usr/bin/env python3
"""Push the normalised price feeds into MongoDB.

    pricescraper/out/jhs_normalised.json  ->  collection  price_jhs
    pricescraper/out/yyt_normalised.json  ->  collection  price_yyt

Each row is upserted on its normalised identity `key`
(`<set_code>|<card_number>|<rarity>`, unique per game): existing docs are refreshed in
place, new ones inserted. `price_history` is MERGED with what's already in the
doc (points accumulate across runs); `price` / `observed_at` / `in_stock` are
recomputed from the newest merged point. `created_at` is stamped once,
`last_updated` every run. A unique index on `key` is ensured on first run.

    python3 pricescraper/upload_normalised.py                 # both
    python3 pricescraper/upload_normalised.py --only yyt
    python3 pricescraper/upload_normalised.py --dry-run        # counts only, no writes
    python3 pricescraper/upload_normalised.py --replace        # wipe collection first
    python3 pricescraper/upload_normalised.py --database geekstack

Use --replace after a schema/key change so rows keyed the old way don't linger.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv
from pymongo import UpdateOne

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from service.mongo_service import MongoService  # noqa: E402

load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")

FEEDS = {
    "jhs": ("jhs_normalised.json", "price_jhs"),
    "yyt": ("yyt_normalised.json", "price_yyt"),
}


def upload(mongo: MongoService, path: str, collection_name: str,
           batch_size: int = 1000, dry_run: bool = False,
           replace: bool = False) -> None:
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)

    bad = [i for i, r in enumerate(rows) if not r.get("key")]
    if bad:
        raise SystemExit(f"{path}: {len(bad)} row(s) with no 'key' (first at {bad[0]})")
    keys = {r["key"] for r in rows}
    print(f"\n{collection_name}: {len(rows)} rows ({len(keys)} unique keys) from {os.path.basename(path)}")
    if len(keys) != len(rows):
        raise SystemExit(f"{path}: keys are not unique -- refusing to upload")

    if dry_run:
        print(f"  --dry-run: nothing written{' (--replace would wipe first)' if replace else ''}")
        return

    collection = mongo._get_collection(collection_name)
    if replace:
        deleted = collection.delete_many({}).deleted_count
        print(f"  --replace: cleared {deleted} existing doc(s)")
    collection.create_index("key", unique=True)

    # Merge price_history across runs so it grows instead of being overwritten.
    # One round trip: pull every existing key's history, then fold this run's
    # point(s) in and recompute the "current" price from the newest point.
    existing = {} if replace else {
        d["key"]: (d.get("price_history") or {})
        for d in collection.find({}, {"key": 1, "price_history": 1})
    }
    grown = 0
    for r in rows:
        merged = {**existing.get(r["key"], {}), **(r.get("price_history") or {})}
        if len(merged) > len(r.get("price_history") or {}):
            grown += 1
        r["price_history"] = merged
        if merged:
            newest = merged[max(merged, key=int)]
            r["price"] = newest.get("price")
            r["observed_at"] = int(max(merged, key=int))
            if "stock" in newest:
                r["in_stock"] = newest["stock"] > 0
    print(f"  price_history: {grown} doc(s) gained a new point")

    now = int(time.time() * 1000)
    ops = [
        UpdateOne(
            {"key": r["key"]},
            {"$set": {**r, "last_updated": now}, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        for r in rows
    ]

    inserted = modified = 0
    for i in range(0, len(ops), batch_size):
        res = collection.bulk_write(ops[i:i + batch_size], ordered=False)
        inserted += res.upserted_count
        modified += res.modified_count
        print(f"  batch {i // batch_size + 1}: {res.upserted_count} inserted, "
              f"{res.modified_count} updated")
    print(f"  done: {inserted} inserted, {modified} updated, "
          f"{len(ops) - inserted - modified} unchanged")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=FEEDS, help="upload just one feed")
    ap.add_argument("--database", default=None, help="override MONGO_DATABASE")
    ap.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    ap.add_argument("--replace", action="store_true",
                    help="delete every doc in the collection before inserting")
    args = ap.parse_args()

    mongo = MongoService(database=args.database)
    feeds = [args.only] if args.only else list(FEEDS)
    for name in feeds:
        fname, coll = FEEDS[name]
        upload(mongo, os.path.join(OUT_DIR, fname), coll,
               dry_run=args.dry_run, replace=args.replace)


if __name__ == "__main__":
    main()
