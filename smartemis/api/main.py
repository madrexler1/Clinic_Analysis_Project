"""FastAPI app for Smartemis report generation + feedback capture.

Run locally:
    uvicorn smartemis.api.main:app --reload --host 127.0.0.1 --port 8000

In production (EC2 eu-central-1):
    uvicorn smartemis.api.main:app --host 127.0.0.1 --port 8000
    Access via SSM port-forward — no public ingress.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from smartemis.config import get_settings
from smartemis.feedback import Feedback, FeedbackStore, Report
from smartemis.reports import ReportGenerator
from smartemis.storage import SessionLocal, init_db

from .pipeline import kpis_and_benchmarks, list_clinic_sites, load_pseudonymized_frame
from .schemas import (
    ClinicListResponse,
    FeedbackRequest,
    FeedbackResponse,
    FewShotRef,
    ReportRequest,
    ReportResponse,
    ReportSummary,
)

logger = logging.getLogger("smartemis.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        # Warm the pseudonymized frame so first request is fast and any
        # ingestion errors surface at startup rather than mid-request.
        load_pseudonymized_frame()
        logger.info("Pipeline warm-up complete.")
    except FileNotFoundError as e:
        logger.warning("Startup warm-up skipped: %s", e)
    yield


settings = get_settings()
app = FastAPI(
    title="Smartemis Agent",
    version="0.1.0",
    description="Vet-clinic financial analysis + Claude Sonnet 4.6 report drafting (EU data residency).",
    lifespan=lifespan,
)


def get_db() -> Session:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_generator() -> ReportGenerator:
    return ReportGenerator(settings)


def _expand_few_shot_refs(db: Session, ids: list[int] | None) -> list[FewShotRef]:
    """Hydrate a list of past-report IDs into UI-facing few-shot refs."""
    if not ids:
        return []
    net_expr = func.coalesce(
        func.sum(
            case((Feedback.thumbs == "up", 1), (Feedback.thumbs == "down", -1), else_=0)
        ),
        0,
    ).label("net_score")
    rows = (
        db.query(Report, net_expr)
        .outerjoin(Feedback, Feedback.report_id == Report.id)
        .filter(Report.id.in_(ids))
        .group_by(Report.id)
        .all()
    )
    by_id = {r.id: (r, int(n or 0)) for r, n in rows}
    refs: list[FewShotRef] = []
    for rid in ids:
        if rid not in by_id:
            continue
        r, net_score = by_id[rid]
        snippet = (r.text or "").strip().splitlines()[0:1]
        snippet_text = (snippet[0][:140] + "…") if snippet and len(snippet[0]) > 140 else (snippet[0] if snippet else "")
        refs.append(
            FewShotRef(id=r.id, clinic_site=r.clinic_site, net_score=net_score, snippet=snippet_text)
        )
    return refs


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "env": settings.env,
        "source": settings.source,
        "region": settings.aws_region,
        "model": settings.bedrock_model_id,
    }


@app.get("/api/clinics", response_model=ClinicListResponse)
def clinics():
    try:
        return ClinicListResponse(clinics=list_clinic_sites())
    except FileNotFoundError as e:
        raise HTTPException(503, detail=str(e))


@app.get("/api/clinics/{clinic_site}/kpis")
def clinic_kpis(clinic_site: str):
    try:
        kpis, peers = kpis_and_benchmarks(clinic_site)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(503, detail=str(e))
    return {"kpis": kpis.as_prompt_payload(), "peer_benchmarks": peers}


@app.post("/api/reports", response_model=ReportResponse)
def create_report(
    req: ReportRequest,
    db: Session = Depends(get_db),
    gen: ReportGenerator = Depends(get_generator),
):
    try:
        kpis, peers = kpis_and_benchmarks(req.clinic_site)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(503, detail=str(e))

    store = FeedbackStore(db)
    few_shot = store.top_few_shot_examples(limit=req.few_shot_n) if req.few_shot_n else []

    draft = gen.generate(kpis, peers, few_shot_examples=few_shot, max_tokens=req.max_tokens)

    report = store.save_report(
        clinic_site=draft.clinic_site,
        period_start=kpis.period_start,
        period_end=kpis.period_end,
        text=draft.text,
        model_id=draft.model_id,
        kpi_payload=kpis.as_prompt_payload(),
        input_tokens=draft.input_tokens,
        output_tokens=draft.output_tokens,
        cache_read_tokens=draft.cache_read_tokens,
        cache_write_tokens=draft.cache_write_tokens,
        few_shot_ids=draft.few_shot_ids,
    )

    rubric_scores = None
    if req.score_after_generate:
        try:
            rubric_scores = gen.score(draft.text)
            store.attach_rubric(report.id, rubric_scores)
        except Exception as e:
            logger.warning("Rubric scoring failed for report %d: %s", report.id, e)

    return ReportResponse(
        report_id=report.id,
        clinic_site=report.clinic_site,
        text=report.text,
        model_id=report.model_id,
        input_tokens=report.input_tokens,
        output_tokens=report.output_tokens,
        cache_read_tokens=report.cache_read_tokens,
        cache_write_tokens=report.cache_write_tokens,
        rubric_scores=rubric_scores,
        few_shot_examples=_expand_few_shot_refs(db, report.few_shot_ids),
        created_at=report.created_at,
    )


@app.get("/api/reports", response_model=list[ReportSummary])
def list_reports(limit: int = 50, db: Session = Depends(get_db)):
    net = func.coalesce(
        func.sum(
            case((Feedback.thumbs == "up", 1), (Feedback.thumbs == "down", -1), else_=0)
        ),
        0,
    ).label("net_feedback")
    rows = (
        db.query(Report, net)
        .outerjoin(Feedback, Feedback.report_id == Report.id)
        .group_by(Report.id)
        .order_by(Report.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        ReportSummary(
            id=r.id,
            clinic_site=r.clinic_site,
            period_start=r.period_start,
            period_end=r.period_end,
            language=r.language,
            net_feedback=int(n or 0),
            created_at=r.created_at,
        )
        for r, n in rows
    ]


@app.get("/api/reports/{report_id}", response_model=ReportResponse)
def get_report(report_id: int, db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    return ReportResponse(
        report_id=r.id,
        clinic_site=r.clinic_site,
        text=r.text,
        model_id=r.model_id,
        input_tokens=r.input_tokens,
        output_tokens=r.output_tokens,
        cache_read_tokens=r.cache_read_tokens,
        cache_write_tokens=r.cache_write_tokens,
        rubric_scores=r.rubric_scores,
        few_shot_examples=_expand_few_shot_refs(db, r.few_shot_ids),
        created_at=r.created_at,
    )


@app.post("/api/reports/{report_id}/feedback", response_model=FeedbackResponse)
def add_feedback(report_id: int, req: FeedbackRequest, db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    store = FeedbackStore(db)
    fb = store.record_feedback(report_id, reviewer=req.reviewer, thumbs=req.thumbs, comment=req.comment)
    return FeedbackResponse(
        id=fb.id, report_id=fb.report_id, thumbs=fb.thumbs, created_at=fb.created_at
    )


# --- Static UI ---
_STATIC_DIR = Path(__file__).resolve().parents[2] / "smartemis" / "ui" / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def root():
        return FileResponse(_STATIC_DIR / "index.html")
