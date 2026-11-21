# PlagCheck — wstępne wykrywanie plagiatu i treści AI

Narzędzie do **samokontroli** prac (DOCX / PDF / ODT / TXT) przed oddaniem:

- **podobieństwo do internetu** — frazy kontrolne (10–15 słów) wyszukiwane w Brave / Serper (Google) / SerpAPI
  lub w polskiej Wikipedii (bez klucza), pobranie stron źródłowych i dokładne porównanie,
- **podobieństwo do bazy lokalnej** — Twoje pliki referencyjne (+ wspólna baza admina),
- **parafrazy** — mostkowanie podmienionych słów + TF-IDF/cosinus na rdzeniach słów (zdania z przestawionym szykiem),
- **detekcja AI** — burstiness, frazy-markery („warto zauważyć”, „odgrywa kluczową rolę”…), łączniki,
  brak nieregularności, wyliczenia trójkowe — z uzasadnieniem i podziałem na fragmenty,
- **raport** — procent podobieństwa, podświetlenia w tekście, linki do źródeł, wykryte parafrazy,
  wskaźnik AI, frazy kontrolne z linkami do Google, eksport HTML / druk do PDF,
- wykluczanie **cytatów**, **bibliografii**, **spisu treści** i (opcjonalnie) **aktów prawnych**,
- **historia** sprawdzeń (anonimowo, per przeglądarka) i automatyczne usuwanie raportów.

> **To nie jest zamiennik JSA ani komercyjnych detektorów AI.** Wyniki mają charakter pomocniczy i mogą
> zawierać fałszywe trafienia. ORPPD nie jest przeszukiwane — jego API służy wyłącznie do depozytu prac
> przez uczelnie.

## Szybki start (lokalnie)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # http://127.0.0.1:8000
pytest                                 # testy jednostkowe + integracyjne
```

Konfiguracja: skopiuj `.env.example` → `.env` (klucze API wyszukiwarek, limity, retencja).

## Wdrożenie na CT8

```bash
./deploy/ct8/deploy.sh LOGIN sN.ct8.pl [DOMENA]     # buduje paczkę, wysyła scp, instaluje przez ssh
```

albo ręcznie z gotowej paczki (`./scripts/build_package.sh` → `dist/plagcheck-ct8-1.0.0.tar.gz`):

```bash
scp dist/plagcheck-ct8-1.0.0.tar.gz LOGIN@sN.ct8.pl: && ssh -t LOGIN@sN.ct8.pl 'tar -xzf plagcheck-ct8-1.0.0.tar.gz && bash plagcheck-ct8-1.0.0/install.sh LOGIN.ct8.pl'
```

Szczegóły, MySQL, HTTPS, diagnostyka: **[docs/DEPLOY_CT8.md](docs/DEPLOY_CT8.md)**.

## Architektura

```
przeglądarka (app/static: vanilla JS, bez kroku budowania)
      │  /api/*  (X-Owner-Token = anonimowy identyfikator przeglądarki, opcjonalnie X-Access-Key)
      ▼
FastAPI (app/main.py) ── Passenger na CT8: passenger_wsgi.py (a2wsgi: ASGI → WSGI)
      │ zadanie w tle (wątek + cron `python -m app.worker run` jako zabezpieczenie)
      ▼
pipeline.py ── extractor → preprocessor → phrases → web_search ─┐
                                        local refs (db) ────────┼→ similarity → report
                                        ai_detector ────────────┘
      ▼
SQLAlchemy Core: SQLite (domyślnie) / MySQL — jobs, reference_docs, search_cache
```

| Moduł | Plik | Uwagi |
|-------|------|-------|
| Extractor | `app/services/extractor.py` | DOCX/ODT przez zipfile+XML (bez lxml), PDF przez pypdf |
| Preprocessor | `app/services/preprocessor.py` | zdania (skróty PL), cytaty „…”, bibliografia, spis treści, akty prawne |
| Narzędzia PL | `app/services/textutils.py` | składanie diakrytyków, lekki stemmer, stop-lista; opcjonalnie simplemma |
| Phrase Generator | `app/services/phrases.py` | najlepsze okno w zdaniu, równomierny rozkład budżetu zapytań |
| Web Searcher | `app/services/web_search.py` | Brave/Serper/SerpAPI/Wikipedia, cache w DB, ochrona SSRF |
| Similarity Engine | `app/services/similarity.py` | shingles 5-gramów + mostkowanie luk; TF-IDF z indeksem odwróconym |
| AI Detection | `app/services/ai_detector.py` | heurystyki stylometryczne + wyjaśnienia |
| Report Generator | `app/services/report.py` | JSON dla UI + samodzielny HTML |

Dlaczego bez spaCy / sentence-transformers / FAISS / Next.js — patrz [docs/solutions/](docs/solutions/).

## Testy

```bash
pytest                                  # 55 testów: moduły, API, Passenger/WSGI, worker CLI
# E2E w przeglądarce (Playwright, Node):
uvicorn app.main:app --port 8765 &
NODE_PATH=$(npm root -g) E2E_TEXT="$(cat jakis_tekst.txt)" node tests/e2e/e2e.mjs
```

## Prywatność

- przesłany plik nie jest trwale zapisywany (duże pliki trafiają najwyżej do pliku tymczasowego na czas żądania);
  wyciągnięty tekst jest w bazie tylko na czas analizy i jest kasowany po jej zakończeniu,
- raport (zawiera fragmenty tekstu) wygasa po `REPORT_TTL_HOURS` (domyślnie 72 h) i można go usunąć ręcznie,
- pliki bazy lokalnej są przechowywane tylko po zaznaczeniu zgody i można je usunąć w każdej chwili,
- do wyszukiwarki trafiają wyłącznie wybrane frazy (domyślnie ≤ 25 na dokument).
