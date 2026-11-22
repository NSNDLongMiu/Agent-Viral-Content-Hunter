"""Configurable focus keywords and their compiled matching rules."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class FocusRules:
    """Keyword groups for short films, micro-drama, entertainment, and AI production."""

    phim_ngan: tuple[str, ...] = (
        "phim ngắn", "short film", "short films", "shortfilm", "短片", "微电影",
    )
    micro_drama: tuple[str, ...] = (
        "micro-drama", "microdrama", "microdramas", "micro drama", "short drama",
        "short dramas", "vertical drama", "mini drama", "phim nhiều tập",
        "phim ngắn nhiều tập", "短剧", "微短剧", "reelshort", "dramabox",
    )
    giai_tri: tuple[str, ...] = (
        "giải trí", "phim", "điện ảnh", "phim truyền hình", "diễn viên", "ca sĩ",
        "nghệ sĩ", "concert", "album", "gameshow", "game show", "talk show", "hài",
        "meme", "hoạt hình", "anime", "animation", "film", "movie", "tv series",
        "web series", "celebrity", "trailer", "娱乐", "电影", "综艺", "动画", "搞笑",
    )
    ai_san_xuat: tuple[str, ...] = (
        "ai video", "ai film", "ai movie", "ai short", "ai microdrama", "ai animation",
        "ai actor", "ai actors", "text-to-video", "text to video",
        "image-to-video", "image to video", "video generation", "video generator",
        "generative video", "aigc", "làm phim bằng ai", "video do ai", "phim ai",
        "ai生成", "ai短剧", "人工智能生成",
    )
    ai_san_xuat_weak: tuple[str, ...] = (
        "ai-generated", "ai generated", "ai-made", "ai voice", "ai music", "ai avatar",
    )
    ai_san_xuat_media: tuple[str, ...] = (
        "video", "videos", "film", "films", "movie", "movies", "animation", "animated",
        "cartoon", "anime", "drama", "series", "trailer", "clip", "cinema", "short",
        "shorts", "phim", "hoạt hình", "视频", "电影", "动画", "短剧", "短片",
    )


# Han (including extensions), kana, bopomofo, and Hangul.
_CJK = re.compile(
    r"[\u1100-\u11ff\u3040-\u30ff\u3100-\u312f\u3130-\u318f\u31a0-\u31bf"
    r"\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\ua960-\ua97f\uac00-\ud7ff"
    r"\uf900-\ufaff\uff66-\uff9f\U00020000-\U000323af]"
)
_AI_TOKEN = re.compile(r"(?<!\w)(?:AI|A\.I\.)(?!\w)")


class KeywordMatcher:
    def __init__(self, keywords: Sequence[str]) -> None:
        self._keywords: list[tuple[str, str, re.Pattern[str] | None]] = []
        for keyword in keywords:
            if not keyword:
                continue
            normalized = keyword.lower()
            if normalized == "ai":
                pattern = _AI_TOKEN
            elif _CJK.search(normalized):
                pattern = None
            else:
                pattern = re.compile(rf"(?<!\w){re.escape(normalized)}(?!\w)")
            self._keywords.append((keyword, normalized, pattern))

    def find(self, text: str, lowercase_text: str) -> Iterator[str]:
        for keyword, normalized, pattern in self._keywords:
            if pattern is None:
                matches = normalized in lowercase_text
            else:
                corpus = text if normalized == "ai" else lowercase_text
                matches = pattern.search(corpus) is not None
            if matches:
                yield keyword

    def matches(self, text: str, lowercase_text: str) -> bool:
        return next(self.find(text, lowercase_text), None) is not None
