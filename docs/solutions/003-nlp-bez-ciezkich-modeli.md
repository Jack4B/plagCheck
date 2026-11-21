# 003 — Polskie NLP bez spaCy i sentence-transformers

**Problem.** Konspekt zakłada spaCy `pl_core_news_lg` (~500 MB) i Sentence-BERT (torch, >1 GB RAM).
Nie mieszczą się w limitach CT8.

**Rozwiązanie (lekkie odpowiedniki).**
| Konspekt | Implementacja | Koszt |
|----------|---------------|-------|
| lematyzacja spaCy | stemmer regułowy (końcówki fleksyjne) na tekście bez diakrytyków; opcjonalnie `simplemma` (`LEMMATIZER=simplemma`) | ~0 MB |
| dokładne dopasowanie | 5-gramy słowne (hash w pamięci) + mostkowanie ≤ 2 słów + min. 8 słów | O(n) |
| Levenshtein na frazach | mostkowanie luk w shinglach (podmiana pojedynczych słów) | O(n) |
| Sentence-BERT | TF-IDF na rdzeniach + cosinus, indeks odwrócony (bez macierzy N×M) | ~MB |
| FAISS | niepotrzebny — referencje porównywane strumieniowo, jedna na raz | stała pamięć |

**Ograniczenie.** Parafrazy ze zmianą słownictwa (synonimy) nie są wykrywane — wymagałyby
embeddingów. Miejsce rozszerzenia: `similarity.paraphrase_matches` (np. osobny serwis
z embeddingami poza CT8).
