"""
Union Arena TCG terminology and icon mappings.
Centralized storage for all Union Arena-specific card game terminology and alt text mappings.
"""

import re

# ========================
# UNION ARENA ALT TEXT MAPPINGS
# ========================
# Maps alt text from <img> tags to their English equivalents
# Used in card effect translations

ALT_TEXT_MAPPING = {
    'インパクト（1）': '[Impact 1]',
    'インパクト（2）': '[Impact 2]',
    'インパクト（3）': '[Impact 3]',
    'インパクト（4）': '[Impact 4]',
    'インパクト': '[Impact]',
    '2回ブロック': '[Block x2]',
    '2回アタック': '[Attack x2]',
    '狙い撃ち': '[Snipe]',
    'インパクト（+1）': '[Impact +1]',
    'ステップ': '[Step]',
    'ダメージ': '[Damage]',
    'ダメージ（+1）': '[Damage +1]',
    'ダメージ（2）': '[Damage 2]',
    'ダメージ（3）': '[Damage 3]',
    'ダメージ（4）': '[Damage 4]',
    'ダメージ（5）': '[Damage 5]',
    'ダメージ（6）': '[Damage 6]',
    'ダメージ（7）': '[Damage 7]',
    'インパクト無効': '[Impact Negate]',
    'ターン1': '[Once Per Turn]',
    'レストにする': '[Rest this card]',
    'このカードを退場させる': '[Retire this card]',
    '手札を1枚場外に置く': '[Place 1 card from hand to Outside Area]',
    '手札を2枚場外に置く': '[Place 2 cards from hand to Outside Area]',
    '手札を3枚場外に置く': '[Place 3 cards from hand to Outside Area]',
    'フロントLにある場合': '[When In Front Line]',
    'エナジーLにある場合': '[When In Energy Line]',
    '場外にある場合': '[When In Outside Area]',
    '除外エリアにある場合': '[When In Remove Area]',
    'APを1支払う': '[Pay 1 AP]',
    'レイド': '[Raid]',
    '登場時': '[On Play]',
    '退場時': '[On Retire]',
    'ブロック時': '[When Blocking]',
    '起動メイン': '[Activate Main]',
    'アタック時': '[When Attacking]',
    '自分のターン中': '[Your Turn]',
    '相手のターン中': "[Opponent's Turn]",
    'トリガー': '[Trigger]',
}

# ========================
# UNION ARENA TERMINOLOGY MAPPINGS
# ========================
# Maps Japanese game terminology to English equivalents

TERMINOLOGY_MAPPING = {
    # Add Union Arena specific terminology here
}

# Combine all mappings
ALL_MAPPINGS = {
    **ALT_TEXT_MAPPING,
    **TERMINOLOGY_MAPPING,
}


def apply_unionarena_mappings(text):
    """
    Apply pre-defined Union Arena mappings to text.
    Processes from longest to shortest keys to avoid partial replacements.
    
    Args:
        text (str): Text containing alt text or game terminology
        
    Returns:
        str: Text with mappings applied
    """
    if not text or text.strip() == '-':
        return text
    
    result = text
    # Sort by length (longest first) to avoid partial replacements
    sorted_terms = sorted(ALL_MAPPINGS.keys(), key=len, reverse=True)
    
    for jp_term in sorted_terms:
        english_term = ALL_MAPPINGS[jp_term]
        
        # Use word boundaries for matching
        pattern = re.escape(jp_term)
        
        def replace_with_spacing(match):
            start = match.start()
            end = match.end()
            
            # Add space before if needed
            space_before = ''
            if start > 0 and result[start - 1] not in ' \n\t':
                space_before = ' '
            
            # Add space after if needed
            space_after = ''
            if end < len(result) and result[end] not in ' \n\t':
                space_after = ' '
            
            return space_before + english_term + space_after
        
        result = re.sub(pattern, replace_with_spacing, result)
    
    return result


