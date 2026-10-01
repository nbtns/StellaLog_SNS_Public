from __future__ import annotations

import pytest

from stellalog_sns.natural_language import naturalize_tiktok_text


@pytest.mark.parametrize(
    ("original", "expected"),
    (
        (
            "あなたの恋愛が落ち着かないのは性格ではなく脳の仕様です",
            "あなたの恋愛が落ち着かないのは\n次々と新しい刺激に心が動きやすいからです",
        ),
        (
            "ESTP×牡羊座の超高速ロックオンシステムです",
            "気になる相手を一瞬で見つけて\n行動を始める傾向があります",
        ),
        (
            "あなたの脳に埋め込まれた待機モードです",
            "慎重になりすぎて\n動き出せない傾向があります",
        ),
        (
            "存在するだけで場の温度を上げる人間発熱装置です",
            "存在するだけで\n場を明るくする人です",
        ),
        (
            "内部で矛盾した二つのOSが同時に稼働しているような人です",
            "行動したい気持ちと\n慎重に考えたい気持ちを同時に抱える人です",
        ),
    ),
)
def test_reviewed_machine_metaphors_are_naturalized(
    original: str,
    expected: str,
) -> None:
    assert naturalize_tiktok_text(original) == expected


def test_real_technical_design_wording_is_not_changed() -> None:
    original = "公正な評価基準を設計する能力です"
    assert naturalize_tiktok_text(original) == original
