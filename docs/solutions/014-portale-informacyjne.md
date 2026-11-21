# 014 — Kopie z portali informacyjnych (Onet, WP, Interia…) (v1.4.8)

**Kontekst.** Typowy przypadek z uczelni: kilka osób przepisuje ten sam fragment artykułu
z portalu. JSA wyłapuje to od razu, bo ma indeks internetu. PlagCheck też musi.

**Warunek konieczny: wyszukiwarka z całego internetu.** Wikipedia i OpenAlex nie indeksują
portali. Bez klucza Serper (Google) albo Brave portale w ogóle nie są przeszukiwane.
Darmowych, legalnych API do Google/Bing praktycznie już nie ma (Bing Search API wyłączone
w 2025 r., Google Custom Search zamknięte dla nowych klientów). Serper daje 2 500 zapytań
na start; praca ~1 500 słów zużywa ok. 40, a powtórne sprawdzenie bierze wyniki z pamięci.

**Sonda (`scripts/probe_portals.py`, workflow „Sonda portali”).** Pobiera po dwa artykuły
z ~20 portali trzema nagłówkami User-Agent i mierzy ilość tekstu. Wyniki (listopad 2026):
- identyfikowalny User-Agent PlagCheck dostaje 200 tak samo jak przeglądarka; nagłówek
  przeglądarki dostawał *więcej* odmów (403 na rp.pl, forum bankier.pl) — zostaje nasz,
- sciaga.pl blokuje pobieranie (403) — tu pomaga snippet albo archiwum,
- Internet Archive odpowiada w 1–6 s i ma kopie części artykułów.

**Zmiany.**
1. `extract_page_text` dokłada treść z JSON-LD (`articleBody`) i `og:description`, jeśli nie ma
   jej w widocznym tekście (artykuł ładowany skryptem, podzielony reklamami).
2. Snippety z wyników wyszukiwania **zawsze** trafiają do porównania. Wcześniej używane były
   tylko, gdy strony nie udało się pobrać; gdy pobrana strona była pusta (zgoda na cookies,
   paywall), dowód z Google przepadał.
3. Strony z trafieniem frazy dokładnej, których nie udało się pobrać → kopia z Internet Archive
   (`fetch_archived_text`, raw `id_`), maks. `ARCHIVE_MAX_PAGES` (telefon: 8), łącznie 45 s.
   Źródło w raporcie: „kopia z Internet Archive” albo „tylko fragment z wyników wyszukiwania”.

**Czego nie robimy.** Podszywania się pod przeglądarkę, obchodzenia paywalli, darmowych
proxy (patrz 013) ani scrapowania wyników Google bez API.