# ========================
# DISCORD TRANSLATION CLEANUP
# ========================
# Community (Discord card_list) translations are written for humans: costs and
# conditions are italicised (_Rest_), and a few tags are named differently from
# the DB vocabulary above. clean_discord_effect() rewrites that text into the
# same bracket-tag style the AI-translated / ALT_TEXT_MAPPING cards use.

# "_Rest_" style tokens (lower-cased key) -> DB tag. Costs/conditions only;
# unknown ones fall through to the generic rules in clean_discord_effect().
DISCORD_UNDERSCORE_MAP = {
    'rest': '[Rest this card]',
    'retire this card': '[Retire this card]',
    'pay 1 ap': '[Pay 1 AP]',
    'place 1 card from hand to outside area': '[Place 1 card from hand to Outside Area]',
    'place 2 cards from hand to outside area': '[Place 2 cards from hand to Outside Area]',
    'place 3 cards from hand to outside area': '[Place 3 cards from hand to Outside Area]',
}

# [Tag] spelled differently on Discord -> DB spelling (lower-cased key)
DISCORD_TAG_ALIASES = {
    'impact cancel': '[Impact Negate]',
    'double attack': '[Attack x2]',
    'double block': '[Block x2]',
    'once per turn': '[Once Per Turn]',
}

# /Raid/ style keywords (lower-cased key) -> DB tag
DISCORD_SLASH_MAP = {
    'raid': '[Raid]',
}

_SLASH_TOKEN_RE = re.compile(r'(?<![\w/])/([A-Za-z][^/\n]{1,30}?)/(?![\w/])')
_ONCE_PER_TURN_RE = re.compile(r'\(\s*once per turn\s*\)', re.IGNORECASE)
_UNDERSCORE_TOKEN_RE = re.compile(r'(?<![\w])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w])')
_BRACKET_TAG_RE = re.compile(r'\[([^\]\n]+)\]')
_IN_AREA_RE = re.compile(r'^in (?:the )?(.+)$', re.IGNORECASE)


def clean_discord_effect(text, unmapped=None):
    """Normalise a Discord-posted effect into DB tag style. Idempotent.

    - strips stray code fences / backticks left by code-block posts
    - `_Rest_` -> `[Rest this card]` via DISCORD_UNDERSCORE_MAP
    - `_In Front Line_` -> `[When In Front Line]` (any `_In <area>_`)
    - other `_x_` -> `[x]` and reported through `unmapped` (a set) for review
    - `[Impact Cancel]` etc. -> DB spelling via DISCORD_TAG_ALIASES
    - `/Raid/` -> `[Raid]` (DISCORD_SLASH_MAP); `(Once Per Turn)` -> `[Once Per Turn]`
    - collapses repeated spaces and blank lines (the DB uses single newlines)
    """
    if not text:
        return text
    out = text.replace('```', '').replace('`', '')

    def underscore(m):
        inner = m.group(1).strip()
        key = inner.lower()
        if key in DISCORD_UNDERSCORE_MAP:
            return DISCORD_UNDERSCORE_MAP[key]
        a = _IN_AREA_RE.match(inner)
        if a:
            return f'[When In {a.group(1).strip()}]'
        if unmapped is not None:
            unmapped.add(inner)
        return f'[{inner}]'

    out = _UNDERSCORE_TOKEN_RE.sub(underscore, out)

    def slash(m):
        inner = m.group(1).strip()
        if inner.lower() in DISCORD_SLASH_MAP:
            return DISCORD_SLASH_MAP[inner.lower()]
        if unmapped is not None:
            unmapped.add(f'/{inner}/')
        return m.group(0)

    out = _SLASH_TOKEN_RE.sub(slash, out)
    out = _ONCE_PER_TURN_RE.sub('[Once Per Turn]', out)
    out = _BRACKET_TAG_RE.sub(
        lambda m: DISCORD_TAG_ALIASES.get(m.group(1).strip().lower(), m.group(0)), out)
    out = re.sub(r'[ \t]{2,}', ' ', out)
    out = '\n'.join(ln.rstrip() for ln in out.split('\n'))
    out = re.sub(r'\n{2,}', '\n', out).strip()
    return out

