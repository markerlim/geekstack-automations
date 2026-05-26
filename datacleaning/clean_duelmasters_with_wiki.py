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
DM_EXPORT_ORIG = HERE / "dmfull25MAY2026.json"
WIKI_EXPORT_ORIG = HERE / "dmwikifull25MAY2026.json"
CLEANED_OUT = HERE / "dmfull_cleaned.json"
WIKI_CLEANED = HERE / "dmwikifull_cleaned.json"
UNMATCHED_OUT = HERE / "unmatched_cards.json"
UNMATCHED_WIKI_OUT = HERE / "unmatched_wiki.json"

# Read from cleaned versions if they exist (idempotent re-runs), otherwise
# fall back to the original exports for the very first pass.
DM_INPUT = CLEANED_OUT if CLEANED_OUT.exists() else DM_EXPORT_ORIG
WIKI_INPUT = WIKI_CLEANED if WIKI_CLEANED.exists() else WIKI_EXPORT_ORIG

# Match ONE OR MORE trailing parens groups so we strip both the serial
# suffix "(DM18 55/140)" AND any rubi-in-parens like "(ルビー・グラス)" or
# "(Avatar of Strength)" that follow the kanji.
SERIAL_SUFFIX_RE = re.compile(r'(\s*\([^)]*\)\s*)+$')


def normalize_jp_name(s: str) -> str:
    if not s:
        return ''
    s = unicodedata.normalize('NFKC', s)
    s = s.replace('〜', '~')
    s = (s.replace('“', '"').replace('”', '"')
           .replace('‘', "'").replace('’', "'"))
    # Fold separator dots: wiki tends to use ASCII '.', takaratomy uses '・' or '·'
    s = s.replace('・', '.').replace('·', '.').replace('•', '.')
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
    # Back up JP fields only if not already backed up — otherwise re-applies
    # would overwrite the JP backup with the already-EN cardName.
    if not awaken_card.get('cardNameJP'):
        awaken_card['cardNameJP'] = awaken_card.get('cardName')
    if not awaken_card.get('raceJP'):
        awaken_card['raceJP'] = awaken_card.get('race')
    if not awaken_card.get('effectsJP'):
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
            # Strip trailing parens on the wiki side too — wiki sometimes has
            # "(Avatar of Strength)" EN-in-parens after the kanji.
            key = normalize_jp_name(strip_serial(name_jp))
            if key in lookup:
                if lookup[key].get('url') != doc.get('url'):
                    collisions += 1
            else:
                lookup[key] = doc
    return lookup, collisions


def main():
    print("📖 Loading exports...")
    print(f"   DM:   {DM_INPUT.name}")
    print(f"   wiki: {WIKI_INPUT.name}")
    dm_cards = json.loads(DM_INPUT.read_text())
    wiki_docs = json.loads(WIKI_INPUT.read_text())
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

    # Refresh pass: for every card/awaken with an existing wikiurl, re-apply
    # from the wiki doc by URL. Catches cases where a strict match was made in
    # a previous run but the wiki has since been updated (or where Pipeline B
    # set a wikiurl on an awaken but never re-pulled its EN data).
    wiki_by_url = {d.get('url'): d for d in wiki_docs if d.get('url')}
    refreshed_main = 0
    refreshed_awaken = 0
    for card in dm_cards:
        url = card.get('wikiurl')
        if url:
            wd = wiki_by_url.get(url)
            if wd and apply_wiki_to_card(card, wd):
                refreshed_main += 1
        for aw in card.get('awaken', []) or []:
            url = aw.get('wikiurl')
            if url:
                wd = wiki_by_url.get(url)
                if wd and apply_awaken_wiki(aw, wd):
                    refreshed_awaken += 1
    print(f"\n🔄 Re-applied EN from wikiurl: {refreshed_main:,} cards, {refreshed_awaken} awaken forms")

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

    # Reverse check: which wiki docs don't match ANY DM card?
    # Useful for spotting wiki-side typos / wrong JP names.
    dm_name_keys = set()
    for card in dm_cards:
        for field in ('cardNameJP', 'cardName2JP'):
            v = strip_serial(card.get(field) or '')
            k = normalize_jp_name(v)
            if k:
                dm_name_keys.add(k)
        for aw in card.get('awaken', []) or []:
            v = strip_serial(aw.get('cardNameJP') or aw.get('cardName') or '')
            k = normalize_jp_name(v)
            if k:
                dm_name_keys.add(k)

    unmatched_wiki = []
    for doc in wiki_docs:
        cards = doc.get('cards', []) or []
        # A wiki doc is matched if ANY of its name_jp values appears in DM
        if any(normalize_jp_name(strip_serial(c.get('name_jp', ''))) in dm_name_keys for c in cards):
            continue
        unmatched_wiki.append({
            'url': doc.get('url'),
            'is_twinpact': doc.get('is_twinpact', False),
            'names': [
                {'name': c.get('name'), 'name_jp': c.get('name_jp')}
                for c in cards
            ],
        })
    unmatched_wiki.sort(key=lambda d: d.get('url') or '')

    print(f"\n📊 Reverse check (wiki → DM):")
    print(f"   ❌ Wiki docs with no DM match: {len(unmatched_wiki):,} / {len(wiki_docs):,}")

    CLEANED_OUT.write_text(json.dumps(dm_cards, ensure_ascii=False, indent=2))
    UNMATCHED_OUT.write_text(json.dumps(
        {'main': unmatched, 'awaken': awaken_unmatched},
        ensure_ascii=False, indent=2,
    ))
    UNMATCHED_WIKI_OUT.write_text(json.dumps(unmatched_wiki, ensure_ascii=False, indent=2))
    print(f"\n💾 Cleaned cards    → {CLEANED_OUT.name} ({len(dm_cards):,} docs)")
    print(f"💾 Unmatched cards  → {UNMATCHED_OUT.name} (main={len(unmatched)}, awaken={len(awaken_unmatched)})")
    print(f"💾 Unmatched wiki   → {UNMATCHED_WIKI_OUT.name} ({len(unmatched_wiki)} docs)")


if __name__ == '__main__':
    main()
