"""Align known lyric lines to a word-timestamped transcript of the sung audio.

Transcription of singing is noisy, so instead of trusting the transcript text we match the
*known* lyrics against it (accent-insensitive sequence matching), take timestamps from matched
words, and interpolate lines that couldn't be matched.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from app.models.timing import TimedLine, Word

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_token(token: str) -> str:
    token = token.lower().replace("đ", "d")
    token = unicodedata.normalize("NFKD", token)
    token = "".join(ch for ch in token if not unicodedata.combining(ch))
    return _PUNCT.sub("", token).strip()


def tokenize(text: str) -> list[str]:
    return [t for t in (normalize_token(w) for w in text.split()) if t]


def align_lines(
    lines: list[tuple[int, str]],
    words: list[Word],
    duration: float,
    *,
    lead_in: float = 0.0,
) -> list[TimedLine]:
    """``lines`` is ``[(line_id, sung_text)]`` in order. Returns one TimedLine per input line."""
    lyric_tokens: list[str] = []
    owner: list[int] = []  # index into ``lines`` for each lyric token
    for idx, (_, text) in enumerate(lines):
        toks = tokenize(text)
        lyric_tokens += toks
        owner += [idx] * len(toks)

    trans = [(normalize_token(w.text), w) for w in words]
    trans = [(t, w) for t, w in trans if t]
    trans_tokens = [t for t, _ in trans]

    matched: dict[int, list[Word]] = {}
    sm = SequenceMatcher(None, lyric_tokens, trans_tokens, autojunk=False)
    for block in sm.get_matching_blocks():
        for k in range(block.size):
            matched.setdefault(owner[block.a + k], []).append(trans[block.b + k][1])

    token_counts = [max(1, len(tokenize(text))) for _, text in lines]
    starts: list[float | None] = [None] * len(lines)
    ends: list[float | None] = [None] * len(lines)
    conf = [0.0] * len(lines)
    for idx, ws in matched.items():
        starts[idx] = min(w.start for w in ws)
        ends[idx] = max(w.end for w in ws)
        conf[idx] = min(1.0, len(ws) / token_counts[idx])

    # Interpolate runs of unmatched lines between their matched neighbours.
    i = 0
    while i < len(lines):
        if starts[i] is not None:
            i += 1
            continue
        j = i
        while j < len(lines) and starts[j] is None:
            j += 1
        left = ends[i - 1] if i > 0 else lead_in
        right = starts[j] if j < len(lines) else duration
        span = max(right - left, 0.0)
        weight = sum(token_counts[i:j])
        t = left
        for k in range(i, j):
            d = span * token_counts[k] / weight
            starts[k], ends[k] = t, t + d
            t += d
        i = j

    out: list[TimedLine] = []
    prev_end = 0.0
    for idx, (line_id, text) in enumerate(lines):
        start = max(float(starts[idx]), prev_end)
        end = min(max(float(ends[idx]), start), duration)
        out.append(TimedLine(
            line_id=line_id, text=text, start=round(start, 3), end=round(end, 3),
            confidence=round(conf[idx], 3),
            source="aligned" if idx in matched else "interpolated",
        ))
        prev_end = end
    return out
