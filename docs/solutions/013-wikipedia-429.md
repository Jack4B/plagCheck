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

## v1.4.2 — szybkość na telefonie

Pomiar (praca 1 500 słów, 24 pobrane strony, preset maksymalny): główny koszt to **model
parafraz w numpy** (~31 zdań/s), nie tylko Wikipedia.
- GELU: przybliżenie tanh zamiast erf (Abramowitz–Stegun) — 5,6× szybsze, błąd < 5e-4;
  `erf` zajmował 41% czasu modelu.
- Model liczy tylko dla 12 najlepiej rokujących źródeł (kolejność wg trafień) i maks. 300 zdań
  na źródło, wybranych wg liczby wspólnych rdzeni. Nic nie jest odrzucane z góry — czysta
  parafraza synonimiczna w krótkim źródle nadal trafia do modelu (pierwsza wersja sita z progiem
  „≥ 2 wspólne rdzenie” blokowała właśnie takie przypadki — wyłapały to testy).
  Zdań przez model: ~5 800 → 3 041.
- Wikipedia: osobny budżet (WIKIPEDIA_MAX_QUERIES=40: 60% fraz dokładnych, 40% słów kluczowych)
  i adaptacyjne tempo AIMD: start 0,5 s, po 429 ×2 (maks. 4 s), po 20 udanych −20%.

**Odrzucone: darmowe publiczne proxy do obchodzenia limitu Wikipedii.** Łamie zasady Wikimedia
(limity służą ochronie ich serwerów, grozi blokada), otwarte proxy to często przejęte urządzenia
i punkty podsłuchu (przez nie szłyby frazy z pracy), większość jest martwa lub wolna — analiza
byłaby wolniejsza i mniej przewidywalna. Więcej źródeł legalnie: klucz Brave/Serper/SerpAPI.
