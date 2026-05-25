import requests
import re
import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

WIKI_API = "https://duelmasters.fandom.com/api.php"
WIKI_BASE = "https://duelmasters.fandom.com/wiki/"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'duelmasterdb', 'wiki_sets.json')
SOURCE_URL = "https://duelmasters.fandom.com/wiki/List_of_Duel_Masters_OCG_Sets"
PAGE_NAME = "List_of_Duel_Masters_OCG_Sets"

# Top-level category boundaries (ordered so we can slice the text)
CATEGORIES = [
    ("Booster Packs",     "==[[Booster Packs]]=="),
    ("Other Sets",        "==Other Sets=="),
    ("Fabulous Art",      "==[[Fabulous Art]]=="),
    ("Promotional Packs", "==Promotional Packs=="),
]
STOP_MARKER = "==Other=="

# Regex to extract a set code embedded at the start of a link title
# e.g. "DMART-01 Fabulous Art: Name" or "DMR-07 Golden Dragon: CoroCoro Edition"
CODE_IN_TITLE_RE = re.compile(r'^([A-Za-z極]+-\d+\S*)\s+(.+)$')


def fetch_wikitext(page: str) -> str:
    params = {
        "action": "parse",
        "page": page,
        "prop": "wikitext",
        "format": "json",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    response = requests.get(WIKI_API, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    return data["parse"]["wikitext"]["*"]


def extract_wiki_url(link_target: str) -> str:
    page_title = link_target.strip().replace(' ', '_')
    return WIKI_BASE + page_title


def clean_link_display(s: str) -> str:
    """Return display text from [[Target|Display]] or [[Target]]."""
    s = re.sub(r'\[\[([^|\]]+)\|([^\]]+)\]\]', r'\2', s)
    s = re.sub(r'\[\[([^\]]+)\]\]', r'\1', s)
    return s.strip()


def clean_templates(s: str) -> str:
    s = re.sub(r'\{\{[^}]*\}\}', '', s)
    s = re.sub(r'\[\[File:[^\]]+\]\]', '', s)
    return s.strip()


def clean_name(s: str) -> str:
    s = clean_link_display(s)
    s = clean_templates(s)
    s = re.sub(r"'''", '', s)
    return s.strip(" :'")


def get_link_target(raw: str) -> str | None:
    """Extract the wiki page target from the first [[...]] in a string."""
    m = re.search(r'\[\[([^|\]#\{]+)(?:\|[^\]]+)?\]\]', raw)
    if not m:
        return None
    target = m.group(1).strip()
    # Skip File: links
    if target.startswith('File:'):
        return None
    return target


def parse_set_line_with_code(code: str, raw_value: str) -> dict:
    """Parse a line that has an explicit '''CODE''': [[...]] format."""
    link_target = get_link_target(raw_value)
    name = clean_name(raw_value)
    url = extract_wiki_url(link_target) if link_target else None
    return {"set_code": code, "name": name, "url": url}


def parse_set_line_no_code(raw_value: str) -> dict:
    """Parse a *[[Link]] line where the code may be embedded in the link title."""
    link_target = get_link_target(raw_value)
    if not link_target:
        return None

    url = extract_wiki_url(link_target)
    display = clean_name(raw_value)

    # Try to extract a code from the start of the link target
    m = CODE_IN_TITLE_RE.match(link_target)
    if m:
        code = m.group(1)
        name = m.group(2).strip()
    else:
        code = None
        name = display

    return {"set_code": code, "name": name, "url": url}


def parse_section(text: str, category: str) -> list:
    sets = []
    current_series = None
    current_block = None

    for line in text.splitlines():
        line = line.rstrip()

        # Skip the category header line itself
        if re.match(r'^==[^=]', line):
            continue

        # Series header: ===DM Packs===
        series_m = re.match(r'^===(.+?)===$', line)
        if series_m:
            current_series = clean_name(series_m.group(1))
            current_block = None
            continue

        # Block header: '''[[Beginner's Block]]''' (no * prefix)
        if re.match(r"^'''", line) and not line.startswith('*'):
            block_m = re.match(r"^'''(.+?)'''", line)
            if block_m:
                current_block = clean_name(block_m.group(1))
            continue

        # Format A: *'''CODE''': [[Link]]
        set_m = re.match(r"^\*+'''([^']+)''':\s*(.+)", line)
        if set_m:
            code = set_m.group(1).strip()
            raw_value = set_m.group(2).strip()
            entry = parse_set_line_with_code(code, raw_value)
            entry.update({
                "category": category,
                "series": current_series,
                "block": current_block,
            })
            if line.startswith('**'):
                entry["variant"] = True
            sets.append(entry)
            continue

        # Format B: *[[Link]] (no explicit code)
        no_code_m = re.match(r'^\*+\[\[(.+)', line)
        if no_code_m:
            entry = parse_set_line_no_code(line.lstrip('*').strip())
            if entry:
                entry.update({
                    "category": category,
                    "series": current_series,
                    "block": current_block,
                })
                sets.append(entry)

    return sets


def parse_all_sets(wikitext: str) -> list:
    stop_pos = wikitext.find(STOP_MARKER)
    relevant = wikitext[:stop_pos] if stop_pos != -1 else wikitext

    all_sets = []

    for i, (category, marker) in enumerate(CATEGORIES):
        start = relevant.find(marker)
        if start == -1:
            continue
        # End at the next category marker or end of text
        end = len(relevant)
        for _, next_marker in CATEGORIES[i + 1:]:
            pos = relevant.find(next_marker, start + 1)
            if pos != -1:
                end = min(end, pos)
                break
        # Also stop at STOP_MARKER
        if stop_pos != -1:
            end = min(end, stop_pos)

        section_text = relevant[start:end]
        section_sets = parse_section(section_text, category)
        all_sets.extend(section_sets)
        print(f"  {category}: {len(section_sets)} sets")

    return all_sets


def scrape_ocg_sets():
    print(f"Fetching wikitext from: {SOURCE_URL}")
    wikitext = fetch_wikitext(PAGE_NAME)

    print("Parsing all sets...")
    sets = parse_all_sets(wikitext)
    print(f"Total: {len(sets)} sets")

    output = {
        "source": SOURCE_URL,
        "total": len(sets),
        "sets": sets,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved to {OUTPUT_PATH}")
    return output


if __name__ == "__main__":
    scrape_ocg_sets()
