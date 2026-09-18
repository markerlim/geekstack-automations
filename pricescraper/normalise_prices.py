#!/usr/bin/env python3
"""Conform the two Union Arena price feeds to one cross-TCG schema.

Sources
-------
  JHS  jihuanshe/union_arena_boosters_all_sets.json   (jihuanshe.com, CNY, current price)
  YYT  yuyuteidb/yuyutei_cardlist_backup_*.json       (yuyu-tei.jp, JPY, price + stock history)

Each feed is rewritten to per-source docs that share ONE generic contract --
the same field names and meanings for every game and every marketplace -- with
a per-source / per-game `ext` bucket for everything that isn't generic:

    {
      # -- identity (generic) --
      "key":         "UA54BT|MST-1-054|SR★★★",   # <set_code>|<card_number>|<rarity>, per game
      "game":        "unionarena",
      "source":      "yyt",              # machine id: jhs | yyt
      "source_name": "YuYu-Tei",         # display

      # -- card (generic: same keys for every TCG) --
      "set_code":    "UA54BT",
      "card_number": "MST-1-054",
      "rarity":      "SR★★★",
      "name":        "ロキシー(パラレル/特別仕様)",

      # -- price (generic, render-ready; values = newest point of price_history) --
      "price":       248000,             # number, MAJOR units (yen / yuan)
      "currency":    "JPY",              # ISO 4217
      "in_stock":    false,              # bool, or null when the source can't say
      "url":         "https://yuyu-tei.jp/...",   # null when the source has none
      "observed_at": 1785162890695,      # ms: timestamp of the newest point

      # -- price history (generic: same shape for every source) --
      # every point records "price"; "stock" is added only by sources that
      # track it (YYT), because a low/zero stock makes that price a weak
      # signal of the real market. The uploader MERGES this across runs.
      "price_history": { "1785162890695": { "price": 248000, "stock": 0 } },

      # -- source / TCG specific --
      "ext": {
        "card_number_raw": "MST-1-054",
        "rarity_raw":      "SR★★★",
        "series_code":     "mst",              # UA-specific, lower-cased
        "yyt_product_id":  "10070",            # yyt-only
        "jhs_code":        "UA54BT/MST",       # jhs-only
        "price_raw":       "24.8w"             # jhs-only, when price couldn't be parsed cleanly
      }
    }

Only SINGLES are kept: JHS sealed-product rows (原盒/卡套/卡垫/收纳盒) and YYT
junk rows (cardId "-") are dropped.

Outputs (into pricescraper/out/):
    jhs_normalised.json  yyt_normalised.json
    jhs_collisions.json  yyt_collisions.json     -- rows that lost the key race
    match_report.json    -- matched / jhs-only / yyt-only, with breakdowns

    python normalise_prices.py                       # default paths
    python normalise_prices.py --jhs X.json --yyt Y.json
    python normalise_prices.py --report              # print report, don't write files
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, "out")

GAME = "unionarena"          # matches the backend `tcg` id (build_all_cards.py)
SOURCE_NAME = {"jhs": "Jihuanshe", "yyt": "YuYu-Tei"}
CURRENCY = {"jhs": "CNY", "yyt": "JPY"}

CANONICAL_JHS = os.path.join(REPO, "jihuanshe", "union_arena_boosters_all_sets.json")
JHS_SNAPSHOT_GLOB = os.path.join(REPO, "jihuanshe", "runs", "union_arena", "*", "snapshot.json")
YYT_GLOB = os.path.join(REPO, "yuyuteidb", "yuyutei_cardlist*.json")
STALE_HOURS = 18            # a source file older than this is a stale-run guard trip


def _newest(pattern: str) -> str | None:
    hits = glob.glob(pattern)
    return max(hits, key=os.path.getmtime) if hits else None


def _resolve_jhs() -> str:
    """Newest per-run snapshot that finished cleanly (its status.json says
    ok:true), else the canonical. The snapshot is preferred because the
    canonical's mtime moves on any merge -- even one that changed nothing --
    while a snapshot is a single run's real output."""
    snaps = sorted(glob.glob(JHS_SNAPSHOT_GLOB), key=os.path.getmtime, reverse=True)
    for snap in snaps:
        status = json.load(open(os.path.join(os.path.dirname(snap), "status.json"))) \
            if os.path.exists(os.path.join(os.path.dirname(snap), "status.json")) else None
        if status is None:
            print(f"  note: {snap} has no status.json (pre-guard run) -- using it")
            return snap
        if status.get("ok"):
            return snap
        print(f"  skip: {os.path.dirname(snap)} run was incomplete "
              f"(sets_missed={status.get('sets_missed')}, tabs_nonzero={status.get('tabs_nonzero')})")
    print("  no clean JHS run snapshot -- falling back to the canonical file")
    return CANONICAL_JHS


