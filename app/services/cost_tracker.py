"""Records every provider call with usage and estimated cost."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.core.config import PipelineConfig
from app.core.db import Database, ProviderCall
from app.providers.common import Usage

STAGE_LABELS = {
    "lyrics": "Lyrics",
    "language_review": "Language Review",
    "bible": "Character Bible",
    "music": "Music",
    "timing": "Timing",
    "images": "Images",
    "image_review": "AI Review",
    "videos": "Videos",
    "video_review": "AI Review",
    "thumbnail": "Thumbnail",
    "metadata": "Metadata",
}


@dataclass(frozen=True)
class CallScope:
    project_id: str
    stage: str
    scene_id: int | None = None
    regeneration: bool = False


class CostTracker:
    def __init__(self, db: Database, config: PipelineConfig):
        self.db = db
        self.config = config

    def estimate(self, provider: str, model: str, usage: Usage) -> float:
        price = self.config.price(provider, model)
        cost = price.per_call
        cost += usage.input_tokens / 1e6 * price.input_per_1m
        cost += usage.output_tokens / 1e6 * price.output_per_1m
        match usage.unit_type:
            case "images":
                cost += usage.units * price.per_image
            case "seconds":
                cost += usage.units * price.per_second
            case "minutes":
                cost += usage.units * price.per_minute
        return round(cost, 6)

    def record(
        self,
        scope: CallScope,
        *,
        provider: str,
        model: str,
        operation: str,
        usage: Usage | None = None,
        cache_hit: bool = False,
        success: bool = True,
        error: str | None = None,
        duration_s: float = 0.0,
        request_hash: str | None = None,
    ) -> ProviderCall:
        usage = usage or Usage()
        cost = 0.0 if (cache_hit or not success) else self.estimate(provider, model, usage)
        row = ProviderCall(
            project_id=scope.project_id,
            stage=scope.stage,
            scene_id=scope.scene_id,
            provider=provider,
            model=model,
            operation=operation,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            units=usage.units,
            unit_type=usage.unit_type,
            generation_count=0 if cache_hit else 1,
            estimated_cost=cost,
            cache_hit=cache_hit,
            regeneration=scope.regeneration,
            success=success,
            error=error,
            duration_s=round(duration_s, 3),
            request_hash=request_hash,
        )
        with self.db.Session() as session:
            session.add(row)
            session.commit()
        return row

    def calls(self, project_id: str) -> list[ProviderCall]:
        with self.db.Session() as session:
            stmt = select(ProviderCall).where(ProviderCall.project_id == project_id)
            return list(session.scalars(stmt.order_by(ProviderCall.id)))

    def summary(self, project_id: str) -> dict:
        """Cost per stage, with regenerations broken out, as shown on the dashboard."""
        rows: dict[str, dict] = {}
        total = 0.0
        cache_hits = 0
        for call in self.calls(project_id):
            label = "Regenerations" if call.regeneration else STAGE_LABELS.get(call.stage,
                                                                                call.stage)
            entry = rows.setdefault(label, {"label": label, "cost": 0.0, "calls": 0})
            entry["cost"] += call.estimated_cost
            entry["calls"] += 1
            total += call.estimated_cost
            cache_hits += int(call.cache_hit)
        for entry in rows.values():
            entry["cost"] = round(entry["cost"], 4)
        return {"rows": list(rows.values()), "total": round(total, 4), "cache_hits": cache_hits}
