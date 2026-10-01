from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from stellalog_sns.article_repository import ArticleRepository
from stellalog_sns.generator import (
    TIKTOK_TEMPLATE_IDS,
    PostGenerator,
    _apply_reviewed_tiktok_layout,
    _format_tiktok_text,
    _group_tiktok_caption_cards,
    _build_tiktok,
    _extract_points,
    _ordered_source_points,
    _deduplicate_source_points,
    _context_penalty,
    _render_tiktok,
    _to_polite_x_sentence,
    _wrap_tiktok_caption_line,
)
from stellalog_sns.models import Article, ContentBlock
from stellalog_sns.url_builder import x_weighted_length
from stellalog_sns.x_thread import split_x_thread


def _article(concern: str = "love") -> Article:
    return Article(
        article_key=f"{concern}/female/enfj/aquarius",
        concern=concern,
        gender="female",
        mbti="enfj",
        zodiac="aquarius",
        title="ENFJ×水瓶座の記事タイトル",
        sns_catchphrase="理想と現実の間で考え込むことがある",
        source_path=Path("article.json"),
        content=(
            ContentBlock("h3", "人の気持ちを先回りして考える"),
            ContentBlock("p", "相手の表情や言葉を丁寧に受け取ります。自分より相手を優先することがあります。"),
            ContentBlock("h3", "一方で本音を後回しにする矛盾"),
            ContentBlock("p", "気づかないうちに無理を重ねることがあります。"),
            ContentBlock("h3", "強みを活かすために必要なこと"),
            ContentBlock("p", "自分の希望も短い言葉で伝える方法があります。"),
            ContentBlock("cta", "個別鑑定を購入すると未来が変わります。"),
        ),
    )


def _caption_text(script: str) -> str:
    """字幕用の改行を除き、文章そのものを検証する。"""
    return script.replace("\n", "")


def test_generates_offline_post_set_with_safe_lengths() -> None:
    post = PostGenerator().generate(
        _article(),
        "https://n-stellalog.com",
        selected_at=datetime(2026, 9, 1, 9),
    )

    assert 0 < post.estimated_tiktok_seconds <= 75
    assert post.x_weighted_length <= 280
    assert _caption_text(post.tiktok_script.split("\n\n", 1)[0]) == (
        "理想と現実の間で考え込むことがあるENFJ水瓶座の恋愛"
    )
    assert "StellaLogの解釈では" not in post.tiktok_script
    assert "これは絶対的な診断ではなく、StellaLogによるタイプの読み解きです。" not in post.tiktok_script
    assert "——" not in post.tiktok_script
    assert "長所の裏に隠れた本音まで見ていきます" not in post.tiktok_script
    assert "記事では" not in post.tiktok_script
    assert "と描かれています" not in post.tiktok_script
    assert not any(mark in post.tiktok_script.replace("「StellaLog」", "StellaLog") for mark in "、。！!?「」『』")
    assert post.tiktok_script.count("？") == 1
    assert "当てはまるところはありますか？" in _caption_text(post.tiktok_script)
    assert "\n" in post.tiktok_script
    tiktok_cards = post.tiktok_script.split("\n\n")
    assert _caption_text(tiktok_cards[1]).startswith("ENFJ水瓶座のあなたは")
    assert "理想と現実の間で考え込むことがある" in _caption_text(tiktok_cards[0])
    first_x, second_x = split_x_thread(post.x_post)
    assert first_x.startswith("ENFJ×水瓶座の本当の恋愛傾向\n\n・")
    assert "これあるある？" not in first_x
    assert "×" not in post.tiktok_script
    assert "ENFJ×水瓶座" in post.x_post
    assert first_x.count("\n・") >= 2
    assert first_x.endswith("でも、いちばん気になるところは…")
    assert second_x.endswith(post.x_url)
    assert f"詳しい続きはStellaLogの記事でどうぞ。\n{post.x_url}" in second_x
    assert not second_x.startswith("見過ごしやすい本音はここ。")
    assert "いちばん刺さるのはここ。" not in second_x
    assert not second_x.startswith("・")
    assert post.x_url in second_x
    assert "utm_source=x" in second_x
    assert "StellaLogの解釈" not in post.x_post
    assert "──" not in post.x_post
    assert all(x_weighted_length(part) <= 280 for part in (first_x, second_x))
    assert "相手の表情や言葉を丁寧に受け取ります" in _caption_text(post.tiktok_script)
    assert "相手の表情や言葉を丁寧に受け取ります" in post.x_post
    assert "個別鑑定を購入" not in post.tiktok_script
    assert "個別鑑定を購入" not in post.x_post
    assert "utm_source=tiktok" in post.tiktok_url
    assert "utm_source=x" in post.x_url
    assert len(post.hashtags) <= 6


