"""公開版は本番記事フォルダに依存せず、同梱のサンプルを読み込みます。"""
from stellalog_sns.article_repository import ArticleRepository
from stellalog_sns.models import AppSettings


def test_packaged_sample_data_loads_without_external_articles():
    result = ArticleRepository(AppSettings().data_dir).load_all()
    assert result.indexed_count == 7
    assert len(result.articles) == 7
    assert result.warnings == ()
