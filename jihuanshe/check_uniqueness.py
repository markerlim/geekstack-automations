#!/usr/bin/env python3
"""Confirm every card object in a scraped JSON list is unique.

Two notions of "duplicate" are checked:

  1. exact      -- two objects with every field identical (pure redundant rows).
  2. identity   -- two objects sharing the card key (jhs_code, cardId, rarity)
                   but differing somewhere (usually price / name). These are the
                   ones that corrupt a merge: same card, conflicting data.

Exit code is non-zero if any duplicate of either kind is found, so this can
gate a pipeline step.

    python check_uniqueness.py                                  # default file
    python check_uniqueness.py union_arena_fresh_20260830.json  # another file
    python check_uniqueness.py --key jhs_code cardId rarity     # custom identity
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

DEFAULT_FILE = "union_arena_boosters_all_sets.json"
DEFAULT_KEY = ("jhs_code", "cardId", "rarity")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", default=DEFAULT_FILE)
    ap.add_argument("--key", nargs="+", default=list(DEFAULT_KEY),
                    help=f"fields forming the card identity (default: {' '.join(DEFAULT_KEY)})")
    ap.add_argument("--show", type=int, default=20,
                    help="max example groups to print per section (default 20)")
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        sys.exit(f"{args.file}: expected a JSON list, got {type(data).__name__}")

    print(f"file            : {args.file}")
    print(f"objects         : {len(data)}")
    print(f"identity key    : ({', '.join(args.key)})")

    # ---- key presence sanity --------------------------------------------
    missing_key = [i for i, o in enumerate(data)
                   if not all(k in o for k in args.key)]
    if missing_key:
        print(f"\n!! {len(missing_key)} object(s) missing an identity field "
              f"(first indices: {missing_key[:10]})")

    # ---- 1. exact-duplicate objects -----------------------------------------
    canon = [json.dumps(o, sort_keys=True, ensure_ascii=False) for o in data]
    exact_counts = Counter(canon)
    exact_dupes = {s: n for s, n in exact_counts.items() if n > 1}
    exact_extra = sum(n - 1 for n in exact_dupes.values())

    print(f"\n[1] exact-duplicate objects")
    print(f"    distinct objects        : {len(exact_counts)}")
    print(f"    duplicated groups       : {len(exact_dupes)}")
    print(f"    redundant rows to drop  : {exact_extra}")
    for s, n in list(sorted(exact_dupes.items(), key=lambda kv: -kv[1]))[:args.show]:
        print(f"      x{n}  {s}")

    # ---- 2. identity collisions (same card, different data) ---------------
    by_key: dict[tuple, list[int]] = defaultdict(list)
    for i, o in enumerate(data):
        by_key[tuple(o.get(k) for k in args.key)].append(i)

    id_dupes = {k: idxs for k, idxs in by_key.items() if len(idxs) > 1}
    # split: identity dupes that are ONLY exact repeats vs. genuine conflicts
    conflicts = {}
    for k, idxs in id_dupes.items():
        variants = {canon[i] for i in idxs}
        if len(variants) > 1:
            conflicts[k] = idxs

    print(f"\n[2] identity collisions ({', '.join(args.key)})")
    print(f"    distinct card identities : {len(by_key)}")
    print(f"    identities with >1 row   : {len(id_dupes)}")
    print(f"    ...of which are conflicts : {len(conflicts)}  (differ beyond the key)")
    for k, idxs in list(conflicts.items())[:args.show]:
        print(f"      {k}")
        for i in idxs:
            print(f"        [{i}] {json.dumps(data[i], sort_keys=True, ensure_ascii=False)}")

    # ---- verdict ----------------------------------------------------------
    unique = not exact_dupes and not id_dupes
    print()
    if unique:
        print("OK: every object is unique on both counts.")
    else:
        print("NOT UNIQUE: "
              f"{exact_extra} redundant row(s), "
              f"{len(id_dupes) - len(conflicts)} pure-repeat identit(ies), "
              f"{len(conflicts)} conflicting identit(ies).")
    sys.exit(0 if unique else 1)


if __name__ == "__main__":
    main()
