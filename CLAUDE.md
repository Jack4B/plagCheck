# CLAUDE.md

## Projekt

**Nazwa:** PlagCheck — Plagiarism Detector (wstępne wykrywanie plagiatu i treści AI)
**Cel:** Narzędzie pomocnicze do samokontroli dokumentów studenckich pod kątem podobieństw do treści publicznych, lokalnej bazy oraz cech tekstu generowanego przez AI.
**Nie jest** zamiennikiem JSA/Turnitin ani komercyjnych detektorów AI.
**Hosting:** **Oracle Cloud Always Free** (Ampere A1, Docker, profil full) — główny od v1.2.
Alternatywa: CT8.pl (MyDevil, FreeBSD, Passenger, profil lite).
**Konspekt:** `docs/konspekt.md`. Skill cyklu życia: `.claude/skills/plagiarism-detector-lifecycle/`.

## Stan (v1.4.7)

Etapy 1–6 konspektu zrealizowane. **Koncepcja v1.1** (`docs/KONCEPCJA.md`): dwa profile jednej bazy kodu —
**lite** (CT8, Passenger, czysty Python) i **full** (Docker/VPS, + parafrazy synonimiczne przez embeddingi);
źródła przeszukiwane równolegle (web API + Wikipedia + OpenAlex); baza lokalna z indeksem winnowing.
**v1.2:** Oracle Cloud jako główny hosting — `deploy/oracle/setup.sh` (Docker + Caddy/HTTPS + zapora + kopie),
paczka `plagcheck-oracle-<wersja>.tar.gz`, `deploy/oracle/deploy.sh IP`.
**v1.4:** aplikacja na Androida (APK) — cały rdzeń w telefonie (Chaquopy + WebView, `app/mobile.py`),
model parafraz w czystym numpy (`app/services/minilm_numpy.py`), zapytania słowami kluczowymi,
ustawienia w aplikacji (`/api/settings`, tylko MOBILE_MODE). Budowa APK: `.github/workflows/android.yml`.
Skill pisania po polsku: `.claude/skills/polski-jak-czlowiek/` — używaj go do wszystkich tekstów PL.
**Aktualizacje APK (Obtainium):** każda zmiana dla telefonu wymaga podbicia `__version__` w `app/__init__.py` —
workflow publikuje wtedy GitHub Release `v<wersja>` z APK; bez podbicia Obtainium nie zobaczy aktualizacji.

## Stos technologiczny (faktyczny)

- **Backend:** Python 3.11+ / FastAPI 0.115 + **pydantic v1** (czysty Python — v2 wymaga kompilacji Rusta na FreeBSD)
- **Uruchamianie na CT8:** Passenger (`passenger_wsgi.py`, ASGI→WSGI przez `a2wsgi`) + cron `python -m app.worker run`
- **NLP:** własne, lekkie — tokenizacja, składanie diakrytyków, stemmer regułowy PL, TF-IDF; opcjonalnie `simplemma`
- **Wyszukiwanie:** Brave / Serper / SerpAPI + Wikipedia + OpenAlex — równolegle (urllib)
- **Baza lokalna:** odciski winnowing (MOSS) w tabeli `ref_fingerprints` zamiast Elasticsearch/FAISS
- **Profil full:** sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`), torch CPU — `requirements-full.txt`, `Dockerfile`
- **Pliki:** zipfile + xml.etree (DOCX/ODT), pypdf (PDF)
- **Baza:** SQLAlchemy Core — SQLite (domyślnie) lub MySQL (PyMySQL)
- **Frontend:** vanilla JS (ES modules) + CSS, bez kroku budowania, CSP `script-src 'self'`
- Wszystkie zależności produkcyjne to koła `py3-none-any` (lista: `requirements-lock.txt`)

## Oracle Cloud (główny hosting)

- Ampere A1 (ARM64): darmowo do 4 OCPU / 24 GB RAM łącznie; zalecane 2 OCPU / 12 GB, Ubuntu 24.04.
- Porty 80/443 trzeba otworzyć **w konsoli** (Security List VCN) — skrypt otwiera tylko zaporę w systemie.
- Darmowe konto: Oracle może odebrać bezczynną instancję → zalecany upgrade do Pay As You Go (Always Free dalej 0 zł).
- Obraz musi działać na ARM64 i x86_64 (python:3.12-slim, torch CPU, caddy:2 — wszystkie multi-arch).

## Ograniczenia CT8 (profil lite)

- Darmowy plan: ~512 MB RAM, 3 GB dysk, limit procesów.
- Brak stałego ASGI → Passenger (WSGI) + a2wsgi; procesy mogą być ubijane → zadania wznawiane (cron + samonaprawa przy odpytywaniu statusu).
- Zmierzone: dokument ~16 tys. słów + 20 plików bazy: <1 s CPU, ~60 MB RSS.
- spaCy `pl_core_news_lg`, torch, FAISS — poza budżetem; patrz `docs/solutions/`.

## Komendy

```bash
# lokalnie
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest

