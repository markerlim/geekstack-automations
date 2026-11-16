# Duel Masters Scrapers

## Quick commands

Run everything from the repo root (`geekstack-automations/`) with the venv (`venv/bin/python3`, shown below as `python`).

**Weekly card/cover check** (what the cron runs — Pipeline A + B):

```
python scrapers/duelmasters/main.py
```

Also runs on GitHub Actions every Sat 18:00 SGT (`.github/workflows/dmscrape.yml`, can be triggered manually).
It only scrapes boosters that are on the takaratomy dropdown but missing from `series.json`.

**Re-scrape a booster** (code is the dropdown value, no `dm` prefix; overwrites that booster in Mongo, with backup):

```
python scrapers/duelmasters/scripts/rescrape_booster.py 26ex1
python scrapers/duelmasters/scripts/rescrape_booster.py 25ex4 26rp1 26sd1
```

**Wiki data** (English text; run before B for a new set, so wiki lookups hit):

```
python scrapers/duelmasters/pipelines/c_scrape_wiki_cards.py                    # all cards not yet in CL_duelmasters_wiki
python scrapers/duelmasters/pipelines/c_scrape_wiki_cards.py --test             # first 3 cards only
python scrapers/duelmasters/pipelines/c_scrape_wiki_cards.py --set-url <wiki set page URL> [--set-code CODE]
python scrapers/duelmasters/pipelines/c_scrape_wiki_cards.py --rescrape --workers 3 [--limit N]   # redo every doc, resumable
python scrapers/duelmasters/pipelines/d_apply_wiki_to_booster.py dm26ex2        # apply wiki to an already-scraped booster
```

**Prices** (fullahead-dm.com -> match to `CL_duelmasters` -> Mongo `price_fau`), via the root Makefile:

```
make dm-prices                    # scrape every DB booster the shop has + upload
make dm-prices-nodb               # scrape + match only; writes pricescraper/out/fau_*.json, no DB write
make dm-prices-set SET=DM26-EX4   # one booster, scrape + match only
make dm-prices-upload             # upload the fau_normalised.json already on disk
make dm-prices MIN_SET=24         # skip boosters older than dm24 (default 22)
```

Review `pricescraper/out/fau_match_report.json` (unmatched / ambiguous / fuzzy) before uploading.
Direct equivalent: `python scrapers/duelmasters/scripts/match_fullahead.py --all --min-set 22`
(also `--db-json FILE`, `--no-write`, `--delay SECS`).

**Retry failed wiki link scrapes** (setup step 2 backlog):

```
python scrapers/duelmasters/scripts/retry_backlog_card_links.py
```

---

Folder layout:

```
scrapers/duelmasters/
├── main.py                          # weekly cron entry — runs Pipeline A + B
├── lib/
│   └── wiki_card_scraper.py         # DuelMastersCardWikiScraper class (shared)
├── pipelines/
│   ├── a_scrape_covers.py           # Pipeline A — booster covers
│   ├── b_scrape_cards.py            # Pipeline B — card data (takaratomy.co.jp)
│   ├── c_scrape_wiki_cards.py       # Pipeline C — bulk wiki card scrape
│   └── d_apply_wiki_to_booster.py   # Pipeline D — retroactive wiki mapping
├── setup/                           # one-time, run in order to build the URL list
│   ├── 1_scrape_set_list.py
│   ├── 2_scrape_card_links.py
│   └── 3_dedupe_card_urls.py
└── scripts/
    ├── rescrape_booster.py          # CLI — re-run Pipeline B for one booster
    └── wiki_scraper_upload.py       # legacy per-booster wiki scrape
```

---

## Recommended run order for a new set

1. **Pipeline C** (`pipelines/c_scrape_wiki_cards.py`) — populates `CL_duelmasters_wiki` from the fandom wiki.
2. **Pipeline A + B** via `main.py` (also what the cron runs) — covers + card data, wiki lookup will hit.
3. If some cards had no wiki match, add them to the wiki then run **Pipeline D** (`pipelines/d_apply_wiki_to_booster.py`) for that booster.

The setup pipeline (`setup/`) only needs to run if `duelmasterdb/wiki_unique_cards.json` is missing or stale.

---

## Automation entry point (`main.py`)

GitHub Action: `.github/workflows/dmscrape.yml` runs weekly (Sat 18:00 SGT).

```
__main__
  ├── duelmaster_cover_scrape()   ← Pipeline A
  └── run_check()                 ← Pipeline B
```

---

## Pipeline A — Cover scrape (`pipelines/a_scrape_covers.py`)

Goal: detect new product releases and store their cover image + metadata.

```
duelmaster_cover_scrape()
  │
  ├─ Load last_pdt_date.json from GitHub        # per-category watermark
  │
  ├─ For each category: [deck, expansion, others]
  │   ├─ Paginate dm.takaratomy.co.jp/product/{category}/page/{n}
  │   ├─ Parse items: booster code, title (JP), release date, cover img URL
  │   ├─ Skip products older than last watermark date
  │   ├─ If booster NOT in CL_duelmasters → mark category as "{key}_unreleased"
  │   ├─ Upload cover image to GCS: boostercover/duelmaster/{booster}
  │   └─ Append to category_new_products[]
  │
  ├─ mongo_service.upload_data(category_new_products, "NewList")
  └─ Update last_pdt_date.json on GitHub with latest release date
```

