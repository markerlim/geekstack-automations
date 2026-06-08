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

# Strip all trailing parens groups (serial + rubi + EN-in-parens) so that
# DM "紅玉草(ルビー・グラス)(DM18 55/140)" matches wiki "紅玉草". Wiki side
# stays clean (kanji-only) — the rubi is a takaratomy display annotation
# that we don't want polluting the canonical wiki name.
SERIAL_SUFFIX_RE = re.compile(r'(\s*\([^)]*\)\s*)+$')

# Narrow form: trailing parens that look like a takaratomy set+serial code
# (e.g. "(DM24EX4 PR27/PR60)"). Used to clean DM EN fields (cardName,
# cardName2) where the generic SERIAL_SUFFIX_RE would over-strip legitimate
# disambiguating parens like "(Battle Card)" or "(For Live)".
DM_SERIAL_RE = re.compile(r'\s*\(DM[^)]*\)\s*$', re.I)

# "Gachinko Souls" reprint suffix on DM side. Wiki may or may not have a
# dedicated `_GS` page — used as a fallback when strict match misses.
GS_SUFFIX_RE = re.compile(r'\s+GS\s*$')

# "Play's" reprint suffix — parallels GS. Wiki entry is the base card.
PS_SUFFIX_RE = re.compile(r"P'S\s*$")

# Art-card pattern: "<art-name> [<actual card JP>]" (dmart10 series).
# Match the inner bracketed JP against the wiki.
ART_BRACKET_RE = re.compile(r'\[(.+)\]')

# Awaken-form JP names sometimes ship with takaratomy artifacts:
# {…} braces around the name, and trailing " Top"/" Bottom"/" side X".
# Side-suffix regex matches ONE OR MORE consecutive `top`/`bottom`/`side X`
# tokens at the end (whitespace optional between them) so that names like
# `{side B} {Top}` — which become `side B Top` after brace strip — get
# fully cleaned in a single pass.
AWAKEN_BRACES_RE = re.compile(r'\{|\}')
AWAKEN_SIDE_SUFFIX_RE = re.compile(r'(\s*(top|bottom|side\s+[A-Z]))+\s*$', re.I)

LATIN_ONLY_RE = re.compile(r'[\x00-\x7F\s]+')

# Tier 1 normalize: typographic / character-equivalent folds. Verified safe —
# add zero new wiki-side collision groups and zero reroutes of already-matched
# DM cards under the existing dataset.
_KANJI_FOLD = {'竜': '龍'}                       # simplified ↔ traditional
_GREEK_KATA = {                                  # katakana spelling ↔ Greek letter
    'デルタ': 'Δ', 'アルファ': 'Α', 'ベータ': 'Β',
    'ガンマ': 'Γ', 'カイ': 'Χ',
    'イプシロン': 'Ε', 'ゼータ': 'Ζ',
}
_DASH_VARIANTS_RE = re.compile(r'[ー~\-–—]')      # all dashes/waves → '-'
_TRAILING_UNDERSCORE_RE = re.compile(r'_+$')      # scraper artifact: 'テック__'

# Tier 2 normalize: small/regular kana + hira ↔ kata. Same safety as Tier 1
# under the current dataset.
_SMALL_TO_BIG = str.maketrans({
    'ァ': 'ア', 'ィ': 'イ', 'ゥ': 'ウ', 'ェ': 'エ', 'ォ': 'オ',
    'ャ': 'ヤ', 'ュ': 'ユ', 'ョ': 'ヨ', 'ヮ': 'ワ',
    'ぁ': 'あ', 'ぃ': 'い', 'ぅ': 'う', 'ぇ': 'え', 'ぉ': 'お',
    'ゃ': 'や', 'ゅ': 'ゆ', 'ょ': 'よ', 'ゎ': 'わ',
})
_HIRA_TO_KATA = str.maketrans({chr(c): chr(c + 0x60) for c in range(0x3041, 0x3097)})