def _age_hours(path: str) -> float:
    return (time.time() - os.path.getmtime(path)) / 3600.0

# JHS marks the print FINISH on the rarity: 闪 / (闪) = foil, (平) = non-foil.
# YYT doesn't distinguish finish (its plain grade is the foil), so strip only
# these. Event/promo qualifiers -- (Winner) [Winner] (WCS23) (亚洲优胜) [PR]
# (PR) -- are LEFT ON: they're a distinct printing with its own price and
# collapsing them just collides with the base row in the same feed.
_FINISH_RE = re.compile(r"(（闪）|\(闪\)|（平）|\(平\)|闪)+$")
SEALED_RARITIES = {"原盒", "卡套", "卡垫", "收纳盒"}          # not singles -> drop


def _norm_card_number(cid: str) -> str:
    # Spelling only -- upper-case + drop inner whitespace. Trailing "★" and
    # "-パラレル/特別仕様" markers are LEFT ON: they distinguish a real alt-art
    # printing with its own price, and the identity key is
    # (set_code, card_number, rarity). Over-stripping just manufactures dup keys.
    return re.sub(r"\s+", "", cid).upper()


def _norm_rarity_jhs(rarity: str) -> str | None:
    if rarity in SEALED_RARITIES:
        return None
    base = _FINISH_RE.sub("", rarity).strip()
    return base or rarity


def _norm_rarity_yyt(rarity: str, card_id: str) -> str | None:
    if rarity == "-":
        return "AP" if re.search(r"-AP\d+$", card_id) else None
    return rarity


def _key(set_code: str, card_number: str, rarity: str) -> str:
    # No game prefix: collections are per-game (see the `game` field), so it
    # would be the same dead prefix on every key.
    return f"{set_code}|{card_number}|{rarity}"


_JHS_PRICE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([wW万kK]?)$")
_MULT = {"": 1, "w": 10_000, "万": 10_000, "k": 1_000}


def _parse_jhs_price(s: str | None) -> tuple[float | None, str | None]:
    """JHS prices are strings: '2500', '12.5', '3.89w' (w/万 = x10000), '--'
    (unpriced). Return (amount_in_yuan | None, raw_if_unparsed | None)."""
    raw = (s or "").strip().replace(",", "")
    if not raw or set(raw) <= {"-"}:
        return None, None
    m = _JHS_PRICE_RE.match(raw)
    if not m:
        return None, raw
    val = float(m.group(1)) * _MULT[m.group(2).lower().replace("万", "w") if m.group(2) else ""]
    return (int(val) if val == int(val) else round(val, 2)), None


def _series_code(set_code: str, card_number: str, jhs_code: str | None,
                 anime_code: str | None) -> str | None:
    # Lower-cased to match the backend series id (e.g. app route /unionarena/imc).
    if anime_code:
        return anime_code.lower()
    if jhs_code and "/" in jhs_code:
        return jhs_code.split("/", 1)[1].lower()
    m = re.match(r"^([A-Za-z]+?)-\d", card_number)       # "MST-1-054" -> "mst"
    return m.group(1).lower() if m else None


def normalise_jhs(rows: list[dict], observed_at: int) -> tuple[list[dict], Counter]:
    out, dropped = [], Counter()
    for o in rows:
        rarity = _norm_rarity_jhs(o["rarity"])
        if rarity is None:
            dropped[o["rarity"]] += 1
            continue
        num = _norm_card_number(o["cardId"])
        amount, price_raw = _parse_jhs_price(o.get("price"))
        ext = {
            "card_number_raw": o["cardId"],
            "rarity_raw": o["rarity"],
            "series_code": _series_code(o["booster"], num, o.get("jhs_code"),
                                        o.get("animeCode")),
            "jhs_code": o.get("jhs_code"),
        }
        if price_raw is not None:
            ext["price_raw"] = price_raw
        # JHS is a single untimestamped snapshot; the source file's mtime is
        # the one point we can record. The uploader merges points across runs.
        history = {str(observed_at): {"price": amount}} if amount is not None else {}
        out.append({
            "key": _key(o["booster"], num, rarity),
            "game": GAME,
            "source": "jhs",
            "source_name": SOURCE_NAME["jhs"],
            "set_code": o["booster"],
            "card_number": num,
            "rarity": rarity,
            "name": o.get("name"),
            "price": amount,
            "currency": CURRENCY["jhs"],
            "in_stock": None,                 # JHS listings carry no stock signal
            "url": None,
            "observed_at": observed_at,
            "price_history": history,
            "ext": ext,
        })
    return out, dropped


