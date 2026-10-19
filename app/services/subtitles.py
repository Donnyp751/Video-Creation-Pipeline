"""SRT subtitles per language plus a bilingual track, from song timing."""

from __future__ import annotations

from pathlib import Path

from app.models.creative import CreativePlan, LyricLine
from app.models.timing import SongTiming
from app.pipeline.context import PipelineContext
from app.utils.files import write_text
from app.utils.scripts import is_chinese


def srt_timestamp(seconds: float) -> str:
    ms_total = max(0, round(seconds * 1000))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(cues: list[tuple[float, float, str]]) -> str:
    blocks = []
    for i, (start, end, text) in enumerate(cues, start=1):
        blocks.append(f"{i}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{text.strip()}\n")
    return "\n".join(blocks)


def _with_romanization(text: str, lang: str, line: LyricLine, show: bool) -> str:
    """Chinese text, with the pinyin line above it when requested (common for learners)."""
    if show and is_chinese(lang) and line.romanization.strip():
        return f"{line.romanization.strip()}\n{text}"
    return text


def subtitle_tracks(plan: CreativePlan, timing: SongTiming, primary: str, secondary: str,
                    *, romanization: bool = False) -> dict[str, str]:
    p, s, both = [], [], []
    for line in plan.lyrics:
        t = timing.line(line.id)
        if t.end - t.start <= 0.05:
            continue
        prim = _with_romanization(line.primary, primary, line, romanization)
        sec = _with_romanization(line.secondary, secondary, line, romanization)
        p.append((t.start, t.end, prim))
        s.append((t.start, t.end, sec))
        both.append((t.start, t.end, f"{prim}\n{sec}"))
    return {primary: build_srt(p), secondary: build_srt(s), "bilingual": build_srt(both)}


def write_subtitles(ctx: PipelineContext) -> dict[str, Path]:
    langs = ctx.spec.languages
    tracks = subtitle_tracks(ctx.plan(), ctx.timing(), langs.primary, langs.secondary,
                             romanization=langs.romanization)
    out = {}
    for name, text in tracks.items():
        path = ctx.paths.subtitles / f"{name}.srt"
        write_text(path, text)
        out[name] = path
    return out