@pytest.mark.parametrize("template_id", TIKTOK_TEMPLATE_IDS)
def test_every_tiktok_template_leads_with_target_and_removes_unwanted_phrases(
    template_id: str,
) -> None:
    article = Article(
        article_key="personality/female/infp/pisces",
        concern="personality",
        gender="female",
        mbti="infp",
        zodiac="pisces",
        title="INFP×魚座の記事タイトル",
        sns_catchphrase="優しさ——その奥に意外な本音がある",
        source_path=Path("article.json"),
        content=(ContentBlock("p", "静かな時間を大切にします。"),),
    )

    script = _render_tiktok(
        article,
        template_id,
        (
            "境界線が溶けている──あなたはどこまでが自分で、どこからが他人なのか",
        ),
    )

    compact_script = _caption_text(script)
    assert compact_script.startswith("INFP×魚座の本当の性格")
    assert script.split("\n\n", 1)[0].splitlines() == ["INFP×魚座の", "本当の性格"]
    assert "INFP×魚座のあなたは" in compact_script
    assert "どこまでが自分で" in compact_script
    assert "優しさ" not in script
    assert "StellaLogの解釈では" not in script
    assert "これは絶対的な診断ではなく、StellaLogによるタイプの読み解きです。" not in script
    assert "——" not in script
    assert "──" not in script
    assert "長所の裏に隠れた本音まで見ていきます" not in script
    assert "記事では" not in script
    assert "と描かれています" not in script
    assert "どこまでが自分でどこからが他人なのか境界線が曖昧です" in compact_script
    assert "あなたは\nあなたは" not in script
    assert not any(mark in script.replace("「StellaLog」", "StellaLog") for mark in "、。！!?「」『』")
    assert script.count("？") == 1
    assert "当てはまるところはありますか？" in compact_script
    assert not any(
        line.startswith(("しかし", "ただし", "一方で", "そして", "また"))
        for line in script.splitlines()
    )


def test_source_points_are_verbatim_article_material() -> None:
    article = _article()
    post = PostGenerator().generate(article, "https://n-stellalog.com")
    source_text = "\n".join(
        block.text for block in article.content if block.type != "cta"
    )
    assert post.source_points
    assert all(point in source_text for point in post.source_points)


def test_tiktok_keeps_original_explanation_order_after_strength_and_weakness_selection() -> None:
    article = _article()
    original = _extract_points(article)["general"]
    points = _ordered_source_points(_extract_points(article), is_ranking=False)
    _, selected = _build_tiktok(article, "tiktok_question_opening", points)
    assert len(selected) >= 3
    positions = [original.index(point) for point in selected]
    assert positions == sorted(positions)


def test_duplicate_detection_preserves_opposite_meanings_and_conditions() -> None:
    first = "相手の意見を聞いて、自分の気持ちを伝えます。"
    punctuated = "相手の意見を聞いて自分の気持ちを伝えます"
    negative = "相手の意見を聞いて、自分の気持ちを伝えません。"
    conditional = "親しい相手の意見を聞いて、自分の気持ちを伝えます。"
    assert _deduplicate_source_points((first, punctuated, negative, conditional)) == [first, negative, conditional]


