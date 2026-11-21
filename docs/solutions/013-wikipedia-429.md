# 013 — Wikipedia: HTTP 429 (za dużo zapytań) w aplikacji na telefon (v1.4.1)

**Objaw.** Na telefonie z presetem „Maksymalna skuteczność” (80 fraz + 60 zapytań słowami
kluczowymi) raport: „Źródło »wikipedia« zwraca błędy (HTTP 429) — pominięto je”.

**Przyczyna.** ~140 zapytań do API Wikipedii co 0,1 s + równoległe pobieranie artykułów
(4 wątki) bez limitu, brak ponawiania po 429, ogólnikowy User-Agent (Wikimedia ogranicza takie
klienty mocniej).

**Rozwiązanie (`web_search.py`).**
- `_HostThrottle` — odstęp per host, wspólny dla wszystkich wątków: *.wikipedia.org 1 s,
  OpenAlex 0,15 s, Brave 1,1 s (obejmuje też pobieranie stron).
- `_get_json` ponawia 429/503 do 3 razy: `Retry-After` albo 2/4/8 s (maks. 30 s).
- User-Agent `PlagCheck/<wersja> (...) python-urllib`; e-mail kontaktowy dopisywany tylko,
  gdy użytkownik sam go poda w ustawieniach (OPENALEX_MAILTO / CONTACT_EMAIL).

**Koszt.** Preset maksymalny trwa dłużej (Wikipedia ~1 zapytanie/s → ok. 2–3 min na samo
wyszukiwanie w Wikipedii); źródła są przeszukiwane równolegle, więc OpenAlex nie czeka.