def normalize_jp_name(s: str) -> str:
    if not s:
        return ''
    s = unicodedata.normalize('NFKC', s)
    for k, v in _KANJI_FOLD.items():
        s = s.replace(k, v)
    for k, v in _GREEK_KATA.items():
        s = s.replace(k, v)
    s = _TRAILING_UNDERSCORE_RE.sub('', s)
    s = s.replace('〜', '~')
    s = (s.replace('“', '"').replace('”', '"')
           .replace('‘', "'").replace('’', "'"))
    # Strip quote chars entirely — DM and wiki disagree on whether tags like
    # `NYZ` are wrapped in quotes (`ラウド NYZ` vs `ラウド "NYZ"`). Also catches
    # backtick vs apostrophe mismatches (der'Zen Mondo vs der`ZenMondo).
    s = s.replace('"', '').replace("'", '').replace('`', '')
    # Fold separator dots: wiki tends to use ASCII '.', takaratomy uses '・' or '·'
    s = s.replace('・', '.').replace('·', '.').replace('•', '.')
    # Fold dash/wave variants used as subtitle brackets.
    s = _DASH_VARIANTS_RE.sub('-', s)
    s = s.translate(_SMALL_TO_BIG)
    s = s.translate(_HIRA_TO_KATA)
    return s.replace(' ', '').replace('　', '').casefold()


def strip_serial(name: str) -> str:
    return SERIAL_SUFFIX_RE.sub('', name).strip() if name else name


def strip_dm_serial(name: str) -> str:
    return DM_SERIAL_RE.sub('', name).strip() if name else name


def strip_gs_variant(name: str) -> str:
    return GS_SUFFIX_RE.sub('', name).strip() if name else name


def strip_ps_variant(name: str) -> str:
    return PS_SUFFIX_RE.sub('', name).strip() if name else name


def extract_art_bracket(name: str) -> str:
    """Return the inner `[...]` JP from a dmart10-style name, else original."""
    if not name:
        return name
    m = ART_BRACKET_RE.search(name)
    return m.group(1).strip() if m else name


def clean_awaken_name(name: str) -> str:
    """Strip {…} braces and ' Top'/' Bottom'/' side X' suffixes from awaken JP.

    Brace-strip first so that `{side B} {Top}` becomes `side B Top`, then
    the side regex sweeps multiple consecutive side/top/bottom tokens.
    """
    if not name:
        return name
    s = AWAKEN_BRACES_RE.sub('', name)
    s = AWAKEN_SIDE_SUFFIX_RE.sub('', s)
    return s.strip()


def is_latin_only(s: str) -> bool:
    return bool(s) and bool(LATIN_ONLY_RE.fullmatch(s))


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
                existing = lookup[key]
                if existing.get('url') == doc.get('url'):
                    continue
                # Collision tiebreaker: prefer twinpact entries. Wiki has
                # separate pages for each form of a twinpact (e.g.
                # `Dorbro,_Final_Forbidden_Gamma` single-form AND
                # `_Bone_Dance_Charger` combined twinpact) — both have the
                # same form-0 name_jp `終断γ ドルブロ`. DM cards that have a
                # cardName2JP are themselves twinpacts and need the combined
                # wiki entry so apply_wiki_to_card can set both cardName and
                # cardName2. Without this preference, first-insert wins
                # arbitrarily and 179 DM twinpacts end up linked to the
                # single-form wiki, leaving their cardName2 dirty with the
                # takaratomy serial bracket.
                if doc.get('is_twinpact') and not existing.get('is_twinpact'):
                    lookup[key] = doc
                else:
                    collisions += 1
            else:
                lookup[key] = doc
    return lookup, collisions


def build_en_lookup(wiki_docs):
    """EN cardName → wiki_doc, only for unambiguous single-form non-twinpact
    docs. Used as a fallback when DM cardNameJP is itself latin (data-entry
    bug on the takaratomy side)."""
    counts = {}
    docs_by_name = {}
    for doc in wiki_docs:
        cards = doc.get('cards', [])
        if doc.get('is_twinpact') or len(cards) != 1:
            continue
        name = (cards[0].get('name') or '').strip().casefold()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
        docs_by_name.setdefault(name, doc)
    return {nm: docs_by_name[nm] for nm, c in counts.items() if c == 1}


