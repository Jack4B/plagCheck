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
from .config import Settings, get_settings
from .pipeline import run_analysis, summarize
from .services.semantic import get_encoder
from .services.web_search import CachedSearcher, build_providers

log = logging.getLogger("plagcheck.jobs")


class JobCancelled(Exception):
    """Zadanie zatrzymane lub usunięte przez użytkownika w trakcie analizy."""


def _progress(job_id: str):
    def report(progress: int, stage: str) -> None:
        if not db.set_progress(job_id, progress, stage):
            raise JobCancelled(job_id)
    return report

# Liczba równoległych analiz: 2 na CT8 (RAM), więcej na Oracle (MAX_CONCURRENT_JOBS).
_slots = threading.BoundedSemaphore(get_settings().max_concurrent_jobs)

# Wstrzykiwalne fabryki (testy podmieniają je na fałszywe).
providers_factory = build_providers
encoder_factory = lambda settings: get_encoder(settings.semantic_model)  # noqa: E731


def make_searchers(settings: Settings) -> list[CachedSearcher]:
    return [
        CachedSearcher(
            provider,
            cache_get=lambda p, q: db.cache_get(p, q, settings.search_cache_hours),
            cache_put=db.cache_put,
        )
        for provider in providers_factory(settings)
    ]


class DbReferenceSource:
    """Baza lokalna: mała → porównanie z każdym dokumentem (wykrywa też parafrazy);
    duża → tylko kandydaci z indeksu odcisków winnowing."""

    def __init__(self, owner: str, settings: Settings):
        self.owner = owner
        self.settings = settings

    def load(self, doc_hashes: set[int]):
        stats = db.reference_stats(self.owner)
        if stats["count"] == 0:
            return [], "empty"
        if stats["words"] <= self.settings.local_fullscan_words:
            return db.iter_references(self.owner), "full"
        ids = db.candidate_references(self.owner, doc_hashes, self.settings.local_max_candidates)
        return db.iter_references(self.owner, ids), "index"


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
                searchers=make_searchers(settings) if options.get("web", True) else [],
                references=DbReferenceSource(job["owner"], settings) if options.get("local", True) else None,
                encoder=encoder_factory(settings),
                progress=_progress(job_id),
            )
            db.finish_job(job_id, report, summarize(report))
            return True
        except JobCancelled:
            log.info("job %s zatrzymany przez użytkownika", job_id)
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
