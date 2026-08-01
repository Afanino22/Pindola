"""Local FastAPI wrapper for the Pindola localization pipeline."""
import asyncio, os, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from main import process_one_language

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"; OUTPUT = BASE / "output"; DB = BASE / "jobs.db"
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "200")) * 1024 * 1024
STEPS = {"queued": 0, "extracting": 15, "transcribing": 30, "localizing": 50, "tts": 65, "subtitles": 78, "exporting": 90, "done": 100, "failed": 100}
app = FastAPI(title="Pindola Localization API")
queue = asyncio.Queue(); worker_task = None

def db():
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT, language TEXT, progress_step TEXT, created_at TEXT, error TEXT)")
    conn.commit(); return conn

def update(job_id, status, error=None):
    with db() as c: c.execute("UPDATE jobs SET status=?, progress_step=?, error=? WHERE id=?", (status, status, error, job_id)); c.commit()

def run_job(job_id, src, language):
    out = OUTPUT / job_id / language
    def progress(step): update(job_id, step)
    try:
        process_one_language(src, language, out, llm_provider="auto", tts_provider="auto", progress_callback=progress)
        update(job_id, "done")
    except Exception as e: update(job_id, "failed", str(e))
    finally: src.unlink(missing_ok=True)

async def worker():
    while True:
        job_id, src, lang = await queue.get()
        await asyncio.to_thread(run_job, job_id, src, lang)
        queue.task_done()

@app.on_event("startup")
async def startup():
    global worker_task
    UPLOADS.mkdir(exist_ok=True); OUTPUT.mkdir(exist_ok=True); db().close()
    worker_task = asyncio.create_task(worker())

@app.on_event("shutdown")
async def shutdown():
    if worker_task: worker_task.cancel()

@app.post("/jobs")
async def create_job(file: UploadFile = File(...), target_language: str = Form(...)):
    job_id = uuid.uuid4().hex
    dest = UPLOADS / f"{job_id}_{Path(file.filename or 'input.mp4').name}"
    size = 0
    with dest.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD: dest.unlink(missing_ok=True); raise HTTPException(413, "Upload exceeds MAX_UPLOAD_MB")
            f.write(chunk)
    with db() as c: c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", (job_id, "queued", target_language, "queued", datetime.now(timezone.utc).isoformat(), None)); c.commit()
    await queue.put((job_id, dest, target_language))
    return {"job_id": job_id}

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    with db() as c: row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row: raise HTTPException(404, "Job not found")
    data = dict(row); data["progress"] = STEPS.get(row["status"], 0)
    if row["status"] == "done":
        data["download_urls"] = [f"/jobs/{job_id}/download/{p.name}" for p in (OUTPUT / job_id / row["language"]).glob("*") if p.suffix in (".mp4", ".srt")]
    return data

@app.get("/jobs/{job_id}/download/{filename}")
def download(job_id: str, filename: str):
    with db() as c: row = c.execute("SELECT language FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row: raise HTTPException(404, "Job not found")
    base = (OUTPUT / job_id / row["language"]).resolve(); path = (base / Path(filename).name).resolve()
    if base not in path.parents or not path.is_file(): raise HTTPException(404, "Output not found")
    return FileResponse(path)
