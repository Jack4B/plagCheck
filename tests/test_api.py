"""Testy integracyjne API — pełny przepływ z fałszywą wyszukiwarką."""
import io
import json

import pytest
from fastapi.testclient import TestClient

from app import jobs
from app.main import app
from app.services.web_search import SearchResult
from samples import AI_LIKE, SOURCE_ARTICLE, STUDENT_WITH_COPY
from test_extractor import make_docx

OWNER = {"X-Owner-Token": "a" * 32}
OTHER = {"X-Owner-Token": "b" * 32}


class FakeProvider:
    """Udaje wyszukiwarkę: każde zapytanie zwraca artykuł o Koperniku."""

    name = "fake"
    min_interval = 0.0

    def __init__(self):
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return [SearchResult("https://example.org/kopernik", "Kopernik — artykuł", "snippet")]

    def fetch_text(self, url):
        return SOURCE_ARTICLE


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fake_provider(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(jobs, "providers_factory", lambda settings: [provider])
    return provider


def run_pending():
    assert jobs.process_pending() >= 1


def submit_docx(client, paragraphs, options=None, headers=OWNER):
    files = {"file": ("praca.docx", make_docx(paragraphs), "application/octet-stream")}
    data = {"options": json.dumps(options or {})}
    res = client.post("/api/check", files=files, data=data, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_full_flow_web_report_export_delete(client, fake_provider):
    job_id = submit_docx(client, STUDENT_WITH_COPY.split("\n\n"))
    assert client.get(f"/api/jobs/{job_id}", headers=OWNER).json()["status"] == "pending"
    run_pending()

    status = client.get(f"/api/jobs/{job_id}", headers=OWNER).json()
    assert status["status"] == "done" and status["progress"] == 100
    assert status["summary"]["similarity"] > 20

    report = client.get(f"/api/jobs/{job_id}/report", headers=OWNER).json()
    assert report["sources"][0]["url"] == "https://example.org/kopernik"
    assert report["similarity"]["exact_percent"] > 0
    assert report["similarity"]["paraphrase_percent"] > 0
    assert any(s["type"] == "exact" for s in report["segments"])
    assert any(s["type"] == "excluded" and s["reason"] == "bibliografia" for s in report["segments"])
    # segmenty odtwarzają dokładnie tekst dokumentu
    assert "".join(s["text"] for s in report["segments"]).startswith("Wstęp\n\nMoja praca")
    assert report["phrases"] and any(p["found"] for p in report["phrases"])
    assert fake_provider.queries and all(q.startswith('"') for q in fake_provider.queries)
    assert "To nie jest zamiennik JSA" in report["disclaimer"]

    export = client.get(f"/api/jobs/{job_id}/export.html", headers=OWNER)
    assert export.status_code == 200
    assert "attachment" in export.headers["content-disposition"]
    assert "<mark class='exact'>" in export.text and "To nie jest zamiennik JSA" in export.text

    history = client.get("/api/jobs", headers=OWNER).json()["jobs"]
    assert [j["id"] for j in history] == [job_id]
    assert client.get("/api/jobs", headers=OTHER).json()["jobs"] == []
    assert client.get(f"/api/jobs/{job_id}/report", headers=OTHER).status_code == 404

    assert client.delete(f"/api/jobs/{job_id}", headers=OWNER).json() == {"deleted": True}
    assert client.get(f"/api/jobs/{job_id}", headers=OWNER).status_code == 404


def test_document_text_is_not_stored_after_analysis(client, fake_provider):
    from sqlalchemy import select

    from app import db

    job_id = submit_docx(client, ["Tekst " * 30])
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.jobs.c.text).where(db.jobs.c.id == job_id)).scalar() is not None
    run_pending()
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.jobs.c.text).where(db.jobs.c.id == job_id)).scalar() is None


def test_pasted_text_and_ai_detection_without_search(client):
    res = client.post("/api/check", data={"text": AI_LIKE, "options": json.dumps({"web": False})}, headers=OWNER)
    job_id = res.json()["id"]
    run_pending()
    report = client.get(f"/api/jobs/{job_id}/report", headers=OWNER).json()
    assert report["filename"] == "Wklejony tekst"
    assert report["ai"]["percent"] >= 65
    assert report["sources"] == []
    assert report["options"]["web"] is False


def test_web_enabled_without_provider_warns(client):
    res = client.post("/api/check", data={"text": STUDENT_WITH_COPY}, headers=OWNER)
    run_pending()
    report = client.get(f"/api/jobs/{res.json()['id']}/report", headers=OWNER).json()
    assert any("Wyszukiwanie w sieci wyłączone" in w for w in report["warnings"])
    assert report["phrases"]  # frazy do ręcznego sprawdzenia nadal są


