"""Wykonywanie zadań analizy.

Tryby (WORKER_MODE):
  thread — analiza startuje w wątku procesu WWW zaraz po wgraniu pliku;
           cron (`python -m app.worker run`) jest siatką bezpieczeństwa, gdy
           Passenger ubije bezczynny proces w trakcie analizy.
  cron   — tylko cron/worker (np. gdy hosting ubija wątki w tle).

Semafor ogranicza liczbę równoległych analiz (RAM na CT8).
"""
from __future__ import annotations

import json
import logging
import threading

from . import db
from .config import get_settings
from .pipeline import run_analysis, summarize
from .services.web_search import CachedSearcher, build_provider

log = logging.getLogger("plagcheck.jobs")

_slots = threading.BoundedSemaphore(2)

# Wstrzykiwalny dostawca (testy podmieniają go na fałszywy).
provider_factory = build_provider


def make_searcher(settings):
    provider = provider_factory(settings)
    if provider is None:
        return None
    return CachedSearcher(
        provider,
        cache_get=lambda p, q: db.cache_get(p, q, settings.search_cache_hours),
        cache_put=db.cache_put,
    )


def run_job(job_id: str) -> bool:
    """Wykonuje zadanie, jeśli uda się je przejąć. Zwraca True, gdy je wykonał."""
    with _slots:
        job = db.claim_job(job_id)
        if job is None:
            return False
        settings = get_settings()
        try:
            options = json.loads(job["options"] or "{}")
            report = run_analysis(
                text=job["text"] or "",
                filename=job["filename"],
                options=options,
                settings=settings,
                searcher=make_searcher(settings) if options.get("web", True) else None,
                references=db.iter_references(job["owner"]) if options.get("local", True) else None,
                progress=lambda p, s: db.set_progress(job_id, p, s),
            )
            db.finish_job(job_id, report, summarize(report))
            return True
        except Exception as exc:  # zadanie nie może wywrócić procesu
            log.exception("job %s failed", job_id)
            db.fail_job(job_id, f"{type(exc).__name__}: {exc}")
            return True


def submit(job_id: str) -> None:
    if get_settings().worker_mode == "thread":
        threading.Thread(target=run_job, args=(job_id,), name=f"job-{job_id[:8]}", daemon=True).start()


def process_pending(grace_seconds: int = 0) -> int:
    settings = get_settings()
    db.requeue_stale(settings.job_stale_minutes)
    done = 0
    for job_id in db.pending_job_ids(older_than_seconds=grace_seconds):
        if run_job(job_id):
            done += 1
    return done
