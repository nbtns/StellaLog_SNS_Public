from __future__ import annotations

import re

CATEGORY_LABELS = {
    "personality": "性格",
    "ranking": "ランキング",
    "love": "恋愛",
    "work": "仕事",
    "money": "金運",
    "reunion": "復縁",
    "night": "夜",
}

GENDER_LABELS = {
    "unisex": "共通",
    "female": "女性",
    "male": "男性",
}

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

MBTI_VALUES = (
    "enfj",
    "enfp",
    "entj",
    "entp",
    "esfj",
    "esfp",
    "estj",
    "estp",
    "infj",
    "infp",
    "intj",
    "intp",
    "isfj",
    "isfp",
    "istj",
    "istp",
)

_MBTI_ZODIAC_CROSS = re.compile(
    r"(?<![A-Z])([EI][NS][FT][JP])\s*×\s*("
    + "|".join(map(re.escape, ZODIAC_LABELS.values()))
    + r")",
    flags=re.IGNORECASE,
)


def category_label(value: str) -> str:
    return CATEGORY_LABELS.get(value, value)


def gender_label(value: str) -> str:
    return GENDER_LABELS.get(value, value)


def zodiac_label(value: str) -> str:
    return ZODIAC_LABELS.get(value, value)


def format_mbti_zodiac(mbti: str, zodiac: str) -> str:
    """掛け合わせ記号を使わず、MBTIと星座を続けて表示する。"""
    return f"{mbti.upper()}{zodiac_label(zodiac)}"


def remove_mbti_zodiac_crosses(text: str) -> str:
    """MBTIと星座の間にある掛け合わせ記号だけを除去する。"""
    return _MBTI_ZODIAC_CROSS.sub(r"\1\2", text)
