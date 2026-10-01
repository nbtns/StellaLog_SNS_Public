from __future__ import annotations

import json
from pathlib import Path

import pytest

from stellalog_sns.article_repository import ArticleRepository


def test_loads_valid_article_and_skips_unknown_content(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    article_path = data_dir / "articles" / "love" / "female" / "enfj" / "aquarius.json"
    article_path.parent.mkdir(parents=True)
    (data_dir / "article-index.json").write_text(
        json.dumps(["love/female/enfj/aquarius", "../../outside/bad"]), encoding="utf-8"
    )
    article_path.write_text(
        json.dumps(
            {
                "mbti": "enfj",
                "zodiac": "aquarius",
                "gender": "female",
                "concern": "love",
                "title": "テスト記事",
                "sns_catchphrase": "短いキャッチコピー",
                "content": [
                    {"type": "h3", "text": "見出し"},
                    {"type": "p", "text": "記事に書かれた特徴です。"},
                    {"type": "future", "text": "未知要素"},
                    {"type": "cta", "text": "販売案内"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = ArticleRepository(data_dir).load_all()

    assert result.indexed_count == 2
    assert len(result.articles) == 1
    assert result.articles[0].article_key == "love/female/enfj/aquarius"
    assert [block.type for block in result.articles[0].content] == ["h3", "p", "cta"]
    assert any("未知のcontent.type" in warning for warning in result.warnings)
    assert any("パス形式が不正" in warning for warning in result.warnings)


def test_broken_article_does_not_stop_other_articles(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    root = data_dir / "articles" / "personality" / "unisex" / "infj"
    root.mkdir(parents=True)
    (data_dir / "article-index.json").write_text(
        json.dumps(["personality/unisex/infj/aries", "personality/unisex/infj/taurus"]),
        encoding="utf-8",
    )
    (root / "aries.json").write_text("{broken", encoding="utf-8")
    (root / "taurus.json").write_text(
        json.dumps(
            {
                "mbti": "infj",
                "zodiac": "taurus",
                "gender": "unisex",
                "concern": "personality",
                "title": "有効な記事",
                "sns_catchphrase": "キャッチ",
                "content": [{"type": "p", "text": "本文です。"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = ArticleRepository(data_dir).load_all()

    assert [article.zodiac for article in result.articles] == ["taurus"]
    assert any("JSONを読み込めません" in warning for warning in result.warnings)