def test_context_selection_penalizes_a_demonstrative_without_its_explanation() -> None:
    first = "相手の表情や声の変化に気づきます。"
    second = "そういった小さな変化から本音を考えます。"
    unrelated = "休日は趣味に集中します。"
    order = {first: 0, second: 1, unrelated: 20}
    assert _context_penalty((first, second), order) < _context_penalty((second, unrelated), order)


def test_x_sentences_remove_leading_connector_and_use_polite_style() -> None:
    assert _to_polite_x_sentence(
        "しかし魚座の傾向として、現実との接続が薄れるリスクがある。",
        remove_leading_connector=True,
    ) == "魚座の傾向として、現実との接続が薄れるリスクがあります。"
    assert _to_polite_x_sentence(
        "境界線が溶けている——あなたはどこまでが自分で、どこからが他人なのか"
    ) == "あなたはどこまでが自分で、どこからが他人なのか、境界線が曖昧です。"
    assert _to_polite_x_sentence(
        "隣に座っている人が緊張していれば、あなたの胃も緊張する。"
    ) == "隣に座っている人が緊張していれば、あなたの胃も緊張します。"
    assert _to_polite_x_sentence(
        "遠くにいる友人が落ち込んでいれば、理由もなくあなたの気分も沈む。"
    ) == "遠くにいる友人が落ち込んでいれば、理由もなくあなたの気分も沈みます。"
    assert _to_polite_x_sentence(
        "他者の感情がフィルターなしで流れ込んでくる。"
    ) == "他者の感情がフィルターなしで流れ込んできます。"
    assert _to_polite_x_sentence("ロジックに穴はない。") == "ロジックに穴はありません。"
    assert _to_polite_x_sentence(
        "友人たちは信じて疑わない。"
    ) == "友人たちは信じて疑いません。"
    assert _to_polite_x_sentence("心が動いた。") == "心が動いたのです。"
    assert _to_polite_x_sentence(
        "別に褒められたくないと言いながら、褒められないと不機嫌になる設計"
    ) == "別に褒められたくないと言いながら、褒められないと不機嫌になる傾向があります。"
    assert _to_polite_x_sentence(
        "理想の恋人像の設計です。"
    ) == "理想の恋人像の設計です。"
    assert _to_polite_x_sentence(
        "罪悪感を覚えたことがあるのではないでしょうか"
    ) == "罪悪感を覚えたことがあるのではないでしょうか？"
    assert _to_polite_x_sentence(
        "野心があるのに動き出さない——「準備が終わるまで勝負しない」という賭け方"
    ) == "野心があるのに動き出さない。準備が整うまで勝負に出ない傾向があります。"
    assert _to_polite_x_sentence(
        "データの再評価を繰り返しているだけなのですが"
    ) == "データの再評価を繰り返しているだけなのです。"
    assert _to_polite_x_sentence(
        "あなたは何度繰り返してきましたか"
    ) == "あなたは何度繰り返してきましたか？"


def test_tiktok_text_breaks_between_adjacent_quotes() -> None:
    assert _format_tiktok_text("「なぜAなのか」「なぜBなのか」。") == (
        "なぜAなのか\nなぜBなのか"
    )
    cleaned = _format_tiktok_text(
        "記事では「長所の裏に隠れた本音まで見ていきます」と描かれています。"
    )
    assert "記事では" not in cleaned
    assert "長所の裏に隠れた本音まで見ていきます" not in cleaned
    assert "と描かれています" not in cleaned


def test_tiktok_caption_cards_keep_semantic_boundaries_and_line_order() -> None:
    original = "見出し1\n見出し2\n\n1行目\n2行目\n3行目\n4行目\n5行目\n6行目"

    grouped = _group_tiktok_caption_cards(original)
    cards = grouped.split("\n\n")

    assert [len(card.splitlines()) for card in cards] == [2, 3, 3]
    assert grouped.replace("\n", "") == original.replace("\n", "")


