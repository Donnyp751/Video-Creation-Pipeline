"""Writing-system rules per language: which script lyrics must use, romanization, fonts.

Chinese lyrics must be written in characters (汉字); pinyin is an optional *extra* line, never
a replacement. These rules are enforced on LLM output, not just requested in the prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LATIN_WORD = re.compile(r"[A-Za-z\u00c0-\u024f]{2,}")

CHINESE = {"zh", "zh-hans", "zh-hant", "cmn"}


def is_chinese(lang: str) -> bool:
    return lang.lower() in CHINESE


def has_cjk(text: str) -> bool:
    return bool(CJK.search(text))


def script_name(lang: str, script: str) -> str:
    """Human description of the required writing system, for prompts and errors."""
    if is_chinese(lang):
        return ("Traditional Chinese characters (繁體字)" if script == "traditional"
                else "Simplified Chinese characters (简体字)")
    return "its standard writing system"


def check_chinese_text(text: str, field: str) -> str | None:
    """Error message if ``text`` is not Chinese characters (e.g. pinyin), else None."""
    if not has_cjk(text):
        return f"{field} must be written in Chinese characters (汉字), not pinyin: {text!r}"
    if LATIN_WORD.search(text):
        return (f"{field} must contain only Chinese characters; move pinyin to "
                f"'romanization' and English to the English field: {text!r}")
    return None


# --- fonts -------------------------------------------------------------------------------------
# libass (burned-in subtitles) resolves family names through fontconfig and falls back to any
# installed font with the needed glyphs; naming the right family gives consistent results.
SUBTITLE_FONTS = {"simplified": "Noto Sans CJK SC", "traditional": "Noto Sans CJK TC"}
DEFAULT_SUBTITLE_FONT = "DejaVu Sans"

# (path, face index inside .ttc). Noto Sans CJK collections order faces JP, KR, SC, TC, HK.
_CJK_BOLD_FONTS = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", {"simplified": 2, "traditional": 3}),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", {"simplified": 2, "traditional": 3}),
    ("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc", {"simplified": 2, "traditional": 3}),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", {}),
    ("/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc", {}),
    ("/System/Library/Fonts/PingFang.ttc", {}),
    ("C:/Windows/Fonts/msyhbd.ttc", {}),
    ("C:/Windows/Fonts/msyh.ttc", {}),
]


def subtitle_font(languages: tuple[str, ...], script: str) -> str:
    if any(is_chinese(lang) for lang in languages):
        return SUBTITLE_FONTS.get(script, SUBTITLE_FONTS["simplified"])
    return DEFAULT_SUBTITLE_FONT


def cjk_font_file(script: str = "simplified") -> tuple[Path, int] | None:
    for path, faces in _CJK_BOLD_FONTS:
        p = Path(path)
        if p.is_file():
            return p, faces.get(script, 0)
    return None
