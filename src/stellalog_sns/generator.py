from __future__ import annotations

import hashlib
import itertools
import re
from datetime import datetime
from typing import Iterable, Sequence

from .models import Article, ContentBlock, PostSet
from .hook_phrases import TIKTOK_HOOK_REPLACEMENTS
from .labels import remove_mbti_zodiac_crosses
from .natural_language import naturalize_tiktok_text
from .ranking_posts import build_ranking_posts
from .url_builder import build_article_urls, x_weighted_length
from .x_thread import format_x_thread, split_x_thread


TIKTOK_TEMPLATE_IDS = (
    "tiktok_question_opening",
    "tiktok_contradiction_opening",
    "tiktok_catchphrase_opening",
    "tiktok_instruction_manual",
    "tiktok_strength_then_weakness",
)
TIKTOK_RANKING_TEMPLATE_ID = "tiktok_ranking"
X_TEMPLATE_IDS = (
    "x_relatable",
    "x_manual",
    "x_hidden_weakness",
    "x_strength_weakness",
    "x_someone_close",
)
X_RANKING_TEMPLATE_ID = "x_ranking"
TIKTOK_MIN_CHARS = 330
TIKTOK_MAX_CHARS = 385
TIKTOK_TARGET_CHARS = 358

_WEAKNESS_WORDS = (
    "矛盾",
    "問題",
    "弱点",
    "課題",
    "苦し",
    "注意",
    "一方",
    "葛藤",
    "自滅",
    "リスク",
    "怖",
)
_STRENGTH_WORDS = (
    "長所",
    "強み",
    "武器",
    "方法",
    "対処",
    "活か",
    "接し方",
    "才能",
    "解毒剤",
    "必要",
)
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?])")
_LEADING_CONNECTOR = re.compile(
    r"^(?:しかし|ただし|一方で|そして|また|ですが)[、,\s]*"
)
_BOUNDARY_HEADING = "境界線が溶けている"
_BRAIN_TASK_CONCLUSION = "あなたの脳は別のタスクを走らせています。"
_TIKTOK_LINE_BREAK_WORDS = (
    "けれども",
    "として",
    "について",
    "によって",
    "だから",
    "なので",
    "ながら",
    "から",
    "まで",
    "れば",
    "なら",
    "ため",
    "ので",
    "のに",
    "けれど",
    "でも",
    "より",
    "ほど",
    "だけ",
    "こそ",
    "って",
    "では",
    "には",
    "とは",
    "は",
    "が",
    "を",
    "に",
    "で",
    "と",
    "の",
    "も",
    "へ",
)

ZODIAC_LABELS = {
    "aries": "牡羊座",
    "taurus": "牡牛座",
    "gemini": "双子座",
    "cancer": "蟹座",
    "leo": "獅子座",
    "virgo": "乙女座",
    "libra": "天秤座",
    "scorpio": "蠍座",
    "sagittarius": "射手座",
    "capricorn": "山羊座",
    "aquarius": "水瓶座",
    "pisces": "魚座",
}
CATEGORY_LABELS = {
    "personality": "性格",
    "ranking": "ランキング",
    "love": "恋愛",
    "work": "仕事",
    "money": "金運",
    "reunion": "復縁",
    "night": "夜",
}
TIKTOK_HEADLINE_LABELS = {
    "personality": "本当の性格",
    "ranking": "意外なランキング",
    "love": "本当の恋愛傾向",
    "work": "仕事で見せる本当の顔",
    "money": "お金に表れる本当の性格",
    "reunion": "復縁で見せる本当の気持ち",
    "night": "夜にだけ見せる本当の顔",
}
CATEGORY_HASHTAGS = {
    "personality": "#性格傾向",
    "ranking": "#MBTIランキング",
    "love": "#恋愛傾向",
    "work": "#仕事傾向",
    "money": "#金運",
    "reunion": "#復縁",
    "night": "#夜の本音",
}

_ESFP_TAURUS_REVIEWED_TIKTOK_LAYOUT = """ESFP牡牛座の
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

_ESFP_PISCES_REVIEWED_TIKTOK_LAYOUT = """ESFP魚座の
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

_REVIEWED_TIKTOK_LAYOUTS = {
    "personality/unisex/esfp/taurus": _ESFP_TAURUS_REVIEWED_TIKTOK_LAYOUT,
    "personality/unisex/esfp/pisces": _ESFP_PISCES_REVIEWED_TIKTOK_LAYOUT,
}


class PostGenerationError(ValueError):
    pass