def test_tiktok_caption_lines_prefer_japanese_particles_without_changing_text() -> None:
    original = "あなたの感受性は人の気持ちを深く受け取ります"

    wrapped = _wrap_tiktok_caption_line(original)

    assert "".join(wrapped) == original
    assert all(len(line) <= 13 for line in wrapped)
    assert wrapped[0].endswith("は")

    nuanced = _wrap_tiktok_caption_line(
        "生まれつき他のタイプよりも透過性が高いということです"
    )
    assert not any(line.startswith("も") for line in nuanced)
    assert "\n".join(nuanced).find("と\nいう") == -1

    no_orphan = _wrap_tiktok_caption_line("透過性が高いということです")
    assert no_orphan == ("透過性が高い", "ということです")
    assert min(map(len, no_orphan)) >= 4


def test_generated_tiktok_cards_have_at_most_five_short_lines() -> None:
    script = PostGenerator().generate(
        _article(),
        "https://n-stellalog.com",
        selected_at=datetime(2026, 9, 1, 9),
    ).tiktok_script

    cards = script.split("\n\n")
    assert len(cards) >= 2
    assert all(1 <= len(card.splitlines()) <= 5 for card in cards)
    assert all(len(line) <= 13 for card in cards for line in card.splitlines())
    assert all(
        len(line) >= 4 or line in {"どうぞ"}
        for card in cards
        for line in card.splitlines()
    )


def test_tiktok_removes_repeated_subject_after_mbti_context() -> None:
    article = Article(
        article_key="personality/unisex/estj/aquarius",
        concern="personality",
        gender="unisex",
        mbti="estj",
        zodiac="aquarius",
        title="ESTJ×水瓶座の記事タイトル",
        sns_catchphrase="キャッチフレーズ",
        source_path=Path("article.json"),
        content=(ContentBlock("p", "静かな時間を大切にします。"),),
    )

    script = _render_tiktok(
        article,
        "tiktok_question_opening",
        ("ESTJとしてのあなたは、ルールに安心感を覚えます。",),
    )

    compact_script = _caption_text(script)
    assert compact_script.startswith(
        "ESTJ×水瓶座の本当の性格ESTJ×水瓶座のあなたは"
        "ESTJとしてのルールに安心感を覚えます"
    )
    assert "ESTJとしてのあなたは" not in script

    prefaced_script = _render_tiktok(
        article,
        "tiktok_question_opening",
        ("この矛盾に折り合いをつけるために、あなたは独自のロジックを構築しています。",),
    )
    assert "\nあなたは独自の" not in prefaced_script
    assert "この矛盾に折り合いをつけるために独自のロジック" in _caption_text(
        prefaced_script
    )


def test_esfp_taurus_script_uses_possessive_subject_and_semantic_cards() -> None:
    article = Article(
        article_key="personality/unisex/esfp/taurus",
        concern="personality",
        gender="unisex",
        mbti="esfp",
        zodiac="taurus",
        title="ESFP×牡牛座の記事タイトル",
        sns_catchphrase="キャッチフレーズ",
        source_path=Path("article.json"),
        content=(ContentBlock("p", "静かな時間を大切にします。"),),
    )

    script = _apply_reviewed_tiktok_layout(
        article,
        _render_tiktok(
            article,
            "tiktok_question_opening",
            (
                "しかしあなたの内側では、目に映るもの、耳に届く音、肌に触れる感触、"
                "口に含んだ味——ありとあらゆる感覚情報を「快」か「不快」に仕分ける装置が"
                "ノンストップで稼働しています。",
                "レストランに入った瞬間に「この店は長居できる」と判定するのも、"
                "初対面の人と握手した感触で「この人とは距離を置こう」と決めるのも、"
                "すべてこの感覚フィルターの仕事です。",
                "ESFPの五感優位な処理回路に、牡牛座の「心地よさへの執着」が重なることで、"
                "このフィルターの精度は恐ろしく高くなっています。",
                "安い素材の服が肌に触れただけで集中力が途切れたり、"
                "照明の色味ひとつで居心地が劇的に変わったり。",
            ),
        ),
    )

    assert script == """ESFP牡牛座の
本当の性格

ESFP牡牛座の
あなたの内側では

目に映るもの
耳に届く音
肌に触れる感触
口に含んだ味

ありとあらゆる
感覚情報を
快か不快に
仕分ける装置が
ノンストップで
稼働しています

レストランに
入った瞬間に
この店は長居できると
判定するのも

初対面の人と
握手した感触で
この人とは距離を置こうと
決めるのも

すべてこの
感覚フィルターの
仕事です

ESFPの
五感優位な
処理回路に

牡牛座の
心地よさへの執着が
重なることで

このフィルターの
精度は
恐ろしく
高くなっています

安い素材の服が
肌に触れただけで
集中力が
途切れたり

照明の色味ひとつで
居心地が劇的に
変わったりです

当てはまるところは
ありますか？
詳しい続きは
「StellaLog」で
検索してね"""