Booster code is extracted from the cover image URL path (e.g. `dm25ex4` from `.../dm25ex4.jpg`). `playsdeck` URLs get remapped to `dmpcd01`, `dmpcd02`, etc.

---

## Pipeline B — Card scrape (`pipelines/b_scrape_cards.py`)

Goal: scrape full card data for any series not yet in `series.json`.

```
run_check()                                     # in main.py
  ├─ Load series.json from GitHub               # list of known booster codes
  ├─ Scrape website products dropdown           # live list from dm.takaratomy.co.jp/card/
  ├─ find_missing_values(known, live)           # set difference
  │
  ├─ [if missing]
  │   ├─ startscraping(booster_list)            # ← pipelines/b_scrape_cards.py
  │   └─ Update series.json on GitHub
  │
  └─ [if none missing] done
```

### `startscraping()` internals

```
startscraping(booster_list)
  │
  ├─ Launch headless Chrome (Selenium)
  │
  ├─ For each booster:
  │   │
  │   ├─ scrape_all_pages(driver, booster)
  │   │   └─ Paginate /card/?v=...products={booster}...
  │   │       For each card li: extract [card_id, image_url, detail_url]
  │   │       Stop on 2 consecutive empty pages
  │   │
  │   ├─ scrape_card_details(card_data)
  │   │   ├─ Load civilization.json + type.json mappings from GitHub
  │   │   └─ For each card:
  │   │       ├─ process_card(): upload card image to GCS DMTCG/{booster}/
  │   │       ├─ GET detail_url → BeautifulSoup parse
  │   │       ├─ Count cardDetail divs vs images to classify:
  │   │       │     1 detail  → Single Form
  │   │       │     2 details, 1 image → Twinpact (spell+creature)
  │   │       │     N details, N images → Awaken (evolution forms)
  │   │       ├─ Extract main fields: name, type, civilization, rarity,
  │   │       │     power, cost, mana, race, illustrator, effects
  │   │       ├─ For Twinpact: extract type2/civilization2/race2/effects2
  │   │       └─ For Awaken: build awaken[] array with per-form data + GCS upload
  │   │
  │   ├─ backup_jp_fields()                     # cardName→cardNameJP, etc.
  │   │
  │   ├─ Build jp_name_lookup from CL_duelmasters_wiki (all docs)
  │   │     key = card.name_jp with spaces stripped
  │   │
  │   ├─ For each card: match cardName (JP) → wiki doc
  │   │   ├─ [matched] apply_wiki_data()
  │   │   │     Overwrites: cardName, type, effects, race (EN from wiki)
  │   │   │     Twinpact: also cardName2, type2, effects2, race2
  │   │   │     Awaken: backed up JP, overwrites EN fields per awaken form
  │   │   │     Sets card.wikiurl
  │   │   └─ [not matched] add to cards_needing_translation[]
  │   │
  │   ├─ [if unmatched cards] translate_data()
  │   │     Fields: cardName, cardName2, effects, effects2, race, race2
  │   │     Lang: ja → en, batch=100, max_retries=3
  │   │     Saves unmapped_cards.json for inspection
  │   │
  │   └─ mongo_service.upload_data(all_final_data, C_DUELMASTERS, backup=True)
  │       Also: update NewList category field (strip "_unreleased" suffix)
  │
  └─ driver.quit()
```

**Wiki pre-fetch.** After the "new cards" filter and before the wiki lookup, `startscraping()` calls `ensure_wiki_for_booster()` (in `pipelines/c_scrape_wiki_cards.py`). It maps the booster code (`26ex5` / `dm26ex5` -> `DM26-EX5`), opens `https://duelmasters.fandom.com/wiki/DM26-EX5` (redirects to the full set page; `wiki_sets.json` URL is the fallback), and upserts any card pages not yet in `CL_duelmasters_wiki`, so the JP-name match below hits for a brand-new set. It never raises: a missing, blocked or half-filled set page just means fewer wiki hits, and the next run retries. Irregular legacy codes (`9`, `ex08`, `c66`, `promoy*`) are skipped.

To rescrape one booster manually: `python scrapers/duelmasters/scripts/rescrape_booster.py 26ex1`.

