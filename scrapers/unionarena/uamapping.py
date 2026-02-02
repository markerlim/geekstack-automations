COLOR_MAP = {
    "黄": "yellow",
    "赤": "red",
    "青": "blue",
    "緑": "green",
    "紫": "purple",
    "無": "colorless"
}

CATEGORY_MAP = {
    "キャラクター": "character",
    "フィールド": "field",
    "イベント": "event",
}

TRIGGER_MAP = {
    "draw": "Draw a card.",
    "get": "Add this card to your hand.",
    "raid": "Add this to hand or Raid it if you have the required energy.",
    "active": "Active 1 of your character and give it +3000BP.",
    "special": "Choose one of your opponent's Front Line characters and retire it.",
    "final": "If you have no life, place the top card of your deck into your life area.",
    "color_yellow": "Choose 1 character on your opponent's front line and rest it. The next time it becomes active, it doesn't.",
    "color_red": "Choose one of your opponent's Front Line characters with BP2500 or less and retire it.",
    "color_blue": "Choose one of your opponent's Front Line characters with BP3500 or less, and return it to their hand.",
    "color_green": "Play 1 Green Character Card with required energy of 2 or less and AP 1 from your hand to your area and set it to active.",
    "color_purple": "Play a purple character with 2 Energy cost or less and 1 AP from Outside Area to your Front Line in Active.",
    "-" : "-"
}

TRIGGER_STATE_MAP = {
    "カードを1枚引く。" : "draw",
    "このカードを手札に加える。" : "get",
    "このカードを手札に加えるか、必要エナジーを満たしている場合、レイドさせる。" : "raid",
    "自分の場のキャラを1枚選び、アクティブにし、このターン中、BP+3000。" : "active",
    "相手のフロントLのキャラを1枚選び、退場させる。" : "special",
    "自分のライフが無い場合、自分の山札の上から1枚を自分のライフエリアに置く。":"final",
    "相手のフロントLのキャラを1枚選び、レストにする。それは次の1回アクティブにならない。" : "color_yellow",
    "BP2500以下の相手のフロントLのキャラを1枚選び、退場させる。" : "color_red",
    "BP3500以下の相手のフロントLのキャラを1枚選び、手札に戻す。" : "color_blue",
    "自分の手札から必要エナジーが2以下で消費APが1の緑のキャラカードを1枚自分の場にアクティブで登場させる。" : "color_green",
    "自分の場外から必要エナジーが2以下で消費APが1の紫のキャラカードを1枚自分のフロントLにアクティブで登場させる。" : "color_purple",
    "-" : "-"
}

UATAG_MAP = {
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