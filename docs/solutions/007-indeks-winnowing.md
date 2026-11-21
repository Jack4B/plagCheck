# 007 — Indeks odcisków winnowing dla bazy lokalnej (v1.1)

**Problem.** Porównanie z każdym plikiem bazy przy każdej analizie: O(rozmiar bazy). Przy 300
pracach (1,5 mln słów) — 16 s na CT8 i rośnie liniowo.

**Rozwiązanie.** Algorytm MOSS: hasze 5-gramów (stabilne, blake2b → int64), w każdym oknie 4
haszy zachowujemy minimum (~40% haszy). Gwarancja: wspólne dopasowanie ≥ 4 + 5 − 1 = 8 słów
(dokładnie nasz `min_run`) zawsze daje wspólny odcisk. Odciski w tabeli `ref_fingerprints`
(indeks B-tree) — bez Elasticsearch/FAISS. Zapytanie `hash IN (...)` partiami po 500.

**Kompromis.** W trybie indeksu nie znajdziemy pliku, z którym tekst dzieli *tylko* parafrazy.
Dlatego mała baza (≤ `LOCAL_FULLSCAN_WORDS`) nadal jest skanowana w całości; raport ostrzega,
gdy użyto indeksu. Migracja ze starszej wersji: `python -m app.worker reindex` (robi to też cron).

**Wynik.** 3,0 s zamiast 16,2 s przy 300 dokumentach; indeksowanie 300 dokumentów: 14 s (jednorazowo).
