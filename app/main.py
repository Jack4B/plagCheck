"""API (FastAPI) + serwowanie frontendu.

Uruchomienie lokalne:  uvicorn app.main:app --reload
Na CT8 aplikację uruchamia Passenger przez passenger_wsgi.py (ASGI→WSGI, a2wsgi).
"""
from __future__ import annotations

import hmac
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__, db, jobs
from .config import get_settings
from .pipeline import normalize_options
from .services.extractor import ExtractionError, extract_text
from .services.report import DISCLAIMER, report_to_html

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("plagcheck")

STATIC_DIR = Path(__file__).resolve().parent / "static"
OWNER_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

app = FastAPI(title="PlagCheck", version=__version__, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    _maybe_housekeeping()
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if not request.url.path.startswith("/api/docs"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
    return response


_housekeeping_lock = threading.Lock()
_last_housekeeping = 0.0


def _maybe_housekeeping() -> None:
    """Sprzątanie co ≥10 min przy okazji ruchu — działa także bez crona."""
    global _last_housekeeping
    now = time.monotonic()
    if now - _last_housekeeping < 600 or not _housekeeping_lock.acquire(blocking=False):
        return
    try:
        _last_housekeeping = now
        settings = get_settings()
        db.cleanup_expired(settings.search_cache_hours)
        db.requeue_stale(settings.job_stale_minutes)
    except Exception:  # pragma: no cover
        log.exception("housekeeping failed")
    finally:
        _housekeeping_lock.release()


# ------------------------------------------------------------------ zależności


def require_access(x_access_key: str | None = Header(None)) -> None:
    key = get_settings().access_key
    if key and not (x_access_key and hmac.compare_digest(x_access_key.encode(), key.encode())):
        raise HTTPException(401, "Wymagany klucz dostępu.")


def owner_token(x_owner_token: str | None = Header(None)) -> str:
    if not x_owner_token or not OWNER_RE.match(x_owner_token):
        raise HTTPException(400, "Brak lub niepoprawny nagłówek X-Owner-Token.")
    return x_owner_token


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds") + "Z"
    return value


def _job_public(job: dict) -> dict:
    out = {
        "id": job["id"],
        "filename": job["filename"],
        "status": job["status"],
        "progress": job["progress"],
        "stage": job["stage"],
        "error": job.get("error"),
        "created_at": _iso(job["created_at"]),
        "expires_at": _iso(job["expires_at"]),
        "summary": json.loads(job["summary"]) if job.get("summary") else None,
    }
    return out


async def _read_upload(upload: UploadFile, limit: int) -> bytes:
    chunks, size = [], 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, f"Plik przekracza limit {limit // (1024 * 1024)} MB.")
        chunks.append(chunk)
    return b"".join(chunks)


# ------------------------------------------------------------------------ API


@app.get("/api/health")
def health():
    settings = get_settings()
    from .services.semantic import semantic_available

    semantic = bool(settings.semantic_model) and semantic_available()
    return {
        "status": "ok",
        "version": __version__,
        "profile": "full" if semantic else "lite",
        "search_sources": [p.name for p in jobs.providers_factory(settings)],
        "semantic_model": settings.semantic_model if semantic else None,
        "worker_mode": settings.worker_mode,
        "access_required": bool(settings.access_key),
        "max_upload_mb": settings.max_upload_mb,
        "report_ttl_hours": settings.report_ttl_hours,
        "disclaimer": DISCLAIMER,
    }


@app.post("/api/check", dependencies=[Depends(require_access)])
async def create_check(
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    options: str | None = Form(None),
    owner: str = Depends(owner_token),
):
    settings = get_settings()
    try:
        opts = normalize_options(json.loads(options) if options else None)
    except (ValueError, TypeError):
        raise HTTPException(400, "Niepoprawne opcje.")
    if file is not None and file.filename:
        data = await _read_upload(file, settings.max_upload_bytes)
        filename = Path(file.filename).name
        try:
            content = extract_text(filename, data)
        except ExtractionError as exc:
            raise HTTPException(422, str(exc))
        del data  # plik nie jest nigdzie zapisywany
    elif text and text.strip():
        if len(text) > settings.max_text_chars * 2:
            raise HTTPException(413, "Tekst jest zbyt długi.")
        filename = "Wklejony tekst"
        from .services.extractor import normalize_whitespace

        content = normalize_whitespace(text)
    else:
        raise HTTPException(400, "Wgraj plik albo wklej tekst.")
    if len(content.split()) < 20:
        raise HTTPException(422, "Za mało tekstu do analizy (minimum 20 słów).")
    job_id = db.create_job(owner, filename, content, opts, settings.report_ttl_hours)
    jobs.submit(job_id)
    return {"id": job_id, "status": "pending"}


@app.get("/api/jobs", dependencies=[Depends(require_access)])
def list_jobs(owner: str = Depends(owner_token)):
    return {"jobs": [_job_public(j) for j in db.list_jobs(owner)]}


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_access)])
def job_status(job_id: str, owner: str = Depends(owner_token)):
    job = db.get_job(job_id, owner)
    if not job:
        raise HTTPException(404, "Nie znaleziono sprawdzenia (mogło wygasnąć).")
    settings = get_settings()
    # Samonaprawa: jeśli wątek analizy zginął (np. restart Passengera), wznów zadanie.
    age = db.utcnow() - job["updated_at"]
    if settings.worker_mode == "thread":
        if job["status"] == "running" and age > timedelta(minutes=settings.job_stale_minutes):
            db.requeue_stale(settings.job_stale_minutes)
            jobs.submit(job_id)
        elif job["status"] == "pending" and age > timedelta(seconds=30):
            jobs.submit(job_id)
    return _job_public(job)


