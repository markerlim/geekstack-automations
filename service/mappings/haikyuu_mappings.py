"""
Haikyuu BREAK TCG terminology and translation mappings.
Centralized storage for all Haikyuu-specific card game terminology.
"""

import re

# ========================
# HAIKYUU BREAK TERMINOLOGY MAPPINGS
# ========================

# Card Parameters
PARAMETER_MAPPING = {
    "サーブポイント": "Serve Point",
    "ブロックポイント": "Block Point",
    "レシーブポイント": "Receive Point",
    "トスポイント": "Toss Point",
    "アタックポイント": "Attack Point",
}

# Game Areas/Zones
AREA_MAPPING = {
    "サーブエリア": "Serve Area",
    "ブロックエリア": "Block Area",
    "レシーブエリア": "Receive Area",
    "トスエリア": "Toss Area",
    "アタックエリア": "Attack Area",
    "ドロップエリア": "Drop Area",
    "コート": "Court",
    "手札": "Hand",
}

# Phase/Turn timing
PHASE_MAPPING = {
    "サーブフェイズ": "Serve Phase",
    "ブロックフェイズ": "Block Phase",
    "ドローフェイズ": "Draw Phase",
    "レシーブフェイズ": "Receive Phase",
    "トスフェイズ": "Toss Phase",
    "アタックフェイズ": "Attack Phase",
    "ターン開始時": "At the start of turn",
    "ターン終了時": "At the end of turn",
    "フェイズ開始時": "At the start of phase",
    "フェイズ終了時": "At the end of phase",
}

# Common game action terms
GAME_ACTION_MAPPING = {
    "登場": "Deploy",
    "ロスト": "Lost",
    "ガッツ": "Guts",
    "キャラ": "Character",
    "ドロップ": "Drop",
    "手札に加える": "Add to Hand",
    "デッキに戻す": "Return to Deck",
    "シャッフル": "Shuffle",
    "公開する": "Reveal",
    "選ぶ": "Choose",
    "無効": "Negate",
    "待機状態": "Standby State",
}

# Trigger/Condition keywords
TRIGGER_MAPPING = {
    "登場した時": "When deployed",
    "登場するたび": "Each time deployed",
    "ロストした時": "When Lost is declared",
    "カードを引くたび": "Each time a card is drawn",
    "インターバル中": "During Interval",
    "このセット中": "During this Set",
    "このターン中": "During this turn",
    "このフェイズ中": "During this phase",
    "代わりに": "Instead",
    "そうした場合": "If you do",
}

# Haikyuu-specific keywords
KEYWORD_MAPPING = {
    "ドシャット": "Stuff Block",
    "ワンタッチ": "One Touch",
    "フェイント": "Feint",
    "ブロックアウト": "Block Out",
    "ターン1": "Turn 1",
    "Aパス": "A Pass",
    "ツーアタック": "Two Attack"
}

# Combine all mappings for easy access
ALL_MAPPINGS = {
    **PARAMETER_MAPPING,
    **KEYWORD_MAPPING,
    **AREA_MAPPING,
    **PHASE_MAPPING,
    **GAME_ACTION_MAPPING,
    **TRIGGER_MAPPING,
}


def apply_terminology_mappings(text):
    """
    Apply pre-defined Haikyuu terminology mappings to Japanese text.
    Processes from longest to shortest keys to avoid partial replacements.
    Automatically adds spaces around mapped terms when needed.
    
    Args:
        text (str): Japanese text containing game terminology
        
    Returns:
        str: Text with terminology replaced by English equivalents
    """
    if not text or text.strip() == '-':
        return text
    
    result = text
    # Sort by length (longest first) to avoid partial replacements
    sorted_terms = sorted(ALL_MAPPINGS.keys(), key=len, reverse=True)
    
    for jp_term in sorted_terms:
        english_term = ALL_MAPPINGS[jp_term]
        
        # For single-character terms, use word boundaries
        if len(jp_term) == 1:
            pattern = r'\b' + re.escape(jp_term) + r'\b'
        else:
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


def apply_cardname_consistency_for_translation(effectsJP_text, cardname_mapping):
    """
    Apply cardName substitutions to effectsJP text for translation purposes ONLY.
    This creates a modified copy without changing the original data.
    
    Args:
        effectsJP_text (str): Original Japanese effects text
        cardname_mapping (dict): Mapping of Japanese cardName -> English cardName
    
    Returns:
        str: Modified text with cardNames replaced for translation
    """
    modified_effects = effectsJP_text
    
    # Replace any cardNames that appear in effects with their English translations
    for jp_name, en_name in cardname_mapping.items():
        if jp_name in modified_effects:
            modified_effects = modified_effects.replace(jp_name, en_name)
    
    return modified_effects


