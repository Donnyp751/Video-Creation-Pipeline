"""Music generation: approved lyrics -> audio/song.wav (+ request/response provenance)."""

from __future__ import annotations

import shutil

from app.models.creative import CreativePlan
from app.models.project import ProjectSpec
from app.models.state import Gate
from app.pipeline.context import PipelineContext
from app.providers.music.base import MusicRequest, MusicSection
from app.services.creative_director import lang_name
from app.utils.ffmpeg import media_duration, to_wav
from app.utils.files import list_versions, now_iso, write_json


def build_music_request(spec: ProjectSpec, plan: CreativePlan) -> MusicRequest:
    sections: list[MusicSection] = []
    counts: dict[str, int] = {}
    for line in plan.lyrics:
        if not sections or sections[-1].name.rsplit(" ", 1)[0] != line.section.title():
            counts[line.section] = counts.get(line.section, 0) + 1
            sections.append(MusicSection(name=f"{line.section.title()} {counts[line.section]}",
                                         lines=[]))
        sections[-1].lines.append(line.sung)
    c = spec.creative
    return MusicRequest(
        title=plan.title,
        style=c.music_style or plan.music.style,
        tempo_bpm=c.tempo_bpm or plan.music.tempo_bpm,
        mood=plan.music.mood,
        vocal_description=c.vocal_description or plan.music.vocal_description,
        duration_seconds=c.duration_target_seconds,
        languages=[lang_name(spec.languages.primary), lang_name(spec.languages.secondary)],
        sections=sections,
        avoid=["explicit content", "scary sounds", "heavy distortion"],
    )


async def generate_music(ctx: PipelineContext, *, force: bool = False):
    paths = ctx.paths
    if paths.song.exists() and not force:
        return paths.song
    ctx.require_gate(Gate.lyrics)

    request = build_music_request(ctx.spec, ctx.plan())
    versions = list_versions(paths.audio, "song", ".wav")
    n = versions[-1][0] + 1 if versions else 1
    provider = ctx.music(regeneration=n > 1)
    raw = paths.audio / f"song_raw_v{n}{provider.output_extension}"

    write_json(paths.music_request, {"version": n, "provider": provider.name,
                                     "model": provider.model, "request": request.model_dump()})
    result = await provider.compose(request, raw, variant=n)

    wav = paths.audio / f"song_v{n}.wav"
    await to_wav(raw, wav)
    duration = await media_duration(wav)
    shutil.copy2(wav, paths.song)
    write_json(paths.music_response, {
        "version": n,
        "created_at": now_iso(),
        "provider": provider.name,
        "model": result.model,
        "cache_hit": result.cache_hit,
        "raw_file": raw.name,
        "song_file": wav.name,
        "duration": duration,
        "provider_payload": result.request_payload,
        "provider_meta": result.raw,
    })
    # Timing and everything downstream describe the old song now.
    paths.timing.unlink(missing_ok=True)
    ctx.revoke(Gate.storyboard)
    return paths.song
