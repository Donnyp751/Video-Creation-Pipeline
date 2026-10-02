import json

import pytest

from app.models.creative import CreativePlan
from app.models.state import Gate
from app.providers.common import Usage
from app.providers.llm.base import ChatMessage, LLMProvider, LLMResponse, StructuredOutputError
from app.providers.llm.mock import MockLLM
from app.services.creative_director import generate_plan, update_plan


def plan_dict(**over) -> dict:
    base = {
        "title": "T",
        "music": {"style": "pop", "tempo_bpm": 100, "mood": "happy", "vocal_description": "v"},
        "lyrics": [
            {"id": i, "section": "verse", "sung": f"s{i}", "primary": f"p{i}",
             "secondary": f"e{i}"} for i in range(1, 5)
        ],
        "scenes": [
            {"id": i, "lyric_line_ids": [i], "characters": ["brother"], "action": "a",
             "motion_prompt": "m"} for i in range(1, 5)
        ],
    }
    base.update(over)
    return base


def test_plan_requires_full_ordered_coverage():
    data = plan_dict()
    data["scenes"][1]["lyric_line_ids"] = [3]
    data["scenes"][2]["lyric_line_ids"] = [2]
    with pytest.raises(ValueError, match="cover every lyric line"):
        CreativePlan.model_validate(data)


class ScriptedLLM(LLMProvider):
    """Returns canned responses in order and records the conversation."""

    name = "scripted"
    model = "scripted"

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.seen: list[list[ChatMessage]] = []

    async def complete(self, messages, *, json_mode=True, schema_name=None) -> LLMResponse:
        self.seen.append(list(messages))
        return LLMResponse(model=self.model, usage=Usage(10, 10), text=self.replies.pop(0))


async def test_structured_generation_retries_with_validation_errors():
    bad = plan_dict()
    del bad["music"]
    llm = ScriptedLLM(["not json", json.dumps(bad), "```json\n" + json.dumps(plan_dict()) + "\n```"])
    result = await llm.generate_structured("sys", "user", CreativePlan, max_attempts=3)
    assert result.attempts == 3
    assert result.usage.input_tokens == 30
    # The validation error is fed back to the model on the retry.
    assert "not valid JSON" in llm.seen[1][-1].text
    assert "music" in llm.seen[2][-1].text


async def test_structured_generation_gives_up():
    llm = ScriptedLLM(["{}", "{}"])
    with pytest.raises(StructuredOutputError):
        await llm.generate_structured("sys", "user", CreativePlan, max_attempts=2)


async def test_extra_validator_feedback():
    data = plan_dict()
    data["scenes"][0]["characters"] = ["dragon"]
    llm = ScriptedLLM([json.dumps(data), json.dumps(plan_dict())])
    result = await llm.generate_structured(
        "sys", "user", CreativePlan,
        extra_validator=lambda p: [f"bad {c}" for s in p.scenes for c in s.characters
                                   if c != "brother"],
    )
    assert result.attempts == 2
    assert "bad dragon" in llm.seen[1][-1].text


async def test_generate_plan_contract(ctx):
    plan = await generate_plan(ctx)
    assert ctx.paths.creative_plan.is_file()
    assert len(plan.scenes) >= 4
    known = set(ctx.spec.character_ids)
    for scene in plan.scenes:
        assert scene.motion_prompt and scene.action
        assert set(scene.characters) <= known
    for line in plan.lyrics:
        assert line.primary and line.secondary and line.sung
    # Existing plans are reused, not regenerated.
    assert await generate_plan(ctx) == plan


async def test_human_edit_is_validated_and_versioned(ctx):
    plan = await generate_plan(ctx)
    ctx.approve(Gate.lyrics)
    data = plan.model_dump()
    data["lyrics"][0]["secondary"] = "An apple!"
    update_plan(ctx, data)
    assert (ctx.paths.history / "creative_plan_v1.json").is_file()
    assert ctx.state().approvals.get("lyrics") is None  # edit revokes approval
    data["scenes"][0]["characters"] = ["dragon"]
    with pytest.raises(ValueError, match="unknown character"):
        update_plan(ctx, data)


async def test_mock_llm_reads_context():
    llm = MockLLM()
    ctx_json = {"characters": [{"id": "cat"}], "languages": {"primary": "vi", "secondary": "en"},
                "duration_target_seconds": 30}
    result = await llm.generate_structured(
        "s", f"<context>{json.dumps(ctx_json)}</context>", CreativePlan)
    assert {c for s in result.value.scenes for c in s.characters} == {"cat"}
