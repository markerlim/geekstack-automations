# Duel Masters Data Cleanup

One-off cleanup pass that took a MongoDB export of `CL_duelmasters` (21,932 cards)
and `CL_duelmasters_wiki` (11,830 docs → 11,835 after re-scraping 5 missing
pages) and produced cleaned, cross-consistent re-import files. Match rate
improved from a pre-existing baseline to **100.0% main (21,932/21,932) + 99.8%
awaken (466/467)** through 12 rounds of iterative matching, fuzzy detection,
apply-and-reflow, targeted fallbacks for known data-quality buckets, and
user-confirmed manual patches for the long-tail unmatched (kanji variants,
wiki-side typos, takaratomy single-set inconsistencies, missing wiki pages
that needed re-scraping).

---

## Source-of-truth rules

| Field | Source | Why |
|---|---|---|
| **EN card name + EN fields** (`cardName`, `type`, `effects`, `race`, `illustrator`) | **Wiki** | Fandom is the canonical English translation. |
| **JP card name** (`cardNameJP`, `cardName2JP`) | **DM** (takaratomy) | Future scrapes look up wiki by DM cardNameJP — DM is the publisher. |

Surface forms differ on purpose:
- DM stores `紅玉草(ルビー・グラス)(DM18 55/140)` (takaratomy display with rubi + serial)
- Wiki stores `紅玉草` (canonical kanji only)

They compare equal because matching runs `strip_serial` on both sides.

---

## Inputs and outputs

```
datacleaning/
├── dmfull25MAY2026.json          (input — original Mongo export of CL_duelmasters)
├── dmwikifull25MAY2026.json      (input — original Mongo export of CL_duelmasters_wiki)
├── dmfull_cleaned.json           (output — re-import to CL_duelmasters)
├── dmwikifull_cleaned.json       (output — re-import to CL_duelmasters_wiki)
├── unmatched_cards.json          (review — DM cards with no wiki match)
├── unmatched_wiki.json           (review — wiki docs with no DM match)
├── fuzzy_matches.json            (review — name-only fuzzy suggestions)
├── fuzzy_matches_metadata.json   (review — fuzzy + type/civ constraint)
├── fuzzy_applied.json            (audit log of last apply run)
└── CLEANUP.md                    (this file)
```

The cleaner is **idempotent**: if `dmfull_cleaned.json` / `dmwikifull_cleaned.json`
exist, it reads from those instead of the original exports, so iterative rounds
preserve prior edits.

---

## Pipeline

```
┌─────────────────────────────────┐
│ clean_duelmasters_with_wiki.py  │  strict match (NFKC + casefold + strip)
│                                 │  refresh EN from wikiurl
│                                 │  sync clean DM cardNameJP → wiki name_jp
│                                 │  reverse check (wiki → DM)
└──────────────┬──────────────────┘
               │
               ▼
   unmatched_cards.json + unmatched_wiki.json
               │
       ┌───────┴───────────────┐
       ▼                       ▼
fuzzy_match_unmatched.py   fuzzy_match_metadata.py
(name-only, ≥0.7)          (name + type + civ, ≥0.4)
       │                       │
       └──────────┬────────────┘
                  ▼
       apply_fuzzy_matches.py
       --source <file>
       --min-ratio 0.X
       --require-en-match    ← safety filter
                  │
                  ▼   (writes back to dmfull_cleaned + dmwikifull_cleaned)
       re-run cleaner → re-run fuzzy → reapply → converge
```

### `clean_duelmasters_with_wiki.py`
Reads exports, strict-matches DM ↔ wiki by normalized JP name, applies wiki
EN data to DM cards, syncs clean DM JP to wiki name_jp, computes both unmatched
lists. After strict match, two ordered fallbacks fire only when strict missed:

1. **GS-suffix fallback** — DM cards ending in ` GS` (Gachinko Souls reprint)
   re-try with the suffix stripped. Wiki sometimes has a dedicated `_GS` page
   (12 such entries exist and still match strictly), sometimes only the base
   card. Stripping only on miss preserves both behaviors.