@app.get("/api/jobs/{job_id}/report", dependencies=[Depends(require_access)])
def job_report(job_id: str, owner: str = Depends(owner_token)):
    job = db.get_job(job_id, owner, with_report=True)
    if not job:
        raise HTTPException(404, "Nie znaleziono sprawdzenia (mogło wygasnąć).")
    if job["status"] != "done" or not job["report"]:
        raise HTTPException(409, "Raport nie jest jeszcze gotowy.")
    return Response(job["report"], media_type="application/json")


@app.get("/api/jobs/{job_id}/export.html", dependencies=[Depends(require_access)])
def job_export(job_id: str, owner: str = Depends(owner_token)):
    job = db.get_job(job_id, owner, with_report=True)
    if not job or job["status"] != "done":
        raise HTTPException(404, "Raport niedostępny.")
    html = report_to_html(json.loads(job["report"]))
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(job["filename"]).stem)[:60] or "raport"
    return HTMLResponse(
        html, headers={"Content-Disposition": f'attachment; filename="raport_{safe}.html"'}
    )


@app.delete("/api/jobs/{job_id}", dependencies=[Depends(require_access)])
def remove_job(job_id: str, owner: str = Depends(owner_token)):
    if not db.delete_job(job_id, owner):
        raise HTTPException(404, "Nie znaleziono sprawdzenia.")
    return {"deleted": True}


@app.get("/api/references", dependencies=[Depends(require_access)])
def list_refs(owner: str = Depends(owner_token)):
    refs = db.list_references(owner)
    return {
        "references": [
            {"id": r["id"], "name": r["name"], "words": r["words"], "shared": r["owner"] == "",
             "created_at": _iso(r["created_at"])}
            for r in refs
        ],
        "stats": db.reference_stats(owner),
    }


@app.post("/api/references", dependencies=[Depends(require_access)])
async def add_ref(
    file: UploadFile = File(...),
    consent: str = Form("false"),
    owner: str = Depends(owner_token),
):
    if consent.lower() not in ("true", "1", "on", "tak"):
        raise HTTPException(400, "Dodanie do bazy lokalnej wymaga zgody na przechowywanie pliku.")
    settings = get_settings()
    data = await _read_upload(file, settings.max_upload_bytes)
    try:
        content = extract_text(Path(file.filename or "").name, data)
    except ExtractionError as exc:
        raise HTTPException(422, str(exc))
    ref_id = db.add_reference(owner, Path(file.filename or "plik").name, content[: settings.max_text_chars])
    return {"id": ref_id, "words": len(content.split())}


@app.delete("/api/references/{ref_id}", dependencies=[Depends(require_access)])
def remove_ref(ref_id: int, owner: str = Depends(owner_token)):
    if not db.delete_reference(ref_id, owner):
        raise HTTPException(404, "Nie znaleziono pliku (pliki wspólne usuwa administrator).")
    return {"deleted": True}


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ------------------------------------------------------------------- frontend


@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(STATIC_DIR / "landing.html", headers={"Cache-Control": "no-cache"})


@app.get("/app", include_in_schema=False)
@app.get("/app/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