class PostGenerator:
    def generate(
        self,
        article: Article,
        site_origin: str,
        recent_template_ids: Iterable[str] = (),
        selected_at: datetime | None = None,
        reading_cpm: int = 330,
    ) -> PostSet:
        if reading_cpm <= 0:
            raise ValueError("読み上げ速度は1以上で指定してください")
        selected_at = selected_at or datetime.now().astimezone()
        recent = tuple(recent_template_ids)[-3:]
        canonical_url, tiktok_url, x_url = build_article_urls(article, site_origin)

        extracted = _extract_points(article)
        if not extracted["general"] and not extracted["ranking"]:
            raise PostGenerationError("投稿文に使える見出しまたは本文がありません")

        is_ranking = article.concern == "ranking" and bool(extracted["ranking"])
        tiktok_ids = (
            (TIKTOK_RANKING_TEMPLATE_ID,)
            if is_ranking
            else TIKTOK_TEMPLATE_IDS
        )
        x_ids = (X_RANKING_TEMPLATE_ID,) if is_ranking else X_TEMPLATE_IDS
        tiktok_template_id = _choose_template(
            tiktok_ids, recent, article.article_key, selected_at, "tiktok"
        )
        x_template_id = _choose_template(
            x_ids, recent, article.article_key, selected_at, "x"
        )

        ranking_post = build_ranking_posts(article, x_url, format_tiktok=_format_tiktok_text)
        if ranking_post is not None:
            tiktok_script = ranking_post.tiktok_script
            x_post = format_x_thread(ranking_post.x_first, ranking_post.x_second)
            used_tiktok_points = used_x_points = ranking_post.source_points
        else:
            source_points = _ordered_source_points(extracted, is_ranking=is_ranking)
            tiktok_script, used_tiktok_points = _build_tiktok(
                article,
                tiktok_template_id,
                source_points,
                preserve_context=article.article_key not in _REVIEWED_TIKTOK_LAYOUTS and not is_ranking,
            )
            # 採用する要点を選び終えてから、確認済みの文章配置を反映する。
            # 選定中に改行数や重複語を変えると、別の要点が選ばれるため。
            tiktok_script = _apply_reviewed_tiktok_layout(article, tiktok_script)
            tiktok_script = _apply_tiktok_hook(article, tiktok_script)
            x_post, used_x_points = _build_x(
                article,
                x_template_id,
                used_tiktok_points,
                source_points,
                x_url,
            )
        hashtags = _build_hashtags(article)
        x_parts = split_x_thread(x_post)
        weighted = max(x_weighted_length(part) for part in x_parts)
        if any(x_weighted_length(part) > 280 for part in x_parts):
            raise PostGenerationError("Xの各投稿を280文字相当以内に短縮できませんでした")

        used_points = tuple(dict.fromkeys((*used_tiktok_points, *used_x_points)))
        return PostSet(
            article=article,
            selected_at=selected_at,
            tiktok_script=tiktok_script,
            x_post=x_post,
            canonical_url=canonical_url,
            tiktok_url=tiktok_url,
            x_url=x_url,
            hashtags=hashtags,
            tiktok_template_id=tiktok_template_id,
            x_template_id=x_template_id,
            source_points=used_points,
            estimated_tiktok_seconds=len(tiktok_script) / reading_cpm * 60,
            x_weighted_length=weighted,
        )

    @staticmethod
    def build_chatgpt_prompt(post_set: PostSet) -> str:
        article = post_set.article
        points = remove_mbti_zodiac_crosses(
            "\n".join(f"- {point}" for point in post_set.source_points)
        )
        article_title = remove_mbti_zodiac_crosses(article.title)
        prompt = f"""【調整したい内容】
（ここに希望を追記してください）

【元記事】
カテゴリー: {CATEGORY_LABELS.get(article.concern, article.concern)}
MBTI: {article.mbti.upper()}
星座: {ZODIAC_LABELS.get(article.zodiac, article.zodiac)}
性別: {article.gender}
タイトル: {article_title}

【元記事から抽出した要点】
{points}

【TikTok台本】
{post_set.tiktok_script}

【X投稿文（1つ目と2つ目）】
{post_set.x_post}

【変更してはいけないURL】
TikTok: {post_set.tiktok_url}
X投稿内の計測用記事URL: {post_set.x_url}

元記事にない内容を事実として追加しないでください。MBTIや星座を科学的診断や絶対的事実として断定しないでください。TikTokは60〜70秒程度にし、記事からの引用口調を使わず、対象者へ直接語りかけてください。人物を設計、仕様、プログラム、バグ、装置などの機械として説明せず、実際の思考や行動の傾向を直接表現してください。TikTokは締めの疑問符と「StellaLog」のカギ括弧以外の句読点やカギ括弧を使わず、意味の区切りごとに改行してください。TikTokの最後は「当てはまるところはありますか？」に続けて、詳しい続きは「StellaLog」で検索してね と案内してください。Xは1つ目を複数のあるある項目、2つ目を刺さる内容にし、それぞれ280文字相当以内に整えてください。Xはです・ます調に統一し、2つ目を接続詞から始めないでください。2つ目は「詳しい続きはStellaLogの記事でどうぞ。」の直後に記事URLを置いてください。URLは変更しないでください。"""
        return prompt


