"""Feedback store + RLHF-lite learning helpers.

The learning loop:
  1. User submits thumbs + optional text feedback on a Report.
  2. `top_few_shot_examples()` selects the highest-net-thumbs reports and
     returns them for the next generation call's few-shot context.
  3. Over time the generator's in-context examples improve. This is
     Reinforcement-from-Human-Feedback-lite: no fine-tuning (Claude API does
     not support it), but generations shift toward reviewer preferences.

Later we can mine textual feedback into rules and append them to the system
prompt — keep that separate to preserve the stable-prefix invariant for caching.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .models import Feedback, Report


class FeedbackStore:
    def __init__(self, session: Session):
        self.session = session

    def save_report(
        self,
        *,
        clinic_site: str,
        period_start: str,
        period_end: str,
        text: str,
        language: str = "en",
        model_id: str,
        kpi_payload: dict[str, Any] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        few_shot_ids: list[int] | None = None,
    ) -> Report:
        r = Report(
            clinic_site=clinic_site,
            period_start=period_start,
            period_end=period_end,
            text=text,
            language=language,
            model_id=model_id,
            kpi_payload=kpi_payload,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            few_shot_ids=few_shot_ids or [],
        )
        self.session.add(r)
        self.session.flush()
        return r

    def attach_rubric(self, report_id: int, scores: dict[str, Any]) -> None:
        r = self.session.get(Report, report_id)
        if r is not None:
            r.rubric_scores = scores

    def record_feedback(
        self,
        report_id: int,
        *,
        reviewer: str,
        thumbs: str,
        comment: str | None = None,
    ) -> Feedback:
        if thumbs not in {"up", "down", "none"}:
            raise ValueError(f"Invalid thumbs: {thumbs!r}")
        fb = Feedback(report_id=report_id, reviewer=reviewer, thumbs=thumbs, comment=comment)
        self.session.add(fb)
        self.session.flush()
        return fb

    def get_report(self, report_id: int) -> Report | None:
        return self.session.get(Report, report_id)

    def list_reports(self, limit: int = 50) -> list[Report]:
        stmt = select(Report).order_by(Report.created_at.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def top_few_shot_examples(
        self,
        *,
        limit: int = 2,
        min_net_score: int = 1,
    ) -> list[dict[str, Any]]:
        """Highest-net-thumbs reports for use as in-context examples.

        A report's "net score" = thumbs_up count − thumbs_down count. Only
        reports above `min_net_score` are returned. Kept short (default 2) to
        avoid blowing the system-prompt prefix beyond its effective cache budget.
        """
        net = func.sum(
            case((Feedback.thumbs == "up", 1), (Feedback.thumbs == "down", -1), else_=0)
        ).label("net_score")

        stmt = (
            select(Report, net)
            .join(Feedback, Feedback.report_id == Report.id)
            .group_by(Report.id)
            .having(net >= min_net_score)
            .order_by(net.desc(), Report.created_at.desc())
            .limit(limit)
        )

        return [
            {"id": r.id, "text": r.text, "score": int(score), "clinic_site": r.clinic_site}
            for r, score in self.session.execute(stmt)
        ]
