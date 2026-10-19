"""Mandarin editions: lyrics must be 汉字 (pinyin only as an extra line), timing works without
spaces, subtitles and fonts handle Chinese."""

import json
from pathlib import Path

import pytest
import yaml

from app.core.config import RenderPreset
from app.models.creative import CreativePlan, validate_plan_against_spec
from app.models.project import ProjectSpec
from app.models.timing import SongTiming, TimedLine, Word
from app.providers.common import Usage
from app.providers.llm.base import LLMProvider, LLMResponse
from app.services.render_service import Clip, build_render_plan
from app.services.subtitles import subtitle_tracks
from app.utils.alignment import align_lines
from tests.test_creative_director import plan_dict

ZH_EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "fruit-song-zh" / "project.yaml"


def zh_spec(romanization: bool = True) -> ProjectSpec:
    data = yaml.safe_load(ZH_EXAMPLE.read_text("utf-8"))
    data["languages"]["romanization"] = romanization
    return ProjectSpec.model_validate(data)


def zh_plan(**line_over) -> dict:
    data = plan_dict()
    words = [("苹果", "píng guǒ"), ("香蕉", "xiāng jiāo"), ("橙子", "chéng zi"), ("草莓", "cǎo méi")]
    for line, (hanzi, pinyin) in zip(data["lyrics"], words, strict=True):
        line.update(sung=f"{hanzi}，apple!", primary=f"{hanzi}！", secondary="Apple!",
                    romanization=pinyin)
        line.update(line_over)
    return data


def test_example_spec_loads():
    spec = zh_spec()
    assert spec.languages.codes == ("zh", "en")
    assert spec.languages.script == "simplified" and spec.languages.romanization


def test_valid_chinese_plan_passes():
    plan = CreativePlan.model_validate(zh_plan())
    assert validate_plan_against_spec(plan, zh_spec()) == []


@pytest.mark.parametrize("override, message", [
    ({"primary": "píng guǒ!"}, "Chinese characters"),            # pinyin instead of 汉字
    ({"primary": "苹果 apple!"}, "only Chinese characters"),      # mixed into the Chinese field
    ({"sung": "píng guǒ, apple!"}, "'sung'"),
    ({"romanization": ""}, "romanization"),                     # required when enabled
    ({"romanization": "苹果"}, "must be pinyin"),
])
def test_pinyin_in_place_of_characters_is_rejected(override, message):
    plan = CreativePlan.model_validate(zh_plan(**override))
    errors = validate_plan_against_spec(plan, zh_spec())
    assert any(message in e for e in errors), errors


class ScriptedLLM(LLMProvider):
    name = model = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    async def complete(self, messages, *, json_mode=True, schema_name=None):
        self.seen.append(list(messages))
        return LLMResponse(model="scripted", usage=Usage(), text=self.replies.pop(0))


async def test_pinyin_output_is_sent_back_for_correction():
    spec = zh_spec()
    llm = ScriptedLLM([json.dumps(zh_plan(primary="píng guǒ!")), json.dumps(zh_plan())])
    result = await llm.generate_structured(
        "sys", "user", CreativePlan,
        extra_validator=lambda p: validate_plan_against_spec(p, spec))
    assert result.attempts == 2
    assert "not pinyin" in llm.seen[1][-1].text


def test_alignment_without_spaces():
    lines = [(1, "苹果，apple!"), (2, "香蕉，banana!")]
    # Whisper returns multi-character Chinese words; they are split per character.
    words = [Word(text="苹果", start=1.0, end=2.0), Word(text="apple", start=2.0, end=2.5),
             Word(text="香蕉", start=4.0, end=5.0), Word(text="banana", start=5.0, end=5.6)]
    out = align_lines(lines, words, duration=8.0)
    assert [t.source for t in out] == ["aligned", "aligned"]
    assert out[0].start == 1.0 and out[1].start == 4.0
    assert out[0].confidence == 1.0


def test_subtitles_show_characters_with_optional_pinyin():
    plan = CreativePlan.model_validate(zh_plan())
    timing = SongTiming(duration=20, method="t", lines=[
        TimedLine(line_id=i, text="", start=i * 4.0, end=i * 4.0 + 3, confidence=1,
                  source="aligned") for i in range(1, 5)])
    with_pinyin = subtitle_tracks(plan, timing, "zh", "en", romanization=True)
    assert "píng guǒ\n苹果！\nApple!" in with_pinyin["bilingual"]
    without = subtitle_tracks(plan, timing, "zh", "en", romanization=False)
    assert "苹果！\nApple!" in without["bilingual"] and "píng" not in without["bilingual"]


def test_burned_subtitles_use_a_chinese_font():
    plan = build_render_plan([Clip(Path("a.mp4"), 3.0)], Path("s.wav"), 3.0, RenderPreset(),
                             subtitles_file="s.srt", subtitle_font="Noto Sans CJK SC")
    assert "FontName=Noto Sans CJK SC" in plan.filter_complex


async def test_mock_build_of_chinese_plan(workspace):
    from app.pipeline.context import PipelineContext
    from app.services.creative_director import generate_plan
    from app.utils.files import write_text

    root = workspace.projects_dir / "fruit-song-zh"
    write_text(root / "project.yaml", ZH_EXAMPLE.read_text("utf-8"))
    ctx = PipelineContext(workspace, "fruit-song-zh")
    plan = await generate_plan(ctx)
    assert "苹果" in plan.lyrics[0].primary
    assert plan.lyrics[0].romanization == "píng guǒ"