def _extract_points(article: Article) -> dict[str, list[str]]:
    general: list[str] = []
    weakness: list[str] = []
    strength: list[str] = []
    ranking: list[str] = []

    for block in article.content:
        if block.type == "cta":
            continue
        raw_points = _block_points(block)
        for point in raw_points:
            if not point or point in general:
                continue
            general.append(point)
            lowered = point.lower()
            if any(word in lowered for word in _WEAKNESS_WORDS):
                weakness.append(point)
            if any(word in lowered for word in _STRENGTH_WORDS):
                strength.append(point)
        if block.type == "ranking":
            label = f"{block.rank}位：{block.text}" if block.rank is not None else block.text
            ranking.append(label)
            if block.desc:
                ranking.extend(_split_sentences(block.desc))

    return {
        "general": general,
        "weakness": weakness,
        "strength": strength,
        "ranking": list(dict.fromkeys(ranking)),
    }


def _block_points(block: ContentBlock) -> list[str]:
    if block.type in {"h3", "h4"}:
        return [block.text.strip()]
    if block.type == "ranking":
        points = [block.text.strip()]
        if block.desc:
            points.extend(_split_sentences(block.desc))
        return points
    if block.type == "p":
        return _split_sentences(block.text)
    return []


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text.strip()) if part.strip()]


def _ordered_source_points(
    extracted: dict[str, list[str]], *, is_ranking: bool
) -> tuple[str, ...]:
    if is_ranking:
        ranked = [point for point in extracted["ranking"] if len(point) <= 150]
        if ranked:
            explanations = [
                point
                for point in extracted["general"]
                if 8 <= len(point) <= 150 and point not in ranked
            ]
            return tuple(dict.fromkeys((*ranked[:5], *explanations[:12])))

    general = [point for point in extracted["general"] if 8 <= len(point) <= 150]
    if not general:
        general = extracted["general"]
    first = general[:3]
    weakness = next((p for p in extracted["weakness"] if p not in first and len(p) <= 150), None)
    strength = next((p for p in extracted["strength"] if p not in first and len(p) <= 150), None)
    ordered = [*first]
    if weakness:
        ordered.append(weakness)
    if strength:
        ordered.append(strength)
    ordered.extend(point for point in general[3:12] if point not in ordered)
    return tuple(dict.fromkeys(ordered))


def _deduplicate_source_points(points: Sequence[str]) -> list[str]:
    """空白と句読点だけが違う重複を除く。肯定・否定や条件は同一視しない。"""
    kept: list[str] = []
    signatures: set[str] = set()
    for point in points:
        normalized = re.sub(r"[\s、。]", "", point)
        if normalized in signatures:
            continue
        signatures.add(normalized)
        kept.append(point)
    return kept


def _choose_template(
    choices: Sequence[str],
    recent: Sequence[str],
    article_key: str,
    selected_at: datetime,
    kind: str,
) -> str:
    available = [choice for choice in choices if choice not in recent] or list(choices)
    digest = hashlib.sha256(
        f"{kind}|{article_key}|{selected_at.date().isoformat()}".encode("utf-8")
    ).digest()
    return available[int.from_bytes(digest[:4], "big") % len(available)]


