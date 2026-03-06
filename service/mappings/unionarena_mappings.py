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
