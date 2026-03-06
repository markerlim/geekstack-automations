"""
Haikyuu BREAK Card Game - Japanese to English Mappings

Comprehensive mapping dictionaries for translating card game terminology,
school names, attributes, and effects without relying on the translation API.

These mappings are applied before translation to prevent API hallucination
on known terminology and ensure consistent output.
"""

import re

# Area/Zone Icons that appear on cards
AREA_ICON_MAPPING = {
    "サーブエリア": "Serve Area",
    "ブロックエリア": "Block Area",
    "レシーブエリア": "Receive Area",
    "トスエリア": "Toss Area",
    "アタックエリア": "Attack Area",
    "コート": "Court",
    "手札": "Hand",
}

# Phase Timing Icons on Active Skills
PHASE_TIMING_MAPPING = {
    "サーブフェイズ": "Serve Phase",
    "ブロックフェイズ": "Block Phase",
    "ドローフェイズ": "Draw Phase",
    "レシーブフェイズ": "Receive Phase",
    "トスフェイズ": "Toss Phase",
    "アタックフェイズ": "Attack Phase",
}

# Play Timing Icons on Event Cards
EVENT_TIMING_MAPPING = {
    "サーブ": "Serve",
    "ブロック": "Block",
    "ドロー": "Draw",
    "レシーブ": "Receive",
    "トス": "Toss",
    "アタック": "Attack",
}

# Card Parameters
PARAMETER_MAPPING = {
    "サーブポイント": "Serve Point",
    "ブロックポイント": "Block Point",
    "レシーブポイント": "Receive Point",
    "トスポイント": "Toss Point",
    "アタックポイント": "Attack Point",
}

# Card Types
CARD_TYPE_MAPPING = {
    "キャラカード": "Character Card",
    "イベントカード": "Event Card",
}

# Skill Types
SKILL_TYPE_MAPPING = {
    "パーマネント型スキル": "Permanent Skill",
    "パッシブ型スキル": "Passive Skill",
    "アクティブ型スキル": "Active Skill",
    "イベント型スキル": "Event Skill",
}

# Effect Types
EFFECT_TYPE_MAPPING = {
    "即時効果": "Immediate Effect",
    "継続効果": "Continuous Effect",
    "置換効果": "Replacement Effect",
    "遅発型効果": "Delayed Effect",
}

# Card Attributes
ATTRIBUTE_MAPPING = {
    # Positions
    "WS": "WS",  # Wing Spiker
    "MB": "MB",  # Middle Blocker
    "S": "S",    # Setter
    "Li": "Li",  # Libero
    "OH": "OH",  # Outside Hitter
    "OP": "OP",  # Opposite
    # Non-player roles
    "監督": "Coach",
    "元監督": "Former Coach",
    "コーチ": "Assistant Coach",
    "マネージャー": "Manager",
    "応援団長": "Cheer Captain",
    "応援団": "Cheer Squad",
    "マスコット": "Mascot",
}

# School/Team Affiliations (comprehensive list)
AFFILIATION_MAPPING = {
    # High schools
    "烏野": "Karasuno",
    "音駒": "Nekoma",
    "青葉城西": "Aoba Johsai",
    "梟谷": "Fukurodani",
    "常波": "Tokonami",
    "生川": "Ikejiri",
    "伊達工業": "Date Tech",
    "森然": "Shinzen",
    "白鳥沢": "Shiratorizawa",
    "稲荷崎": "Inarizaki",
    "扇南": "Ohgiminami",
    "鴎台": "Kamomedai",
    "角川": "Kakugawa",
    "井闥山": "Itachiyama",
    "条善寺": "Johzenji",
    "椿原": "Tsubakihara",
    "和久谷南": "Wakutani South",
    "早流川工業": "Hayakawa Industrial",
    "白水館": "Hakusuikan",
    "戸美": "Tobi",
    "狢坂": "Mujinazaka",
    # V-League Teams
    "MSBY ブラックジャッカル": "MSBY Black Jackals",
    "シュバイデン アドラーズ": "Schweiden Adlers",
    "立花Red falcons": "Tachibana Red Falcons",
    "Azuma Pharmacy グリーンロケッツ": "Azuma Pharmacy Green Rockets",
    "EJP（東日本製紙）RAIJIN": "EJP Raijin",
    "大日本電鉄ウォリアーズ": "Dainippon Dentetsu Warriors",
    "VC神奈川": "VC Kanagawa",
    "DESEO ホーネッツ": "DESEO Hornets",
    "仙台フロッグス": "Sendai Frogs",
    "日脚自動車ライオンズ": "Hinata Automobile Lions",
    "たまでんエレファンツ": "Tamaden Elephants",
    "東海重工エスペランツァ": "Tokai Heavy Industries Esperanza",
    "EJP RAIJIN": "EJP Raijin",
    "ヨツヤモータースピリッツ": "Yotsuya Motor Spirits",
    "静岡Penectジャガーズ": "Shizuoka Penect Jaguars",
    "キンイロスポーツジャンパーズ": "Kiniro Sports Jumpers",
    "光新薬レッドラビッツ": "Koshin Pharmaceutical Red Rabbits",
    "加持ワイルド・ドッグス": "Kaji Wild Dogs",
    # National Teams
    "日本代表": "Japan National Team",
    "アルゼンチン代表": "Argentina National Team",
    "Asas São Paulo": "Asas São Paulo",
    "Ifviga Torino": "Ifviga Torino",
    # Middle schools
    "雪ヶ丘中": "Yukigaoka Middle",
    "北川第一中": "Kitagawa Daiichi Middle",
    "千鳥山中": "Chidoriyama Middle",
    "泉館中": "Izumikan Middle",
    "長虫中": "Nagamushi Middle",
    "西光台中": "Nishikodai Middle",
    "光仙学園中": "Kousen Gakuen Middle",
    "白鳥沢中等部": "Shiratorizawa Middle",
    "音駒中": "Nekoma Middle",
    # Other
    "烏野女子": "Karasuno Girls",
    "新山女子": "Niiyama Girls",
    "町内会": "Neighborhood Association",
}

