"""Text-based sample localization API (consumed by the Pindola MCP server).

Endpoints
---------
POST /samples                  Create a sample job: {script_text, target_language, prospect_email}
GET  /samples/{job_id}         Job status (queued/processing/complete/failed) + outputs
GET  /samples/{job_id}/report  Structured localization report (changes, cultural, CTA, compliance)
GET  /samples/stats            Aggregate counts for project status dashboards

Jobs are executed asynchronously on a background worker that calls
sample_mode.localize_variants() (Groq -> xKiro, validated; both failed -> needs_review), so the
MCP create_localization_sample tool returns a job_id immediately.
"""
import asyncio
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from sample_mode import localize_variants, VARIANTS, VARIANT_LABELS, LocalizationUnavailable

BASE = Path(__file__).resolve().parent
DB = BASE / "jobs.db"
SUPPORTED_LANGUAGES = {"de", "es", "fr"}
MAX_SCRIPT_CHARS = 10000
MIN_SCRIPT_CHARS = 10
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

router = APIRouter()
sample_queue: asyncio.Queue = asyncio.Queue()
sample_worker_task = None


def samples_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS samples (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            language TEXT NOT NULL,
            source_script TEXT NOT NULL,
            prospect_email TEXT,
            variants_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        )"""
    )
    conn.commit()
    return conn


def update_sample(job_id, status, variants_json=None, error=None):
    with samples_db() as c:
        if status == "complete":
            c.execute(
                "UPDATE samples SET status=?, variants_json=?, completed_at=?, error=? WHERE id=?",
                (status, variants_json, datetime.now(timezone.utc).isoformat(), error, job_id),
            )
        else:
            c.execute(
                "UPDATE samples SET status=?, error=? WHERE id=?",
                (status, error, job_id),
            )
        c.commit()


def run_sample_job(job_id, source, language):
    update_sample(job_id, "processing")
    try:
        variants = localize_variants(source, language)
        update_sample(job_id, "complete", json.dumps(variants))
    except LocalizationUnavailable as exc:
        update_sample(job_id, "needs_review", error=str(exc)[:2000])
    except Exception as exc:  # noqa: BLE001 - report any failure to the job
        update_sample(job_id, "failed", error=str(exc)[:2000])


async def sample_worker():
    while True:
        job_id, source, language = await sample_queue.get()
        await asyncio.to_thread(run_sample_job, job_id, source, language)
        sample_queue.task_done()


def start_sample_worker():
    global sample_worker_task
    if sample_worker_task is None or sample_worker_task.done():
        samples_db().close()
        sample_worker_task = asyncio.create_task(sample_worker())


def stop_sample_worker():
    global sample_worker_task
    if sample_worker_task:
        sample_worker_task.cancel()
        sample_worker_task = None


@router.post("/samples")
async def create_sample(payload: dict = Body(...)):
    script_text = payload.get("script_text")
    target_language = payload.get("target_language")
    prospect_email = payload.get("prospect_email")

    if not isinstance(script_text, str) or not script_text.strip():
        raise HTTPException(400, "script_text is required")
    script_text = script_text.strip()
    if len(script_text) < MIN_SCRIPT_CHARS:
        raise HTTPException(400, f"script_text must be at least {MIN_SCRIPT_CHARS} characters")
    if len(script_text) > MAX_SCRIPT_CHARS:
        raise HTTPException(400, f"script_text must be at most {MAX_SCRIPT_CHARS} characters")

    if not isinstance(target_language, str) or target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, "target_language must be one of: de, es, fr")

    if prospect_email is not None:
        if not isinstance(prospect_email, str) or not EMAIL_RE.match(prospect_email.strip()):
            raise HTTPException(400, "prospect_email must be a valid email address")
        prospect_email = prospect_email.strip()

    job_id = uuid.uuid4().hex
    with samples_db() as c:
        c.execute(
            "INSERT INTO samples (id, status, language, source_script, prospect_email, created_at) VALUES (?,?,?,?,?,?)",
            (job_id, "queued", target_language, script_text, prospect_email, datetime.now(timezone.utc).isoformat()),
        )
        c.commit()
    await sample_queue.put((job_id, script_text, target_language))
    return {"job_id": job_id}


def _row_to_status(row):
    data = dict(row)
    data["outputs"] = {
        "variants": list(VARIANTS) if data["status"] == "complete" else [],
        "report_path": f"/samples/{data['id']}/report" if data["status"] == "complete" else None,
    }
    data.pop("variants_json", None)
    data.pop("source_script", None)
    return data


@router.get("/samples/stats")
def samples_stats():
    with samples_db() as c:
        c.execute("UPDATE samples SET status='needs_review', error=COALESCE(error, 'Legacy unvalidated/fallback output; blocked from prospect delivery') WHERE variants_json LIKE '%Fallback preserves source wording%' AND status='complete'")
        c.commit()
        total = c.execute("SELECT COUNT(*) FROM samples WHERE COALESCE(archived,0)=0").fetchone()[0]
        completed = c.execute("SELECT COUNT(*) FROM samples WHERE status='complete' AND COALESCE(archived,0)=0").fetchone()[0]
        failed = c.execute("SELECT COUNT(*) FROM samples WHERE status='failed' AND COALESCE(archived,0)=0").fetchone()[0]
        needs_review = c.execute("SELECT COUNT(*) FROM samples WHERE status='needs_review' AND COALESCE(archived,0)=0").fetchone()[0]
        processing = c.execute("SELECT COUNT(*) FROM samples WHERE status IN ('queued','processing') AND COALESCE(archived,0)=0").fetchone()[0]
        recent = c.execute(
            "SELECT id, status, language, created_at, completed_at FROM samples WHERE COALESCE(archived,0)=0 ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
    return {
        "samples_total": total,
        "samples_completed": completed,
        "samples_processing": processing,
        "samples_failed": failed,
        "samples_needs_review": needs_review,
        "recent_samples": [dict(r) for r in recent],
    }


@router.get("/samples/{job_id}")
def get_sample(job_id: str):
    with samples_db() as c:
        row = c.execute("SELECT * FROM samples WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Sample job not found")
    return _row_to_status(row)


@router.get("/samples/{job_id}/report")
def get_sample_report(job_id: str):
    with samples_db() as c:
        row = c.execute("SELECT * FROM samples WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Sample job not found")
    if row["status"] != "complete":
        raise HTTPException(409, "Sample job is not complete yet")
    variants = json.loads(row["variants_json"]) if row["variants_json"] else {}
    report = {
        "job_id": job_id,
        "status": "complete",
        "language": row["language"],
        "prospect_email": row["prospect_email"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "source_script": row["source_script"],
        "variants": {},
    }
    for key in VARIANTS:
        v = variants.get(key) if isinstance(variants, dict) else None
        report["variants"][key] = {
            "label": VARIANT_LABELS[key],
            "script": (v or {}).get("script", ""),
            "sentence_changes": (v or {}).get("sentence_changes", []),
            "cultural_adaptations": (v or {}).get("cultural_adaptations", []),
            "cta_recommendations": (v or {}).get("cta_recommendations", []),
            "alternative_hooks": (v or {}).get("alternative_hooks", []),
            "alternative_headlines": (v or {}).get("alternative_headlines", []),
            "alternative_ctas": (v or {}).get("alternative_ctas", []),
            "compliance_notes": (v or {}).get("compliance_notes", []),
            "confidence": (v or {}).get("confidence", 0),
        }
    return report


@router.get("/samples/stats")
def samples_stats():
    with samples_db() as c:
        c.execute("UPDATE samples SET status='needs_review', error=COALESCE(error, 'Legacy unvalidated/fallback output; blocked from prospect delivery') WHERE variants_json LIKE '%Fallback preserves source wording%' AND status='complete'")
        c.commit()
        total = c.execute("SELECT COUNT(*) FROM samples WHERE COALESCE(archived,0)=0").fetchone()[0]
        completed = c.execute("SELECT COUNT(*) FROM samples WHERE status='complete' AND COALESCE(archived,0)=0").fetchone()[0]
        failed = c.execute("SELECT COUNT(*) FROM samples WHERE status='failed' AND COALESCE(archived,0)=0").fetchone()[0]
        needs_review = c.execute("SELECT COUNT(*) FROM samples WHERE status='needs_review' AND COALESCE(archived,0)=0").fetchone()[0]
        processing = c.execute("SELECT COUNT(*) FROM samples WHERE status IN ('queued','processing') AND COALESCE(archived,0)=0").fetchone()[0]
        recent = c.execute(
            "SELECT id, status, language, created_at, completed_at FROM samples WHERE COALESCE(archived,0)=0 ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
    return {
        "samples_total": total,
        "samples_completed": completed,
        "samples_processing": processing,
        "samples_failed": failed,
        "samples_needs_review": needs_review,
        "recent_samples": [dict(r) for r in recent],
    }
