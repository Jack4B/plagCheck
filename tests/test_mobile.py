"""Tryb mobilny (APK): start serwera, ustawienia w aplikacji, zapytania słowami kluczowymi."""
import json
import os
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app import jobs, mobile
from app.config import get_settings
from app.main import app
from app.services.phrases import generate_keyword_queries, generate_phrases
from app.services.preprocessor import preprocess
from app.services.web_search import SearchResult
from samples import SOURCE_ARTICLE, STUDENT_WITH_COPY

OWNER = {"X-Owner-Token": "m" * 32}


@pytest.fixture
def mobile_env(monkeypatch):
    for key in list(mobile.MOBILE_DEFAULTS) + list(mobile.EDITABLE) + ["SEMANTIC_MODEL"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MOBILE_MODE", "1")
    monkeypatch.setattr(mobile, "_state", {"port": None, "model_dir": ""})
    yield
    for key in list(mobile.MOBILE_DEFAULTS) + list(mobile.EDITABLE) + ["SEMANTIC_MODEL"]:
        os.environ.pop(key, None)


def test_settings_api_hidden_on_server():
    assert TestClient(app).get("/api/settings").status_code == 404


def test_settings_roundtrip_masks_secrets_and_applies(mobile_env):
    client = TestClient(app)
    view = client.get("/api/settings").json()
    assert view["BRAVE_API_KEY"] == {"set": False, "hint": ""}
    res = client.put("/api/settings", json={"BRAVE_API_KEY": "abcd1234efgh5678", "MAX_WEB_QUERIES": 60,
                                            "SEARCH_OPENALEX": False})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["BRAVE_API_KEY"] == {"set": True, "hint": "••••5678"}
    assert "abcd1234" not in res.text  # klucz nigdy nie wraca do przeglądarki w całości
    assert body["SEARCH_OPENALEX"] is False
    s = get_settings()
    assert s.brave_api_key == "abcd1234efgh5678" and s.max_web_queries == 60 and s.search_openalex is False


@pytest.mark.parametrize("payload", [{"MAX_WEB_QUERIES": 999}, {"NIEZNANE": 1}, {"BRAVE_API_KEY": "a\nb"},
                                     {"SEMANTIC_THRESHOLD": "abc"}])
def test_settings_validation(mobile_env, payload):
    assert TestClient(app).put("/api/settings", json=payload).status_code == 400


def test_mobile_start_serves_app_on_localhost(tmp_path, mobile_env):
    port = mobile.start(str(tmp_path / "dane"))
    assert mobile.start(str(tmp_path / "inne")) == port  # idempotentne
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as resp:
        health = json.loads(resp.read())
    assert health["mobile"] is True and health["access_required"] is False
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/app", timeout=5) as resp:
        assert b"/static/app.js" in resp.read()
    assert get_settings().max_web_queries == 40 and get_settings().report_ttl_hours == 24 * 365


def test_keyword_queries_pick_rare_words_and_can_skip_sentences():
    doc = preprocess(STUDENT_WITH_COPY)
    phrases = generate_phrases(doc, limit=2)
    queries = generate_keyword_queries(doc, limit=10, skip_sentences={p.sentence for p in phrases})
    assert queries
    for q in queries:
        assert q.sentence not in {p.sentence for p in phrases}
        assert not q.query.startswith('"') and 1 <= len(q.query.split()) <= 6


class KeywordOnlyWiki:
    """Wikipedia, która znajduje artykuł tylko po słowach kluczowych (nie po cytacie)."""

    name = "wikipedia"
    min_interval = 0.0

    def __init__(self):
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        if query.startswith('"'):
            return []
        return [SearchResult("https://pl.wikipedia.org/wiki/Kopernik", "Kopernik", "")]

    def fetch_text(self, url):
        return SOURCE_ARTICLE


def test_keyword_queries_find_sources_missed_by_exact_search(monkeypatch):
    wiki = KeywordOnlyWiki()
    monkeypatch.setattr(jobs, "providers_factory", lambda s: [wiki])
    client = TestClient(app)
    job = client.post("/api/check", data={"text": STUDENT_WITH_COPY, "options": json.dumps({"local": False})},
                      headers=OWNER).json()
    jobs.process_pending()
    report = client.get(f"/api/jobs/{job['id']}/report", headers=OWNER).json()
    assert any(not q.startswith('"') for q in wiki.queries)
    assert report["search"]["keyword_queries"] > 0
    assert report["sources"] and report["sources"][0]["kind"] == "wikipedia"


class RateLimitedWiki(KeywordOnlyWiki):
    def search(self, query):
        from app.services.web_search import RateLimited

        self.queries.append(query)
        raise RateLimited("HTTP 429 od pl.wikipedia.org")


class FastOpenAlex:
    name = "openalex"
    min_interval = 0.0

    def __init__(self):
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return [SearchResult("https://doi.org/10.1/x", "Publikacja", "")]

    def fetch_text(self, url):
        return SOURCE_ARTICLE


def _run_report(monkeypatch, providers):
    monkeypatch.setattr(jobs, "providers_factory", lambda s: providers)
    client = TestClient(app)
    job = client.post("/api/check", data={"text": STUDENT_WITH_COPY, "options": json.dumps({"local": False})},
                      headers=OWNER).json()
    jobs.process_pending()
    return client.get(f"/api/jobs/{job['id']}/report", headers=OWNER).json()


def test_rate_limited_source_is_skipped_immediately(monkeypatch):
    wiki, openalex = RateLimitedWiki(), FastOpenAlex()
    report = _run_report(monkeypatch, [wiki, openalex])
    assert len(wiki.queries) == 1  # bezpiecznik: po odmowie nie wysyłamy kolejnych zapytań
    assert len(openalex.queries) > 1  # pozostałe źródła działają dalej
    stats = report["search"]["sources"]
    assert stats["wikipedia"]["stopped"].startswith("ograniczenie") and stats["openalex"]["stopped"] is None
    assert any("ograniczyło liczbę zapytań" in w for w in report["warnings"])
    assert report["sources"]  # wynik z OpenAlex nadal jest


def test_source_time_budget_stops_slow_source(monkeypatch):
    monkeypatch.setenv("SOURCE_TIME_BUDGET", "0")
    openalex = FastOpenAlex()
    report = _run_report(monkeypatch, [openalex])
    assert len(openalex.queries) == 1
    assert report["search"]["sources"]["openalex"]["stopped"] == "limit czasu"
