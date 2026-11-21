"""Konfiguracja aplikacji — zmienne środowiskowe + opcjonalny plik .env.

Celowo bez zależności (python-dotenv), żeby instalacja na CT8 była minimalna.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    """Wczytuje proste pliki KEY=VALUE. Nie nadpisuje istniejących zmiennych."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "tak"}


@dataclass
class Settings:
    data_dir: Path
    database_url: str
    access_key: str
    # Wyszukiwanie w sieci
    search_provider: str  # auto | brave | serper | serpapi | wikipedia | none (none = bez sieci)
    search_wikipedia: bool
    search_openalex: bool
    openalex_mailto: str
    brave_api_key: str
    serper_api_key: str
    serpapi_api_key: str
    search_lang: str
    max_web_queries: int
    keyword_queries: int  # zapytania bez cudzysłowu (parafrazy) do darmowych źródeł
    wikipedia_max_queries: int  # Wikipedia ma limit tempa (1/s) — osobny, mniejszy budżet
    source_time_budget: float  # maks. sekund wyszukiwania na jedno źródło (potem idziemy dalej)
    openalex_max_queries: int
    keyword_queries_web: bool  # także do płatnej wyszukiwarki (zużywa limit API)
    max_pages_fetched: int
    archive_max_pages: int  # strony niedostępne → kopia z Internet Archive (0 = wyłączone)
    search_cache_hours: int
    http_timeout: float
    # Analiza
    phrase_min_words: int
    phrase_max_words: int
    shingle_size: int
    paraphrase_threshold: float
    max_upload_mb: int
    max_text_chars: int
    # Baza lokalna
    local_fullscan_words: int
    local_max_candidates: int
    # Profil "full": silnik semantyczny (sentence-transformers), pusty = wyłączony
    semantic_model: str
    semantic_threshold: float
    # Prywatność / retencja
    report_ttl_hours: int
    # Zadania w tle
    worker_mode: str  # thread | cron
    max_concurrent_jobs: int
    mobile_mode: bool  # aplikacja na telefonie (APK): ustawienia edytowalne w UI
    job_stale_minutes: int
    extra: dict = field(default_factory=dict)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def get_settings() -> Settings:
    load_env_file(BASE_DIR / ".env")
    data_dir = Path(os.environ.get("DATA_DIR") or BASE_DIR / "data").expanduser()
    if not data_dir.is_absolute():
        data_dir = (BASE_DIR / data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    default_db = f"sqlite:///{data_dir / 'plagcheck.sqlite3'}"
    return Settings(
        data_dir=data_dir,
        database_url=os.environ.get("DATABASE_URL") or default_db,
        access_key=os.environ.get("ACCESS_KEY", ""),
        search_provider=(os.environ.get("SEARCH_PROVIDER") or "auto").strip().lower(),
        search_wikipedia=_bool("SEARCH_WIKIPEDIA", True),
        search_openalex=_bool("SEARCH_OPENALEX", True),
        openalex_mailto=os.environ.get("OPENALEX_MAILTO", ""),
        brave_api_key=os.environ.get("BRAVE_API_KEY", ""),
        serper_api_key=os.environ.get("SERPER_API_KEY", ""),
        serpapi_api_key=os.environ.get("SERPAPI_API_KEY", ""),
        search_lang=os.environ.get("SEARCH_LANG") or "pl",
        max_web_queries=_int("MAX_WEB_QUERIES", 25),
        keyword_queries=_int("KEYWORD_QUERIES", 15),
        wikipedia_max_queries=_int("WIKIPEDIA_MAX_QUERIES", 40),
        source_time_budget=_float("SOURCE_TIME_BUDGET", 150.0),
        openalex_max_queries=_int("OPENALEX_MAX_QUERIES", 30),
        keyword_queries_web=_bool("KEYWORD_QUERIES_WEB", False),
        max_pages_fetched=_int("MAX_PAGES_FETCHED", 12),
        archive_max_pages=_int("ARCHIVE_MAX_PAGES", 6),
        search_cache_hours=_int("SEARCH_CACHE_HOURS", 24 * 7),
        http_timeout=_float("HTTP_TIMEOUT", 10.0),
        phrase_min_words=_int("PHRASE_MIN_WORDS", 10),
        phrase_max_words=_int("PHRASE_MAX_WORDS", 15),
        shingle_size=_int("SHINGLE_SIZE", 5),
        paraphrase_threshold=_float("PARAPHRASE_THRESHOLD", 0.6),
        max_upload_mb=_int("MAX_UPLOAD_MB", 15),
        max_text_chars=_int("MAX_TEXT_CHARS", 400_000),
        local_fullscan_words=_int("LOCAL_FULLSCAN_WORDS", 300_000),
        local_max_candidates=_int("LOCAL_MAX_CANDIDATES", 25),
        semantic_model=os.environ.get("SEMANTIC_MODEL", "").strip(),
        semantic_threshold=_float("SEMANTIC_THRESHOLD", 0.8),
        report_ttl_hours=_int("REPORT_TTL_HOURS", 72),
        worker_mode=(os.environ.get("WORKER_MODE") or "thread").strip().lower(),
        max_concurrent_jobs=max(1, _int("MAX_CONCURRENT_JOBS", 2)),
        mobile_mode=_bool("MOBILE_MODE", False),
        job_stale_minutes=_int("JOB_STALE_MINUTES", 15),
    )
