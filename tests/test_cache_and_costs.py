from app.providers.common import Usage
from app.services.cost_tracker import CallScope


async def test_identical_image_request_hits_cache(ctx, tmp_path):
    provider = ctx.image("images", scene_id=1)
    a = await provider.generate("a cat", [], "16:9", tmp_path / "a.png")
    b = await ctx.image("images", scene_id=1).generate("a cat", [], "16:9", tmp_path / "b.png")
    assert not a.cache_hit and b.cache_hit
    assert (tmp_path / "a.png").read_bytes() == (tmp_path / "b.png").read_bytes()
    # A deliberate regeneration (new variant) is a new request.
    c = await provider.generate("a cat", [], "16:9", tmp_path / "c.png", variant=2)
    assert not c.cache_hit
    calls = ctx.tracker.calls(ctx.project_id)
    assert [x.cache_hit for x in calls] == [False, True, False]


async def test_reference_image_content_is_part_of_key(ctx, tmp_path):
    ref = tmp_path / "ref.png"
    await ctx.image().generate("ref", [], "1:1", ref)
    provider = ctx.image()
    await provider.generate("x", [ref], "16:9", tmp_path / "1.png")
    await provider.generate("other", [], "1:1", ref)  # overwrite reference contents
    second = await provider.generate("x", [ref], "16:9", tmp_path / "2.png")
    assert not second.cache_hit


def test_cost_estimates_and_summary(ctx):
    ctx.config.pricing["openai"]["gpt-image-1"].per_image = 0.05
    scope = CallScope(ctx.project_id, "images", 1)
    ctx.tracker.record(scope, provider="openai", model="gpt-image-1", operation="image",
                       usage=Usage(units=2, unit_type="images"))
    ctx.tracker.record(CallScope(ctx.project_id, "images", 1, regeneration=True),
                       provider="openai", model="gpt-image-1", operation="image",
                       usage=Usage(units=1, unit_type="images"))
    ctx.tracker.record(CallScope(ctx.project_id, "lyrics"), provider="openai", model="gpt-5",
                       operation="chat", usage=Usage(1_000_000, 100_000))
    ctx.tracker.record(scope, provider="openai", model="gpt-image-1", operation="image",
                       cache_hit=True, usage=Usage(units=1, unit_type="images"))
    summary = ctx.tracker.summary(ctx.project_id)
    rows = {r["label"]: r["cost"] for r in summary["rows"]}
    assert rows["Images"] == 0.1
    assert rows["Regenerations"] == 0.05
    assert rows["Lyrics"] == 1.25 + 1.0
    assert summary["cache_hits"] == 1
    assert summary["total"] == round(0.1 + 0.05 + 2.25, 4)
