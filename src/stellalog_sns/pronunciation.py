"""StellaLogの台本だけに適用する、保守的な読み上げ補正。"""

from __future__ import annotations

import re


# 長い語句から先に置き換える。一般的な漢字を無差別に仮名へ変えず、
# StellaLogの記事と現在のVOICEVOXで誤読を確認できた語句だけを扱う。
_LITERAL_PRONUNCIATIONS = (
    # 食べ物の「辛い」は「からい」。後続の一般ルールより先に保護する。
    ("辛い食べ物", "からい食べ物"),
    ("金星星座", "きんせいせいざ"),
    ("一段落", "ひとだんらく"),
    ("他人事", "ひとごと"),
    ("一途", "いちず"),
    ("辛かった", "つらかった"),
    ("辛ければ", "つらければ"),
    ("辛く", "つらく"),
)


# 「快」は単独なら「かい」と読むが、「快適」「不快」「爽快」や
# 「快い」「快く」では別の語になるため、漢字の複合語と活用形を除外する。
_STANDALONE_KAI = re.compile(
    r"(?<![一-龯々])快(?![一-龯々]|い|く|かった)"
)

# 「口」は単独の名詞なら「くち」と読む。VOICEVOXが「こう」と誤読する場合に
# 限って補正し、「人口」「蛇口」「口座」「入口」などの複合語は変えない。
# 数字に続く「3口」のような助数詞も読みが文脈で変わるため対象外にする。
_STANDALONE_KUCHI = re.compile(
    r"(?<![一-龯々0-9０-９])口(?![一-龯々])"
)


def correct_pronunciation(text: str) -> str:
    """字幕を変えず、VOICEVOXへ渡す文章だけ既知の正しい読みにする。"""

    corrected = text
    for surface, pronunciation in _LITERAL_PRONUNCIATIONS:
        corrected = corrected.replace(surface, pronunciation)
    corrected = _STANDALONE_KAI.sub("かい", corrected)
    return _STANDALONE_KUCHI.sub("くち", corrected)