def _build_tiktok(
    article: Article,
    template_id: str,
    source_points: tuple[str, ...],
    *,
    preserve_context: bool = True,
) -> tuple[str, tuple[str, ...]]:
    # Search small combinations rather than cutting sentences. This keeps every
    # factual phrase traceable to one complete source point.
    # 案内文の変更で本文の選定が変わらないよう、選定時だけ従来の長さを使う。
    selection_outro = "当てはまるところはありますか？\n詳しい続きはStellaLogの記事でどうぞ"
    points = source_points[:10]
    source_order = {point: index for index, point in enumerate(_extract_points(article)["general"])}
    if preserve_context:
        points = tuple(_deduplicate_source_points(points))
        points = tuple(sorted(points, key=lambda point: source_order.get(point, len(source_order))))
    candidates: list[tuple[int, int, int, int, int, str, tuple[str, ...]]] = []
    has_brain_task_explanation = any(
        _BRAIN_TASK_CONCLUSION in point for point in points
    )
    # The direct opening is intentionally shorter than the former explanatory
    # preamble, so allow one more complete source point to keep the 60-70 sec
    # target without padding the script with generic wording.
    max_items = min(10, len(points))
    for count in range(1, max_items + 1):
        for indexes in itertools.combinations(range(len(points)), count):
            if preserve_context and 0 not in indexes:
                # 導入の主題を残し、具体例だけを「あなたは」の直後へ置かない。
                continue
            if not _has_complete_tiktok_explanation(points, indexes):
                continue
            selected = tuple(points[index] for index in indexes)
            script = _render_tiktok(article, template_id, selected, outro=selection_outro)
            length = len(script)
            if length <= TIKTOK_MAX_CHARS:
                in_target = 0 if length >= TIKTOK_MIN_CHARS else 1
                missing_boundary = int(
                    not any(point.startswith(_BOUNDARY_HEADING) for point in selected)
                )
                missing_brain_task_explanation = int(
                    has_brain_task_explanation
                    and not any(
                        _BRAIN_TASK_CONCLUSION in point for point in selected
                    )
                )
                distance = abs(TIKTOK_TARGET_CHARS - length)
                candidates.append(
                    (
                        in_target,
                        missing_boundary,
                        missing_brain_task_explanation,
                        _context_penalty(selected, source_order) if preserve_context else 0,
                        distance,
                        script,
                        selected,
                    )
                )
    if not candidates:
        script = _render_tiktok(article, template_id, ())
        return script, ()
    _, _, _, _, _, script, selected = min(
        candidates,
        key=lambda item: (item[0], item[1], item[2], item[3], item[4]),
    )
    if len(script) < TIKTOK_MIN_CHARS:
        selected_list = list(selected)
        remaining = tuple(point for point in source_points if point not in points)
        index = 0
        while index < len(remaining) and len(script) < TIKTOK_MIN_CHARS:
            group = (remaining[index],)
            if (
                _BRAIN_TASK_CONCLUSION in remaining[index]
                and index + 1 < len(remaining)
                and remaining[index + 1].lstrip().startswith(("「", "『"))
            ):
                group = (remaining[index], remaining[index + 1])
            trial_selected = tuple((*selected_list, *group))
            if preserve_context:
                trial_selected = tuple(sorted(_deduplicate_source_points(trial_selected), key=lambda point: source_order.get(point, len(source_order))))
                if _context_penalty(trial_selected, source_order) > _context_penalty(selected, source_order):
                    index += len(group)
                    continue
            trial_script = _render_tiktok(article, template_id, trial_selected, outro=selection_outro)
            if len(trial_script) <= TIKTOK_MAX_CHARS:
                selected_list = list(trial_selected)
                script = trial_script
                selected = tuple(selected_list)
            index += len(group)
    return _render_tiktok(article, template_id, selected), selected


def _context_penalty(selected: tuple[str, ...], source_order: dict[str, int]) -> int:
    """指示語だけの文や、遠い段落の飛び込みを避けるための選定指標。"""
    positions = [source_order[point] for point in selected if point in source_order]
    chosen = set(positions)
    dangling = sum(
        1 for point in selected
        if re.match(r"^(?:そういった|そうした|そのため|それによって|それは|それが|これは|これが|この二つ|この矛盾)", point)
        and source_order.get(point, 0) - 1 not in chosen
    )
    gaps = sum(max(0, right - left - 1) for left, right in zip(positions, positions[1:]))
    return dangling * 20 + gaps


def _has_complete_tiktok_explanation(
    points: tuple[str, ...],
    indexes: tuple[int, ...],
) -> bool:
    selected_indexes = set(indexes)
    for index, point in enumerate(points[:-1]):
        if (
            _BRAIN_TASK_CONCLUSION in point
            and points[index + 1].lstrip().startswith(("「", "『"))
            and ((index in selected_indexes) != (index + 1 in selected_indexes))
        ):
            return False
    return True


