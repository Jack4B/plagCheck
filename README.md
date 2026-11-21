# PlagCheck — wstępne wykrywanie plagiatu i treści AI

Narzędzie do **samokontroli** prac (DOCX / PDF / ODT / TXT) przed oddaniem:

- **podobieństwo do internetu i publikacji** — frazy kontrolne (10–15 słów) wyszukiwane **równolegle** w Brave /
  Serper (Google) / SerpAPI (z kluczem), polskiej Wikipedii i **OpenAlex** (publikacje naukowe) — dwa ostatnie bez klucza,
- **podobieństwo do bazy lokalnej** — Twoje pliki + wspólna baza admina, z **indeksem odcisków (winnowing)**
  — szybkie także przy setkach prac,
- **parafrazy** — mostkowanie podmienionych słów + TF-IDF (przestawiony szyk); w profilu **full** także
  **parafrazy synonimiczne** (embeddingi zdaniowe),
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

> **Instalacja krok po kroku (Oracle Cloud, ze zrzutami ekranu): [PRZEWODNIK.md](PRZEWODNIK.md)**

## Dwa profile (szczegóły: [docs/KONCEPCJA.md](docs/KONCEPCJA.md))

| | **full** — Oracle Cloud (zalecane) | **lite** — CT8 |
|---|---|---|
| RAM | ~1–1,5 GB | ~60–100 MB |
| Parafrazy synonimiczne | ✔ | — |
| HTTPS | Caddy (automatycznie) | panel CT8 |
| Wdrożenie | [docs/DEPLOY_ORACLE.md](docs/DEPLOY_ORACLE.md) | [docs/DEPLOY_CT8.md](docs/DEPLOY_CT8.md) |

## Wdrożenie na Oracle Cloud Always Free (zalecane)

Najpierw w konsoli Oracle: maszyna Ampere A1 (Ubuntu 24.04) i reguły Ingress 80/443 —
krok po kroku w **[docs/DEPLOY_ORACLE.md](docs/DEPLOY_ORACLE.md)**. Potem jedno polecenie:

```bash
SSH_KEY=~/.ssh/oracle.key ./deploy/oracle/deploy.sh IP_SERWERA [--domain plagiat.mojadomena.pl]
```

albo z gotowej paczki (`./scripts/build_package.sh oracle`):

```bash
scp -i ~/.ssh/oracle.key plagcheck-oracle-1.2.1.tar.gz ubuntu@IP: && ssh -t -i ~/.ssh/oracle.key ubuntu@IP 'tar -xzf plagcheck-oracle-1.2.1.tar.gz && sudo bash plagcheck-oracle-1.2.1/setup.sh'
```

## Wdrożenie na CT8 (lite)

```bash
./deploy/ct8/deploy.sh LOGIN sN.ct8.pl [DOMENA]     # buduje paczkę, wysyła scp, instaluje przez ssh
```

albo ręcznie z gotowej paczki (`./scripts/build_package.sh ct8` → `dist/plagcheck-ct8-1.2.1.tar.gz`):

```bash
scp dist/plagcheck-ct8-1.2.1.tar.gz LOGIN@sN.ct8.pl: && ssh -t LOGIN@sN.ct8.pl 'tar -xzf plagcheck-ct8-1.2.1.tar.gz && bash plagcheck-ct8-1.2.1/install.sh LOGIN.ct8.pl'
```

Szczegóły, MySQL, HTTPS, diagnostyka: **[docs/DEPLOY_CT8.md](docs/DEPLOY_CT8.md)**.

## Inny VPS z Dockerem

Ten sam `setup.sh` działa na każdym Ubuntu/Debian/Oracle Linux — patrz [docs/DEPLOY_DOCKER.md](docs/DEPLOY_DOCKER.md).

## Architektura

```
przeglądarka (app/static: vanilla JS, bez kroku budowania)
      │  /api/*  (X-Owner-Token = anonimowy identyfikator przeglądarki, opcjonalnie X-Access-Key)
      ▼
FastAPI (app/main.py) ── Passenger na CT8: passenger_wsgi.py (a2wsgi: ASGI → WSGI)
      │ zadanie w tle (wątek + cron `python -m app.worker run` jako zabezpieczenie)
      ▼
pipeline.py ── extractor → preprocessor → phrases → web_search ∥ (web API, Wikipedia, OpenAlex) ─┐
                                        baza lokalna: indeks winnowing → kandydaci ──────────────┼→ similarity → report
                                        ai_detector ─────────────────────────────────────────────┘
                                                    similarity: shingles + TF-IDF [+ embeddingi w profilu full]
      ▼
SQLAlchemy Core: SQLite (domyślnie) / MySQL — jobs, reference_docs, search_cache
```

| Moduł | Plik | Uwagi |
|-------|------|-------|
| Extractor | `app/services/extractor.py` | DOCX/ODT przez zipfile+XML (bez lxml), PDF przez pypdf |
| Preprocessor | `app/services/preprocessor.py` | zdania (skróty PL), cytaty „…”, bibliografia, spis treści, akty prawne |
| Narzędzia PL | `app/services/textutils.py` | składanie diakrytyków, lekki stemmer, stop-lista; opcjonalnie simplemma |
| Phrase Generator | `app/services/phrases.py` | najlepsze okno w zdaniu, równomierny rozkład budżetu zapytań |
| Web Searcher | `app/services/web_search.py` | Brave/Serper/SerpAPI + Wikipedia + OpenAlex równolegle, cache w DB, ochrona SSRF |
| Local Indexer | `app/services/fingerprints.py` | winnowing (MOSS), tabela `ref_fingerprints` |
| Similarity Engine | `app/services/similarity.py` | shingles 5-gramów + mostkowanie luk; TF-IDF z indeksem odwróconym |
| Semantic Engine | `app/services/semantic.py` | profil full: sentence-transformers (opcjonalny) |
| AI Detection | `app/services/ai_detector.py` | heurystyki stylometryczne + wyjaśnienia |
| Report Generator | `app/services/report.py` | JSON dla UI + samodzielny HTML |

Dlaczego bez spaCy / sentence-transformers / FAISS / Next.js — patrz [docs/solutions/](docs/solutions/).

## Testy

```bash
pytest                                  # 64 testy: moduły, API, Passenger/WSGI, worker CLI, indeks, źródła
# E2E w przeglądarce (Playwright, Node):
uvicorn app.main:app --port 8765 &
NODE_PATH=$(npm root -g) E2E_TEXT="$(cat jakis_tekst.txt)" node tests/e2e/e2e.mjs
```

## Prywatność

- przesłany plik nie jest trwale zapisywany (duże pliki trafiają najwyżej do pliku tymczasowego na czas żądania);
  wyciągnięty tekst jest w bazie tylko na czas analizy i jest kasowany po jej zakończeniu,
- raport (zawiera fragmenty tekstu) wygasa po `REPORT_TTL_HOURS` (domyślnie 72 h) i można go usunąć ręcznie,
- pliki bazy lokalnej są przechowywane tylko po zaznaczeniu zgody i można je usunąć w każdej chwili,
- do wyszukiwarek trafiają wyłącznie wybrane frazy (domyślnie ≤ 25 na dokument i źródło);
  model embeddingów (profil full) działa lokalnie — tekst nie opuszcza serwera.
