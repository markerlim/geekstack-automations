"""
UI-scraper for Jihuanshe's Union Arena (携战之境UA) card browse grid.

Does NOT touch the network layer at all — it drives the app through adb
(uiautomator dumps of the on-screen accessibility tree + swipe gestures),
reading the same publicly-visible name/code/rarity/price data a human
browsing the app would see. No login, no proxy, no APK teardown.

Requires: an Android emulator/device already running the Jihuanshe app,
reachable via `adb`, with the app already navigated to the target browse
tab (携战之境UA -> 补充包/简中版/构筑/现场活动).

Usage:
    python3 scrape_union_arena.py [--max-idle-swipes 5] [--out cards.json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict


NS = "com.jihuanshe:id/"


@dataclass
class CardRow:
    name: str
    number: str
    rarity: str
    price: str  # numeric string, e.g. "0.5" -- "起" (starting-from) prefix implied


def adb_dump() -> str:
    out = subprocess.run(
        ["adb", "exec-out", "uiautomator", "dump", "/dev/tty"],
        capture_output=True, timeout=15,
    ).stdout.decode("utf-8", errors="replace")
    end = out.rfind("</hierarchy>")
    if end == -1:
        raise RuntimeError("uiautomator dump did not return valid XML")
    return out[: end + len("</hierarchy>")]


def parse_cards(xml_text: str) -> list[CardRow]:
    root = ET.fromstring(xml_text)
    rows: list[CardRow] = []
    pending: dict[str, str] = {}
    for node in root.iter("node"):
        rid = node.get("resource-id", "")
        text = node.get("text", "")
        if not rid.startswith(NS) or not text:
            continue
        field = rid[len(NS):]
        if field == "nameTv":
            if "name" in pending:
                # a new card started before the previous one got a price;
                # flush whatever we have (shouldn't normally happen)
                pending = {}
            pending["name"] = text
        elif field == "numberTv" and "name" in pending:
            pending["number"] = text
        elif field == "rarityTv" and "name" in pending:
            pending["rarity"] = text
        elif field == "priceTv" and "name" in pending:
            pending["price"] = text
            rows.append(CardRow(
                name=pending.get("name", ""),
                number=pending.get("number", ""),
                rarity=pending.get("rarity", ""),
                price=pending.get("price", ""),
            ))
            pending = {}
    return rows


# Scroll geometry. The step is deliberately small (~1/4 screen) so that
# every list row shows up in at least two consecutive uiautomator dumps --
# a bigger jump can flick a whole row past between dumps and it's never seen.
# Duplicate rows are free: dedup is keyed on (number, rarity).
_SCROLL_TOP_Y = 1600
_SCROLL_STEP = 520          # px travelled per full swipe_up()
_SETTLE_S = 0.9


def swipe_up(frac: float = 1.0):
    # swipe within the upper 2/3 of the screen to avoid the bottom nav bar
    # and any login-promo banner docked at the bottom.
    dy = int(_SCROLL_STEP * frac)
    subprocess.run(
        ["adb", "shell", "input", "swipe", "540", str(_SCROLL_TOP_Y),
         "540", str(_SCROLL_TOP_Y - dy), "450"],
        check=True,
    )


def swipe_down(frac: float = 0.6):
    dy = int(_SCROLL_STEP * frac)
    subprocess.run(
        ["adb", "shell", "input", "swipe", "540", str(_SCROLL_TOP_Y - _SCROLL_STEP),
         "540", str(_SCROLL_TOP_Y - _SCROLL_STEP + dy), "450"],
        check=True,
    )


def scrape(max_idle_swipes: int = 8, max_total_swipes: int = 800) -> list[CardRow]:
    seen: dict[tuple[str, str], CardRow] = {}
    idle_streak = 0
    stuck_streak = 0
    swipes = 0
    prev_keys: set[tuple[str, str]] = set()

    while idle_streak < max_idle_swipes and swipes < max_total_swipes:
        xml_text = adb_dump()
        rows = parse_cards(xml_text)
        cur_keys = {(r.number, r.rarity) for r in rows}

        new_count = 0
        for row in rows:
            key = (row.number, row.rarity)
            if key not in seen:
                seen[key] = row
                new_count += 1

        # Overlap guard: if this dump shares no row with the previous one,
        # the last swipe jumped a gap. Back up and re-read instead of
        # marching on past the missed rows.
        jumped = bool(prev_keys) and bool(cur_keys) and prev_keys.isdisjoint(cur_keys)
        if jumped and stuck_streak < 3:
            stuck_streak += 1
            print(f"swipe {swipes}: ⚠ no overlap with previous view, backing up ({stuck_streak}/3)", flush=True)
            swipe_down(0.7)
            swipes += 1
            time.sleep(_SETTLE_S)
            prev_keys = cur_keys
            continue
        stuck_streak = 0

        if new_count == 0:
            idle_streak += 1
        else:
            idle_streak = 0

        print(f"swipe {swipes}: +{new_count} new, {len(seen)} total, idle_streak={idle_streak}", flush=True)

        prev_keys = cur_keys
        swipe_up()
        swipes += 1
        time.sleep(_SETTLE_S)

    return list(seen.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-idle-swipes", type=int, default=8,
                     help="stop after this many consecutive swipes with no new cards")
    ap.add_argument("--out", default="union_arena_cards.json")
    args = ap.parse_args()

    rows = scrape(max_idle_swipes=args.max_idle_swipes)
    print(f"collected {len(rows)} unique card rows")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in rows], f, ensure_ascii=False, indent=2)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
