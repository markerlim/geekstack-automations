# Duel Masters Data Cleanup

One-off cleanup pass that took a MongoDB export of `CL_duelmasters` (21,932 cards)
and `CL_duelmasters_wiki` (11,830 docs) and produced cleaned, cross-consistent
re-import files. Match rate improved from a pre-existing baseline to **99.4%
main + 98.3% awaken** through 9 rounds of iterative matching, fuzzy detection,
and apply-and-reflow.

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
lists.

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
| **R9** | **Final (clean sync)** | **21,804 (99.4%)** | — | **128** | **102** |

The R7 jump was the biggest single win: discovering that DM cardNameJP often
has *two* trailing parens groups — rubi `(ルビー・グラス)` followed by serial
`(DM18 55/140)` — and the original single-group regex only stripped the serial.

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

## What's left (128 unmatched DM, 102 unmatched wiki)

Concentrated in old sets where wiki coverage is genuinely thin:
- `dm18, dm10, dm11, dm09, dm06, dm12` — DM-01 through DM-18 era
- `dmrp19, dmc34, dmpcd03, dmart10` — niche promo / art sets

These are **bucket 1** (no wiki entry exists for the card). The fuzzy /
metadata matchers can't help; only adding the wiki entries themselves
(or scraping a wiki source we don't currently visit) will resolve them.