def test_esfp_pisces_script_uses_reviewed_ten_character_balance() -> None:
    article = Article(
        article_key="personality/unisex/esfp/pisces",
        concern="personality",
        gender="unisex",
        mbti="esfp",
        zodiac="pisces",
        title="ESFP×魚座の記事タイトル",
        sns_catchphrase="キャッチフレーズ",
        source_path=Path("article.json"),
        content=(ContentBlock("p", "静かな時間を大切にします。"),),
    )

    script = _apply_reviewed_tiktok_layout(
        article,
        _render_tiktok(
            article,
            "tiktok_question_opening",
            (
                "全身で笑っているのに、心の奥に薄い霧がかかっている感覚",
                "あなたほど「全力で楽しんでいるように見える人」は滅多にいません。",
                "友人の悲しみを聞くだけで自分の胸が物理的に重くなり、"
                "映画の中の登場人物の苦しみに涙が止まらなくなり、"
                "ニュースで見た赤の他人の不幸が一日中頭から離れない。",
                "これは科学というよりも体質であり、あなたの心身の調律にとって"
                "水は他のどんなリフレッシュ方法よりも効果的なのです。",
                "この「楽しさの中の切なさ」は、ESFPの「今この瞬間を全力で味わう」"
                "五感と、魚座の「すべてはいつか流れていく」という直感が同時に"
                "作動している結果です。",
            ),
        ),
    )

    assert script == """ESFP魚座の
本当の性格

ESFP魚座の
あなたは
全身で笑っているのに
心の奥に薄い霧が
かかっている
感覚です

あなたほど全力で
楽しんでいるように
見える人は
滅多にいません

友人の悲しみを
聞くだけで
自分の胸が
物理的に重くなり

映画の中の登場人物の
苦しみに涙が
止まらなくなり

ニュースで
見た赤の他人の不幸が
一日中頭から
離れないです

これは科学
というよりも
体質であり

あなたの心身の
調律にとって
水は他のどんな
リフレッシュ方法よりも
効果的なのです

この楽しさの中の
切なさは
ESFPの
今この瞬間を
全力で味わう五感と

魚座の
すべてはいつか
流れていくという
直感が同時に
作動している結果です

当てはまるところは
ありますか？
詳しい続きは
「StellaLog」で
検索してね"""


def test_tiktok_uses_natural_wording_for_personality_design_metaphor() -> None:
    article = Article(
        article_key="personality/unisex/intp/leo",
        concern="personality",
        gender="unisex",
        mbti="intp",
        zodiac="leo",
        title="INTP×獅子座の記事タイトル",
        sns_catchphrase="キャッチフレーズ",
        source_path=Path("article.json"),
        content=(ContentBlock("p", "静かな時間を大切にします。"),),
    )

    script = _render_tiktok(
        article,
        "tiktok_question_opening",
        ("「別に褒められたくない」と言いながら、褒められないと不機嫌になる設計",),
    )

    assert "褒められないと不機嫌になる傾向があります" in _caption_text(script)
    assert "設計です" not in script