2. **Latin-JP EN fallback** — when DM `cardNameJP` is itself latin (a
   takaratomy-side data-entry bug — e.g. `dmex04-027` ships JP="Bolshack
   Dragon"), match by EN `cardName` against a build of wiki entries where
   the EN name is unambiguous (one non-twinpact wiki doc, no collisions).

**Normalization key** = `normalize_jp_name(strip_serial(name_jp))` where:
- `strip_serial` strips **all** trailing `(...)` groups, e.g.
  `紅玉草(ルビー・グラス)(DM18 55/140)` → `紅玉草`
- `normalize_jp_name`:
  - NFKC (handles fullwidth↔halfwidth: `＝→=`, `～→~`, `７→7`, `！→!`)
  - `〜 ↔ ~` (NFKC misses U+301C)
  - `・ · • → .` (separator dot variants)
  - Curly quotes → straight
  - Strip ASCII + fullwidth spaces
  - `.casefold()` (so `x` matches `X` in latin chars)

### `fuzzy_match_unmatched.py`
For each unmatched wiki entry, finds the closest unmatched DM card by JP-name
edit distance (`difflib.SequenceMatcher`). Catches typos that fall below the
strict-match threshold. Outputs `fuzzy_matches.json`.

### `fuzzy_match_metadata.py`
Same as above but requires **same card_type AND civilization-overlap** as a
hard prefilter, allowing a lower name-similarity threshold. Catches cards
whose JP names diverge a lot but are obviously the same card by metadata.
Outputs `fuzzy_matches_metadata.json`.

### `apply_fuzzy_matches.py`
Takes a fuzzy suggestions JSON and applies the matches to `dmfull_cleaned.json`
(merges wiki EN fields) AND `dmwikifull_cleaned.json` (pushes DM JP into wiki).
Flags:
- `--source <path>` — pick which fuzzy JSON to read (default `fuzzy_matches.json`)
- `--min-ratio 0.9` — threshold for auto-apply (default 0.9 for safety)
- `--require-en-match` — extra safety filter; only apply pairs where wiki and
  DM EN names already agree (case-insensitive). Catches false positives that
  metadata-only can't (different cards with same type+civ).
- `--dry-run` — preview without writing

Emits `fuzzy_applied.json` change log.

---

## Round-by-round progress

| Round | Action | DM matched | Δ | Unmatched DM | Unmatched wiki |
|---|---|---:|---:|---:|---:|
| Baseline | (initial export) | — | — | — | — |
| R1 | First strict cleaner | 21,082 (96.1%) | — | 850 | 504 |
| R2 | Apply fuzzy ≥0.9 + reflow | 21,282 | +200 | 650 | 380 |
| R3 | Apply fuzzy ≥0.85 + reflow | 21,345 | +63 | 587 | 343 |
| R4 | Apply metadata ≥0.7 + EN-filter | 21,374 | +29 | 558 | 321 |
| R5 | Apply metadata ≥0.5 + EN-filter | 21,466 | +92 | 466 | 293 |
| R6 | Apply metadata ≥0.4 + EN-filter | 21,620 | +154 | 312 | 215 |
| R7 | **Multi-parens strip fix** | 21,819 (99.5%) | +199 | 113 | 114 |
| R8 | Add JP sync pass | 21,804 | -15 | 128 | 102 |
| R9 | Final (clean sync) | 21,804 (99.4%) | — | 128 | 102 |
| R10 | Bucket fallbacks + wiki-fix | 21,846 (99.6%) | +42 | 86 | 64 |
| R11 | Typographic+kana folds, P'S/art fallbacks, sync-corruption fix | 21,883 (99.8%) | +37 | 49 | 67 |
| R11b | cardName2JP (sideB) fallback + wiki-dupe form-0 fix + sync guard tightened to normalize-equality | 21,920 (99.95%) | +37 | 12 | 67 |
| R12 | Long-tail patches: wiki/DM kanji-variant fixes, 5 re-scraped wiki pages, awaken regex + 次元の prefix fallback | 21,932 main (100%) + 466/467 awaken (99.8%) | +12 main, +5 awaken | 0 main / 1 awaken | 63 |
| R13 | Twinpact-preferred lookup tiebreaker + EN-side serial-bracket cleanup (cardName/cardName2) | 21,932 main (100%) + 466/467 awaken (99.8%) | 0 net (already 100%); fixes 179 wrong-wiki reroutes + 191 dirty cardName2 | 0 main / 1 awaken | 63 |
| **R14** | **Wiki EN orphan-bracket cleanup — add missing `「` openers (30 auto-rule + 4 manual) to mirror JP bracketing** | **unchanged** | **0 net; cleans 34 wiki EN names + propagates to ~41 DM cards via refresh pass** | **0 main / 1 awaken** | **63** |

The R7 jump was the biggest single win: discovering that DM cardNameJP often
has *two* trailing parens groups — rubi `(ルビー・グラス)` followed by serial
`(DM18 55/140)` — and the original single-group regex only stripped the serial.

The R10 work decomposed the remaining unmatched into four named buckets and
addressed each: 19 cards fixed via GS-suffix fallback, 9 via latin-JP EN
fallback, ~14 via a targeted patch of 4 wiki entries whose scraper had leaked
the "This text is written in Forbidden Characters." tooltip (and mistranslated
the α/β/γ images as A/B/C), and 31 non-card wiki meta-pages (civilization /
character / set pages with empty `cards`) are now suppressed from the unmatched
report instead of counted as misses.

The R11 work expanded the normalizer with **safe typographic/kana folds** (`竜`↔`龍`,
all dash/wave variants → `-`, ASCII/curly/back-quote stripped, small ↔ regular
kana, hira ↔ kata, katakana ↔ Greek letter for the `終断` series), added two
more **suffix/bracket fallbacks** (`P'S` Play's reprints; dmart10
`<art name> [<inner JP>]` extraction), and surfaced and fixed a **JP-sync
corruption bug**: the EN-name and art-bracket fallbacks set `wikiurl` on cards
whose `cardNameJP` is a non-canonical surrogate (latin data-entry bug, or
art-card composite name); the subsequent JP-sync pass was pushing that
surrogate back into wiki `name_jp`, silently destroying the canonical
Japanese name and breaking strict-match for every sibling DM card. Fix: a
`_safe_to_sync` guard that skips sync when DM `cardNameJP` is latin-only
or contains `[`/`]`. Ten corrupted wiki entries (`Metel`, `Khuliang`,
`Tatsurion`, `Bad_Brand`, …) were restored from the original export.

Safety check before R11 landed: simulated every fold against the full dataset
and confirmed (a) no new wiki-side collision groups, (b) no already-matched
DM card silently rerouted to a different wiki URL.

The R11b work added a **cardName2JP (sideB) fallback** — twinpact DM cards
where side A has a kanji typo (`ファイン・撃・ピヨッチ` vs wiki `ファイン・襲・
ピヨッチ`) or an extra word (`戦武の無限皇 ジャッキー` vs wiki `戦武の無限
ジャッキー`) but side B is clean. Restricted to twinpact wiki entries via
`build_twinpact_jp_lookup` so the fallback can't accidentally pick a standalone
wiki entry that shares the same JP name as one half of a twinpact (e.g. wiki
has both `_Ghost_Touch` twinpact and standalone `Ghost_Touch`).

R11b also surfaced and fixed a **scraper bug in 17 wiki twinpact entries**: form
0's `name_jp` had been overwritten with form 1's `name_jp` at scrape time, so
e.g. `Neferkhanen / Time Stopon` showed both forms as `タイム・ストップン`. When
the sideB fallback fires AND the matched wiki has identical name_jp on both
forms (the dupe signature), DM's `cardNameJP` is pushed into wiki form 0
restoring the canonical JP. Self-heals: next run those cards strict-match (the
sideB count dropped from 37 → 18 on the second R11b run, with the remaining
18 being entries where form 0 has a distinct-but-typo'd name, not a dupe).

The R11 explicit latin/bracket sync guards were superseded by a single rule:
**sync only when DM JP and wiki JP normalize-match**. This covers every
strict-path match (rubi/serial differences after `strip_serial` still
normalize identically) and rejects every fallback-path match (GS / P'S /
art-bracket / latin-EN / sideB — these all produce non-matching normalized
keys by definition).

---

## Key bugs / variants found and fixed

| Variant | Example | Fix |
|---|---|---|
| Image-alt-rendered chars | wiki `<img alt="卍">` got dropped → `ギ・ルーギリン` instead of `卍ギ・ルーギリン卍` | `_text_with_img_alts` in `lib/wiki_card_scraper.py` |
| Wave dash | `〜` (U+301C) vs `～` (U+FF5E) | Manual fold `〜 → ~` post-NFKC |
| Fullwidth equals | `＝` vs `=` | NFKC handles |
| Curly vs ASCII quotes | `"…"` vs `"…"` | Manual fold |
| Middle-dot variants | `・` (U+30FB) vs `.` | Manual fold `・·• → .` |
| Case in latin chars | `禁断~解放せしx~` vs `禁断 ～解放せしX～` | `.casefold()` |
| Double trailing parens | `紅玉草(ルビー・グラス)(DM18 55/140)` | `(\s*\([^)]*\)\s*)+$` regex |
| EN-in-parens on wiki side | `怪力の化身(Avatar of Strength)` | Apply `strip_serial` to wiki side too |
| Reprints with diff cardNameJP | dm01-044 `紅玉草` vs dm18-055 `紅玉草(ルビー・グラス)` | Sync uses `strip_serial` so both → `紅玉草` |
| `_GS` reprint variant | DM `斬斬人形コダマンマ GS`, wiki only has `斬斬人形コダマンマ` | `strip_gs_variant` fallback (R10) |
| Latin-only DM JP name | dmex04-027 ships `cardNameJP="Bolshack Dragon"` | EN-name fallback against single-form non-twinpact wiki entries (R10) |
| Forbidden-char tooltip leak | wiki scraper produced `終断CThis text is written inForbidden Characters.ドルブロ` (α/β/γ → A/B/C + tooltip narration) | One-off regex patch on `dmwikifull_cleaned.json`; scraper at `lib/wiki_card_scraper.py` should be hardened to drop the tooltip and map A/B/C → α/β/γ for the `終断` series before the next full scrape (R10) |
| Wiki meta-page noise | `Card_Gamer`, `Choco_Crunch`, `Darkness_Civilization`, `Dragon_Saga`, `Fire_Civilization`, `_(Battle_Card)` stubs | Suppressed from `unmatched_wiki.json` when `cards` is empty (R10) |
| Simplified ↔ traditional kanji | DM `八頭竜 ACE-Yamata` vs wiki `八頭龍ACE-Yamata` | `_KANJI_FOLD = {'竜':'龍'}` in `normalize_jp_name` (R11) |
| Subtitle dash/wave family | DM `禁断 ー封印されしXー` vs wiki `禁断 ～封印されしX～` (long-vowel mark vs wave dash) | `_DASH_VARIANTS_RE` collapses `ー~–—` → `-` (R11) |
| Quote presence mismatch | DM `ラウド NYZ ノイジー` vs wiki `ラウド "NYZ" ノイジー` | Strip `"` `'` `` ` `` entirely from normalizer (R11) |
| Trailing underscore artifact | DM `【問１】 テック__` vs wiki `【問１】 テック` | `_TRAILING_UNDERSCORE_RE.sub('', s)` (R11) |
| Apostrophe vs backtick | DM `der'Zen Mondo` vs wiki `der`ZenMondo` | Backtick included in the same strip as quotes (R11) |
| Greek letter ↔ katakana spelling | DM `終断デルタ ドルハカバ` vs wiki `終断Δ ドルハカバ` | `_GREEK_KATA` map: デルタ↔Δ, アルファ↔Α, … (R11) |
| Small kana ↔ regular kana | DM `撃墜団長メッツアー` vs wiki `撃墜団長メッツァー`; `ウェスタン` vs `ウエスタン`; `ウィング` vs `ウイング` | `_SMALL_TO_BIG` translation table (R11) |
| Hiragana ↔ katakana for foreign names | DM `シンベロス` (kata) vs wiki `シンべロス` (hira `べ` inside kata word) | `_HIRA_TO_KATA` translation table covering U+3041–U+3096 (R11) |
| `P'S` (Play's) reprint variant | DM `ガイアール・カイザーP'S`, wiki only has `ガイアール・カイザー` | `strip_ps_variant` fallback, mirroring GS pattern (R11) |
| Art-card composite JP | DM `バンブルビー [切札勝太&カツキング ー熱血の物語ー]` (dmart10 series — Transformer art on top of a real card) | `extract_art_bracket` returns the inner `[...]`, matched against wiki (R11) |
| Awaken brace + side suffix | `{撃墜王ガイアール・キラードラゴン} Bottom`, `{雷獣ヴォルグ・ティーガー}` | `clean_awaken_name` strips `{…}` and ` Top`/` Bottom`/` side X` (R11) |
| JP-sync corruption from fallbacks | EN-fallback / art-fallback set `wikiurl` using a surrogate JP name; sync then overwrote the canonical wiki `name_jp` with that surrogate (`Metel`, `Khuliang`, `オプティマスプライム [“罰怒“ブランド]`) | `_safe_to_sync` skips latin-only and bracketed DM JP; corrupted entries restored from original wiki export (R11) |
| Twinpact sideA typo / extra word | DM `ファイン・撃・ピヨッチ` vs wiki `ファイン・襲・ピヨッチ` (撃/襲 kanji typo, 5 cards); DM `戦武の無限皇 ジャッキー` vs wiki `戦武の無限ジャッキー` (DM has extra `皇`, 3 cards); DM `めっちゃ！デンヂャラスG３` vs wiki `めっちゃ!デンジャラスG3` (4 cards) | `cardName2JP` (sideB) fallback against twinpact-only wiki lookup — finds the right wiki via the clean spell half (R11b) |
| Wiki form-0 name_jp scraper dupe | 17 twinpact wiki entries have form 0's `name_jp` overwritten with form 1's value (`Neferkhanen / Time Stopon` shows both as `タイム・ストップン`) | When sideB fires AND wiki form 0 jp == form 1 jp, push DM `cardNameJP` into wiki form 0 (R11b); self-heals to strict match on next run |
| Generalized sync-guard | Previous explicit latin/bracket skips were special cases of "the match wasn't strict" | Replaced with single normalize-equality check — sync only fires when DM JP and wiki JP already normalize to the same key, covering strict matches and rejecting every fallback path uniformly (R11b) |
| Long-tail manual patches | Black Lucifer (`dmc55-002` outlier `・`), Fonch the Oracle (預/予 kanji, wiki patch), New Generation (`promoy15-072` outlier 開→明), Return of the Twelves (musical-bar U+1D106 vs ASCII `:||`, wiki patch), Matsurida Wasshoi (`御興`→`御輿` wiki typo), Crasher Burn (`dm17-049` JP+EN both wrong, JP patched to wiki form) | Direct one-off edits to either DM or wiki cleaned JSON based on user-confirmed canonical form (R12) |
| Missing wiki coverage | `Dora_Godai`, `Danger_Sense:_This_way_ahead,_there_is_Redzone`, `Convoy,_Awakened_Commander`, `Recommend!_Haraguro_Festival!`, `Duema_Land_~Night_Parade~` — wiki pages exist on fandom but our original scrape didn't capture them | Re-scraped via `datacleaning/rescrape_two_wiki.py` (one-off helper calling the existing `DuelMastersCardWikiScraper.scrape_card` directly, no MongoDB roundtrip); inserted as full wiki docs with effects/race/illustrator populated (R12) |
| Awaken multi-suffix orphan | `激竜王ガイアール・オウドラゴン{side B} {Top}` — brace strip ran before side-suffix strip, leaving `side B Top` (no leading space) which the suffix regex required | Reorder brace strip first, then make side-suffix regex match ONE OR MORE consecutive side/top/bottom tokens (`(\s*(top\|bottom\|side\s+[A-Z]))+\s*$`) (R12) |
| Awaken `次元の` prefix outlier | 8 of 9 DM awaken cards with `次元の` prefix strict-match wiki (which also has the prefix); the 9th — `次元のメガ・イノセントソード` — points to wiki `Mega_Innocent_Sword` whose name_jp is `メガ・イノセントソード` (no prefix, shared with the non-awaken main-card variant `dm32-110`) | Added awaken-side fallback: when strict misses and JP starts with `次元の`, retry with the prefix stripped (R12) |
| Cloudflare-blocked wiki page | `Blankas` (DM `dmx22b-121` placeholder `Blank` awaken) — chromedriver crashes during the Cloudflare challenge handshake on this specific URL even when other duelmasters.fandom.com pages work | Left as-is (1 awaken unmatched); user resolving manually outside the pipeline (R12) |
| Single-form vs twinpact wiki collision | Wiki has separate pages for each form of a twinpact AND a combined twinpact page (e.g. `Dorbro,_Final_Forbidden_Gamma` single-form AND `_Bone_Dance_Charger` combined). 179 DM twinpacts strict-matched the single-form (insert-order winning) and left `cardName2` dirty because the single-form wiki has no form 1 to apply | `build_jp_lookup` now uses a tiebreaker: when two wiki entries collide on the same JP key, prefer the one with `is_twinpact=True`. DM twinpacts (which need both form names) now reliably route to the combined wiki entry (R13) |
| Serial brackets persisting in DM EN fields | The cleaner used `strip_serial` for *matching* but never wrote the stripped form back, so 191 `cardName2` fields kept the takaratomy `(DM24EX4 PR27/PR60)` serial bracket whenever the wiki had no form-1 to overwrite them | At the top of the per-card loop, apply the narrow `strip_dm_serial` (only `(DM…)` patterns) to `cardName`/`cardName2` so the two wiki EN names with legitimate trailing parens (`(For Live)`, `(Storm Awakening MAXIMUM Shinra Banshou)`) are preserved. **JP-side fields keep their serials intentionally** — `cardNameJP`/`cardName2JP` double as set/print references (e.g. `"終断γ ドルブロ (DM24EX4 PR27/PR60)"` lets you grep back to the exact takaratomy print). Matching and sync already call `strip_serial` themselves, so keeping the serial on JP fields has no impact on pipeline behavior (R13) |
| Wiki EN orphan closing brackets | 34 wiki EN names had a stray `」` with no matching `「` — scraper picked up the closing JP quote bracket but dropped the opener (e.g. `It's coming from the future, so it's a Miracle」`, `Behold, this is the essence of super science!」`) | One-off patch of `dmwikifull_cleaned.json`. Rule: when `count(「)` < `count(」)`, prefix `「` to each closer-delimited segment (handles single quotes AND multi-lyric strings). 30 auto-patched; 7 cases where only PART of the EN should be bracketed (e.g. `「GG」-001` codename inside `Glenglassaugh-Zerozeroone`, `Melody 3 「Temptation」` partial-wrap, `Let it Bee!」 Let it Bee !」` duplicate) hand-patched. DM cards pulling these EN names auto-refresh on next pipeline run via `apply_wiki_to_card`'s overwrite. Scraper hardening still pending (R14) |

---

## Re-running the full pipeline

From the repo root:

```bash
# 1. Strict match + refresh + sync
python datacleaning/clean_duelmasters_with_wiki.py

# 2. Generate fuzzy candidates
python datacleaning/fuzzy_match_unmatched.py
python datacleaning/fuzzy_match_metadata.py

# 3. Apply safe fuzzy matches (chain converges over 2-3 rounds)
python datacleaning/apply_fuzzy_matches.py                                          # name-only, ≥0.9
python datacleaning/apply_fuzzy_matches.py \
    --source datacleaning/fuzzy_matches_metadata.json \
    --min-ratio 0.4 --require-en-match                                              # metadata + EN safety

# 4. Reflow: re-run cleaner so applied changes propagate
python datacleaning/clean_duelmasters_with_wiki.py

# (loop steps 2-4 until counts stabilize)
```

To start fresh: delete `dmfull_cleaned.json` and `dmwikifull_cleaned.json`,
then re-run from step 1 — cleaner falls back to the original exports.

---

## Importing back to MongoDB

`dmfull_cleaned.json` and `dmwikifull_cleaned.json` are array-of-document JSON,
ready for `mongoimport` / `MongoService.upload_data` style re-insert into
`CL_duelmasters` and `CL_duelmasters_wiki` respectively. Each doc already has
`_id` from the original export.

**Recommended:** wipe the collection first or `replace_one({_id: ...}, doc,
upsert=True)` per doc, since cardName / type / effects / race / illustrator
may have changed across many cards.

---

## What's left (0 unmatched DM, 1 unmatched awaken, 63 unmatched wiki)

**Main: 100% match.** Only one awaken remains: `dmx22b-121`'s `Blank` placeholder
awaken pointing to the wiki page `Blankas`, which our scraper can't fetch
(chromedriver crashes inside the Cloudflare challenge handshake on that one
URL). Being resolved manually by the user.

The 63 unmatched wiki entries are the **reverse direction** — cards wiki has
that DM doesn't ship under the same JP. Mostly heroine-series, "Hideaway Hidden
Blade" series, twinpacts where neither half matches, and niche promo cards.
Needs wiki coverage on the DM side, not pipeline work.

---

## Historical: what was left before R12

Captured here for context — these patterns were all resolved during R12 by
user-confirmed wiki URL mappings + direct one-off edits to either DM or wiki
cleaned JSON.

The remaining 12 DM are individually intractable from a pipeline perspective —
each needs a manual or wiki-side fix:

| Booster | DM JP | Issue |
|---|---|---|
| dm25sp2 (2×) | `伍代ドーラ` | No wiki entry yet (new set) |
| dm25rp3 (2×) | `危識:この先、レッドゾーンあり` | No wiki entry yet (new set) |
| dmx16, dmr07 | `駱駝の御輿` | Wiki has `駱駝の御興` (kanji typo `輿`/`興`) |
| dmrp20-063 | `神聖十二神騎:||` | Wiki has `神聖十二神騎𝄇` (musical-repeat-bar `𝄇` U+1D106 vs DM ASCII `:||`) |
| dmc55-002 | `暗黒導師ブラック・ルシファー` | Wiki has `暗黒導師ブラックルシファー` (missing `・`) |
| dmc27, dm02 | `預言者フィンチ` | Wiki has `予言者フィンチ` (kanji variant `預`/`予`) |
| dm17-049 | `クラッシャー・ノヴァ` | No wiki entry (one-off promo) |
| promoy15-072 | `新時代の幕開け` | Wiki has `新時代の幕明け` (kanji variant `開`/`明`) |

The 預/予, 開/明, and 輿/興 cases are technically auto-fixable via a kanji-fold
table similar to `_KANJI_FOLD` for 竜/龍, but each pair has only 1–2 cards in
the corpus, and the kanji distinctions are not always synonymous outside these
specific names — risk of false positives across the 21,920 already-matched
cards outweighs the benefit.

The 6 unmatched awaken are mostly artifacts: `次元のメガ・イノセントソード`
(DM missing 1 `・`), `激竜王ガイアール・オウドラゴンside B Top` (orphan side
suffix the cleaner brace-strip left behind), one `Blank` placeholder, and 3
genuine no-wiki entries.

The 67 unmatched wiki are the **reverse direction**: cards wiki has that DM
doesn't ship under the same JP. Mostly heroine-series (`滝川るる&ラフルル`),
"Hideaway Hidden Blade" series (`裏斬隠`), "Galaxy" series (`愛銀河`), some
twinpacts where neither half matches, and ~30 niche / promo cards. These
need wiki coverage on the DM side, not pipeline work.

`fuzzy_match_unmatched.py` / `fuzzy_match_metadata.py` can still be re-run
against the current unmatched lists for manual review.
