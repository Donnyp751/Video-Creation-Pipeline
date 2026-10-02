"""SRT subtitles per language plus a bilingual track, from song timing."""

from __future__ import annotations

from pathlib import Path

from app.models.creative import CreativePlan
from app.models.timing import SongTiming
from app.pipeline.context import PipelineContext
from app.utils.files import write_text


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


def subtitle_tracks(plan: CreativePlan, timing: SongTiming, primary: str, secondary: str
                    ) -> dict[str, str]:
    p, s, both = [], [], []
    for line in plan.lyrics:
        t = timing.line(line.id)
        if t.end - t.start <= 0.05:
            continue
        p.append((t.start, t.end, line.primary))
        s.append((t.start, t.end, line.secondary))
        both.append((t.start, t.end, f"{line.primary}\n{line.secondary}"))
    return {primary: build_srt(p), secondary: build_srt(s), "bilingual": build_srt(both)}


def write_subtitles(ctx: PipelineContext) -> dict[str, Path]:
    langs = ctx.spec.languages
    tracks = subtitle_tracks(ctx.plan(), ctx.timing(), langs.primary, langs.secondary)
    out = {}
    for name, text in tracks.items():
        path = ctx.paths.subtitles / f"{name}.srt"
        write_text(path, text)
        out[name] = path
    return out
