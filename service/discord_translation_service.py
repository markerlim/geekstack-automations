"""
Union Arena translations taken from the community Discord `card_list` forum,
used before the AI translator.

Workflow (run locally when a new set is out):

    1. Export the set's forum post(s) from Discord to JSON (e.g. with
       DiscordChatExporter) into unionarenadb/discord_exports/, or paste the
       card posts into a .txt file in that folder.
    2. python -m service.discord_translation_service import
       -> merges every file in that folder into unionarenadb/discord_translations.json
    3. The UA scraper (scrapers/unionarena/unionarenascrape.py) looks a card up
       here by `cardId` before calling the AI.

A card post looks like (one Discord message per card):

    Puck
    Yellow Character | EX17BT/REZ-2-001 (U)

    This card is also treated as an Event Card in all places.

    [Activate Main] _In Energy Line_ _Rest_ ...

Parsed to {cardId, booster, cardName, color, category, rarity, effect, traits?, trigger?}.
Text is kept as posted (only whitespace/code-fence cleanup), so it is stored
exactly as the community wrote it.

    python -m service.discord_translation_service import [PATH ...]   # default: the exports folder
    python -m service.discord_translation_service reclean            # re-apply effect cleanup to the cache
    python -m service.discord_translation_service show KMY-1-001
    python -m service.discord_translation_service stats
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from service.mappings.unionarena_mappings import clean_discord_effect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT_DIR = os.path.join(ROOT, "unionarenadb", "discord_exports")
CACHE_PATH = os.path.join(ROOT, "unionarenadb", "discord_translations.json")

# "Yellow Character | EX17BT/REZ-2-001 (U)"  ->  color/category, booster, cardId, rarity
_HEADER_RE = re.compile(
    r"^(?P<kind>[^|\n]*?)\s*\|\s*"
    r"(?P<booster>[A-Z][A-Z0-9]*)/(?P<card>[A-Z0-9]{2,6}(?:-[A-Z0-9]+){1,2})"
    r"(?:\s*\((?P<rarity>[^)]*)\))?\s*$"
)
_TRAITS_RE = re.compile(r"^(?:traits?|features?)\s*[:：]\s*(?P<v>.+)$", re.IGNORECASE)
_TRIGGER_RE = re.compile(r"^trigger\s*[:：]\s*(?P<v>.+)$", re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[a-z]*\s*$", re.IGNORECASE)

# `_x_` tokens the cleanup had no mapping for (filled while parsing; reported by import)
UNMAPPED_TOKENS: set[str] = set()

# Mapping of the first word of the "kind" part when it is a colour.
_COLORS = {"red", "blue", "green", "yellow", "purple", "colorless", "multicolor"}


def _clean_lines(content: str) -> list[str]:
    lines = []
    for ln in content.replace("\r\n", "\n").split("\n"):
        if _FENCE_RE.match(ln.strip()):
            continue
        lines.append(ln.rstrip())
    return lines


def parse_text(content: str) -> list[dict]:
    """Every card found in a block of text (one message, or a pasted dump).

    A card starts at a header line ("<colour> <category> | SET/CARD-1-001 (R)");
    its name is the nearest non-empty line above the header, and its body runs
    to the line before the NEXT card's name. Messages without a header (chat,
    replies, image-only posts) yield nothing."""
    lines = _clean_lines(content)
    # headers are often posted bold/italic/inline-coded: **Blue Character | ... (R)**
    headers = [(i, m) for i, ln in enumerate(lines)
               if (m := _HEADER_RE.match(ln.strip().strip("*_`").strip()))]
    cards = []
    for n, (i, m) in enumerate(headers):
        name_idx = next((j for j in range(i - 1, -1, -1) if lines[j].strip()), None)
        if name_idx is None:
            continue
        end = len(lines)
        if n + 1 < len(headers):
            nxt = headers[n + 1][0]
            nxt_name = next((j for j in range(nxt - 1, i, -1) if lines[j].strip()), nxt)
            end = nxt_name
        body = [ln for ln in lines[i + 1:end]]
        traits = trigger = None
        effect_lines = []
        for ln in body:
            s = ln.strip()
            if (t := _TRAITS_RE.match(s)):
                traits = t.group("v").strip()
            elif (t := _TRIGGER_RE.match(s)):
                trigger = t.group("v").strip()
            else:
                effect_lines.append(s)
        effect_raw = re.sub(r"\n{3,}", "\n\n", "\n".join(effect_lines)).strip()
        effect = clean_discord_effect(effect_raw, unmapped=UNMAPPED_TOKENS)

        kind_words = m.group("kind").split()
        color = kind_words[0] if kind_words and kind_words[0].lower() in _COLORS else None
        category = " ".join(kind_words[1:] if color else kind_words) or None
        card = {
            "cardId": m.group("card"),
            "booster": m.group("booster"),
            "cardName": lines[name_idx].strip().strip("*_ ").strip(),
            "color": color,
            "category": category,
            "rarity": (m.group("rarity") or "").strip() or None,
            "effect": effect or None,
        }
        if effect and effect != effect_raw:
            card["effect_raw"] = effect_raw     # as posted, kept so the cleanup can be re-run
        if traits:
            card["traits"] = clean_discord_effect(traits)
        if trigger:
            card["trigger"] = clean_discord_effect(trigger)
        cards.append(card)
    return cards


def parse_export_file(path: str) -> list[dict]:
    """Cards from one file: DiscordChatExporter JSON (`messages[].content`) or plain text."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    if path.lower().endswith(".json"):
        data = json.loads(raw)
        messages = data.get("messages", []) if isinstance(data, dict) else data
        cards = []
        for msg in messages:
            for card in parse_text(msg.get("content") or ""):
                card["source_message_id"] = str(msg.get("id", ""))
                card["posted_at"] = msg.get("timestamp")
                cards.append(card)
        return cards
    return parse_text(raw)


