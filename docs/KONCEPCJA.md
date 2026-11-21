# Koncepcja v1.1–1.2 — co zmieniono względem konspektu i dlaczego

> **v1.2 (decyzja):** głównym hostingiem jest **Oracle Cloud Always Free** (Ampere A1, profil full,
> Docker + Caddy). CT8 pozostaje wspieraną alternatywą z profilem lite. Wdrożenie: `docs/DEPLOY_ORACLE.md`.

Konspekt (`docs/konspekt.md`) zakładał jeden stos: FastAPI + spaCy + Sentence-BERT + FAISS +
Elasticsearch + Celery/Redis + Next.js — i jednocześnie hosting na darmowym CT8 (FreeBSD, ~512 MB RAM).
Te dwa założenia się wykluczają. Wersja 1.1 rozwiązuje konflikt **dwoma profilami jednej bazy kodu**.

## 1. Dwa profile zamiast jednego stosu

| | **lite** (CT8, domyślny) | **full** (Docker na VPS) |
|---|---|---|
| Uruchomienie | Passenger + `a2wsgi` | `docker compose up -d` (uvicorn) |
| RAM | ~60–100 MB | ~1–1,5 GB |
| Zależności | 11 kół czysto-pythonowych | + torch CPU, sentence-transformers |
| Dopasowania dosłowne / bliskie | ✔ | ✔ |
| Parafrazy z tym samym słownictwem (TF-IDF) | ✔ | ✔ |
| **Parafrazy synonimiczne** (embeddingi) | — | ✔ `paraphrase-multilingual-MiniLM-L12-v2` |
| Detekcja AI (heurystyki) | ✔ | ✔ |

Profil wybiera się sam: silnik semantyczny włącza się, gdy ustawiony jest `SEMANTIC_MODEL`
**i** biblioteki są zainstalowane; w przeciwnym razie aplikacja działa jako lite. `/api/health`
zwraca `"profile": "lite" | "full"`, a UI pokazuje, czy parafrazy synonimiczne są aktywne.

**Hosting (decyzja v1.2).** Oracle Cloud *Always Free* — ARM, do 24 GB RAM, 0 zł — uruchamia profil
full bez kompromisów, ma stały proces (brak problemu z ubijaniem wątków przez Passengera) i pozwala
na 4 równoległe analizy. CT8 zostaje dla osób bez konta Oracle (profil lite).

## 2. Wiele źródeł naraz zamiast jednego dostawcy

v1.0 używała jednego dostawcy (płatne API **albo** Wikipedia). v1.1 przeszukuje równolegle
(osobny wątek i limit zapytań/s na źródło):

- wyszukiwarkę internetową z kluczem (Brave / Serper / SerpAPI) — jeśli skonfigurowana,
- **Wikipedię** (bez klucza),
- **OpenAlex** — otwarty katalog ~250 mln publikacji naukowych (bez klucza): tytuł + abstrakt,
  a dla publikacji w otwartym dostępie — pełny tekst. To właściwe źródło dla prac dyplomowych,
  którego nie ma w zwykłej wyszukiwarce.

Źródła w raporcie mają typ: `internet`, `Wikipedia`, `publikacja naukowa`, `baza lokalna`.

## 3. Indeks odcisków (winnowing) zamiast Elasticsearch/FAISS dla bazy lokalnej

v1.0 porównywała każdy dokument z całą bazą lokalną — przy setkach prac to minuty.
v1.1 przy dodawaniu pliku zapisuje jego **odciski winnowing** (algorytm MOSS) w tabeli
`ref_fingerprints` (zwykły indeks B-tree w SQLite/MySQL). Analiza najpierw wybiera kandydatów
po wspólnych odciskach, a dopiero potem porównuje ich dokładnie.

Zmierzone (CT8-profil, SQLite): baza 300 dokumentów / 1,5 mln słów —
**3,0 s** (indeks) vs **16,2 s** (pełny skan), 58 MB RAM.

Mała baza (≤ `LOCAL_FULLSCAN_WORDS`, domyślnie 300 tys. słów) nadal jest skanowana w całości,
bo tylko wtedy wykrywamy parafrazy bez żadnego wspólnego 8-wyrazowego fragmentu.

## 4. Co celowo zostało bez zmian

| Element | Dlaczego zostaje |
|---|---|
| FastAPI + pydantic v1 | działa na FreeBSD bez kompilacji; testy przechodzą też na v2 |
| SQLite / MySQL zamiast PostgreSQL + Redis | zero dodatkowych usług; cache i kolejka w tej samej bazie |
| Wątek + cron zamiast Celery | Celery wymaga stałego brokera i procesu — niedostępne na CT8 |
| Frontend bez builda zamiast Next.js | 4 widoki; brak Node w pipeline wdrożenia; CSP bez `unsafe-inline` |
| Detekcja AI heurystyczna | patrz niżej |

## 5. Czego świadomie nie dodano

- **Perplexity z polskiego modelu językowego (np. GPT-2) w detekcji AI.** Wymaga kalibracji
  progów na korpusie „AI vs człowiek” po polsku, którego nie mamy. Niekalibrowany sygnał
  pogorszyłby wyniki, a detektory oparte na perplexity i tak mają wysoki odsetek fałszywych
  alarmów (szczególnie dla tekstów akademickich i nie-natywnych autorów). Architektura to
  umożliwia: nowy sygnał w `ai_detector.compute_signals` + waga w `WEIGHTS`.
- **Wysyłanie tekstu do zewnętrznego LLM (np. jako sędzia parafraz/AI).** Sprzeczne z zasadą
  prywatności (tekst pracy opuściłby serwer); LLM-y nie są wiarygodnymi detektorami AI.
- **ORPPD** — brak publicznego API wyszukiwania (bez zmian).
