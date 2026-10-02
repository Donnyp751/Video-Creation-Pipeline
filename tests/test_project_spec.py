from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.models.project import ProjectSpec

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "fruit-song-001" / "project.yaml"


def example_data() -> dict:
    return yaml.safe_load(EXAMPLE.read_text("utf-8"))


def test_example_project_loads():
    spec = ProjectSpec.load(EXAMPLE)
    assert spec.project.id == "fruit-song-001"
    assert spec.project.title == "Trái Cây Gì Đây?"
    assert spec.languages.codes == ("vi", "en")
    assert spec.character_ids == ["brother", "sister"]
    assert spec.project.size == (1920, 1080)
    assert spec.providers.vision_provider == "openai"


def test_roundtrip_yaml():
    spec = ProjectSpec.load(EXAMPLE)
    again = ProjectSpec.model_validate(yaml.safe_load(spec.to_yaml()))
    assert again == spec


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["project"].update(target_age_min=6, target_age_max=3), "target_age_min"),
        (lambda d: d["project"].update(resolution="1920x1081"), "even"),
        (lambda d: d["project"].update(resolution="1080x1920"), "does not match aspect"),
        (lambda d: d["languages"].update(secondary="vi"), "must differ"),
        (lambda d: d["characters"].append(dict(d["characters"][0])), "duplicate character"),
        (lambda d: d["project"].update(id="Fruit Song"), "pattern"),
        (lambda d: d["project"].update(api_key="sk-..."), "Extra inputs"),
        (lambda d: d.update(characters=[]), "at least 1"),
    ],
)
def test_invalid_specs_are_rejected(mutate, message):
    data = example_data()
    mutate(data)
    with pytest.raises(ValidationError, match=message):
        ProjectSpec.model_validate(data)