def normalise_yyt(rows: list[dict]) -> tuple[list[dict], Counter]:
    out, dropped = [], Counter()
    for o in rows:
        if o["cardId"].strip() in ("", "-"):
            dropped["<junk cardId>"] += 1
            continue
        rarity = _norm_rarity_yyt(o["rarity"], o["cardId"])
        if rarity is None:
            dropped[o["rarity"]] += 1
            continue
        num = _norm_card_number(o["cardId"])
        # YYT's feed already carries a timestamped point ({ms: {price, stock}});
        # keep it as-is so the source timestamp is preserved. The uploader
        # merges these across runs into a growing history.
        hist = o.get("price_history") or {}
        ts = max(hist) if hist else None
        latest = hist.get(ts, {}) if ts else {}
        stock = latest.get("stock")
        link = o.get("product_link") or ""
        out.append({
            "key": _key(o["booster"], num, rarity),
            "game": GAME,
            "source": "yyt",
            "source_name": SOURCE_NAME["yyt"],
            "set_code": o["booster"],
            "card_number": num,
            "rarity": rarity,
            "name": o.get("card_name"),
            "price": latest.get("price"),
            "currency": CURRENCY["yyt"],
            "in_stock": (stock > 0) if isinstance(stock, int) else None,
            "url": link or None,
            "observed_at": int(ts) if ts else None,
            "price_history": hist,
            "ext": {
                "card_number_raw": o["cardId"],
                "rarity_raw": o["rarity"],
                "series_code": _series_code(o["booster"], num, None, None),
                "yyt_product_id": link.rstrip("/").rsplit("/", 1)[-1] or None,
            },
        })
    return out, dropped


