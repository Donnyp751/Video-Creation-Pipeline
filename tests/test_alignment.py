from app.models.timing import Word
from app.utils.alignment import align_lines, normalize_token

LINES = [(1, "Quả táo, apple!"), (2, "Chuối vàng, chuối vàng"), (3, "Quả cam, orange!")]


def words(spec: list[tuple[str, float]]) -> list[Word]:
    return [Word(text=t, start=s, end=s + 0.4) for t, s in spec]


def test_normalize_strips_vietnamese_diacritics():
    assert normalize_token("Chuối,") == "chuoi"
    assert normalize_token("Đây?") == "day"


def test_alignment_matches_noisy_transcript():
    # Transcript lacks accents, has a filler word and mishears "orange" as "orang".
    w = words([("qua", 2.0), ("tao", 2.5), ("apple", 3.0), ("la", 3.6), ("chuoi", 5.0),
               ("vang", 5.5), ("chuoi", 6.0), ("vang", 6.5), ("qua", 8.0), ("cam", 8.5),
               ("orang", 9.0)])
    out = align_lines(LINES, w, duration=12.0)
    assert [t.line_id for t in out] == [1, 2, 3]
    assert out[0].start == 2.0 and out[0].source == "aligned"
    assert out[1].start == 5.0 and out[1].end == 6.9
    assert out[2].start == 8.0
    assert 0.5 < out[2].confidence < 1.0
    assert all(a.end <= b.start for a, b in zip(out, out[1:], strict=False))


def test_unmatched_lines_are_interpolated():
    w = words([("qua", 2.0), ("tao", 2.5), ("apple", 3.0), ("qua", 9.0), ("cam", 9.5),
               ("orange", 10.0)])
    out = align_lines(LINES, w, duration=12.0)
    middle = out[1]
    assert middle.source == "interpolated"
    assert out[0].end <= middle.start < middle.end <= out[2].start


def test_no_transcript_spreads_lines_over_song():
    out = align_lines(LINES, [], duration=9.0)
    assert out[0].start == 0.0 and out[-1].end == 9.0
    assert all(t.source == "interpolated" for t in out)
