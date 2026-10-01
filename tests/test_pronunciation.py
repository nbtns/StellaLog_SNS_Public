from __future__ import annotations

import pytest

from stellalog_sns.pronunciation import correct_pronunciation


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("仕事が辛くなる", "仕事がつらくなる"),
        ("本当に辛かった", "本当につらかった"),
        ("仕事が辛ければ休む", "仕事がつらければ休む"),
        ("心の快と不快", "心のかいと不快"),
        ("快・不快の境界", "かい・不快の境界"),
        ("一途さ", "いちずさ"),
        ("他人事ではない", "ひとごとではない"),
        ("仕事が一段落した", "仕事がひとだんらくした"),
        ("金星星座の位置", "きんせいせいざの位置"),
        ("口を開いて口から話す", "くちを開いてくちから話す"),
        ("あなたの口が動き出す", "あなたのくちが動き出す"),
    ),
)
def test_corrects_confirmed_and_high_risk_stellalog_readings(
    source: str,
    expected: str,
) -> None:
    assert correct_pronunciation(source) == expected


def test_keeps_spicy_food_and_other_kai_compounds_distinct() -> None:
    source = (
        "辛い食べ物と仕事が辛いと心の辛さと相手が辛そうと"
        "快適で爽快な場所と不快な音と快い返事と快く応じる"
    )
    assert correct_pronunciation(source) == (
        "からい食べ物と仕事が辛いと心の辛さと相手が辛そうと"
        "快適で爽快な場所と不快な音と快い返事と快く応じる"
    )


def test_keeps_kuchi_compounds_and_counters_distinct() -> None:
    source = "人口と蛇口と口座と入口と一口と三口と3口の窓口"

    assert correct_pronunciation(source) == source


def test_pronunciation_correction_does_not_modify_the_original_subtitle() -> None:
    subtitle = "仕事が辛くなる\n快と不快の境界"

    narration = correct_pronunciation(subtitle)

    assert subtitle == "仕事が辛くなる\n快と不快の境界"
    assert narration == "仕事がつらくなる\nかいと不快の境界"
