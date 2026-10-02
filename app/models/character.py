"""Character Bible: permanent, structured character definitions (assets/characters/<id>/)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# Reference images looked up in a character's directory, in priority order.
REFERENCE_POSES = ("reference_sheet", "front", "side", "happy", "surprised", "singing")


class CharacterBible(BaseModel):
    name: str
    display_name: str | None = None
    age: int | None = None
    species: str = "human"
    description: str = ""
    physical: dict[str, str] = Field(default_factory=dict)
    clothing: dict[str, str] = Field(default_factory=dict)
    personality: str = ""
    never_change: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> CharacterBible:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(exclude_none=True), sort_keys=False,
                              allow_unicode=True, width=100)

    def definition(self) -> str:
        """Deterministic one-paragraph definition used by the prompt compiler."""
        parts = [f"{self.display_name or self.name}"]
        who = []
        if self.age is not None:
            who.append(f"{self.age}-year-old")
        if self.species and self.species != "human":
            who.append(self.species)
        if who:
            parts.append(f"({' '.join(who)})")
        text = " ".join(parts) + ":"
        details = []
        if self.description:
            details.append(" ".join(self.description.split()).rstrip("."))
        details += [f"{k.replace('_', ' ')}: {v}" for k, v in self.physical.items()]
        details += [f"{k.replace('_', ' ')}: {v}" for k, v in self.clothing.items()]
        if details:
            text += " " + "; ".join(details) + "."
        if self.never_change:
            text += f" Always keep identical: {', '.join(self.never_change)}."
        return text
