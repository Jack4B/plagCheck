# 006 — Wiele źródeł wyszukiwania równolegle (v1.1)

**Problem.** v1.0 używała jednego dostawcy: płatne API *albo* Wikipedia. Bez klucza pokrycie było
słabe, a z kluczem traciliśmy darmowe źródła. Prace dyplomowe często korzystają z publikacji
naukowych, których zwykła wyszukiwarka nie indeksuje w treści.

**Rozwiązanie.** `build_providers()` zwraca listę: wyszukiwarka z kluczem (opcjonalnie) +
Wikipedia + OpenAlex. `pipeline._search_all` uruchamia każde źródło w osobnym wątku — każde ma
własny limit zapytań/s (`min_interval`) i własny cache. Wyniki łączone po URL; strona pobierana
przez dostawcę, który ją znalazł (Wikipedia → API `extracts`, OpenAlex → pełny tekst OA albo
abstrakt jako zapas). Źródło zwracające same błędy jest pomijane z ostrzeżeniem w raporcie.

**Prywatność.** `OPENALEX_MAILTO` jest opcjonalny i domyślnie pusty — aplikacja nie wysyła
żadnych danych identyfikujących.
