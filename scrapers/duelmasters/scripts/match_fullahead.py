"""
Scrape a Duel Masters booster from fullahead-dm.com, match each listing to our
CL_duelmasters cards, and write price rows in the cross-TCG schema used by
pricescraper/ (see pricescraper/normalise_prices.py).

Usage:
    python match_fullahead.py DM26-EX4                  # DB cards from MongoDB
    python match_fullahead.py DM26-EX4 --db-json datacleaning/dmfull_cleaned.json
    python match_fullahead.py dm26ex1 --db-json datacleaning/dmfull_cleaned.json --no-write

Outputs (pricescraper/out/):
    fau_normalised.json     price rows, one per shop listing (upload with
                            `pricescraper/upload_normalised.py --only fau`)
    fau_match_report.json   tier counts, unmatched listings, unmatched DB cards,
                            ambiguous / fuzzy / rarity-mismatch items to review

Row identity key is  <set_code>|<card_number>|<rarity>  with set_code = DB booster
(`dm26ex4`) and card_number = the SHOP's number (秘2, 超G5, 14...), which is unique
per listing. The matched DB card is carried in ext.cardUid (null when unmatched).

Matching tiers (highest confidence first), all within one booster:
    1 name_rarity   normalised JP name + rarity equal, one DB card
    2 name          unique normalised JP name (rarity differs -> flagged)
    3 variant       several same-name DB cards, resolved by rarity / secret-vs-normal uid
    4 fuzzy         difflib >= FUZZY_CUTOFF, unique best (always review)
    -  ambiguous / unmatched   left for a human, never guessed
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scrapers.duelmasters.lib.fullahead_scraper import (  # noqa: E402
    normalize_booster_code, booster_to_shop_slug, scrape_booster,
)
from scrapers.duelmasters.pipelines.b_scrape_cards import normalize_jp_name  # noqa: E402

OUT_DIR = REPO / "pricescraper" / "out"
GAME = "duelmasters"
SOURCE = "fau"
SOURCE_NAME = "Full Ahead"
CURRENCY = "JPY"
FUZZY_CUTOFF = 0.92

# "(DM24EX4 PR27/PR60)" / "(DM26EX4 49/99)" serial appended by takaratomy
_SERIAL_RE = re.compile(r"\s*\([^)]*\)\s*$")
_SPLIT_RE = re.compile(r"[／/]")
# boosters the shop slug scheme (dm26-ex04) covers; group 1 = set number
BOOSTER_RE = re.compile(r"^dm(\d+)(?:ex|rp|sd|bd|sp)\d+$")


def clean_db_name(name: str | None) -> str:
    return normalize_jp_name(_SERIAL_RE.sub("", name or ""))


def load_db_cards(booster: str, db_json: str | None) -> list[dict]:
    if db_json:
        with open(db_json, encoding="utf-8") as f:
            return [c for c in json.load(f) if c.get("booster") == booster]
    from service.mongo_service import MongoService
    from dotenv import load_dotenv
    load_dotenv()
    collection = os.getenv("C_DUELMASTERS")
    if not collection:
        raise SystemExit("C_DUELMASTERS env var not set (or pass --db-json)")
    return MongoService().find_all_by_field(collection, "booster", booster)


def build_index(cards: list[dict]) -> dict[str, list[dict]]:
    """normalised JP name -> [{cardUid, rarity, form}] covering main, twinpact
    second form and awaken forms."""
    idx: dict[str, list[dict]] = defaultdict(list)

    def add(name, card, form):
        key = clean_db_name(name)
        if key:
            idx[key].append({"cardUid": card["cardUid"], "rarity": card.get("rarity"),
                             "form": form})

    for c in cards:
        add(c.get("cardNameJP"), c, "main")
        add(c.get("cardName2JP"), c, "form2")
        for aw in c.get("awaken") or []:
            add(aw.get("cardNameJP"), c, "awaken")
    return idx


def name_candidates(shop_name: str) -> list[str]:
    """Normalised names to try, most specific first: the whole title, each half of
    a 'A／B' pair, then each of those minus a leading '切札混成 '-style word."""
    out: list[str] = []

    def push(s):
        n = normalize_jp_name(s)
        if n and n not in out:
            out.append(n)

    push(shop_name)
    parts = [p.strip() for p in _SPLIT_RE.split(shop_name) if p.strip()]
    for p in parts:
        push(p)
    for p in [shop_name, *parts]:
        words = p.split()
        if len(words) > 1:
            push(" ".join(words[1:]))
    return out


def is_secret_uid(uid: str) -> bool:
    """dm26ex4-TR05 style uid (letters after the dash) vs plain numeric dm26ex4-049."""
    tail = uid.split("-", 1)[-1]
    return bool(re.match(r"^[A-Za-z]", tail))


_UID_SIG_RE = re.compile(r"^(SEC)?([A-Za-z]*?)0*(\d+)(CHO)?$")
_SHOP_SIG_RE = re.compile(r"^(秘)?([A-Za-z]*?)0*(\d+)(超)?$")


def uid_signature(uid: str):
    """dm26ex1-SECN001CHO -> (True, 'N', 1, True); dm26ex1-014 -> (False, '', 14, False)."""
    m = _UID_SIG_RE.match(uid.split("-", 1)[-1])
    return (bool(m.group(1)), m.group(2).upper(), int(m.group(3)), bool(m.group(4))) if m else None


def shop_signature(shop_no: str | None):
    """秘N1超 -> (True, 'N', 1, True); 14 -> (False, '', 14, False)."""
    m = _SHOP_SIG_RE.match(shop_no or "")
    return (bool(m.group(1)), m.group(2).upper(), int(m.group(3)), bool(m.group(4))) if m else None


def match_listing(item: dict, idx: dict[str, list[dict]]) -> dict:
    cands = name_candidates(item["name"])
    rarity = item.get("rarity")
    variant = item.get("variant") or ""

    for key in cands:
        hits = idx.get(key)
        if not hits:
            continue
        uids = sorted({h["cardUid"] for h in hits})
        if len(uids) == 1:
            same_rarity = any(h["rarity"] == rarity for h in hits)
            return {"cardUid": uids[0], "tier": "name_rarity" if same_rarity else "name",
                    "flags": [] if same_rarity else ["rarity_mismatch"]}
        # several DB cards share the name: narrow by rarity, then secret-vs-normal
        by_rarity = sorted({h["cardUid"] for h in hits if h["rarity"] == rarity})
        pool = by_rarity or uids
        sig = shop_signature(item.get("shop_no"))
        if len(pool) > 1 and sig:
            sig_pool = [u for u in pool if uid_signature(u) == sig]
            pool = sig_pool or pool
        if len(pool) > 1 and "シークレット" in variant:
            pool = [u for u in pool if is_secret_uid(u)] or pool
        elif len(pool) > 1:
            pool = [u for u in pool if not is_secret_uid(u)] or pool
        if len(pool) == 1:
            return {"cardUid": pool[0], "tier": "variant",
                    "flags": [] if by_rarity else ["rarity_mismatch"]}
        return {"cardUid": None, "tier": "ambiguous", "flags": [], "candidates": pool}

    # fuzzy fallback on the full cleaned name
    full = cands[0] if cands else ""
    close = difflib.get_close_matches(full, list(idx), n=2, cutoff=FUZZY_CUTOFF)
    if close:
        best_uids = sorted({h["cardUid"] for h in idx[close[0]]})
        second_ok = len(close) > 1 and difflib.SequenceMatcher(None, full, close[1]).ratio() >= \
            difflib.SequenceMatcher(None, full, close[0]).ratio() - 0.01
        if len(best_uids) == 1 and not second_ok:
            return {"cardUid": best_uids[0], "tier": "fuzzy", "flags": ["review"],
                    "fuzzy_to": close[0]}
    return {"cardUid": None, "tier": "unmatched", "flags": []}


def to_row(item: dict, booster: str, result: dict, observed_at: int, seen_keys: set) -> dict:
    number = item.get("shop_no") or item["product_id"]
    rarity = item.get("rarity") or ""
    key = f"{booster}|{number}|{rarity}"
    if key in seen_keys:  # shop reused a number+rarity; keep both rows distinct
        key = f"{key}#{item['product_id']}"
    seen_keys.add(key)

    point = {"price": item["price"]}
    if item["stock"] is not None:
        point["stock"] = item["stock"]
    return {
        "key": key,
        "game": GAME,
        "source": SOURCE,
        "source_name": SOURCE_NAME,
        "set_code": booster,
        "card_number": number,
        "rarity": rarity,
        "name": item["name"],
        "price": item["price"],
        "currency": CURRENCY,
        "in_stock": (item["stock"] > 0) if item["stock"] is not None else None,
        "url": item["url"],
        "observed_at": observed_at,
        "price_history": {str(observed_at): point} if item["price"] is not None else {},
        "ext": {
            "card_number_raw": item.get("shop_no"),
            "rarity_raw": item.get("rarity"),
            "cardUid": result["cardUid"],
            "match_tier": result["tier"],
            "match_flags": result["flags"],
            "candidates": result.get("candidates"),  # ambiguous only: same-name DB cards
            "variant": item.get("variant"),
            "shop_set": item.get("shop_set"),
            "fau_product_id": item["product_id"],
            "image": item.get("image"),
            "title_raw": item["title"],
        },
    }


def process_booster(booster: str, cards: list[dict], slug: str | None = None,
                    delay: float = 1.0) -> tuple[list[dict], dict]:
    """Scrape + match one booster. Returns (price rows, report)."""
    slug = slug or booster_to_shop_slug(booster)
    print(f"[{booster}] shop slug={slug}")
    items = scrape_booster(booster, slug=slug, delay=delay)
    print(f"[{booster}] scraped {len(items)} listings, {len(cards)} DB cards")
    idx = build_index(cards)

    observed_at = int(time.time() * 1000)
    seen_keys: set = set()
    rows, results = [], []
    for it in items:
        res = match_listing(it, idx)
        results.append((it, res))
        rows.append(to_row(it, booster, res, observed_at, seen_keys))

    tiers = Counter(r["tier"] for _, r in results)
    matched_uids = {r["cardUid"] for _, r in results if r["cardUid"]}
    all_uids = {c["cardUid"] for c in cards}
    shared = Counter(r["cardUid"] for _, r in results if r["cardUid"])

    def brief(it, r):
        return {"shop_no": it.get("shop_no"), "rarity": it.get("rarity"), "name": it["name"],
                "variant": it.get("variant"), "price": it["price"], **{
                    k: v for k, v in r.items() if k in ("cardUid", "candidates", "fuzzy_to")}}

    report = {
        "booster": booster,
        "scraped": len(items),
        "db_cards": len(cards),
        "tiers": dict(tiers),
        "no_price": sum(1 for it in items if it["price"] is None),
        "unmatched": [brief(i, r) for i, r in results if r["tier"] == "unmatched"],
        "ambiguous": [brief(i, r) for i, r in results if r["tier"] == "ambiguous"],
        "fuzzy": [brief(i, r) for i, r in results if r["tier"] == "fuzzy"],
        "rarity_mismatch": [brief(i, r) for i, r in results if "rarity_mismatch" in r["flags"]],
        "db_cards_without_listing": sorted(all_uids - matched_uids),
        "db_cards_with_multiple_listings": {u: n for u, n in shared.items() if n > 1},
    }
    matched = sum(tiers[t] for t in ("name_rarity", "name", "variant"))
    print(f"[{booster}] matched {matched}/{len(items)}  tiers={dict(tiers)}  "
          f"ambiguous={len(report['ambiguous'])} fuzzy={len(report['fuzzy'])} "
          f"db_without_listing={len(report['db_cards_without_listing'])}")
    return rows, report


def list_db_boosters(db_cards_by_booster: dict | None, mongo_collection: str | None) -> list[str]:
    if db_cards_by_booster is not None:
        found = set(db_cards_by_booster)
    else:
        from service.mongo_service import MongoService
        found = set(MongoService().get_unique_values(mongo_collection, "booster") or [])
    return sorted(b for b in found if b and BOOSTER_RE.match(b))


def write_outputs(rows: list[dict], reports: list[dict], boosters: list[str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows_path = OUT_DIR / "fau_normalised.json"
    done = set(boosters)
    existing = []
    if rows_path.exists():  # keep other boosters' rows already in the feed
        with open(rows_path, encoding="utf-8") as f:
            existing = [r for r in json.load(f) if r["set_code"] not in done]
    with open(rows_path, "w", encoding="utf-8") as f:
        json.dump(existing + rows, f, ensure_ascii=False, indent=2)
    with open(OUT_DIR / "fau_match_report.json", "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)
    print(f"\nwrote {rows_path} ({len(existing) + len(rows)} rows) and fau_match_report.json "
          f"({len(reports)} boosters)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("booster", nargs="?", help="DM26-EX4 / dm26ex4 / 26ex4 (omit with --all)")
    ap.add_argument("--all", action="store_true",
                    help="every booster in the DB that has a fullahead page")
    ap.add_argument("--min-set", type=int, default=0,
                    help="with --all: skip boosters older than dm<N> (e.g. 22)")
    ap.add_argument("--db-json", help="local CL_duelmasters export instead of MongoDB")
    ap.add_argument("--slug", help="override fullahead brand slug (single booster only)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between shop page fetches")
    ap.add_argument("--no-write", action="store_true", help="print the report, write no files")
    args = ap.parse_args()
    if not args.all and not args.booster:
        ap.error("give a booster code or --all")

    from dotenv import load_dotenv
    load_dotenv()
    collection = os.getenv("C_DUELMASTERS")

    by_booster = None
    if args.db_json:
        with open(args.db_json, encoding="utf-8") as f:
            by_booster = defaultdict(list)
            for c in json.load(f):
                by_booster[c.get("booster")].append(c)
    if not by_booster and not collection:
        raise SystemExit("C_DUELMASTERS env var not set (or pass --db-json)")

    if args.all:
        boosters = [b for b in list_db_boosters(by_booster, collection)
                    if int(BOOSTER_RE.match(b).group(1)) >= args.min_set]
        print(f"{len(boosters)} DB boosters to try")
    else:
        boosters = [normalize_booster_code(args.booster)]

    all_rows, reports, failed, no_shop = [], [], [], []
    for n, booster in enumerate(boosters, 1):
        print(f"\n=== {n}/{len(boosters)} {booster} ===")
        try:
            cards = (by_booster.get(booster, []) if by_booster is not None
                     else load_db_cards(booster, None))
            rows, report = process_booster(booster, cards, slug=args.slug, delay=args.delay)
        except Exception as e:  # one bad set must not kill the whole run
            print(f"[{booster}] FAILED: {e}")
            failed.append(booster)
            continue
        if not rows:
            no_shop.append(booster)
            continue
        all_rows += rows
        reports.append(report)

    scraped = sum(r["scraped"] for r in reports)
    matched = sum(sum(r["tiers"].get(t, 0) for t in ("name_rarity", "name", "variant"))
                  for r in reports)
    print(f"\n==== {len(reports)} boosters with listings, {scraped} listings, {matched} matched ====")
    print(f"no shop page / empty: {len(no_shop)} {no_shop}")
    print(f"failed: {len(failed)} {failed}")

    if not args.no_write and reports:
        write_outputs(all_rows, reports, [r["booster"] for r in reports])
    if failed and not reports:
        sys.exit(1)


if __name__ == "__main__":
    main()
