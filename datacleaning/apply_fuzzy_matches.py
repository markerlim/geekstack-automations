"""
Apply fuzzy_matches.json suggestions to dmfull_cleaned.json.

For each fuzzy-matched pair above --min-ratio, find the wiki doc by url and
the DM card by cardUid, then merge the wiki's EN fields (cardName, type,
effects, race, illustrator, plus the twinpact 2nd form) into the DM card.

Default threshold is 0.9 because a wrong match silently overwrites real
data — use --min-ratio 0.7 only if you've spot-checked the lower-confidence
suggestions first.

Run after fuzzy_match_unmatched.py:
    python datacleaning/apply_fuzzy_matches.py [--min-ratio 0.9] [--dry-run]
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).parent
WIKI_EXPORT_ORIG = HERE / "dmwikifull25MAY2026.json"
WIKI_CLEANED = HERE / "dmwikifull_cleaned.json"
CLEANED = HERE / "dmfull_cleaned.json"
FUZZY = HERE / "fuzzy_matches.json"
APPLIED_LOG = HERE / "fuzzy_applied.json"

# Read from the cleaned wiki if it exists so prior JP edits are preserved
WIKI_INPUT = WIKI_CLEANED if WIKI_CLEANED.exists() else WIKI_EXPORT_ORIG


def split_race(s):
    if not s:
        return []
    return [r.strip() for r in s.split('/') if r.strip()]


def apply_wiki_to_card(card: dict, wiki_doc: dict) -> bool:
    wiki_cards = wiki_doc.get('cards', [])
    if not wiki_cards:
        return False

    form0 = wiki_cards[0]
    if form0.get('name'):
        card['cardName'] = form0['name']
    if form0.get('card_type'):
        card['type'] = form0['card_type']
    if form0.get('english_text'):
        card['effects'] = form0['english_text']
    if form0.get('race'):
        card['race'] = split_race(form0['race'])
    if form0.get('illustrator'):
        card['illustrator'] = form0['illustrator']

    if len(wiki_cards) > 1:
        form1 = wiki_cards[1]
        if form1.get('name'):
            card['cardName2'] = form1['name']
        if form1.get('card_type'):
            card['type2'] = form1['card_type']
        if form1.get('english_text'):
            card['effects2'] = form1['english_text']
        if form1.get('race'):
            card['race2'] = split_race(form1['race'])

    card['wikiurl'] = wiki_doc.get('url', '')
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-ratio', type=float, default=0.9,
                    help='Minimum similarity to auto-apply (default 0.9)')
    ap.add_argument('--source', type=str, default=str(FUZZY),
                    help=f'Path to fuzzy suggestions JSON (default {FUZZY.name})')
    ap.add_argument('--require-en-match', action='store_true',
                    help='Only apply pairs where wiki_name_en == dm_cardName_en '
                         '(case-insensitive) — much stricter, catches false positives')
    ap.add_argument('--dry-run', action='store_true',
                    help='Print what would change without writing anything')
    args = ap.parse_args()

    print("📖 Loading inputs...")
    print(f"   wiki:   {WIKI_INPUT.name}")
    print(f"   source: {Path(args.source).name}")
    wiki_docs = json.loads(WIKI_INPUT.read_text())
    dm_cards = json.loads(CLEANED.read_text())
    fuzzy = json.loads(Path(args.source).read_text())
    print(f"   {len(wiki_docs):,} wiki docs / {len(dm_cards):,} DM cards / {len(fuzzy):,} fuzzy suggestions")

    wiki_by_url = {d.get('url'): d for d in wiki_docs if d.get('url')}
    dm_by_uid = {c.get('cardUid'): c for c in dm_cards if c.get('cardUid')}

    eligible = [s for s in fuzzy if s.get('similarity', 0) >= args.min_ratio]
    print(f"\n🎯 {len(eligible)} suggestions at similarity ≥ {args.min_ratio}")

    skipped_en = 0
    if args.require_en_match:
        before = len(eligible)
        eligible = [
            s for s in eligible
            if (s.get('wiki_name_en') or '').strip().casefold()
            == (s.get('dm_cardName_en') or '').strip().casefold()
        ]
        skipped_en = before - len(eligible)
        print(f"   --require-en-match: kept {len(eligible)}, skipped {skipped_en} for EN mismatch")

    applied = []
    missing_wiki = 0
    missing_card = 0
    no_change = 0
    wiki_jp_updates = 0

    for s in eligible:
        wiki_url = s.get('wiki_url')
        cardUid = s.get('dm_cardUid')
        wiki_doc = wiki_by_url.get(wiki_url)
        card = dm_by_uid.get(cardUid)

        if not wiki_doc:
            missing_wiki += 1
            continue
        if not card:
            missing_card += 1
            continue

        # ── Push DM JP name back into the wiki doc (JP follows takaratomy) ──
        # Update the specific cards[i].name_jp entry that the fuzzy matcher hit.
        old_jp = s.get('wiki_name_jp')
        new_jp = s.get('dm_cardNameJP')
        if old_jp and new_jp and old_jp != new_jp:
            for wc in wiki_doc.get('cards', []):
                if wc.get('name_jp') == old_jp:
                    wc['name_jp'] = new_jp
                    wiki_jp_updates += 1
                    break

        before = {
            'cardName': card.get('cardName'),
            'type': card.get('type'),
            'effects': card.get('effects'),
            'race': card.get('race'),
            'wikiurl': card.get('wikiurl'),
        }
        if apply_wiki_to_card(card, wiki_doc):
            after = {k: card.get(k) for k in before}
            if after == before:
                no_change += 1
                continue
            applied.append({
                'similarity': s['similarity'],
                'cardUid': cardUid,
                'booster': card.get('booster'),
                'cardNameJP': card.get('cardNameJP'),
                'wiki_url': wiki_url,
                'wiki_jp_before': old_jp,
                'wiki_jp_after': new_jp if (old_jp and new_jp and old_jp != new_jp) else None,
                'before': {k: v for k, v in before.items() if v},
                'after': {k: v for k, v in after.items() if v},
            })

    print(f"\n📊 Apply summary:")
    print(f"   ✅ DM cards updated: {len(applied)}")
    print(f"   ✏️ Wiki name_jp updated: {wiki_jp_updates}")
    print(f"   ⏭️ No-change (wiki had nothing new): {no_change}")
    print(f"   ⚠️ Wiki url not found in export: {missing_wiki}")
    print(f"   ⚠️ DM cardUid not found in cleaned: {missing_card}")

    if applied:
        print(f"\nSample of applied changes:")
        for a in applied[:10]:
            before_name = a['before'].get('cardName') or '(none)'
            after_name = a['after'].get('cardName') or '(none)'
            print(f"   {a['similarity']:.2f}  {a['cardUid']:<22s}  "
                  f"{before_name[:30]:<32s} → {after_name[:30]}")

    if args.dry_run:
        print(f"\n(dry-run — no files written)")
        return

    CLEANED.write_text(json.dumps(dm_cards, ensure_ascii=False, indent=2))
    WIKI_CLEANED.write_text(json.dumps(wiki_docs, ensure_ascii=False, indent=2))
    APPLIED_LOG.write_text(json.dumps(applied, ensure_ascii=False, indent=2))
    print(f"\n💾 Updated {CLEANED.name} ({len(dm_cards):,} docs)")
    print(f"💾 Updated {WIKI_CLEANED.name} ({len(wiki_docs):,} docs, {wiki_jp_updates} name_jp edits)")
    print(f"💾 Applied changes log → {APPLIED_LOG.name} ({len(applied)} entries)")


if __name__ == '__main__':
    main()