def _render_tiktok(
    article: Article,
    _template_id: str,
    points: tuple[str, ...],
    *,
    outro: str = "当てはまるところはありますか？\n詳しい続きは\n「StellaLog」で\n検索してね",
) -> str:
    mbti_zodiac = f"{article.mbti.upper()}×{ZODIAC_LABELS.get(article.zodiac, article.zodiac)}"
    headline = TIKTOK_HEADLINE_LABELS.get(
        article.concern,
        f"本当の{CATEGORY_LABELS.get(article.concern, article.concern)}",
    )
    intro_lines = [f"{mbti_zodiac}の{headline}"]
    if article.concern == "ranking":
        intro_lines.append("StellaLog独自ランキング")
    points = _reorder_tiktok_points(points)
    rendered_points: list[str] = []
    for index, point in enumerate(points):
        point = _reorder_tiktok_explanation(point)
        direct_point = _to_polite_x_sentence(
            point,
            remove_leading_connector=True,
        )
        if index == 0:
            direct_point = _remove_repeated_tiktok_subject(
                direct_point,
                mbti_zodiac,
            )
            rendered_points.append(f"{mbti_zodiac}のあなたは\n{direct_point}")
        else:
            rendered_points.append(direct_point)
    # 空白行は動画の字幕カード境界として使う。見出し、各要点、締めを
    # 別々の意味単位にしておくと、画面上でも編集位置が分かりやすい。
    intro = "\n".join(intro_lines)
    script = "\n\n".join((intro, *rendered_points, outro))
    return _format_tiktok_text(script)


def _apply_reviewed_tiktok_layout(article: Article, script: str) -> str:
    """要点選定後の台本へ、重複除去と確認済みレイアウトを適用する。"""
    mbti_zodiac = (
        f"{article.mbti.upper()}×{ZODIAC_LABELS.get(article.zodiac, article.zodiac)}"
    )
    cleaned = re.sub(
        rf"(?m)^({re.escape(mbti_zodiac)}の)\nあなたは\n"
        r"(?=あなた(?:の|が|に|を|も|へ|と|から|自身))",
        r"\1\n",
        script,
        count=1,
    )
    display_text = remove_mbti_zodiac_crosses(cleaned)

    # 利用者が確認した文章だけを固定配置にする。本文が更新された場合は
    # 署名が一致しないため、自動生成結果をそのまま使う。
    reviewed_layout = _REVIEWED_TIKTOK_LAYOUTS.get(article.article_key)
    if reviewed_layout is not None:
        compact = re.sub(r"\s+", "", display_text)
        reviewed_compact = re.sub(r"\s+", "", reviewed_layout)
        if compact == reviewed_compact:
            return reviewed_layout
    return display_text


def _apply_tiktok_hook(article: Article, script: str) -> str:
    """本文の選定と確認済み配置を保ち、冒頭だけを記事固有の掴みにする。"""
    source_hook = article.sns_catchphrase.strip()
    _, separator, body = script.partition("\n\n")
    if not source_hook or not separator:
        return script

    hook = TIKTOK_HOOK_REPLACEMENTS.get(source_hook, source_hook)
    is_ranking = article.concern == "ranking"
    if is_ranking:
        match = re.fullmatch(r"一番相性が良いのは(.+?)[！!]?", hook)
        if match:
            hook = f"{match.group(1)}が\n相性1位になる理由"

    mbti_zodiac = (
        f"{article.mbti.upper()}{ZODIAC_LABELS.get(article.zodiac, article.zodiac)}"
    )
    theme = "相性" if is_ranking else CATEGORY_LABELS.get(article.concern, article.concern)
    # フレーズ末尾の句読点で対象タイプが別カードへ分かれないよう、
    # 冒頭の中だけ空行を除く。本文は再整形しない。
    hook_lines = [line for line in _format_tiktok_text(hook).splitlines() if line.strip()]
    context_lines = _wrap_tiktok_caption_line(f"{mbti_zodiac}の{theme}")
    intro_lines = [*hook_lines, *context_lines]
    if is_ranking:
        intro_lines.extend(("StellaLog独自", "ランキング"))
    intro = remove_mbti_zodiac_crosses(
        _group_tiktok_caption_cards("\n".join(intro_lines))
    )
    return f"{intro}{separator}{body}"


