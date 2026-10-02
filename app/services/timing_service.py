"""Song analysis: song.wav -> transcript.json -> timing.json, then timing -> storyboard.json."""

from __future__ import annotations

from app.models.creative import CreativePlan
from app.models.state import Gate
from app.models.timing import SongTiming, Storyboard, StoryboardScene
from app.pipeline.context import MissingArtifact, PipelineContext
from app.utils.alignment import align_lines
from app.utils.ffmpeg import media_duration, to_speech_mp3
from app.utils.files import write_json

MIN_SCENE_SECONDS = 1.0


async def analyze_timing(ctx: PipelineContext, *, force: bool = False) -> SongTiming:
    paths = ctx.paths
    if paths.timing.exists() and not force:
        return ctx.timing()
    if not paths.song.exists():
        raise MissingArtifact(f"no song yet; run: kidsvideo music {ctx.project_id}")

    plan = ctx.plan()
    duration = await media_duration(paths.song)
    speech_file = await to_speech_mp3(paths.song, paths.audio / "song_speech.mp3")
    lyrics_hint = " ".join(line.sung for line in plan.lyrics)
    result = await ctx.speech().transcribe(speech_file, prompt=lyrics_hint)
    write_json(paths.transcript, result.transcript.model_dump())

    lines = align_lines([(line.id, line.sung) for line in plan.lyrics], result.transcript.words,
                        duration)
    timing = SongTiming(duration=round(duration, 3), method=f"align:{result.model}", lines=lines)
    write_json(paths.timing, timing.model_dump())
    return timing


def build_storyboard(plan: CreativePlan, timing: SongTiming) -> Storyboard:
    """Scenes fill the whole song: each starts at its first line and runs until the next scene.

    The first scene also covers any instrumental intro; the last runs to the end of the song.
    """
    scenes: list[StoryboardScene] = []
    starts = [timing.line(s.lyric_line_ids[0]).start for s in plan.scenes]
    starts[0] = 0.0
    for i, scene in enumerate(plan.scenes):
        end = starts[i + 1] if i + 1 < len(plan.scenes) else timing.duration
        scenes.append(StoryboardScene(
            **scene.model_dump(),
            start=round(starts[i], 3),
            end=round(end, 3),
            lyrics=[plan.line(lid) for lid in scene.lyric_line_ids],
        ))
    return Storyboard(duration=timing.duration, scenes=scenes)


def storyboard_warnings(storyboard: Storyboard) -> list[str]:
    return [f"scene {s.id} is only {s.duration:.2f}s long"
            for s in storyboard.scenes if s.duration < MIN_SCENE_SECONDS]


def generate_storyboard(ctx: PipelineContext) -> Storyboard:
    ctx.require_gate(Gate.lyrics)
    storyboard = build_storyboard(ctx.plan(), ctx.timing())
    # If this changes the file, an existing approval goes stale automatically (hash mismatch).
    write_json(ctx.paths.storyboard, storyboard.model_dump())
    return storyboard