**Booster code source of truth:** the `<option value="...">` attribute in the products dropdown at [dm.takaratomy.co.jp/card/](https://dm.takaratomy.co.jp/card/) — e.g. value `26ex1` (label `DM26-EX1 ますますつよいパック 25の援軍`). No `dm` prefix. The same codes are what `series.json` stores.

---

## Pipeline C — Wiki bulk scrape (`pipelines/c_scrape_wiki_cards.py`)

Goal: pre-populate `CL_duelmasters_wiki` with English card data from the Duel Masters fandom wiki. Run this **before** Pipeline B so wiki lookups succeed.

Reads `duelmasterdb/wiki_unique_cards.json`, skips URLs already in `CL_duelmasters_wiki`, and scrapes the remaining card pages with a **fresh Selenium driver per card** (reusing one driver causes Chrome OOM crashes on fandom pages).

Test (3 cards): `python scrapers/duelmasters/pipelines/c_scrape_wiki_cards.py --test`.

Uploads to MongoDB in batches of 10. `is_twinpact: true` cards have 2 entries in the `cards` array (creature form + spell form).

```json
{
  "url": "https://duelmasters.fandom.com/wiki/Aqua_Hulcus",
  "is_twinpact": false,
  "cards": [
    {
      "name": "Aqua Hulcus",
      "name_jp": "アクア・ハルカス",
      "civilization": "Water",
      "card_type": "Creature",
      "mana_cost": "3",
      "race": "Liquid People",
      "power": "1000",
      "mana_number": "1",
      "english_text": "■ When you put this creature into the battle zone, draw a card.",
      "japanese_text": "■ このクリーチャーをバトルゾーンに出した時、カードを1枚引く。",
      "illustrator": "Naoki Saito"
    }
  ]
}
```

---

## Pipeline D — Post-processing wiki mapping (`pipelines/d_apply_wiki_to_booster.py`)

Utility script to retroactively apply wiki data to an already-scraped booster in `CL_duelmasters`. Run manually when wiki data arrives late.

```
ProcessWikiMapping (standalone __main__)
  ├─ getAllCardForBooster(booster_id)            # query CL_duelmasters
  ├─ extractUniqueWikiLinksFromCards(cards)      # collect all wikiurl values incl. awaken
  ├─ getCardsFromWikiUrls(wiki_urls)             # query CL_duelmasters_wiki
  ├─ update_card_with_wiki_data(card, wiki_card, wiki_map)
  │     Updates: cardName, type, effects, cardName2, type2, effects2
  │     Awaken: backs up JP, applies EN from its own wikiurl lookup
  └─ normalize_data_format(cards)
        - race: string → array
        - remove stale "effect" field (keep "effects")
        - _id: string → {$oid: ...}
```

---

## First-time setup (`setup/`)

Builds the deduplicated list of every card wiki page URL across all OCG sets. Prerequisite to Pipeline C if `duelmasterdb/wiki_unique_cards.json` doesn't exist yet.

| Step | Script | Output |
|---|---|---|
| 1 | `setup/1_scrape_set_list.py` | `duelmasterdb/wiki_sets.json` (all OCG sets with metadata + wiki URLs) |
| 2 | `setup/2_scrape_card_links.py` | `duelmasterdb/wiki_set_cards.json` (per-set card link lists) |
| 3 | `setup/3_dedupe_card_urls.py` | `duelmasterdb/wiki_unique_cards.json` (deduped card URL list) |

Step 2 uses a **fresh Selenium driver per page** (required — fandom blocks plain HTTP requests with 403, and reusing one driver across pages causes Chrome OOM crashes). Results save incrementally after each set — safe to interrupt and resume. Sets that fail are saved with an `"error"` field and recorded in `duelmasterdb/backlog.json`.

Test step 2 (1 set): `python scrapers/duelmasters/setup/2_scrape_card_links.py --test`.

---

## Data stores

| Store | Type | Purpose |
|---|---|---|
| `CL_duelmasters` | MongoDB | Primary card collection (final output) |
| `CL_duelmasters_wiki` | MongoDB | Wiki-scraped English card data (lookup source) |
| `NewList` | MongoDB | Booster product covers + release metadata |
| `duelmasterdb/series.json` | GitHub | Watermark — known booster codes |
| `duelmasterdb/last_pdt_date.json` | GitHub | Per-category last cover scrape date |
| `duelmasterdb/civilization.json` | GitHub | JP → EN civilization name mapping |
| `duelmasterdb/type.json` | GitHub | JP → EN card type mapping |
| `GCS DMTCG/{booster}/` | GCS | Card face images |
| `GCS boostercover/duelmaster/` | GCS | Booster pack cover images |

---

## Card schema (`CL_duelmasters`)

```
cardUid          e.g. "dm25ex4-001"
booster          e.g. "dm25ex4"
cardName         EN name (from wiki) or translated JP name
cardNameJP       original JP name (backed up before wiki overwrite)
cardName2        second form name (Twinpact only)
type / typeJP    card type EN / JP
civilization[]   EN civilization list
civilizationJP[] JP civilization list
rarity
power / powerInt
cost
mana
race[]           EN race list
raceJP[]         JP race list (backed up)
effects          EN ability text
effectsJP        JP ability text (backed up)
illustrator
wikiurl          fandom wiki URL (if matched)
urlimage         GCS URL for card image
awaken[]         list of evolution forms (Awaken cards only)
  └─ {cardName, cardNameJP, urlimage, type, civilization[], power,
       cost, mana, race[], effects, effectsJP, wikiurl}
```