def _iter_files(paths: list[str]):
    for p in paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if name.lower().endswith((".json", ".txt")):
                    yield os.path.join(p, name)
        elif os.path.exists(p):
            yield p
        else:
            print(f"  skip (not found): {p}")


def load_cache(path: str = CACHE_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_cache: dict | None = None


def lookup(card_id: str) -> dict | None:
    """Discord translation for a site cardId (e.g. 'REZ-2-001'), or None.
    Only entries with both a name and effect text are usable."""
    global _cache
    if _cache is None:
        _cache = load_cache()
    e = _cache.get(card_id)
    return e if e and e.get("cardName") and e.get("effect") else None


def _is_older(a: str | None, b: str | None) -> bool:
    """True if timestamp a is strictly older than b (ISO strings from the export)."""
    if not a or not b:
        return False
    from datetime import datetime
    try:
        return datetime.fromisoformat(a) < datetime.fromisoformat(b)
    except ValueError:
        return False


def import_files(paths: list[str] | None = None, cache_path: str = CACHE_PATH) -> dict:
    """Merge cards from the given files/dirs into the cache. A later post for the
    same cardId replaces an earlier one (posts get edited/corrected)."""
    cache = load_cache(cache_path)
    added = updated = 0
    for path in _iter_files(paths or [EXPORT_DIR]):
        found = parse_export_file(path)
        print(f"  {os.path.basename(path)}: {len(found)} card post(s)")
        for card in found:
            card["imported_at"] = int(time.time())
            prev = cache.get(card["cardId"])
            if prev and _is_older(card.get("posted_at"), prev.get("posted_at")):
                continue                      # keep the more recent post (files are read in name order, not date order)
            if prev:
                updated += 1
            else:
                added += 1
            cache[card["cardId"]] = {**cache.get(card["cardId"], {}), **{k: v for k, v in card.items() if v is not None}}
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(cache.items())), f, ensure_ascii=False, indent=2)
    os.replace(tmp, cache_path)
    print(f"cache: +{added} new, {updated} updated -> {len(cache)} cards in {cache_path}")
    if UNMAPPED_TOKENS:
        print(f"  unmapped _tokens_ (add to DISCORD_UNDERSCORE_MAP): {sorted(UNMAPPED_TOKENS)}")
    return cache


def reclean(cache_path: str = CACHE_PATH) -> None:
    """Re-run the effect cleanup over the whole cache from the stored posted text,
    after editing the maps in service/mappings/unionarena_mappings.py."""
    cache = load_cache(cache_path)
    changed = 0
    for c in cache.values():
        for f in ("traits", "trigger"):
            if c.get(f):
                c[f] = clean_discord_effect(c[f])
        raw = c.get("effect_raw") or c.get("effect")
        if not raw:
            continue
        new = clean_discord_effect(raw, unmapped=UNMAPPED_TOKENS)
        if new != c.get("effect"):
            changed += 1
        c["effect"] = new
        if new != raw:
            c["effect_raw"] = raw
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(cache.items())), f, ensure_ascii=False, indent=2)
    print(f"recleaned {changed} of {len(cache)} cards")
    if UNMAPPED_TOKENS:
        print(f"  unmapped _tokens_: {sorted(UNMAPPED_TOKENS)}")


def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else "import"
    if cmd == "import":
        os.makedirs(EXPORT_DIR, exist_ok=True)
        import_files(argv[1:] or None)
    elif cmd == "reclean":
        reclean()
    elif cmd == "show" and len(argv) > 1:
        print(json.dumps(load_cache().get(argv[1]), ensure_ascii=False, indent=2))
    elif cmd == "stats":
        cache = load_cache()
        by_booster: dict[str, int] = {}
        for c in cache.values():
            by_booster[c.get("booster", "?")] = by_booster.get(c.get("booster", "?"), 0) + 1
        for b, n in sorted(by_booster.items()):
            print(f"  {b}: {n}")
        print(f"total {len(cache)}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
