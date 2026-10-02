from app.models.creative import CreativePlan
from app.models.timing import SongTiming, TimedLine
from app.services.subtitles import build_srt, srt_timestamp, subtitle_tracks
from app.services.timing_service import build_storyboard
from tests.test_creative_director import plan_dict


def timing() -> SongTiming:
    lines = [TimedLine(line_id=i, text=f"s{i}", start=2.0 + (i - 1) * 4.25,
                       end=5.5 + (i - 1) * 4.25, confidence=1, source="aligned")
             for i in range(1, 5)]
    return SongTiming(duration=20.0, method="test", lines=lines)


def test_srt_timestamp():
    assert srt_timestamp(4.25) == "00:00:04,250"
    assert srt_timestamp(3725.0055) == "01:02:05,006"


def test_bilingual_srt():
    srt = build_srt([(4.25, 8.14, "Quả táo!\nApple!")])
    assert srt == "1\n00:00:04,250 --> 00:00:08,140\nQuả táo!\nApple!\n"


def test_tracks_per_language():
    plan = CreativePlan.model_validate(plan_dict())
    tracks = subtitle_tracks(plan, timing(), "vi", "en")
    assert set(tracks) == {"vi", "en", "bilingual"}
    assert "p1\ne1" in tracks["bilingual"]
    assert tracks["vi"].count("-->") == 4


def test_storyboard_covers_whole_song():
    plan = CreativePlan.model_validate(plan_dict())
    sb = build_storyboard(plan, timing())
    assert sb.scenes[0].start == 0.0
    assert sb.scenes[-1].end == 20.0
    for a, b in zip(sb.scenes, sb.scenes[1:], strict=False):
        assert a.end == b.start
    assert sum(s.duration for s in sb.scenes) == 20.0
