"""
Clean a CL_duelmasters JSON export by applying wiki data from a
CL_duelmasters_wiki export.

Reads two exports from this folder and writes:
  - dmfull_cleaned.json    — cards with wiki data merged into EN fields
  - unmatched_cards.json   — cards that had no wiki match (review list)

Matching is by (cardNameJP) normalized the same way Pipeline B normalizes:
NFKC + wave-dash unification + quote folding + casefold + space strip.

Apply mirrors apply_wiki_data() in pipelines/b_scrape_cards.py:
  Main form  : cardName, type, effects, race, illustrator
  Twinpact   : cardName2, type2, effects2, race2 (if wiki has 2 forms)
  Awaken     : each awaken form looked up by its own JP name

Standalone — does not import b_scrape_cards (which would init MongoService).
Run from anywhere: `python datacleaning/clean_duelmasters_with_wiki.py`
"""
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
DM_EXPORT = HERE / "dmfull25MAY2026.json"
WIKI_EXPORT = HERE / "dmwikifull25MAY2026.json"
CLEANED_OUT = HERE / "dmfull_cleaned.json"
UNMATCHED_OUT = HERE / "unmatched_cards.json"

SERIAL_SUFFIX_RE = re.compile(r'\s*\([^)]*\)\s*$')


def normalize_jp_name(s: str) -> str:
    if not s:
        return ''
    s = unicodedata.normalize('NFKC', s)
    s = s.replace('〜', '~')
    s = (s.replace('“', '"').replace('”', '"')
           .replace('‘', "'").replace('’', "'"))
    return s.replace(' ', '').replace('　', '').casefold()


def strip_serial(name: str) -> str:
    return SERIAL_SUFFIX_RE.sub('', name).strip() if name else name


def split_race(s):
    if not s:
        return []
    return [r.strip() for r in s.split('/') if r.strip()]


def apply_wiki_to_card(card: dict, wiki_doc: dict) -> bool:
    """Apply wiki data to one DM card in place. Returns True if applied."""
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


def apply_awaken_wiki(awaken_card: dict, wiki_doc: dict) -> bool:
    """Apply wiki data to a single awaken form in place."""
    wiki_cards = wiki_doc.get('cards', [])
    if not wiki_cards:
        return False
    form0 = wiki_cards[0]
    # Back up JP fields before overwrite, mirroring Pipeline B
    awaken_card['cardNameJP'] = awaken_card.get('cardName')
    awaken_card['raceJP'] = awaken_card.get('race')
    awaken_card['effectsJP'] = awaken_card.get('effects')
    if form0.get('name'):
        awaken_card['cardName'] = form0['name']
    if form0.get('card_type'):
        awaken_card['type'] = form0['card_type']
    if form0.get('english_text'):
        awaken_card['effects'] = form0['english_text']
    if form0.get('race'):
        awaken_card['race'] = split_race(form0['race'])
    awaken_card['wikiurl'] = wiki_doc.get('url', '')
    return True


def build_jp_lookup(wiki_docs):
    """Return (normalized JP name) → wiki_doc, plus a collision count."""
    lookup = {}
    collisions = 0
    for doc in wiki_docs:
        for wcard in doc.get('cards', []):
            name_jp = wcard.get('name_jp', '')
            if not name_jp:
                continue
            key = normalize_jp_name(name_jp)
            if key in lookup:
                if lookup[key].get('url') != doc.get('url'):
                    collisions += 1
            else:
                lookup[key] = doc
    return lookup, collisions


def main():
    print("📖 Loading exports...")
    dm_cards = json.loads(DM_EXPORT.read_text())
    wiki_docs = json.loads(WIKI_EXPORT.read_text())
    print(f"   {len(dm_cards):,} DM cards / {len(wiki_docs):,} wiki docs")

    jp_lookup, collisions = build_jp_lookup(wiki_docs)
    print(f"   {len(jp_lookup):,} unique normalized JP names in lookup ({collisions} cross-doc collisions ignored)")

    matched_main = 0
    matched_awaken = 0
    awaken_seen = 0
    unmatched = []
    awaken_unmatched = []
    booster_unmatched = Counter()

    for card in dm_cards:
        # MAIN FORM
        jp_name = strip_serial(card.get('cardNameJP', ''))
        key = normalize_jp_name(jp_name)
        wiki_doc = jp_lookup.get(key) if key else None

        if wiki_doc and apply_wiki_to_card(card, wiki_doc):
            matched_main += 1
        else:
            booster = card.get('booster', '?')
            booster_unmatched[booster] += 1
            unmatched.append({
                'cardUid': card.get('cardUid'),
                'booster': booster,
                'cardName': card.get('cardName'),
                'cardNameJP': jp_name,
                'cardNameJP_raw': card.get('cardNameJP'),
                'cardName2JP': card.get('cardName2JP'),
            })

        # AWAKEN FORMS — each has its own JP name and wiki lookup
        for aw in card.get('awaken', []) or []:
            awaken_seen += 1
            aw_jp = strip_serial(aw.get('cardNameJP') or aw.get('cardName') or '')
            aw_key = normalize_jp_name(aw_jp)
            aw_doc = jp_lookup.get(aw_key) if aw_key else None
            if aw_doc and apply_awaken_wiki(aw, aw_doc):
                matched_awaken += 1
            else:
                awaken_unmatched.append({
                    'parent_cardUid': card.get('cardUid'),
                    'booster': card.get('booster'),
                    'awaken_cardName': aw.get('cardName'),
                    'awaken_cardNameJP': aw_jp,
                })

    total = len(dm_cards) or 1
    print("\n📊 Main-card results:")
    print(f"   ✅ Matched: {matched_main:,} / {len(dm_cards):,} ({matched_main / total * 100:.1f}%)")
    print(f"   ❌ Unmatched: {len(unmatched):,}")

    if awaken_seen:
        print("\n📊 Awaken-form results:")
        print(f"   ✅ Matched: {matched_awaken:,} / {awaken_seen:,} ({matched_awaken / max(awaken_seen, 1) * 100:.1f}%)")
        print(f"   ❌ Unmatched: {len(awaken_unmatched):,}")

    if booster_unmatched:
        print("\n   Top boosters by unmatched main cards:")
        for booster, count in booster_unmatched.most_common(15):
            print(f"     {booster:<15s} {count}")

    CLEANED_OUT.write_text(json.dumps(dm_cards, ensure_ascii=False, indent=2))
    UNMATCHED_OUT.write_text(json.dumps(
        {'main': unmatched, 'awaken': awaken_unmatched},
        ensure_ascii=False, indent=2,
    ))
    print(f"\n💾 Cleaned cards   → {CLEANED_OUT.name} ({len(dm_cards):,} docs)")
    print(f"💾 Unmatched cards → {UNMATCHED_OUT.name} (main={len(unmatched)}, awaken={len(awaken_unmatched)})")


if __name__ == '__main__':
    main()
