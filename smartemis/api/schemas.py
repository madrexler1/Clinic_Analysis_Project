from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    clinic_site: str
    max_tokens: int = 8000
    few_shot_n: int = Field(default=2, ge=0, le=5)
    score_after_generate: bool = True


class FewShotRef(BaseModel):
    id: int
    clinic_site: str
    net_score: int
    snippet: str  # first ~140 chars of the example report — for UI preview


class ReportResponse(BaseModel):
    report_id: int
    clinic_site: str
    text: str
    model_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    rubric_scores: dict[str, Any] | None = None
    few_shot_examples: list[FewShotRef] = []
    created_at: datetime


class ReportSummary(BaseModel):
    id: int
    clinic_site: str
    period_start: str
    period_end: str
    language: str
    net_feedback: int
    created_at: datetime


class FeedbackRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=128)
    thumbs: Literal["up", "down", "none"] = "none"
    comment: str | None = None


class FeedbackResponse(BaseModel):
    id: int
    report_id: int
    thumbs: str
    created_at: datetime


class ClinicListResponse(BaseModel):
    clinics: list[str]