# paczki + wdrożenie
./scripts/build_package.sh oracle                  # dist/plagcheck-oracle-<wersja>.tar.gz (Docker, full)
./scripts/build_package.sh ct8                     # dist/plagcheck-ct8-<wersja>.tar.gz (lite)
SSH_KEY=~/.ssh/oracle.key ./deploy/oracle/deploy.sh IP [--domain D]   # Oracle: scp + ssh setup.sh
# albo GitHub Actions "Deploy Oracle" (sekrety: ORACLE_HOST, ORACLE_SSH_KEY, PLAGCHECK_ACCESS_KEY)
# — sesja Claude Code nie ma wyjścia na port 22; wdrożenie wyzwala przez actions_run_trigger i czyta logi
./deploy/ct8/deploy.sh LOGIN sN.ct8.pl [DOMENA]    # CT8: scp + ssh install.sh

# na serwerze Oracle
cd /opt/plagcheck && sudo docker compose logs -f plagcheck
sudo docker compose --profile https up -d          # po zmianie .env
sudo docker compose exec plagcheck python -m app.worker backup /data/kopia.sqlite3

# na serwerze CT8
devil www restart DOMENA
tail -50 ~/domains/DOMENA/logs/error.log
cd ~/domains/DOMENA/public_python && ~/.virtualenvs/plagcheck/bin/python -m app.worker run
~/.virtualenvs/plagcheck/bin/python -m app.worker import-refs KATALOG   # baza wspólna
~/.virtualenvs/plagcheck/bin/python -m app.worker reindex               # odciski bazy (migracja z 1.0)
```

## Struktura

```
app/main.py            API + serwowanie frontendu, nagłówki bezpieczeństwa
app/pipeline.py        orkiestracja analizy
app/jobs.py, worker.py zadania w tle (wątek / cron), CLI
app/db.py              tabele: jobs, reference_docs, search_cache
app/services/          extractor, preprocessor, textutils, phrases, web_search,
                       fingerprints, similarity, semantic, ai_detector, report
app/static/            frontend: landing.html/.css/.js (strona główna "/"), index.html + app.js (aplikacja "/app"), img/ (zrzuty, jasne i -dark)
mobile/android/        projekt Androida (Kotlin MainActivity, Chaquopy); app/ i model kopiowane w CI
mobile/model/          convert.py, verify.py — model MiniLM → numpy + weryfikacja z oryginałem
deploy/oracle/         setup.sh (na serwerze), deploy.sh (lokalnie), Caddyfile
deploy/ct8/            install.sh (na serwerze), deploy.sh (lokalnie)
Dockerfile, docker-compose.yml   profil full/lite + Caddy (profil compose "https")
scripts/build_package.sh
tests/                 pytest + tests/e2e/e2e.mjs (Playwright)
```

## Źródła danych — ważne

**ORPPD** posiada REST API **wyłącznie do depozytu prac przez uczelnie** (Bearer token + Institution header).
Nie istnieje publiczne API do wyszukiwania treści prac. Aplikacja **nie może** i **nie powinna** próbować scrapować ORPPD.

## Zasady

- Dokumenty użytkowników są tymczasowe: tekst kasowany po analizie, raport wygasa (`REPORT_TTL_HOURS`).
- Baza lokalna tylko za wyraźną zgodą (checkbox + walidacja w API).
- Obsługa języka polskiego jest obowiązkowa (diakrytyki, skróty, stemming).
- Nowe zależności rdzenia: tylko czysto-pythonowe (sprawdź `pip download --platform any --only-binary=:all:`).
  Ciężkie biblioteki wyłącznie w `requirements-full.txt`, importowane leniwie, z degradacją do lite.
- Małe, testowalne zmiany; testy muszą przechodzić na pydantic v1 i v2.
- Frontend: bez `innerHTML` z danymi i bez stylów inline w HTML (CSP).
- Po większym etapie aktualizuj ten plik + `docs/solutions/` + `docs/CONCEPTS.md`.

## Pamięć

1. Ten plik (CLAUDE.md)
2. `docs/solutions/` — baza rozwiązanych problemów
3. `docs/CONCEPTS.md` — słownik pojęć
4. `docs/KONCEPCJA.md` — decyzje architektoniczne v1.1
5. `docs/ANDROID.md` — APK; `PRZEWODNIK.md` (dla użytkownika, ze zrzutami w `docs/img/`), `docs/DEPLOY_ORACLE.md` (główne), `docs/DEPLOY_DOCKER.md`, `docs/DEPLOY_CT8.md` — wdrożenie

## Disclaimer

Aplikacja służy wyłącznie do samokontroli. Nie może być używana do omijania systemów uczelnianych.

---
*Ostatnia aktualizacja: 21 listopada 2026 — v1.2.0: Oracle Cloud Always Free jako główny hosting.*
