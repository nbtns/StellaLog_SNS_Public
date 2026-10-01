"""利用者が確認したINFJ蟹座の文章と、恋愛の相性1位の出典抽出。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .models import Article
from .labels import format_mbti_zodiac


PILOT_ARTICLE_KEY = "ranking/unisex/infj/cancer"
# 確認済みの文章の根拠にした二つの1位と説明。更新時は内容を見直す。
_REVIEWED_SOURCE_SHA256 = "22da8563ce7cacef67ac7e894ef64c053c6ba65d8a11698b189fb796f5bd757b"

_TIKTOK_SCRIPT = """あなたを自由にする恋と
尽くすほどすれ違う恋
INFJ蟹座の恋愛相性

神相性1位は
ENTP射手座

人の気持ちを気遣って
自分を後回しにしがちな
あなたを
世話をする役割から
解放してくれる相手です

新しい場所や
まだ知らない体験へ
連れ出してくれるので
一緒にいると
世界が広がります

楽しいだけで終わらず
深い話にも
応えてくれるので
表面的な付き合いに
とどまらない相手です

一方で
地雷相性1位は
ESTP牡羊座

あなたは深い絆を
確かめたいのに
相手が求めているのは
今この瞬間の自由です

相手を思って
尽くすほど
重いと受け取られて
距離が開きやすくなります

相手が離れるほど
あなたの執着も
強まりやすくなり
すれ違いが続きます

当てはまるところは
ありますか？
詳しい続きは
「StellaLog」で
検索してね"""

_X_FIRST = """INFJ×蟹座の恋愛相性

【神相性1位：ENTP×射手座】
周囲を気遣い、自分を後回しにしがちなあなたを、世話をする側から解放してくれる相手です。
新しい世界へ連れ出してくれて、深い会話にも応えてくれます。

一方、尽くすほどすれ違いやすい相手は…"""

_X_SECOND = """【地雷相性1位：ESTP×牡羊座】
あなたが深い絆を確かめたいとき、相手は今この瞬間の自由を求めがちです。
尽くすほど相手が離れ、離れるほどあなたの執着が強まる、すれ違いの繰り返しになりやすい相性です。

詳しい続きはStellaLogの記事でどうぞ。
{url}"""


@dataclass(frozen=True, slots=True)
class RankingPilot:
    tiktok_script: str
    x_first: str
    x_second: str
    source_points: tuple[str, ...]


def _first_rank_in_section(article: Article, kind: str) -> tuple[str, ...]:
    in_section = False
    for index, block in enumerate(article.content):
        if block.type in {"h3", "h4"}:
            in_section = "恋愛" in block.text and kind in block.text
        elif in_section and block.type == "ranking" and block.rank == 1:
            reasons = [block.desc] if block.desc else []
            for following in article.content[index + 1 :]:
                if following.type != "p":
                    break
                reasons.append(following.text)
            if reasons:
                return (block.text, *reasons)
    label = format_mbti_zodiac(article.mbti, article.zodiac)
    raise ValueError(f"{label}の恋愛の{kind}1位と理由を確認できませんでした。元記事を確認してください。")


def _ranking_source_points(article: Article) -> tuple[str, ...]:
    return (
        *_first_rank_in_section(article, "神相性"),
        *_first_rank_in_section(article, "地雷相性"),
    )


def build_ranking_pilot(article: Article, x_url: str) -> RankingPilot | None:
    if (
        article.article_key != PILOT_ARTICLE_KEY
        or (article.concern, article.gender, article.mbti, article.zodiac)
        != ("ranking", "unisex", "infj", "cancer")
    ):
        return None
    source_points = _ranking_source_points(article)
    signature = hashlib.sha256(
        json.dumps(source_points, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if signature != _REVIEWED_SOURCE_SHA256:
        raise ValueError(
            "INFJ蟹座の恋愛相性1位か、その説明が更新されています。"
            "元記事に合わせて投稿文を見直してください。"
        )
    return RankingPilot(_TIKTOK_SCRIPT, _X_FIRST, _X_SECOND.format(url=x_url), source_points)
