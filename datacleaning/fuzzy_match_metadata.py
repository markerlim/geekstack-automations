"""
Metadata-aware fuzzy match between unmatched wiki ↔ unmatched DM cards.

The name-only fuzzy matcher (fuzzy_match_unmatched.py) misses cases where
the JP names differ a lot but the cards are obviously the same — different
romanization, missing/extra long-vowel marks, character-level typos that
push similarity below 0.7. By REQUIRING same card_type AND civilization
overlap as a hard filter, we can lower the name similarity threshold and
still get high-confidence matches.

Matching rule:
  1. wiki card_type == DM type (case-insensitive)
  2. wiki civilization ∈ DM civilization[] (multi-civ DM cards OK)
  3. name similarity ≥ --min-ratio (default 0.4 — looser than name-only)

Run after clean_duelmasters_with_wiki.py:
    python datacleaning/fuzzy_match_metadata.py [--min-ratio 0.4] [--top 30]
"""
import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).parent
DM_CLEANED = HERE / "dmfull_cleaned.json"
WIKI_CLEANED = HERE / "dmwikifull_cleaned.json"
WIKI_ORIG = HERE / "dmwikifull25MAY2026.json"
UNMATCHED_CARDS = HERE / "unmatched_cards.json"
UNMATCHED_WIKI = HERE / "unmatched_wiki.json"
OUT = HERE / "fuzzy_matches_metadata.json"

SERIAL_RE = re.compile(r'\s*\([^)]*\)\s*$')


def normalize(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKC', s).replace('〜', '~')
    s = (s.replace('“', '"').replace('”', '"')
           .replace('‘', "'").replace('’', "'"))
    s = s.replace('・', '.').replace('·', '.').replace('•', '.')
    return s.replace(' ', '').replace('　', '').casefold()


def strip_serial(s):
    return SERIAL_RE.sub('', s or '').strip()


def low(s):
    return (s or '').strip().lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-ratio', type=float, default=0.4,
                    help='Minimum name similarity to include (default 0.4 — '
                         'lower than name-only fuzzy because type+civ already filter)')
    ap.add_argument('--top', type=int, default=30)
    args = ap.parse_args()

    dm_cards = json.loads(DM_CLEANED.read_text())
    wiki_path = WIKI_CLEANED if WIKI_CLEANED.exists() else WIKI_ORIG
    wiki = json.loads(wiki_path.read_text())
    unmatched_dm = json.loads(UNMATCHED_CARDS.read_text())['main']
    unmatched_wiki = json.loads(UNMATCHED_WIKI.read_text())

    print(f"📖 {len(unmatched_dm):,} unmatched DM cards × {len(unmatched_wiki):,} unmatched wiki docs")
    print(f"   wiki source: {wiki_path.name}\n")

    # Build the DM pool: only unmatched cards, with metadata pre-extracted
    unmatched_uids = {c['cardUid'] for c in unmatched_dm}
    dm_pool = []
    for c in dm_cards:
        if c.get('cardUid') not in unmatched_uids:
            continue
        jp_key = normalize(strip_serial(c.get('cardNameJP', '')))
        if not jp_key:
            continue
        dm_pool.append({
            'card': c,
            'jp_key': jp_key,
            'type': low(c.get('type')),
            'civs': {low(x) for x in (c.get('civilization') or [])},
        })

    # Build wiki pool: only unmatched docs
    unmatched_urls = {w['url'] for w in unmatched_wiki}
    wiki_pool = [d for d in wiki if d.get('url') in unmatched_urls]

    suggestions = []
    skipped_no_meta = 0
    skipped_no_match = 0

    for wd in wiki_pool:
        for wc in wd.get('cards', []) or []:
            wc_type = low(wc.get('card_type'))
            wc_civ = low(wc.get('civilization'))
            wc_jp = normalize(wc.get('name_jp', ''))
            if not (wc_jp and wc_type and wc_civ):
                skipped_no_meta += 1
                continue

            best = None
            for dm in dm_pool:
                if dm['type'] != wc_type:
                    continue
                if wc_civ not in dm['civs']:
                    continue
                ratio = SequenceMatcher(None, wc_jp, dm['jp_key']).ratio()
                if not best or ratio > best['ratio']:
                    best = {'ratio': ratio, 'dm': dm['card']}

            if not best or best['ratio'] < args.min_ratio:
                skipped_no_match += 1
                continue

            dc = best['dm']
            suggestions.append({
                'similarity': round(best['ratio'], 3),
                'wiki_url': wd.get('url'),
                'wiki_name_jp': wc.get('name_jp'),
                'wiki_name_en': wc.get('name'),
                'wiki_type': wc.get('card_type'),
                'wiki_civilization': wc.get('civilization'),
                'dm_cardUid': dc.get('cardUid'),
                'dm_booster': dc.get('booster'),
                'dm_cardNameJP': strip_serial(dc.get('cardNameJP', '')),
                'dm_cardName_en': dc.get('cardName'),
                'dm_type': dc.get('type'),
                'dm_civilization': dc.get('civilization'),
            })

    suggestions.sort(key=lambda s: -s['similarity'])
    OUT.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2))

    print(f"📊 {len(suggestions)} suggestions  (same type + civ, name sim ≥ {args.min_ratio})")
    print(f"   ⏭️  wiki cards skipped (missing type/civ/name_jp): {skipped_no_meta}")
    print(f"   ⏭️  no DM with matching type+civ and ≥ ratio: {skipped_no_match}")
    print(f"\n💾 → {OUT.name}\n")

    if not suggestions:
        return

    for low_, high in [(0.9, 1.01), (0.7, 0.9), (0.5, 0.7), (0.4, 0.5)]:
        n = sum(1 for s in suggestions if low_ <= s['similarity'] < high)
        if n:
            print(f"  {low_}–{high}: {n}")

    print(f"\nTop {min(args.top, len(suggestions))}:")
    print(f"  {'sim':<5s}  {'wiki name_jp':<32s}  {'dm cardNameJP':<32s}  [type/civ]  cardUid")
    print(f"  {'-'*5}  {'-'*32}  {'-'*32}  {'-'*22}  {'-'*18}")
    for s in suggestions[:args.top]:
        wj = (s['wiki_name_jp'] or '')[:30]
        dj = (s['dm_cardNameJP'] or '')[:30]
        meta = f"[{(s['wiki_type'] or '')[:9]}/{(s['wiki_civilization'] or '')[:8]}]"
        print(f"  {s['similarity']:<5.2f}  {wj:<32s}  {dj:<32s}  {meta:<22s}  {s['dm_cardUid']}")


if __name__ == '__main__':
    main()
