# CLAUDE.md

## Projekt

**Nazwa:** PlagCheck — Plagiarism Detector (wstępne wykrywanie plagiatu i treści AI)
**Cel:** Narzędzie pomocnicze do samokontroli dokumentów studenckich pod kątem podobieństw do treści publicznych, lokalnej bazy oraz cech tekstu generowanego przez AI.
**Nie jest** zamiennikiem JSA/Turnitin ani komercyjnych detektorów AI.
**Hosting:** CT8.pl (MyDevil, FreeBSD) — self-hosted, Passenger.
**Konspekt:** `docs/konspekt.md`. Skill cyklu życia: `.claude/skills/plagiarism-detector-lifecycle/`.

## Stan (v1.0.0)

Etapy 1–6 konspektu zrealizowane w wersji „lekkiej” (MVP pod CT8):
ekstrakcja, frazy + linki Google, wyszukiwarka API z cache, baza lokalna, parafrazy (TF-IDF),
detekcja AI (stylometria + reguły), UI z podświetleniami, historia, eksport HTML/druk PDF,
wykluczanie cytatów/bibliografii, paczka instalacyjna CT8.

## Stos technologiczny (faktyczny)

- **Backend:** Python 3.11+ / FastAPI 0.115 + **pydantic v1** (czysty Python — v2 wymaga kompilacji Rusta na FreeBSD)
- **Uruchamianie na CT8:** Passenger (`passenger_wsgi.py`, ASGI→WSGI przez `a2wsgi`) + cron `python -m app.worker run`
- **NLP:** własne, lekkie — tokenizacja, składanie diakrytyków, stemmer regułowy PL, TF-IDF; opcjonalnie `simplemma`
- **Wyszukiwanie:** Brave / Serper / SerpAPI / Wikipedia (urllib, bez dodatkowych zależności)
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
./scripts/build_package.sh                         # dist/plagcheck-ct8-<wersja>.tar.gz
./deploy/ct8/deploy.sh LOGIN sN.ct8.pl [DOMENA]    # scp + ssh install.sh

# na serwerze CT8
devil www restart DOMENA
tail -50 ~/domains/DOMENA/logs/error.log
cd ~/domains/DOMENA/public_python && ~/.virtualenvs/plagcheck/bin/python -m app.worker run
~/.virtualenvs/plagcheck/bin/python -m app.worker import-refs KATALOG   # baza wspólna
```

## Struktura

```
app/main.py            API + serwowanie frontendu, nagłówki bezpieczeństwa
app/pipeline.py        orkiestracja analizy
app/jobs.py, worker.py zadania w tle (wątek / cron), CLI
app/db.py              tabele: jobs, reference_docs, search_cache
app/services/          extractor, preprocessor, textutils, phrases, web_search,
                       similarity, ai_detector, report
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
- Nowe zależności: tylko czysto-pythonowe (sprawdź `pip download --platform any --only-binary=:all:`).
- Małe, testowalne zmiany; testy muszą przechodzić na pydantic v1 i v2.
- Frontend: bez `innerHTML` z danymi i bez stylów inline w HTML (CSP).
- Po większym etapie aktualizuj ten plik + `docs/solutions/` + `docs/CONCEPTS.md`.

## Pamięć

1. Ten plik (CLAUDE.md)
2. `docs/solutions/` — baza rozwiązanych problemów
3. `docs/CONCEPTS.md` — słownik pojęć
4. `docs/DEPLOY_CT8.md` — wdrożenie

## Disclaimer

Aplikacja służy wyłącznie do samokontroli. Nie może być używana do omijania systemów uczelnianych.

---
*Ostatnia aktualizacja: 21 listopada 2026 — v1.0.0: pełne MVP + paczka CT8.*
