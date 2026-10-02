from pathlib import Path

from app.core.config import RenderPreset
from app.services.render_service import Clip, Segment, build_render_plan

PRESET = RenderPreset(resolution="1280x720", fps=25, crossfade=0.5)


def test_crossfade_offsets_keep_audio_sync():
    clips = [Clip(Path("a.mp4"), 4.0), Clip(Path("b.mp4"), 3.0), Clip(Path("c.mp4"), 5.0)]
    plan = build_render_plan(clips, Path("song.wav"), 12.0, PRESET)
    # Each transition starts exactly where the next scene starts on the song timeline.
    assert plan.xfade_offsets == [4.0, 7.0]
    # Non-final clips are extended by the crossfade so total length equals the song.
    assert "trim=duration=4.500" in plan.filter_complex
    assert "trim=duration=3.500" in plan.filter_complex
    assert "trim=duration=5.000" in plan.filter_complex
    assert plan.total_duration == 12.0
    assert "loudnorm" in plan.filter_complex


def test_stills_subtitles_and_crop():
    preset = PRESET.model_copy(update={"fit": "crop", "crossfade": 0.0})
    clips = [Clip(Path("a.png"), 2.0, still=True), Clip(Path("b.mp4"), 2.0)]
    plan = build_render_plan(clips, Path("song.wav"), 4.0, preset, subtitles_file="subs.srt")
    assert plan.inputs[0][:2] == ["-loop", "1"]
    assert "concat=n=2:v=1:a=0" in plan.filter_complex
    assert "subtitles=filename=subs.srt" in plan.filter_complex
    assert "crop=1280:720" in plan.filter_complex


def test_intro_outro_extend_total():
    clips = [Clip(Path("a.mp4"), 10.0)]
    plan = build_render_plan(clips, Path("song.wav"), 10.0, PRESET,
                             intro=Segment(Path("i.mp4"), 2.0, has_audio=False),
                             outro=Segment(Path("o.mp4"), 3.0, has_audio=True))
    assert plan.total_duration == 15.0
    assert "anullsrc" in plan.filter_complex
    assert "concat=n=3:v=1:a=1" in plan.filter_complex


def test_short_scene_falls_back_to_cuts():
    clips = [Clip(Path("a.mp4"), 0.3), Clip(Path("b.mp4"), 3.0)]
    plan = build_render_plan(clips, Path("song.wav"), 3.3, PRESET)
    assert "xfade" not in plan.filter_complex