# ========================
# ICON TO TEXT MAPPINGS
# ========================

# Icon names to phase/keyword mappings
# These represent the icon keywords (ignoring suffixes like _01, _02, _p, _w, etc.)
ICON_KEYWORD_MAPPING = {
    "onetouch": "One Touch",
    "doshut": "Stuff Block",
    "twoattack": "Two Attack",
    "apass": "A Pass",
    "blockout": "Block Out",
    "turn": "Turn",
    "feint": "Feint",
    # Phase keywords
    "draw": "Draw Phase",
    "receive": "Receive Phase",
    "toss": "Toss Phase",
    "attack": "Attack Phase",
    "block": "Block Phase",
    "serve": "Serve Phase",
}

# Keywords that should retain their numeric suffix
ICON_KEYWORDS_WITH_NUMBER = {
    "onetouch",
    "doshut",
    "twoattack",
    "blockout",
    "turn",
}

# Keywords that should retain any suffix (numeric or letter like N, P, etc.)
ICON_KEYWORDS_WITH_SUFFIX = {
    "feint",
}

# Icon location/context suffixes (e.g., tefuda = from hand/hand area)
ICON_SUFFIX_MAPPING = {
    "tefuda": "From Hand",
    "itadaki": "From Top",
}

# Icon app area keywords for expansion
# Used to detect combined areas (e.g., servetoss = serve + toss)
ICON_AREA_KEYWORDS = {
    "serve": "Serve Area",
    "attack": "Attack Area",
    "receive": "Receive Area",
    "block": "Block Area",
    "toss": "Toss Area",
}


def process_icons_in_text(text):
    """
    Process icon placeholders in text and convert them to readable keywords.
    
    Icons fall into two categories:
    1. Area icons: icon_app_* → [Area Name(s)]
    2. Keyword/Phase icons: icon_* → [Keyword/Phase Name]
    
    Examples:
        [icon_app_servetossarea] → [Serve Area] [Toss Area]
        [icon_draw] → [Draw Phase]
        [icon_onetouch_03] → [One Touch]
    
    Args:
        text (str): Text containing icon placeholders
    
    Returns:
        str: Text with icons replaced by readable names
    """
    if not text or text.strip() == '-':
        return text
    
    # Pattern to find all [icon_...] placeholders
    icon_pattern = r'\[icon_([^\]]+)\]'
    
    def replace_icon(match):
        icon_full = match.group(1)  # e.g., "app_servetossarea" or "draw_p"
        
        # Handle app area icons
        if icon_full.startswith('app_'):
            area_name = icon_full[4:]  # Remove "app_" prefix
            return process_area_icon(area_name)
        else:
            # Handle keyword/phase icons
            return process_keyword_icon(icon_full)
    
    return re.sub(icon_pattern, replace_icon, text)


def process_area_icon(area_name):
    """
    Process area icon names and expand combined areas.
    
    Examples:
        servearea → [Serve Area]
        servetossarea → [Serve Area] [Toss Area]
        serveattackarea → [Serve Area] [Attack Area]
    """
    # Remove suffixes like _p, _itadaki, _tefuda
    area_clean = re.sub(r'_(p|itadaki|tefuda|w)$', '', area_name.lower())
    
    # Check for combined areas by looking for keywords in the name
    found_areas = []
    for keyword, area_text in ICON_AREA_KEYWORDS.items():
        if keyword in area_clean:
            found_areas.append(area_text)
    
    if found_areas:
        # Return expanded areas with brackets
        return ' '.join([f'[{area}]' for area in found_areas])
    else:
        # If no keyword matched, return the original in brackets
        return f'[{area_name}]'