def _build_x(
    article: Article,
    _template_id: str,
    tiktok_points: tuple[str, ...],
    source_points: tuple[str, ...],
    post_url: str,
) -> tuple[str, tuple[str, ...]]:
    compact_points = tuple(
        point
        for point in dict.fromkeys((*source_points, *tiktok_points))
        if len(point) <= 105
    )[:8]
    if not compact_points:
        compact_points = tuple(dict.fromkeys((*tiktok_points, *source_points)))[:1]

    candidates: list[
        tuple[tuple[int, int, int, int, int, int, int], str, tuple[str, ...]]
    ] = []
    first_candidates = compact_points[:6]
    first_options: list[tuple[int, tuple[str, ...]]] = []
    for count in range(1, min(4, len(first_candidates)) + 1):
        for first_points in itertools.combinations(first_candidates, count):
            first_post, _ = _render_x_posts(article, first_points, (), post_url)
            first_weight = x_weighted_length(first_post)
            if first_weight <= 280:
                first_options.append((first_weight, first_points))

    # Try the fullest first-post options. Keeping this list small also keeps
    # daily generation fast across the full article corpus.
    first_options.sort(
        key=lambda item: (
            int(len(item[1]) >= 2),
            int(any(point.startswith(_BOUNDARY_HEADING) for point in item[1])),
            item[0],
        ),
        reverse=True,
    )
    for first_weight, first_points in first_options[:4]:
        remaining = tuple(point for point in compact_points if point not in first_points)
        weakness = tuple(
            point for point in remaining if any(word in point for word in _WEAKNESS_WORDS)
        )
        second_candidates = tuple(dict.fromkeys((*weakness, *remaining)))
        if not second_candidates:
            second_candidates = first_points[:1]
        for count in range(1, min(4, len(second_candidates)) + 1):
            for second_points in itertools.combinations(second_candidates, count):
                first_post, second_post = _render_x_posts(
                    article,
                    first_points,
                    second_points,
                    post_url,
                )
                second_weight = x_weighted_length(second_post)
                if second_weight > 280:
                    continue
                has_weakness = int(
                    any(
                        any(word in point for word in _WEAKNESS_WORDS)
                        for point in second_points
                    )
                )
                shared_in_both = int(
                    any(point in tiktok_points for point in first_points)
                    and any(point in tiktok_points for point in second_points)
                )
                shared_count = sum(
                    point in tiktok_points
                    for point in dict.fromkeys((*first_points, *second_points))
                )
                score = (
                    int(len(first_points) >= 2),
                    int(
                        any(
                            point.startswith(_BOUNDARY_HEADING)
                            for point in first_points
                        )
                    ),
                    has_weakness,
                    min(first_weight, second_weight),
                    first_weight + second_weight,
                    shared_in_both,
                    shared_count,
                )
                used = tuple(dict.fromkeys((*first_points, *second_points)))
                candidates.append(
                    (score, format_x_thread(first_post, second_post), used)
                )
    if candidates:
        _, thread, used = max(candidates, key=lambda item: item[0])
        return thread, used
    raise PostGenerationError("Xの2投稿を安全な長さに調整できませんでした")


def _render_x_posts(
    article: Article,
    first_points: tuple[str, ...],
    second_points: tuple[str, ...],
    post_url: str,
) -> tuple[str, str]:
    mbti_zodiac = f"{article.mbti.upper()}×{ZODIAC_LABELS.get(article.zodiac, article.zodiac)}"
    headline = TIKTOK_HEADLINE_LABELS.get(
        article.concern,
        f"本当の{CATEGORY_LABELS.get(article.concern, article.concern)}",
    )
    first_lines = [f"{mbti_zodiac}の{headline}", ""]
    first_lines.extend(
        f"・{_strip_terminal(_to_polite_x_sentence(point))}"
        for point in first_points
    )
    first_lines.extend(("", "でも、いちばん気になるところは…"))

    second_lines = [
        _to_polite_x_sentence(point, remove_leading_connector=index == 0)
        for index, point in enumerate(second_points)
    ]
    second_lines.extend(("", "詳しい続きはStellaLogの記事でどうぞ。", post_url))

    first_post = _clean_social_text("\n".join(first_lines))
    second_post = _clean_social_text("\n".join(second_lines))
    return first_post, second_post


def _build_hashtags(article: Article) -> tuple[str, ...]:
    candidates = (
        "#StellaLog",
        "#MBTI",
        "#星座",
        f"#{article.mbti.upper()}",
        f"#{ZODIAC_LABELS.get(article.zodiac, article.zodiac)}",
        CATEGORY_HASHTAGS.get(article.concern, f"#{article.concern}"),
    )
    return tuple(dict.fromkeys(candidates))[:6]


def _strip_terminal(text: str) -> str:
    return text.rstrip().rstrip("。！？!?")


def _ensure_sentence(text: str) -> str:
    stripped = text.strip()
    return stripped if stripped.endswith(("。", "！", "？", "!", "?")) else f"{stripped}。"


def _clean_social_text(text: str) -> str:
    cleaned = re.sub(r"[—―─]{2,}", "。", text)
    return re.sub(r"。{2,}", "。", cleaned)


