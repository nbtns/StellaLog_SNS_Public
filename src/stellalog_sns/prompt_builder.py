from __future__ import annotations

from .labels import (
    category_label,
    format_mbti_zodiac,
    gender_label,
    remove_mbti_zodiac_crosses,
)
from .models import PostSet


def build_chatgpt_prompt(post_set: PostSet) -> str:
    article = post_set.article
    points = "\n".join(f"- {point}" for point in post_set.source_points)
    hashtags = " ".join(post_set.hashtags)
    prompt = f"""以下のStellaLog記事を元に作ったSNS投稿案を調整してください。

【調整したいこと】
ここに希望を書いてください。

【元記事】
カテゴリー: {category_label(article.concern)}
タイプ: {format_mbti_zodiac(article.mbti, article.zodiac)}
性別: {gender_label(article.gender)}
タイトル: {article.title}

【元記事から抽出した要点】
{points}

【TikTok動画台本】
{post_set.tiktok_script}

【X投稿文（1つ目と2つ目）】
{post_set.x_post}

【URL】
TikTok: {post_set.tiktok_url}
X投稿内の計測用記事URL: {post_set.x_url}

【ハッシュタグ候補】
{hashtags}

【守ってほしい条件】
- 元記事にない内容を事実のように追加しない
- MBTIや星座を科学的診断や絶対的な事実として断定しない
- TikTok台本は自然に読み上げられる60〜70秒程度にする
- TikTokは記事からの引用口調を使わず、対象者へ直接語りかける
- TikTokは締めの疑問符と「StellaLog」のカギ括弧以外の句読点とカギ括弧を使わず、意味の区切りごとに改行する
- TikTokの最後は「当てはまるところはありますか？」に続けて、詳しい続きは「StellaLog」で検索してね と案内する
- 人物を「設計」「仕様」「プログラム」「バグ」「装置」などの機械として説明せず、実際の思考や行動の傾向を直接表現する
- Xは1つ目をあるあるネタ、2つ目を刺さる内容にする
- 1つ目のあるあるネタは複数の箇条書きにする
- Xの2投稿をそれぞれ文字数上限に収める
- Xはです・ます調に統一し、2つ目を接続詞から始めない
- 2つ目は「詳しい続きはStellaLogの記事でどうぞ。」の直後に記事URLを置く
- URLを変更しない
- 投稿前に人が確認する文章として仕上げる
""".strip()
    return remove_mbti_zodiac_crosses(prompt)