def test_tiktok_places_enfj_leo_examples_before_the_explanation() -> None:
    article = Article(
        article_key="personality/unisex/enfj/leo",
        concern="personality",
        gender="unisex",
        mbti="enfj",
        zodiac="leo",
        title="ENFJ×獅子座の記事タイトル",
        sns_catchphrase="キャッチフレーズ",
        source_path=Path("article.json"),
        content=(ContentBlock("p", "静かな時間を大切にします。"),),
    )
    context_point = (
        "あなたがプレゼンを終えた瞬間、あるいは宴席でいい話をして笑いを取った瞬間、"
        "普通なら達成感に浸るところですが、あなたの脳は別のタスクを走らせています。"
    )
    examples_point = (
        "「右端に座っているあの人、笑ってなかったな」"
        "「さっきの発言で傷つけた人がいないか」"
        "「この空気に乗れていない人はいないか」。"
    )

    script = _render_tiktok(
        article,
        "tiktok_question_opening",
        (context_point, examples_point),
    )

    compact_script = _caption_text(script)
    conclusion_index = compact_script.index("あなたの脳は別のタスクを走らせています")
    assert compact_script.index("この空気に乗れていない人はいないか") < conclusion_index
    assert "この空気に乗れていない人はいないかです" not in script


def test_tiktok_rephrases_intp_capricorn_betting_metaphor() -> None:
    article = Article(
        article_key="personality/unisex/intp/capricorn",
        concern="personality",
        gender="unisex",
        mbti="intp",
        zodiac="capricorn",
        title="INTP×山羊座の記事タイトル",
        sns_catchphrase="キャッチフレーズ",
        source_path=Path("article.json"),
        content=(ContentBlock("p", "静かな時間を大切にします。"),),
    )

    script = _render_tiktok(
        article,
        "tiktok_question_opening",
        ("野心があるのに動き出さない——「準備が終わるまで勝負しない」という賭け方",),
    )

    compact_script = _caption_text(script)
    assert "野心があるのに動き出さない" in compact_script
    assert "準備が整うまで勝負に出ない傾向があります" in compact_script
    assert "賭け方" not in script


def test_recent_templates_are_avoided_and_ranking_template_is_scoped() -> None:
    generator = PostGenerator()
    post = generator.generate(
        _article(),
        "https://n-stellalog.com",
        recent_template_ids=(
            "tiktok_question_opening",
            "tiktok_contradiction_opening",
            "tiktok_catchphrase_opening",
        ),
        selected_at=datetime(2026, 9, 1),
    )
    assert post.tiktok_template_id not in {
        "tiktok_question_opening", "tiktok_contradiction_opening", "tiktok_catchphrase_opening"
    }
    assert post.tiktok_template_id != "tiktok_ranking"
    assert post.x_template_id != "x_ranking"

    path = Path(__file__).parent / "fixtures" / "infj_cancer_ranking.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    ranking = Article(
        article_key="ranking/unisex/infj/cancer", source_path=path,
        content=tuple(ContentBlock(**block) for block in payload.pop("content")),
        **payload,
    )
    ranking_post = generator.generate(ranking, "https://n-stellalog.com")
    assert ranking_post.tiktok_template_id == "tiktok_ranking"
    assert ranking_post.x_template_id == "x_ranking"
    assert "StellaLog独自" not in _caption_text(ranking_post.tiktok_script)
    assert "神相性1位" in _caption_text(ranking_post.tiktok_script)
    assert "地雷相性1位" in _caption_text(ranking_post.tiktok_script)
    assert "INFJ蟹座" in _caption_text(ranking_post.tiktok_script)
    assert "×" not in ranking_post.tiktok_script
    assert "INFJ×蟹座" in ranking_post.x_post


def test_chatgpt_prompt_contains_material_and_immutable_urls() -> None:
    generator = PostGenerator()
    post = generator.generate(_article(), "https://n-stellalog.com")
    prompt = generator.build_chatgpt_prompt(post)
    assert post.tiktok_script in prompt
    assert post.x_post in prompt
    assert post.tiktok_url in prompt
    assert "元記事にない内容を事実として追加しない" in prompt
    assert "ENFJ×水瓶座" in prompt
