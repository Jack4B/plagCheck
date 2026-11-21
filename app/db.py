"""Warstwa danych — SQLAlchemy Core (SQLite lokalnie, MySQL na CT8).

Tabele:
  jobs            — zadania analizy; tekst dokumentu kasowany zaraz po analizie,
                    raport wygasa po REPORT_TTL_HOURS (RODO / prywatność)
  reference_docs  — lokalna baza referencyjna (pliki dodane świadomie przez
                    użytkownika; owner='' = baza wspólna dodana przez admina)
  search_cache    — cache wyników wyszukiwarki (oszczędza limity API)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import (
    BigInteger,
    Column,
    Index,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    create_engine,
    delete,
    event,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import Engine

from .config import get_settings

LongText = Text().with_variant(mysql.LONGTEXT(), "mysql")

metadata = MetaData()

jobs = Table(
    "jobs",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner", String(64), nullable=False, index=True),
    Column("filename", String(255), nullable=False),
    Column("status", String(16), nullable=False, index=True),  # pending|running|done|error
    Column("progress", Integer, nullable=False, default=0),
    Column("stage", String(128), nullable=False, default=""),
    Column("options", Text, nullable=False, default="{}"),
    Column("text", LongText, nullable=True),
    Column("report", LongText, nullable=True),
    Column("summary", Text, nullable=True),
    Column("error", Text, nullable=True),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    Column("expires_at", DateTime, nullable=False, index=True),
)

reference_docs = Table(
    "reference_docs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("owner", String(64), nullable=False, index=True),
    Column("name", String(255), nullable=False),
    Column("text", LongText, nullable=False),
    Column("words", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False),
)

# Odciski winnowing dokumentów bazy lokalnej (szybkie wyszukiwanie kandydatów).
ref_fingerprints = Table(
    "ref_fingerprints",
    metadata,
    Column("ref_id", Integer, nullable=False),
    Column("hash", BigInteger, nullable=False),
    Index("ix_ref_fingerprints_hash", "hash"),
    Index("ix_ref_fingerprints_ref", "ref_id"),
)

# Ustawienia edytowalne w aplikacji (tylko tryb mobilny — na serwerze konfiguracja jest w .env).
app_settings = Table(
    "app_settings",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)

search_cache = Table(
    "search_cache",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("provider", String(32), nullable=False),
    Column("query", Text, nullable=False),
    Column("results", LongText, nullable=False),
    Column("created_at", DateTime, nullable=False, index=True),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@lru_cache(maxsize=4)
def _engine_for(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kwargs["pool_recycle"] = 280  # MySQL na CT8 zamyka bezczynne połączenia
        kwargs["pool_size"] = 3
        kwargs["max_overflow"] = 2
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trywialne
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    metadata.create_all(engine)
    return engine


def get_engine() -> Engine:
    return _engine_for(get_settings().database_url)


# ------------------------------------------------------------------ jobs


def create_job(owner: str, filename: str, text: str, options: dict, ttl_hours: int) -> str:
    import uuid

    job_id = uuid.uuid4().hex
    now = utcnow()
    with get_engine().begin() as conn:
        conn.execute(
            insert(jobs).values(
                id=job_id,
                owner=owner,
                filename=filename[:255],
                status="pending",
                progress=0,
                stage="W kolejce",
                options=json.dumps(options),
                text=text,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(hours=ttl_hours),
            )
        )
    return job_id


def claim_job(job_id: str) -> dict | None:
    """Atomowo przełącza pending → running. Zwraca zadanie albo None (ktoś je już wziął)."""
    with get_engine().begin() as conn:
        res = conn.execute(
            update(jobs)
            .where(and_(jobs.c.id == job_id, jobs.c.status == "pending"))
            .values(status="running", stage="Start analizy", updated_at=utcnow())
        )
        if res.rowcount != 1:
            return None
        row = conn.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
        return dict(row) if row else None


def set_progress(job_id: str, progress: int, stage: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            update(jobs)
            .where(jobs.c.id == job_id)
            .values(progress=progress, stage=stage[:128], updated_at=utcnow())
        )


def finish_job(job_id: str, report: dict, summary: dict) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            update(jobs)
            .where(jobs.c.id == job_id)
            .values(
                status="done",
                progress=100,
                stage="Zakończono",
                text=None,  # prywatność: oryginalny tekst nie jest przechowywany po analizie
                report=json.dumps(report, ensure_ascii=False),
                summary=json.dumps(summary, ensure_ascii=False),
                updated_at=utcnow(),
            )
        )


def fail_job(job_id: str, message: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            update(jobs)
            .where(jobs.c.id == job_id)
            .values(status="error", stage="Błąd", error=message[:2000], text=None, updated_at=utcnow())
        )


def get_job(job_id: str, owner: str | None = None, with_report: bool = False) -> dict | None:
    cols = [c for c in jobs.c if c.name != "text" and (with_report or c.name != "report")]
    q = select(*cols).where(jobs.c.id == job_id)
    if owner is not None:
        q = q.where(jobs.c.owner == owner)
    with get_engine().connect() as conn:
        row = conn.execute(q).mappings().first()
    return dict(row) if row else None


def list_jobs(owner: str, limit: int = 50) -> list[dict]:
    cols = [c for c in jobs.c if c.name not in ("text", "report")]
    q = (
        select(*cols)
        .where(and_(jobs.c.owner == owner, jobs.c.expires_at > utcnow()))
        .order_by(jobs.c.created_at.desc())
        .limit(limit)
    )
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(q).mappings()]


def delete_job(job_id: str, owner: str) -> bool:
    with get_engine().begin() as conn:
        res = conn.execute(delete(jobs).where(and_(jobs.c.id == job_id, jobs.c.owner == owner)))
        return res.rowcount > 0


def pending_job_ids(older_than_seconds: int = 0) -> list[str]:
    cutoff = utcnow() - timedelta(seconds=older_than_seconds)
    with get_engine().connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                select(jobs.c.id)
                .where(and_(jobs.c.status == "pending", jobs.c.updated_at <= cutoff))
                .order_by(jobs.c.created_at)
            )
        ]


def requeue_stale(stale_minutes: int) -> int:
    """Zadania 'running' bez postępu (np. proces ubity przez Passenger) wracają do kolejki."""
    cutoff = utcnow() - timedelta(minutes=stale_minutes)
    with get_engine().begin() as conn:
        res = conn.execute(
            update(jobs)
            .where(and_(jobs.c.status == "running", jobs.c.updated_at < cutoff, jobs.c.text.is_not(None)))
            .values(status="pending", stage="Wznowienie po przerwaniu", updated_at=utcnow() - timedelta(hours=1))
        )
        return res.rowcount


def cleanup_expired(cache_hours: int) -> dict:
    now = utcnow()
    with get_engine().begin() as conn:
        j = conn.execute(delete(jobs).where(jobs.c.expires_at < now)).rowcount
        c = conn.execute(
            delete(search_cache).where(search_cache.c.created_at < now - timedelta(hours=cache_hours))
        ).rowcount
    return {"jobs_deleted": j, "cache_deleted": c}


# ------------------------------------------------------------ reference docs


def _insert_fingerprints(conn, ref_id: int, text: str) -> None:
    from .services.fingerprints import text_fingerprints

    rows = [{"ref_id": ref_id, "hash": h} for h in text_fingerprints(text)]
    for i in range(0, len(rows), 5000):
        conn.execute(insert(ref_fingerprints), rows[i:i + 5000])


def add_reference(owner: str, name: str, text: str) -> int:
    with get_engine().begin() as conn:
        res = conn.execute(
            insert(reference_docs).values(
                owner=owner, name=name[:255], text=text, words=len(text.split()), created_at=utcnow()
            )
        )
        ref_id = int(res.inserted_primary_key[0])
        _insert_fingerprints(conn, ref_id, text)
        return ref_id


def index_missing_fingerprints() -> int:
    """Indeksuje dokumenty bez odcisków (np. dodane przed wersją 1.1)."""
    indexed = select(ref_fingerprints.c.ref_id).distinct()
    with get_engine().connect() as conn:
        missing = [
            r[0] for r in conn.execute(
                select(reference_docs.c.id).where(reference_docs.c.id.not_in(indexed))
            )
        ]
    for ref_id in missing:
        with get_engine().begin() as conn:
            text = conn.execute(select(reference_docs.c.text).where(reference_docs.c.id == ref_id)).scalar()
            if text:
                _insert_fingerprints(conn, ref_id, text)
    return len(missing)


def candidate_references(owner: str, hashes: set[int], limit: int = 30, min_hits: int = 2) -> list[int]:
    """Dokumenty bazy lokalnej dzielące z tekstem najwięcej odcisków (najlepsze najpierw)."""
    if not hashes:
        return []
    visible = select(reference_docs.c.id).where(or_(reference_docs.c.owner == owner, reference_docs.c.owner == ""))
    counts: dict[int, int] = {}
    values = list(hashes)
    with get_engine().connect() as conn:
        for i in range(0, len(values), 500):
            q = (
                select(ref_fingerprints.c.ref_id, func.count())
                .where(ref_fingerprints.c.hash.in_(values[i:i + 500]))
                .where(ref_fingerprints.c.ref_id.in_(visible))
                .group_by(ref_fingerprints.c.ref_id)
            )
            for ref_id, n in conn.execute(q):
                counts[ref_id] = counts.get(ref_id, 0) + n
    ranked = sorted((r for r, n in counts.items() if n >= min_hits), key=lambda r: -counts[r])
    return ranked[:limit]


def list_references(owner: str) -> list[dict]:
    q = (
        select(reference_docs.c.id, reference_docs.c.owner, reference_docs.c.name,
               reference_docs.c.words, reference_docs.c.created_at)
        .where(or_(reference_docs.c.owner == owner, reference_docs.c.owner == ""))
        .order_by(reference_docs.c.created_at.desc())
    )
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(q).mappings()]


def iter_references(owner: str, ids: list[int] | None = None):
    """Generator — referencje wczytywane pojedynczo (oszczędność RAM)."""
    if ids is None:
        ids = [r["id"] for r in list_references(owner)]
    for ref_id in ids:
        with get_engine().connect() as conn:
            row = conn.execute(
                select(reference_docs.c.id, reference_docs.c.name, reference_docs.c.text)
                .where(reference_docs.c.id == ref_id)
            ).mappings().first()
        if row:
            yield dict(row)


def delete_reference(ref_id: int, owner: str) -> bool:
    with get_engine().begin() as conn:
        res = conn.execute(
            delete(reference_docs).where(and_(reference_docs.c.id == ref_id, reference_docs.c.owner == owner))
        )
        if res.rowcount:
            conn.execute(delete(ref_fingerprints).where(ref_fingerprints.c.ref_id == ref_id))
        return res.rowcount > 0


def reference_stats(owner: str) -> dict:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(func.count(), func.coalesce(func.sum(reference_docs.c.words), 0))
            .where(or_(reference_docs.c.owner == owner, reference_docs.c.owner == ""))
        ).first()
    return {"count": int(row[0]), "words": int(row[1])}


# ------------------------------------------------------------- app settings


def get_app_settings() -> dict[str, str]:
    with get_engine().connect() as conn:
        return {k: v for k, v in conn.execute(select(app_settings.c.key, app_settings.c.value))}


def set_app_settings(values: dict[str, str]) -> None:
    with get_engine().begin() as conn:
        for key, value in values.items():
            conn.execute(delete(app_settings).where(app_settings.c.key == key))
            conn.execute(insert(app_settings).values(key=key, value=str(value)))


# ---------------------------------------------------------------- search cache


def _cache_key(provider: str, query: str) -> str:
    return hashlib.sha256(f"{provider}\x00{query}".encode()).hexdigest()


def cache_get(provider: str, query: str, max_age_hours: int):
    with get_engine().connect() as conn:
        row = conn.execute(
            select(search_cache.c.results, search_cache.c.created_at)
            .where(search_cache.c.key == _cache_key(provider, query))
        ).first()
    if not row or row[1] < utcnow() - timedelta(hours=max_age_hours):
        return None
    return json.loads(row[0])


def cache_put(provider: str, query: str, results: list) -> None:
    key = _cache_key(provider, query)
    with get_engine().begin() as conn:
        conn.execute(delete(search_cache).where(search_cache.c.key == key))
        conn.execute(
            insert(search_cache).values(
                key=key, provider=provider, query=query, results=json.dumps(results, ensure_ascii=False),
                created_at=utcnow(),
            )
        )