def test_local_reference_base(client):
    # bez zgody — odmowa
    files = {"file": ("zrodlo.txt", SOURCE_ARTICLE.encode(), "text/plain")}
    assert client.post("/api/references", files=files, headers=OWNER).status_code == 400
    files = {"file": ("zrodlo.txt", SOURCE_ARTICLE.encode(), "text/plain")}
    res = client.post("/api/references", files=files, data={"consent": "true"}, headers=OWNER)
    assert res.status_code == 200
    refs = client.get("/api/references", headers=OWNER).json()
    assert refs["stats"]["count"] == 1 and refs["references"][0]["name"] == "zrodlo.txt"
    assert client.get("/api/references", headers=OTHER).json()["stats"]["count"] == 0

    res = client.post("/api/check", data={"text": STUDENT_WITH_COPY, "options": json.dumps({"web": False})}, headers=OWNER)
    run_pending()
    report = client.get(f"/api/jobs/{res.json()['id']}/report", headers=OWNER).json()
    assert report["sources"][0]["kind"] == "local"
    assert report["sources"][0]["title"] == "zrodlo.txt"
    assert report["similarity"]["percent"] > 20

    ref_id = refs["references"][0]["id"]
    assert client.delete(f"/api/references/{ref_id}", headers=OTHER).status_code == 404
    assert client.delete(f"/api/references/{ref_id}", headers=OWNER).status_code == 200


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"data": {"text": "za krótki tekst"}}, 422),
        ({"data": {}}, 400),
        ({"files": {"file": ("x.exe", b"MZ", "application/octet-stream")}}, 422),
        ({"data": {"text": "x " * 30, "options": "{not json"}}, 400),
    ],
)
def test_validation_errors(client, kwargs, status):
    assert client.post("/api/check", headers=OWNER, **kwargs).status_code == status


def test_owner_token_required(client):
    assert client.get("/api/jobs").status_code == 400
    assert client.get("/api/jobs", headers={"X-Owner-Token": "../etc"}).status_code == 400


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    files = {"file": ("big.txt", b"a " * (600 * 1024), "text/plain")}
    assert client.post("/api/check", files=files, headers=OWNER).status_code == 413


def test_access_key(client, monkeypatch):
    monkeypatch.setenv("ACCESS_KEY", "tajne")
    assert client.get("/api/health").json()["access_required"] is True
    assert client.get("/api/jobs", headers=OWNER).status_code == 401
    assert client.get("/api/jobs", headers={**OWNER, "X-Access-Key": "zle"}).status_code == 401
    assert client.get("/api/jobs", headers={**OWNER, "X-Access-Key": "zł".encode()}).status_code == 401
    assert client.get("/api/jobs", headers={**OWNER, "X-Access-Key": "tajne"}).status_code == 200


def test_frontend_and_security_headers(client):
    res = client.get("/")
    assert res.status_code == 200 and "PlagCheck" in res.text
    assert "default-src 'self'" in res.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200


def test_thread_mode_runs_job_in_background(client, fake_provider, monkeypatch):
    import time

    monkeypatch.setenv("WORKER_MODE", "thread")
    job_id = submit_docx(client, STUDENT_WITH_COPY.split("\n\n"))
    for _ in range(100):
        if client.get(f"/api/jobs/{job_id}", headers=OWNER).json()["status"] == "done":
            break
        time.sleep(0.1)
    assert client.get(f"/api/jobs/{job_id}", headers=OWNER).json()["status"] == "done"


def test_stale_running_job_is_requeued(client, fake_provider):
    from datetime import timedelta

    from sqlalchemy import update

    from app import db

    job_id = submit_docx(client, STUDENT_WITH_COPY.split("\n\n"))
    db.claim_job(job_id)  # symulacja: proces ubity w trakcie analizy
    with db.get_engine().begin() as conn:
        conn.execute(update(db.jobs).where(db.jobs.c.id == job_id).values(updated_at=db.utcnow() - timedelta(hours=1)))
    assert jobs.process_pending() == 1
    assert client.get(f"/api/jobs/{job_id}", headers=OWNER).json()["status"] == "done"


def test_expired_reports_are_cleaned(client, fake_provider):
    from datetime import timedelta

    from sqlalchemy import update

    from app import db

    job_id = submit_docx(client, ["Tekst " * 30])
    with db.get_engine().begin() as conn:
        conn.execute(update(db.jobs).where(db.jobs.c.id == job_id).values(expires_at=db.utcnow() - timedelta(minutes=1)))
    assert db.cleanup_expired(24)["jobs_deleted"] == 1


def test_passenger_wsgi_entrypoint():
    import passenger_wsgi

    environ = {
        "REQUEST_METHOD": "GET", "PATH_INFO": "/api/health", "QUERY_STRING": "", "SERVER_NAME": "test",
        "SERVER_PORT": "80", "SERVER_PROTOCOL": "HTTP/1.1", "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""), "wsgi.errors": io.StringIO(), "wsgi.version": (1, 0),
        "wsgi.multithread": True, "wsgi.multiprocess": True, "wsgi.run_once": False,
    }
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status

    body = b"".join(passenger_wsgi.application(environ, start_response))
    assert captured["status"].startswith("200")
    assert json.loads(body)["status"] == "ok"


def test_worker_cli_import_and_run(tmp_path, client, capsys):
    from app import worker

    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "kopernik.txt").write_text(SOURCE_ARTICLE, encoding="utf-8")
    (refs / "ignored.bin").write_bytes(b"\x00")
    assert worker.main(["import-refs", str(refs)]) == 0
    shared = client.get("/api/references", headers=OWNER).json()
    assert shared["references"][0]["shared"] is True  # owner='' → baza wspólna
    assert worker.main(["run"]) == 0
    assert "zadania wykonane" in capsys.readouterr().out
