# CLAUDE.md

## Projekt

**Nazwa:** PlagCheck — Plagiarism Detector (wstępne wykrywanie plagiatu i treści AI)
**Cel:** Narzędzie pomocnicze do samokontroli dokumentów studenckich pod kątem podobieństw do treści publicznych, lokalnej bazy oraz cech tekstu generowanego przez AI.
**Nie jest** zamiennikiem JSA/Turnitin ani komercyjnych detektorów AI.
**Hosting:** CT8.pl (MyDevil, FreeBSD) — self-hosted, Passenger.
**Konspekt:** `docs/konspekt.md`. Skill cyklu życia: `.claude/skills/plagiarism-detector-lifecycle/`.

## Stan (v1.1.0)

Etapy 1–6 konspektu zrealizowane. **Koncepcja v1.1** (`docs/KONCEPCJA.md`): dwa profile jednej bazy kodu —
**lite** (CT8, Passenger, czysty Python) i **full** (Docker/VPS, + parafrazy synonimiczne przez embeddingi);
źródła przeszukiwane równolegle (web API + Wikipedia + OpenAlex); baza lokalna z indeksem winnowing.

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

## Ograniczenia CT8

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

# paczka + wdrożenie
./scripts/build_package.sh                         # dist/plagcheck-ct8-<wersja>.tar.gz (lite)
./deploy/ct8/deploy.sh LOGIN sN.ct8.pl [DOMENA]    # scp + ssh install.sh
docker compose up -d --build                       # profil full na VPS

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
app/static/            frontend
deploy/ct8/            install.sh (na serwerze), deploy.sh (lokalnie)
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
5. `docs/DEPLOY_CT8.md`, `docs/DEPLOY_DOCKER.md` — wdrożenie

## Disclaimer

Aplikacja służy wyłącznie do samokontroli. Nie może być używana do omijania systemów uczelnianych.

---
*Ostatnia aktualizacja: 21 listopada 2026 — v1.1.0: profile lite/full, wiele źródeł, indeks winnowing.*