def _to_polite_x_sentence(
    text: str,
    *,
    remove_leading_connector: bool = False,
) -> str:
    sentence = _clean_social_text(text).strip()
    sentence = sentence.replace(
        "「準備が終わるまで勝負しない」という賭け方",
        "準備が整うまで勝負に出ない傾向があります",
    )
    if remove_leading_connector:
        sentence = _LEADING_CONNECTOR.sub("", sentence, count=1)

    boundary_prefix = "境界線が溶けている。"
    if sentence.startswith(boundary_prefix):
        question = sentence.removeprefix(boundary_prefix).rstrip("。！？!?")
        if question:
            return f"{question}、境界線が曖昧です。"

    stem = sentence.rstrip("。！？!?")
    if re.search(r"(?:なる|れない|できない|しない|見せない|言えない)設計$", stem):
        return f"{stem[:-len('設計')]}傾向があります。"
    if stem.endswith("ですが"):
        return f"{stem[:-len('ですが')]}です。"
    if stem.endswith("か"):
        return f"{stem}？"
    if stem.endswith(
        (
            "です",
            "ます",
            "ません",
            "でした",
            "ました",
            "でしょう",
            "でしょうか",
            "ですか",
            "ますか",
            "ませんか",
        )
    ):
        return f"{stem}。"

    replacements = (
        ("ではない", "ではありません"),
        ("ている自分", "ている自分に気づきます"),
        ("である", "です"),
        ("なのだ", "なのです"),
        ("のだ", "のです"),
        ("だった", "でした"),
        ("している", "しています"),
        ("ている", "ています"),
        ("してしまう", "してしまいます"),
        ("てしまう", "てしまいます"),
        ("てくる", "てきます"),
        ("くる", "きます"),
        ("たがる", "たがります"),
        ("となる", "となります"),
        ("になる", "になります"),
        ("できる", "できます"),
        ("がある", "があります"),
        ("ある", "あります"),
        ("がいる", "がいます"),
        ("いる", "います"),
        ("する", "します"),
    )
    for plain, polite in replacements:
        if stem.endswith(plain):
            return f"{stem[: -len(plain)]}{polite}。"

    if stem.endswith("はない"):
        return f"{stem[:-3]}はありません。"
    negative_endings = {
        "わない": "いません",
        "かない": "きません",
        "がない": "ぎません",
        "さない": "しません",
        "たない": "ちません",
        "なない": "にません",
        "ばない": "びません",
        "まない": "みません",
        "らない": "りません",
    }
    for plain, polite in negative_endings.items():
        if stem.endswith(plain):
            return f"{stem[: -len(plain)]}{polite}。"

    godan_endings = {
        "う": "います",
        "く": "きます",
        "ぐ": "ぎます",
        "す": "します",
        "つ": "ちます",
        "ぬ": "にます",
        "ぶ": "びます",
        "む": "みます",
    }
    if stem and stem[-1] in godan_endings:
        return f"{stem[:-1]}{godan_endings[stem[-1]]}。"
    if stem.endswith(("る", "た")):
        if stem.endswith("る"):
            ichidan_preceding = "いきぎしじちにひびみりえけげせぜてでねへべめれ"
            polite = "ます" if len(stem) >= 2 and stem[-2] in ichidan_preceding else "ります"
            return f"{stem[:-1]}{polite}。"
        return f"{stem}のです。"

    return f"{stem}です。"


def _format_tiktok_text(text: str) -> str:
    question_marker = "__TIKTOK_QUESTION_MARK__"
    brand_marker = "__TIKTOK_STELLALOG__"
    text = text.replace("「StellaLog」", brand_marker)
    text = text.replace("当てはまるところはありますか？", f"当てはまるところはありますか{question_marker}")
    cleaned = _clean_social_text(text)
    cleaned = cleaned.replace("長所の裏に隠れた本音まで見ていきます", "")
    cleaned = cleaned.replace("記事では", "")
    cleaned = cleaned.replace("と描かれています", "です")
    cleaned = cleaned.replace("ですです", "です")
    cleaned = re.sub(r"[」』”\"]\s*[「『“\"]", "\n", cleaned)
    cleaned = re.sub(r"[、，,。．.!！?？:：;；]+", "\n", cleaned)
    cleaned = re.sub(r"[「」『』“”\"…]+", "", cleaned)
    cleaned = naturalize_tiktok_text(cleaned)
    cleaned = cleaned.replace(question_marker, "？")
    cleaned = cleaned.replace(brand_marker, "「StellaLog」")

    blocks = re.split(r"\n\s*\n", cleaned)
    formatted_blocks: list[str] = []
    for block in blocks:
        lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in block.splitlines()
            if line.strip()
        ]
        wrapped_lines = [
            wrapped
            for line in lines
            for wrapped in _wrap_tiktok_caption_line(line)
        ]
        if wrapped_lines:
            formatted_blocks.append("\n".join(wrapped_lines))
    return _group_tiktok_caption_cards("\n\n".join(formatted_blocks))