def process_keyword_icon(icon_name):
    """
    Process keyword/phase icon names.
    
    For certain keywords (onetouch, doshut, etc.), the numeric suffix is retained.
    For feint and similar, any suffix (numeric or letter) is retained.
    For others, the suffix is ignored.
    
    Handles compound phase keywords like "blockphase" or "blockreceivephase" by
    extracting individual phase components.
    
    Examples:
        draw → [Draw Phase]
        onetouch_03 → [One Touch 3]
        doshut_07 → [Stuff Block 7]
        turn_01 → [Turn 1]
        feint_N → [Feint N]
        feint_04 → [Feint 04]
        blockout_02 → [Block Out 2]
        blockphase_tefuda → [Block Phase]
        blockreceivephase_tefuda → [Block Phase] [Receive Phase]
    """
    # Extract any suffix after underscore
    suffix_match = re.search(r'_([a-zA-Z0-9]+)$', icon_name)
    suffix = suffix_match.group(1) if suffix_match else None
    
    # Remove all suffixes to get the keyword
    keyword_clean = re.sub(r'_[a-zA-Z0-9]+$', '', icon_name.lower())
    
    # Try to look up the keyword directly first
    if keyword_clean in ICON_KEYWORD_MAPPING:
        base_text = ICON_KEYWORD_MAPPING[keyword_clean]
        
        # For certain keywords with number suffix, append just the number
        if keyword_clean in ICON_KEYWORDS_WITH_NUMBER and suffix and suffix[0].isdigit():
            return f'[{base_text} {suffix}]'
        # For feint and similar, append the suffix as-is
        elif keyword_clean in ICON_KEYWORDS_WITH_SUFFIX and suffix:
            return f'[{base_text} {suffix}]'
        else:
            return f'[{base_text}]'
    else:
        # Try to parse as compound phase keyword (e.g., "blockphase" or "blockreceivephase")
        compound_result = parse_compound_phase_keyword(keyword_clean, suffix)
        if compound_result:
            return compound_result
        
        # If no mapping found, return the original in brackets
        return f'[icon_{icon_name}]'


def parse_compound_phase_keyword(keyword_clean, suffix=None):
    """
    Parse compound phase keywords like "blockphase" or "blockreceivephase".
    
    This function attempts to extract individual phase keywords from concatenated
    phase names by looking for known keywords. If a suffix is provided and maps
    to a known suffix meaning (like "tefuda" → "From Hand"), it will be appended
    to the result.
    
    Examples:
        blockphase → [Block Phase]
        blockreceivephase → [Block Phase] [Receive Phase]
        receivetossphase → [Receive Phase] [Toss Phase]
        receivephase (with suffix "tefuda") → [Receive Phase] [From Hand]
        blockphase (with suffix "tefuda") → [Block Phase] [From Hand]
    
    Args:
        keyword_clean (str): Cleaned keyword string (lowercase, no suffix)
        suffix (str): Optional suffix like "tefuda" or "itadaki"
    
    Returns:
        str: Formatted phase keywords with brackets, or None if not a compound phase
    """
    # List of phase keywords to check, ordered by length (longest first) to avoid partial matches
    phase_keywords = ['serve', 'receive', 'attack', 'block', 'toss', 'draw']
    phase_keywords_sorted = sorted(phase_keywords, key=len, reverse=True)
    
    # Remove "phase" suffix if present
    keyword_to_parse = keyword_clean
    if keyword_to_parse.endswith('phase'):
        keyword_to_parse = keyword_to_parse[:-5]  # Remove "phase"
    
    # Try to extract phase keywords from the string
    extracted_phases = []
    remaining = keyword_to_parse
    
    while remaining:
        found = False
        for phase_kw in phase_keywords_sorted:
            if remaining.startswith(phase_kw):
                extracted_phases.append(phase_kw)
                remaining = remaining[len(phase_kw):]
                found = True
                break
        
        if not found:
            # Couldn't parse the entire string, this isn't a valid compound phase keyword
            return None
    
    # If we extracted at least one phase keyword, convert to formatted output
    if extracted_phases:
        phase_texts = []
        for phase in extracted_phases:
            # Map the phase keyword to its full text
            if phase == 'serve':
                phase_texts.append('[Serve Phase]')
            elif phase == 'receive':
                phase_texts.append('[Receive Phase]')
            elif phase == 'attack':
                phase_texts.append('[Attack Phase]')
            elif phase == 'block':
                phase_texts.append('[Block Phase]')
            elif phase == 'toss':
                phase_texts.append('[Toss Phase]')
            elif phase == 'draw':
                phase_texts.append('[Draw Phase]')
        
        # Append suffix meaning if available
        if suffix and suffix in ICON_SUFFIX_MAPPING:
            phase_texts.append(f'[{ICON_SUFFIX_MAPPING[suffix]}]')
        
        return ' '.join(phase_texts)
    
    return None
