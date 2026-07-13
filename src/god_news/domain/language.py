from __future__ import annotations


def is_chinese_language(language: str | None) -> bool:
    """Return whether a declared source language denotes Chinese."""

    if language is None:
        return False
    normalized = language.strip().casefold().replace("_", "-")
    return normalized in {"zh", "zh-cn", "zh-hans", "zh-hant", "chinese", "cmn"} or (
        normalized.startswith("zh-")
    )


def looks_like_chinese_han_text(content: str) -> bool:
    """Conservatively identify unlabelled Chinese Han text.

    Japanese Kana vetoes the fallback.  A Han majority and a modest minimum
    avoid treating a lone proper noun or a mixed English article as Chinese.
    """

    han_count = sum(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in content
    )
    kana_count = sum(
        "\u3040" <= character <= "\u30ff" or "\u31f0" <= character <= "\u31ff"
        for character in content
    )
    letter_count = sum(character.isalpha() for character in content)
    return han_count >= 8 and kana_count == 0 and han_count * 2 >= max(1, letter_count)


def should_preserve_chinese_source(content: str, source_language: str | None) -> bool:
    """Decide whether a translation adapter must retain original Chinese text.

    Explicit non-Chinese metadata wins over the text heuristic.  This protects
    sources which legitimately contain quoted Chinese while declaring another
    source language.
    """

    return is_chinese_language(source_language) or (
        source_language is None and looks_like_chinese_han_text(content)
    )