def build_twinpact_jp_lookup(wiki_docs):
    """Normalized JP → twinpact wiki_doc. Restricted to twinpact docs so that
    the cardName2JP (sideB) fallback can't accidentally pick up a standalone
    wiki entry that shares the same JP name as one half of a twinpact
    (e.g. wiki has both `_Ghost_Touch` twinpact and `Ghost_Touch` standalone)."""
    lk = {}
    for doc in wiki_docs:
        if not doc.get('is_twinpact'):
            continue
        for c in doc.get('cards', []):
            nj = c.get('name_jp', '')
            if not nj:
                continue
            k = normalize_jp_name(strip_serial(nj))
            lk.setdefault(k, doc)
    return lk


def main():
    print("📖 Loading exports...")
    print(f"   DM:   {DM_INPUT.name}")
    print(f"   wiki: {WIKI_INPUT.name}")
    dm_cards = json.loads(DM_INPUT.read_text())
    wiki_docs = json.loads(WIKI_INPUT.read_text())
    print(f"   {len(dm_cards):,} DM cards / {len(wiki_docs):,} wiki docs")

    jp_lookup, collisions = build_jp_lookup(wiki_docs)
    print(f"   {len(jp_lookup):,} unique normalized JP names in lookup ({collisions} cross-doc collisions ignored)")
    en_lookup = build_en_lookup(wiki_docs)
    print(f"   {len(en_lookup):,} unambiguous EN names available for latin-JP fallback")
    twinpact_jp_lookup = build_twinpact_jp_lookup(wiki_docs)
    print(f"   {len(twinpact_jp_lookup):,} twinpact JP names available for cardName2JP (sideB) fallback")

    matched_main = 0
    matched_awaken = 0
    awaken_seen = 0
    gs_fallback = 0
    ps_fallback = 0
    art_fallback = 0
    en_fallback = 0
    sideb_fallback = 0
    wiki_dupe_fixes = 0
    unmatched = []
    awaken_unmatched = []
    booster_unmatched = Counter()

    fields_cleaned = 0
    for card in dm_cards:
        # Clean EN-side serial brackets from DM source. JP-side fields keep
        # their serials intentionally — they double as set/print references
        # (e.g. cardNameJP="終断γ ドルブロ (DM24EX4 PR27/PR60)" lets you grep
        # back to the exact takaratomy print). Matching and sync already
        # call strip_serial themselves, so keeping the serial on JP fields
        # has no impact on pipeline behavior.
        #
        # EN side uses the narrow DM_SERIAL_RE to avoid stripping the 2
        # wiki EN names with legitimate trailing parens ("(For Live)",
        # "(Storm Awakening MAXIMUM Shinra Banshou)").
        for field in ('cardName', 'cardName2'):
            v = card.get(field)
            if v:
                new = strip_dm_serial(v)
                if new != v:
                    card[field] = new
                    fields_cleaned += 1
        for aw in card.get('awaken', []) or []:
            v = aw.get('cardName')
            if v:
                new = strip_dm_serial(v)
                if new != v:
                    aw['cardName'] = new
                    fields_cleaned += 1

        # MAIN FORM
        jp_name = strip_serial(card.get('cardNameJP', ''))
        key = normalize_jp_name(jp_name)
        wiki_doc = jp_lookup.get(key) if key else None

        # Fallback 1: DM " GS" (Gachinko Souls reprint) — wiki often only
        # has the base card. Try the JP name with " GS" stripped.
        if not wiki_doc and jp_name and jp_name.endswith(' GS'):
            base_key = normalize_jp_name(strip_gs_variant(jp_name))
            if base_key and base_key != key:
                wiki_doc = jp_lookup.get(base_key)
                if wiki_doc:
                    gs_fallback += 1

        # Fallback 2: DM "P'S" (Play's reprint) — same shape as GS.
        if not wiki_doc and jp_name and "P'S" in jp_name:
            base_key = normalize_jp_name(strip_ps_variant(jp_name))
            if base_key and base_key != key:
                wiki_doc = jp_lookup.get(base_key)
                if wiki_doc:
                    ps_fallback += 1

        # Fallback 3: dmart10-style "<art name> [<actual card JP>]" — match
        # the bracketed inner JP against wiki.
        if not wiki_doc and jp_name and '[' in jp_name and ']' in jp_name:
            inner = extract_art_bracket(jp_name)
            inner_key = normalize_jp_name(inner)
            if inner_key and inner_key != key:
                wiki_doc = jp_lookup.get(inner_key)
                if wiki_doc:
                    art_fallback += 1

        # Fallback 4: DM cardNameJP is latin (data-entry bug) — match by EN.
        if not wiki_doc and is_latin_only(jp_name):
            en_key = (card.get('cardName') or '').strip().casefold()
            wiki_doc = en_lookup.get(en_key) if en_key else None
            if wiki_doc:
                en_fallback += 1

        # Fallback 5: cardName2JP (sideB) — for twinpacts where DM's sideA has
        # a kanji typo or extra word but sideB is clean. Lookup is restricted
        # to twinpact wiki entries (build_twinpact_jp_lookup) so this can't
        # pick up a standalone wiki entry sharing the same JP name.
        sideb_matched = False
        if not wiki_doc:
            side_b = strip_serial(card.get('cardName2JP') or '')
            side_b_key = normalize_jp_name(side_b)
            if side_b_key:
                wiki_doc = twinpact_jp_lookup.get(side_b_key)
                if wiki_doc:
                    sideb_fallback += 1
                    sideb_matched = True

        if wiki_doc and apply_wiki_to_card(card, wiki_doc):
            matched_main += 1
            # Wiki-dupe fix: a known scraper bug duplicates form-0 name_jp
            # with form-1's value. When sideB matched and we can detect the
            # dupe (both forms have identical name_jp), push DM cardNameJP
            # into wiki form 0 so subsequent runs strict-match.
            if sideb_matched:
                cards = wiki_doc.get('cards', [])
                if (len(cards) >= 2
                        and cards[0].get('name_jp')
                        and cards[0].get('name_jp') == cards[1].get('name_jp')):
                    dm_side_a = strip_serial(card.get('cardNameJP') or '')
                    if dm_side_a and not is_latin_only(dm_side_a):
                        cards[0]['name_jp'] = dm_side_a
                        wiki_dupe_fixes += 1
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
            aw_raw = aw.get('cardNameJP') or aw.get('cardName') or ''
            aw_jp = strip_serial(clean_awaken_name(aw_raw))
            aw_key = normalize_jp_name(aw_jp)
            aw_doc = jp_lookup.get(aw_key) if aw_key else None
            # Awaken fallback: 8 of 9 DM awaken cards starting with `次元の`
            # have a wiki entry that includes the prefix (strict match), but
            # the wiki page for `Mega_Innocent_Sword` ships without the
            # prefix because the same card also has a non-awaken main-form
            # variant (e.g. dm32-110) where takaratomy omits the prefix.
            # Try stripping the prefix when strict match misses.
            if not aw_doc and aw_jp and aw_jp.startswith('次元の'):
                no_prefix_key = normalize_jp_name(aw_jp[len('次元の'):])
                if no_prefix_key:
                    aw_doc = jp_lookup.get(no_prefix_key)
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

    # JP sync pass: DM is the single source of truth for JP card names because
    # future takaratomy scrapes lookup wiki by DM cardNameJP. Push the CLEAN
    # canonical DM name (all trailing parens stripped — both serial AND rubi)
    # into every linked wiki doc. Matching at scrape time also runs strip on
    # both sides, so the clean form is what they'll compare against. Wiki stays
    # rubi-free.
    #
    # SAFETY: only sync when DM JP and wiki JP already normalize-match. This
    # is true for every strict-path match (rubi/serial differences after
    # strip_serial still normalize to the same key) but false for every
    # fallback path (GS / P'S / art-bracket / latin-EN / sideB). Fallbacks
    # set wikiurl on cards whose DM JP is a non-canonical surrogate; pushing
    # the surrogate into wiki corrupted entries like `Metel` (latin EN
    # fallback), `オプティマスプライム [“罰怒“ブランド]` (art bracket),
    # and the wiki form-1 dupe (sideB) in earlier runs. The wiki form-0 fix
    # for dupe-name_jp twinpacts happens at match time above, not here.
    def _normalize_match(a: str, b: str) -> bool:
        return bool(a) and bool(b) and normalize_jp_name(strip_serial(a)) == normalize_jp_name(strip_serial(b))
    wiki_jp_synced = 0
    for card in dm_cards:
        url = card.get('wikiurl')
        if url:
            wd = wiki_by_url.get(url)
            if wd and wd.get('cards'):
                dm_jp = strip_serial(card.get('cardNameJP') or '')
                wiki_nj_0 = wd['cards'][0].get('name_jp', '')
                if _normalize_match(dm_jp, wiki_nj_0) and wiki_nj_0 != dm_jp:
                    wd['cards'][0]['name_jp'] = dm_jp
                    wiki_jp_synced += 1
                if len(wd['cards']) > 1 and card.get('cardName2'):
                    dm_jp2 = strip_serial(card.get('cardName2JP') or '')
                    wiki_nj_1 = wd['cards'][1].get('name_jp', '')
                    if _normalize_match(dm_jp2, wiki_nj_1) and wiki_nj_1 != dm_jp2:
                        wd['cards'][1]['name_jp'] = dm_jp2
                        wiki_jp_synced += 1
        for aw in card.get('awaken', []) or []:
            aw_url = aw.get('wikiurl')
            if not aw_url:
                continue
            aw_wd = wiki_by_url.get(aw_url)
            if not aw_wd or not aw_wd.get('cards'):
                continue
            aw_jp = strip_serial(aw.get('cardNameJP') or '')
            aw_wiki_nj = aw_wd['cards'][0].get('name_jp', '')
            if _normalize_match(aw_jp, aw_wiki_nj) and aw_wiki_nj != aw_jp:
                aw_wd['cards'][0]['name_jp'] = aw_jp
                wiki_jp_synced += 1
    print(f"🔄 Wiki name_jp synced to DM cardNameJP (clean): {wiki_jp_synced:,} entries")

    total = len(dm_cards) or 1
    print("\n📊 Main-card results:")
    print(f"   ✅ Matched: {matched_main:,} / {len(dm_cards):,} ({matched_main / total * 100:.1f}%)")
    print(f"      (fallbacks — GS: {gs_fallback}, P'S: {ps_fallback}, art-bracket: {art_fallback}, latin-JP→EN: {en_fallback}, sideB: {sideb_fallback})")
    print(f"      (wiki form-0 dupe fixes from sideB matches: {wiki_dupe_fixes})")
    print(f"      (DM-source field cleanups — serial brackets stripped: {fields_cleaned})")
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
    skipped_meta = 0
    for doc in wiki_docs:
        cards = doc.get('cards', []) or []
        # Skip non-card "meta" wiki pages — civilization pages, character
        # pages, set summaries, etc. They have no `cards` array and so can
        # never match a DM card; counting them as unmatched is noise.
        if not cards:
            skipped_meta += 1
            continue
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
    print(f"      (skipped {skipped_meta:,} non-card meta pages with empty `cards`)")

    CLEANED_OUT.write_text(json.dumps(dm_cards, ensure_ascii=False, indent=2))
    WIKI_CLEANED.write_text(json.dumps(wiki_docs, ensure_ascii=False, indent=2))
    UNMATCHED_OUT.write_text(json.dumps(
        {'main': unmatched, 'awaken': awaken_unmatched},
        ensure_ascii=False, indent=2,
    ))
    UNMATCHED_WIKI_OUT.write_text(json.dumps(unmatched_wiki, ensure_ascii=False, indent=2))
    print(f"\n💾 Cleaned cards    → {CLEANED_OUT.name} ({len(dm_cards):,} docs)")
    print(f"💾 Cleaned wiki     → {WIKI_CLEANED.name} ({len(wiki_docs):,} docs)")
    print(f"💾 Unmatched cards  → {UNMATCHED_OUT.name} (main={len(unmatched)}, awaken={len(awaken_unmatched)})")
    print(f"💾 Unmatched wiki   → {UNMATCHED_WIKI_OUT.name} ({len(unmatched_wiki)} docs)")


if __name__ == '__main__':
    main()
