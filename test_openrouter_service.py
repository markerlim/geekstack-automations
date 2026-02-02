import json
from service.openrouter_service import OpenRouterService

def test_translate_fields():

    service = OpenRouterService()
    data = [
        {
            "cardName": "龐煖",
            "effect": '''<dd class="cardDataContents">
                <img src="/jp/images/cardlist/icon/effect/ico_step.png" alt="ステップ">（自分の移動フェイズにフロントLからエナジーLへ移動できる）<br><img src="/jp/images/cardlist/icon/effect/ico_frontl.png" alt="フロントLにある場合">自分のアタックフェイズ終了時、自分のフロントLに元々のBPが4500以上の他のキャラがあるか、このターン中にこのキャラが移動していない場合、このキャラを自分の山札の下に置く。<br><img src="/jp/images/cardlist/icon/effect/ico_attack.png" alt="アタック時">このキャラはこのターン中、<img src="/jp/images/cardlist/icon/effect/ico_impact1.png" alt="インパクト（1）">か<img src="/jp/images/cardlist/icon/effect/ico_damage2.png" alt="ダメージ（2）">を得る。<br><img src="/jp/images/cardlist/icon/effect/ico_exit.png" alt="退場時">このカードを自分の山札の下に置く。              </dd>''',
            "traits": "趙"
        },
        {
            "cardName": "王賁",
            "effect": '''<dd class="cardDataContents">
                <img src="/jp/images/cardlist/icon/effect/ico_raid.png" alt="レイド">〈王賁〉アクティブにし、フロントLに移動できる<br>このキャラのアタックがブロックされなかった時、カードを『1枚』引く。自分のフロントLに〈信〉と〈蒙恬〉がある場合、『2枚』に代わる。<br><img src="/jp/images/cardlist/icon/effect/ico_appearance.png" alt="登場時">BP1500以上の相手のフロントLのキャラを1枚まで選び、このターン中、BP-1000。<br><img src="/jp/images/cardlist/icon/effect/ico_attack.png" alt="アタック時">「APを1支払い、相手のフロントLのキャラを1枚選ぶ。」をしてもよい。そうした場合、相手は選ばれたキャラ以外のキャラでこのアタックをブロックできない。              </dd>''',
            "traits": "秦／玉鳳隊"
        }
    ]
    fields_to_translate = ["cardName", "effect", "traits"]
    result = service.translate_fields_unionarena(data, fields_to_translate, source_lang="Japanese", target_lang="English", keep_original=True,context="Kingdom",batch_size=12)

    # Write result to test.json for clearer visibility
    with open("test.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    test_translate_fields()
