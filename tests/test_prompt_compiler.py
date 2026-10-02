from app.models.character import CharacterBible
from app.models.creative import ObjectSpec, ScenePlan
from app.models.project import ProjectSpec
from app.services.prompt_compiler import compile_image_prompt, compile_motion_prompt
from tests.test_project_spec import EXAMPLE

SISTER = CharacterBible(
    name="sister", display_name="Sister", age=3,
    physical={"hairstyle": "two pigtails", "bows": "pink bows"},
    clothing={"dress": "yellow dress"},
    never_change=["hairstyle", "dress color"],
)

SCENE = ScenePlan(
    id=4, lyric_line_ids=[4], characters=["sister"], action="The girl holds a large orange.",
    composition="wide shot", objects=[ObjectSpec(name="orange", count=1)],
    motion_prompt="She lifts the orange and giggles.", camera="slow push in",
)


def test_image_prompt_sections_in_order():
    spec = ProjectSpec.load(EXAMPLE)
    prompt = compile_image_prompt(spec, SCENE, [SISTER])
    order = ["STYLE:", "CHARACTERS:", "ENVIRONMENT:", "SCENE:", "COMPOSITION:", "CONSTRAINTS:"]
    positions = [prompt.index(h) for h in order]
    assert positions == sorted(positions)
    assert "Cute soft 3D toddler cartoon" in prompt
    assert "two pigtails" in prompt and "yellow dress" in prompt
    assert "Exactly 1 character(s): Sister" in prompt
    assert "Exactly 1 orange." in prompt
    assert "No text" in prompt
    assert "16:9" in prompt


def test_image_prompt_is_deterministic():
    spec = ProjectSpec.load(EXAMPLE)
    assert compile_image_prompt(spec, SCENE, [SISTER]) == compile_image_prompt(spec, SCENE,
                                                                               [SISTER])


def test_motion_prompt_mentions_consistency():
    p = compile_motion_prompt(SCENE, [SISTER])
    assert p.startswith("She lifts the orange")
    assert "Camera: slow push in." in p
    assert "identical" in p