# Grade/Year
GRADE_MAPPING = {
    "1年": "1st Year",
    "2年": "2nd Year",
    "3年": "3rd Year",
    "OB": "Alumni",
    "OG": "Alumni (Female)",
}

# Rarity
# RARITY_MAPPING = {
#     "N": "Normal",
#     "R": "Rare",
#     "S": "Super Rare",
#     "頂": "Top",
#     "P": "Promo",
# }

# Common action/game terms useful for card text parsing
GAME_TERM_MAPPING = {
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
    "センターブロッカー": "Center Blocker",
    "サイドブロッカー": "Side Blocker",
    "ターンプレイヤー": "Turn Player",
    "非ターンプレイヤー": "Non-Turn Player",
    "オフェンスポイント": "Offense Points",
    "ディフェンスポイント": "Defense Points",
    "サーブ権": "Serve Right",
    "インターバル": "Interval",
    "チェックプロセス": "Check Process",
    "スキルコスト": "Skill Cost",
    "発生源": "Source",
    "永久循環": "Infinite Loop",
}

# Condition/Timing keywords useful for parsing trigger conditions
TRIGGER_MAPPING = {
    "登場した時": "When deployed",
    "登場するたび": "Each time deployed",
    "ターン開始時": "At the start of turn",
    "ターン終了時": "At the end of turn",
    "フェイズ開始時": "At the start of phase",
    "フェイズ終了時": "At the end of phase",
    "ロストした時": "When Lost is declared",
    "カードを引くたび": "Each time a card is drawn",
    "インターバル中": "During Interval",
    "このセット中": "During this Set",
    "このターン中": "During this turn",
    "このフェイズ中": "During this phase",
    "代わりに": "Instead",
    "そうした場合": "If you do",
    "そうしなかった場合": "If you don't",
    "以下から": "Choose from the following",
}


def get_all_keyword_mappings():
    """
    Combine all mapping dictionaries into a single resource for applying replacements.
    
    Returns:
        Dictionary of dictionaries organized by category
    """
    return {
        "area": AREA_ICON_MAPPING,
        "phase": PHASE_TIMING_MAPPING,
        "event": EVENT_TIMING_MAPPING,
        "parameter": PARAMETER_MAPPING,
        "card_type": CARD_TYPE_MAPPING,
        "skill_type": SKILL_TYPE_MAPPING,
        "effect_type": EFFECT_TYPE_MAPPING,
        "attribute": ATTRIBUTE_MAPPING,
        "affiliation": AFFILIATION_MAPPING,
        "grade": GRADE_MAPPING,
        # "rarity": RARITY_MAPPING,
        "game_term": GAME_TERM_MAPPING,
        "trigger": TRIGGER_MAPPING,
    }


def apply_all_mappings(text):
    """
    Apply all mapping replacements to text with intelligent spacing.
    Processes from longest to shortest keys to avoid partial replacements.
    Automatically adds spaces around mapped terms when adjacent to non-whitespace.
    Single-character terms only match as whole words (with word boundaries).
    
    Examples:
        "3Guts払えば" → "3 Guts 払えば"
        "Guts払えば" → "Guts 払えば"
        "Guts " → "Guts " (no space added, already has space)
        "Receive Point" → "Receive Point" (R and P don't match inside words)
    
    Args:
        text: Text containing Japanese card game terminology
    
    Returns:
        Text with all mapped terms replaced by English equivalents with proper spacing
    """
    if not text or text.strip() == '-':
        return text
    
    result = text
    all_mappings = get_all_keyword_mappings()
    
    # Collect all mappings and sort by length (longest first)
    all_terms = {}
    for category, mapping in all_mappings.items():
        all_terms.update(mapping)
    
    sorted_terms = sorted(all_terms.keys(), key=len, reverse=True)
    
    # Apply all replacements with intelligent spacing
    for jp_term in sorted_terms:
        english_term = all_terms[jp_term]
        
        # For single-character terms, use word boundaries to avoid matching inside words
        if len(jp_term) == 1:
            pattern = r'\b' + re.escape(jp_term) + r'\b'
        else:
            pattern = re.escape(jp_term)
        
        def replace_with_spacing(match):
            start = match.start()
            end = match.end()
            
            # Check if we need space before (if previous char is not whitespace)
            space_before = ''
            if start > 0 and result[start - 1] not in ' \n\t':
                space_before = ' '
            
            # Check if we need space after (if next char is not whitespace)
            space_after = ''
            if end < len(result) and result[end] not in ' \n\t':
                space_after = ' '
            
            return space_before + english_term + space_after
        
        result = re.sub(pattern, replace_with_spacing, result)
    
    return result