def dedupe(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep one row per key (first seen). Collisions are genuine source
    ambiguity -- e.g. YYT listing a base UR and a "(WINNERver.)" UR under the
    same cardId+rarity, or JHS a foil and non-foil of one card. Return
    (unique_rows, collided_rows) so a conformed file stays uniquely keyed
    while nothing is silently lost."""
    seen: set[str] = set()
    uniq, collided = [], []
    for r in rows:
        (uniq if r["key"] not in seen else collided).append(r)
        seen.add(r["key"])
    return uniq, collided


def build_report(jhs: list[dict], yyt: list[dict],
                 jhs_drop: Counter, yyt_drop: Counter,
                 jhs_dupes: list[dict], yyt_dupes: list[dict]) -> dict:
    jk = {r["key"] for r in jhs}
    yk = {r["key"] for r in yyt}
    matched = jk & yk
    jhs_only = sorted(jk - yk)
    yyt_only = sorted(yk - jk)

    jmap = {r["key"]: r for r in jhs}
    ymap = {r["key"]: r for r in yyt}

    def by(keys, m):
        return {
            "by_set_code": dict(Counter(m[k]["set_code"] for k in keys).most_common()),
            "by_rarity_raw": dict(Counter(m[k]["ext"]["rarity_raw"] for k in keys).most_common()),
        }

    def no_price(rows):
        return sum(1 for r in rows if r["price"] is None)

    return {
        "jhs_rows_in": len(jhs) + sum(jhs_drop.values()) + len(jhs_dupes),
        "yyt_rows_in": len(yyt) + sum(yyt_drop.values()) + len(yyt_dupes),
        "jhs_dropped_not_single": dict(jhs_drop.most_common()),
        "yyt_dropped_not_single": dict(yyt_drop.most_common()),
        "jhs_normalised": len(jhs),
        "yyt_normalised": len(yyt),
        "jhs_no_price": no_price(jhs),
        "yyt_no_price": no_price(yyt),
        "jhs_collided_rows": [r["key"] for r in jhs_dupes],
        "yyt_collided_rows": [r["key"] for r in yyt_dupes],
        "matched": len(matched),
        "jhs_only_count": len(jhs_only),
        "yyt_only_count": len(yyt_only),
        "jhs_only_breakdown": by(jhs_only, jmap),
        "yyt_only_breakdown": by(yyt_only, ymap),
        "jhs_only_keys": jhs_only,
        "yyt_only_keys": yyt_only,
    }


def _print_report(r: dict) -> None:
    print(f"  JHS  {r['jhs_rows_in']:>6} in -> {r['jhs_normalised']:>6} singles"
          f"   ({sum(r['jhs_dropped_not_single'].values())} dropped, {r['jhs_no_price']} no price)")
    print(f"  YYT  {r['yyt_rows_in']:>6} in -> {r['yyt_normalised']:>6} singles"
          f"   ({sum(r['yyt_dropped_not_single'].values())} dropped, {r['yyt_no_price']} no price)")
    print(f"  matched keys      : {r['matched']}")
    print(f"  JHS-only          : {r['jhs_only_count']}")
    print(f"  YYT-only          : {r['yyt_only_count']}")
    for side in ("jhs_only", "yyt_only"):
        bd = r[f"{side}_breakdown"]["by_rarity_raw"]
        if bd:
            top = ", ".join(f"{k}:{v}" for k, v in list(bd.items())[:8])
            print(f"  {side} by rarity_raw : {top}")
    for side in ("jhs", "yyt"):
        col = r[f"{side}_collided_rows"]
        if col:
            print(f"  {side} rows dropped as dup key: {len(col)}"
                  f" (e.g. {col[:3]})  -- kept first, rest in match_report")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jhs", default=None,
                    help="default: newest jihuanshe/runs/union_arena/*/snapshot.json, "
                         "else the canonical file")
    ap.add_argument("--yyt", default=None, help="default: newest yuyuteidb/yuyutei_cardlist*.json")
    ap.add_argument("--report", action="store_true", help="print the report only; write nothing")
    ap.add_argument("--max-age-hours", type=float, default=STALE_HOURS,
                    help=f"fail if a source file is older than this (default {STALE_HOURS}h); "
                         f"stops normalise/upload from re-stamping stale prices with a fresh "
                         f"timestamp when a scrape was skipped or failed")
    ap.add_argument("--stale-ok", action="store_true",
                    help="bypass the --max-age-hours freshness gate")
    args = ap.parse_args()

    jhs_path = args.jhs or _resolve_jhs()
    yyt_path = args.yyt or _newest(YYT_GLOB)
    if not yyt_path:
        raise SystemExit(f"no YYT backup found matching {YYT_GLOB}")
    if not os.path.exists(jhs_path):
        raise SystemExit(f"JHS source not found: {jhs_path}")

    jhs_age, yyt_age = _age_hours(jhs_path), _age_hours(yyt_path)
    print(f"JHS: {jhs_path}   ({jhs_age:.1f}h old)")
    print(f"YYT: {yyt_path}   ({yyt_age:.1f}h old)\n")
    if not args.stale_ok:
        stale = []
        if jhs_age > args.max_age_hours:
            stale.append(f"JHS ({jhs_age:.1f}h)")
        if yyt_age > args.max_age_hours:
            stale.append(f"YYT ({yyt_age:.1f}h)")
        if stale:
            raise SystemExit(
                f"STALE SOURCE: {', '.join(stale)} older than {args.max_age_hours}h.\n"
                f"Re-scrape first (make jhs-daily / make yyt), or pass --stale-ok to "
                f"normalise this data anyway (it will be uploaded with today's timestamp).")

    with open(jhs_path, encoding="utf-8") as f:
        jhs_raw = json.load(f)
    with open(yyt_path, encoding="utf-8") as f:
        yyt_raw = json.load(f)
    args.jhs = jhs_path

    # JHS carries no per-card timestamp; the source file's mtime is the best
    # "observed at" we have for the whole feed.
    jhs_observed = int(os.path.getmtime(args.jhs) * 1000)

    jhs, jhs_drop = normalise_jhs(jhs_raw, jhs_observed)
    yyt, yyt_drop = normalise_yyt(yyt_raw)
    jhs, jhs_dupes = dedupe(jhs)
    yyt, yyt_dupes = dedupe(yyt)
    report = build_report(jhs, yyt, jhs_drop, yyt_drop, jhs_dupes, yyt_dupes)
    _print_report(report)

    if args.report:
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    for name, data in (("jhs_normalised.json", jhs),
                       ("yyt_normalised.json", yyt),
                       ("jhs_collisions.json", jhs_dupes),
                       ("yyt_collisions.json", yyt_dupes),
                       ("match_report.json", report)):
        p = os.path.join(OUT_DIR, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  wrote {p}")


if __name__ == "__main__":
    main()
