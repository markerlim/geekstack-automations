# One-Time Clean: Riftbound Card Ability Text

## Goal
Fix the `ability` field on all existing Riftbound cards. The old scraper used `get_text(strip=True)` which stripped `<img>` glyph icons, producing broken text like `"payto"` instead of `"pay {Body Rune} to"`.

## Approach
Re-scrape every card from the Riftbound website using Selenium, extracting fresh HTML for the ability text and applying the new glyph-conversion logic (same as the fix already applied in `scrapers/riftbound/riftboundscrape.py`). Write the results back to the same JSON export file.

## Input
`riftbounddb/RB_UPDATED.json` — MongoDB export containing all existing cards with their current (broken) `ability` field.

## Output
The same file, overwritten with corrected `ability` fields. Other fields remain untouched.

## Implementation Steps

### 1. Create `datacleaning/clean_riftbound_ability.py`
Standalone script (not part of the main scraper). It will:

**a. Load cards** from `RB_UPDATED.json` into memory, preserving all fields.

**b. Re-scrape ability only** for each card:
- Use Selenium to navigate to `https://riftbound.leagueoflegends.com/en-us/card-gallery/#card-gallery--{code}`
- Wait for the lightbox to appear
- Find the `div[data-testid="rich-text"]` element
- Extract inner HTML, convert `<img>` glyphs to `{Glyph Name}` tokens using the same `replace_glyph()` function, join `<p>` tag text with `\n`
- Update the `ability` field in the in-memory card dict

**c. Handle failures gracefully**:
- If a card fails to load, log a warning and leave its `ability` unchanged
- Continue to next card

**d. Periodic progress saves**:
- Save every 50 cards to a temporary file (`RB_UPDATED_partial.json`) so progress isn't lost on crash

**e. Write final output**:
- Overwrite `RB_UPDATED.json` with the full corrected list
- Print summary: total cards, succeeded, failed

### 2. Reuse logic from the scraper
- Copy/import the `setup_selenium_driver()`, `navigate_to_card()`, and the `replace_glyph()` helper
- The scraper module can be imported via `sys.path` manipulation (same pattern already used in the codebase)

## Files Affected
- **Create**: `datacleaning/clean_riftbound_ability.py`
- **Output**: `riftbounddb/RB_UPDATED.json` (updated in place)

## Validation
1. Spot-check a sample of cards after the run to confirm glyphs appear as `{Glyph Name}`
2. Verify no existing fields (e.g. `urlimage`, `title`, `booster`) were accidentally modified
3. Confirm JSON is valid after write

## Risks / Caveats
- Selenium re-scrape of ~950+ cards will take significant time (~30-60 min depending on website speed)
- The Riftbound website or lightbox DOM structure may change — script may need adjustment for new selectors
- Cards with no rich-text ability field will remain unchanged (e.g., vanilla units with no abilities)