def _wrap_tiktok_caption_line(
    text: str,
    *,
    preferred_chars: int = 12,
    max_chars: int = 13,
) -> tuple[str, ...]:
    """日本語の助詞などを優先し、文字を変えずに字幕用の短い行へ分ける。"""
    clean = text.strip()
    if not clean:
        return ()
    if preferred_chars < 1 or max_chars < preferred_chars:
        raise ValueError("字幕の改行文字数を確認してください")

    wrapped: list[str] = []
    remaining = clean
    while len(remaining) > preferred_chars:
        upper = min(max_chars, len(remaining) - 1)
        lower = min(5, upper)
        candidates: list[tuple[int, int]] = []
        for position in range(lower, upper + 1):
            matching_words = [
                word
                for word in _TIKTOK_LINE_BREAK_WORDS
                if remaining[:position].endswith(word)
            ]
            if matching_words:
                # 「の」は名詞句の途中にも多いため、ほかの助詞・接続より優先度を下げる。
                priority = 2 if matching_words[0] == "の" else 0
                candidates.append((priority, position))
            elif remaining[position:].startswith(("という", "といった")):
                # 「という」は一まとまりで読みたいので、その直前を自然な切れ目にする。
                candidates.append((0, position))

        if candidates:
            non_orphaning = [
                candidate
                for candidate in candidates
                if len(remaining) - candidate[1] >= 4
            ]
            if non_orphaning:
                candidates = non_orphaning
            # 6～12文字に近く、残りが極端に短くならない助詞位置を優先する。
            split_at = min(
                candidates,
                key=lambda candidate: (
                    int(
                        remaining[candidate[1] :].startswith(
                            ("は", "が", "を", "に", "で", "と", "の", "も", "へ")
                        )
                        and not remaining[candidate[1] :].startswith(
                            ("という", "といった")
                        )
                    ),
                    int(
                        remaining[: candidate[1]].endswith("と")
                        and remaining[candidate[1] :].startswith(("いう", "いった"))
                    ),
                    int(0 < len(remaining) - candidate[1] < 4),
                    candidate[0],
                    abs(preferred_chars - candidate[1]),
                    -candidate[1],
                ),
            )[1]
        else:
            split_at = min(preferred_chars, upper)
            if 0 < len(remaining) - split_at < 4:
                split_at = max(1, len(remaining) - 4)
        wrapped.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        wrapped.append(remaining)
    return tuple(wrapped)


def _group_tiktok_caption_cards(
    text: str,
    *,
    max_lines_per_card: int = 5,
) -> str:
    """意味上の空白行を保ち、長いカードだけ同じ順序で分割する。"""
    if max_lines_per_card < 1:
        raise ValueError("字幕は1画面あたり1行以上に設定してください")

    semantic_blocks = re.split(r"\n\s*\n", text.strip())
    semantic_blocks = [block for block in semantic_blocks if block.strip()]
    if not semantic_blocks:
        return ""

    cards: list[str] = []
    for block in semantic_blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        card_count = max(1, (len(lines) + max_lines_per_card - 1) // max_lines_per_card)
        base_size, extra = divmod(len(lines), card_count)
        sizes = [base_size + (1 if index < extra else 0) for index in range(card_count)]
        offset = 0
        for size in sizes:
            cards.append("\n".join(lines[offset : offset + size]))
            offset += size
    return "\n\n".join(cards)


def _reorder_tiktok_explanation(text: str) -> str:
    if _BRAIN_TASK_CONCLUSION not in text:
        return text

    lead, examples = text.split(_BRAIN_TASK_CONCLUSION, maxsplit=1)
    examples = examples.strip()
    if not examples.startswith(("「", "『")):
        return text

    examples = examples.rstrip("。！？!?")
    return f"{lead}{examples}。{_BRAIN_TASK_CONCLUSION}"


def _reorder_tiktok_points(points: tuple[str, ...]) -> tuple[str, ...]:
    reordered: list[str] = []
    index = 0
    while index < len(points):
        current = points[index]
        if (
            _BRAIN_TASK_CONCLUSION in current
            and index + 1 < len(points)
            and points[index + 1].lstrip().startswith(("「", "『"))
        ):
            reordered.append(
                _reorder_tiktok_explanation(f"{current}{points[index + 1]}")
            )
            index += 2
            continue
        reordered.append(_reorder_tiktok_explanation(current))
        index += 1
    return tuple(reordered)


def _remove_repeated_tiktok_subject(text: str, _mbti_zodiac: str) -> str:
    sentence = text.strip()
    subject_index = sentence.find("あなたは")
    if subject_index >= 0:
        return (
            sentence[:subject_index]
            + sentence[subject_index + len("あなたは") :]
        )
    return sentence
