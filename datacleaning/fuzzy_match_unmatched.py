"""
Fuzzy-match unmatched DM cards against unmatched wiki entries.

For each wiki entry in unmatched_wiki.json, find the closest unmatched DM card
in unmatched_cards.json by JP-name edit distance (difflib SequenceMatcher).
Pairs with high similarity are probably the same card with a small name
discrepancy on one side — fix one of them and both resolve next run.

Run after clean_duelmasters_with_wiki.py:
    python datacleaning/fuzzy_match_unmatched.py [--min-ratio 0.7] [--top 50]
"""
import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).parent
UNMATCHED_CARDS = HERE / "unmatched_cards.json"
UNMATCHED_WIKI = HERE / "unmatched_wiki.json"
OUT = HERE / "fuzzy_matches.json"

SERIAL_RE = re.compile(r'(\s*\([^)]*\)\s*)+$')


def normalize(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKC', s)
    s = s.replace('〜', '~')
    s = (s.replace('“', '"').replace('”', '"')
           .replace('‘', "'").replace('’', "'"))
    s = s.replace('・', '.').replace('·', '.').replace('•', '.')
    return s.replace(' ', '').replace('　', '').casefold()


def strip_serial(s):
    return SERIAL_RE.sub('', s or '').strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-ratio', type=float, default=0.7,
                    help='Minimum similarity (0-1) to include in output')
    ap.add_argument('--top', type=int, default=50,
                    help='How many top suggestions to print to console')
    args = ap.parse_args()

    cards = json.loads(UNMATCHED_CARDS.read_text())
    wiki = json.loads(UNMATCHED_WIKI.read_text())

    dm_main = cards['main']
    print(f"📖 {len(dm_main):,} unmatched DM cards × {len(wiki):,} unmatched wiki docs")

    # Pre-normalize DM names once
    dm_pool = []
    for c in dm_main:
        k = normalize(strip_serial(c.get('cardNameJP', '')))
        if k:
            dm_pool.append((c, k))

    # For each wiki entry, find best DM match by ratio
    suggestions = []
    sm = SequenceMatcher(autojunk=False)
    for w in wiki:
        wiki_keys = []
        for n in w.get('names', []) or []:
            k = normalize(n.get('name_jp', ''))
            if k:
                wiki_keys.append((n, k))
        if not wiki_keys:
            continue

        best = None
        for wiki_name, wk in wiki_keys:
            sm.set_seq2(wk)
            for card, dk in dm_pool:
                sm.set_seq1(dk)
                # Cheap prefilter — drops the bulk of pairs in O(1)
                if sm.real_quick_ratio() < args.min_ratio:
                    continue
                if sm.quick_ratio() < args.min_ratio:
                    continue
                ratio = sm.ratio()
                if ratio < args.min_ratio:
                    continue
                if not best or ratio > best['ratio']:
                    best = {'ratio': ratio, 'wiki_name': wiki_name, 'card': card}

        if best:
            suggestions.append({
                'similarity': round(best['ratio'], 3),
                'wiki_url': w.get('url'),
                'wiki_name_jp': best['wiki_name'].get('name_jp'),
                'wiki_name_en': best['wiki_name'].get('name'),
                'dm_cardUid': best['card'].get('cardUid'),
                'dm_booster': best['card'].get('booster'),
                'dm_cardNameJP': best['card'].get('cardNameJP'),
                'dm_cardName_en': best['card'].get('cardName'),
            })

    suggestions.sort(key=lambda s: -s['similarity'])

    OUT.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2))

    print(f"\n📊 {len(suggestions)} suggestions with similarity ≥ {args.min_ratio}")
    print(f"💾 → {OUT.name}\n")

    if not suggestions:
        return

    top = suggestions[:args.top]
    print(f"Top {len(top)}:\n")
    print(f"  {'sim':<5s}  {'wiki name_jp':<30s}  {'dm cardNameJP':<30s}  {'dm cardUid'}")
    print(f"  {'-'*5}  {'-'*30}  {'-'*30}  {'-'*20}")
    for s in top:
        wj = (s['wiki_name_jp'] or '')[:28]
        dj = (s['dm_cardNameJP'] or '')[:28]
        print(f"  {s['similarity']:<5.2f}  {wj:<30s}  {dj:<30s}  {s['dm_cardUid']}")


if __name__ == '__main__':
    main()
