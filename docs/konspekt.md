# Konspekt inżynieryjny: Aplikacja do wstępnego wykrywania plagiatu i treści AI

## 1. Cel i zakres

Aplikacja umożliwia użytkownikowi (studentowi) samodzielne sprawdzenie dokumentu pod kątem:
- podobieństw do treści dostępnych publicznie w internecie,
- podobieństw do lokalnej bazy referencyjnej,
- cech charakterystycznych dla treści generowanych przez modele językowe (AI).

**Cel nie jest** pełnym odwzorowaniem JSA/Turnitin ani komercyjnych detektorów AI (brak dostępu do ORPPD i prywatnych baz prac studenckich). To narzędzie pomocnicze do wykrywania jawnych zapożyczeń, bliskich parafraz oraz prawdopodobnych śladów generowania przez AI.

## 2. Wymagania

### Funkcjonalne

- Wgrywanie plików: DOCX, PDF, TXT, ODT
- Ekstrakcja czystego tekstu (z obsługą polskiego)
- Podział na zdania, akapity i frazy n-gramowe
- Wyszukiwanie dokładnych i przybliżonych dopasowań w internecie
- Porównanie z lokalną bazą (pliki użytkownika / wybrane źródła)
- Wykrywanie cech stylometrycznych i statystycznych typowych dla AI
- Raport: procent podobieństwa, podświetlone fragmenty, linki do źródeł, wskaźnik prawdopodobieństwa AI
- Możliwość wykluczenia cytatów i bibliografii
- Historia sprawdzeń + eksport raportu (PDF/HTML)

### Niefunkcjonalne

- Czas analizy dokumentu 20–40 stron: < 2–5 min (zależnie od trybu)
- Obsługa języka polskiego (lematyzacja, znaki diakrytyczne)
- Prywatność – dokumenty nie są trwale przechowywane bez zgody
- Interfejs webowy (React/Vue) + API (FastAPI / Django)
- Możliwość działania na hostingu z ograniczonymi zasobami (np. CT8)

## 3. Architektura (wysoki poziom)

```
[Frontend] ←→ [API Gateway] ←→ [Backend Services]
                              ├── Text Processing Service
                              ├── Similarity Engine
                              ├── Web Search Service
                              ├── Local Index Service
                              ├── AI Detection Service
                              └── Report Generator
                                      ↓
                              [Baza danych + Cache + Vector DB]
```

## 4. Główne moduły

| Moduł                    | Odpowiedzialność                              | Technologie przykładowe          |
|--------------------------|-----------------------------------------------|----------------------------------|
| **Extractor**            | Wyciąganie tekstu z plików                    | python-docx, PyMuPDF, unstructured |
| **Preprocessor**         | Czyszczenie, tokenizacja, lematyzacja         | spaCy (pl), NLTK, regex          |
| **Phrase Generator**     | Tworzenie fraz 8–20 słów + zdań               | własne + nltk.tokenize           |
| **Web Searcher**         | Wyszukiwanie fraz w sieci                     | SerpAPI / Brave Search API / Serper |
| **Local Indexer**        | Indeksowanie własnych plików + embeddingi     | Elasticsearch / Meilisearch + FAISS / Qdrant |
| **Similarity Engine**    | Obliczanie podobieństwa                       | TF-IDF, cosine, Sentence-BERT, n-gramy |
| **AI Detection Engine**  | Wykrywanie cech tekstu generowanego przez AI  | stylometria, perplexity, burstiness, klasyfikatory |
| **Report Generator**     | Generowanie raportu z podświetleniami         | Jinja2 + WeasyPrint / frontend   |
| **Auth & Storage**       | Użytkownicy, limity, tymczasowe pliki         | PostgreSQL / MySQL + Redis + S3-compatible |

## 5. Algorytmy wykrywania podobieństwa (plagiat)

1. **Dokładne dopasowanie** (najważniejsze)
   - Frazy 10–15 słów → wyszukiwanie w cudzysłowie (`"fraza"`)
   - Przesuwające się okna (sliding window) o różnych długościach

2. **Podobieństwo leksykalne**
   - TF-IDF + cosine similarity
   - Jaccard / Dice na n-gramach znakowych i słownych
   - Wykrywanie zmian pojedynczych słów (Levenshtein na frazach)

3. **Podobieństwo semantyczne** (zaawansowane)
   - Embeddingi zdaniowe (Sentence-BERT / multilingual-e5 / modele polskie z Hugging Face)
   - Próg podobieństwa (np. cosine > 0.85)

4. **Wykrywanie parafraz**
   - Porównanie lematów + struktury zależnościowej (spaCy)
   - Opcjonalnie: lokalny model paraphrase detection

5. **Filtrowanie fałszywych trafień**
   - Wykluczanie cytatów w cudzysłowie
   - Pomijanie bibliografii, spisów treści, aktów prawnych
   - Blacklista typowych fraz (definicje, hasła, powtarzalne zwroty akademickie)

## 6. Algorytmy wykrywania treści AI

1. **Cechy stylometryczne i statystyczne**
   - Burstiness (zmienność długości zdań)
   - Perplexity (jeśli dostępny model językowy)
   - Rozkład długości zdań i akapitów
   - Powtarzalność struktur składniowych
   - Użycie rzadkich słów vs. typowych fraz

2. **Cechy leksykalne**
   - Nadreprezentacja typowych fraz AI („w dzisiejszych czasach”, „warto zauważyć”, „należy podkreślić”)
   - Niski poziom błędów językowych i nieregularności
   - Jednorodność stylu na całej długości tekstu

3. **Klasyfikacja**
   - Lekki klasyfikator (Random Forest / Gradient Boosting) na cechach stylometrycznych
   - Opcjonalnie: fine-tuning małego modelu (np. DistilBERT) na polskim korpusie AI vs. human
   - Ensemble kilku sygnałów (stylometria + embeddingi + reguły)

4. **Wskaźnik końcowy**
   - Prawdopodobieństwo AI (0–100%) z uzasadnieniem (które fragmenty i cechy wpłynęły na wynik)
   - Podział na fragmenty (nie cały dokument na raz)

## 7. Źródła danych

| Źródło              | Dostępność          | Uwagi                              |
|---------------------|---------------------|------------------------------------|
| Internet (publiczny)| Tak (przez API)     | Główne źródło                      |
| Wikipedia + Open Access | Tak             | arXiv, PubMed, CORE                |
| Lokalna baza użytkownika | Tak            | Własne pliki, notatki              |
| ORPPD / prace studenckie | **Nie**       | API tylko do depozytu przez uczelnie |
| Pełne bazy naukowe (Scopus itp.) | Częściowo | Wymaga płatnych API            |

## 8. Proponowany stos technologiczny

- **Backend**: Python 3.11+ (FastAPI)
- **NLP**: spaCy (`pl_core_news_lg`), sentence-transformers, scikit-learn
- **Wyszukiwanie**: SerpAPI lub Brave Search API (lepsze limity niż Google)
- **Baza wektorowa**: FAISS (lokalnie, lekkie) lub Qdrant
- **Frontend**: Next.js / React + Tailwind
- **Infrastruktura**: Docker + Redis (cache) + PostgreSQL / MySQL
- **Kolejki**: Celery + Redis (asynchroniczne sprawdzanie)
- **AI Detection**: cechy stylometryczne + opcjonalny lekki klasyfikator

## 9. Główne wyzwania i ograniczenia

- **Limity API wyszukiwarek** – konieczność cache’owania i ograniczenia liczby zapytań
- **Język polski** – słabsze modele embeddingowe niż dla angielskiego
- **Parafrazy zaawansowane** – bardzo trudne do wykrycia bez dużych modeli
- **Fałszywe pozytywy** – definicje, cytaty, akty prawne, powtarzalne zwroty akademickie
- **Detekcja AI** – modele językowe szybko się zmieniają; detektory mają wysoką stopę błędów
- **Prywatność i RODO** – dokumenty studenckie nie mogą być trwale przechowywane
- **Koszty** – płatne API wyszukiwania przy większej skali
- **Zasoby** – na hostingu typu CT8 preferuj lekkie rozwiązania (FAISS, lokalne cechy)

## 10. Etapy realizacji (MVP → pełna wersja)

| Etap | Zakres                                      | Czas szacunkowy |
|------|---------------------------------------------|-----------------|
| 1    | Ekstrakcja tekstu + generowanie fraz + linki Google | 1–2 tyg.     |
| 2    | Integracja z wyszukiwarką API + podstawowy raport | 2–3 tyg.    |
| 3    | Podobieństwo lokalne (TF-IDF + embeddingi)  | 2–3 tyg.       |
| 4    | Podstawowa detekcja AI (stylometria + reguły) | 1–2 tyg.     |
| 5    | Interfejs webowy + podświetlanie fragmentów | 3–4 tyg.       |
| 6    | Optymalizacja, cache, wykrywanie cytatów, eksport | 2 tyg.     |

## 11. Aspekty prawne i etyczne

- Aplikacja służy wyłącznie do **samokontroli** własnych prac.
- Nie może być używana do omijania systemów uczelnianych.
- Dokumenty użytkowników powinny być usuwane po analizie (lub przechowywane zaszyfrowane z limitem czasu).
- Warto dodać wyraźny disclaimer: „To nie jest zamiennik JSA ani komercyjnych detektorów AI. Wyniki mają charakter pomocniczy i mogą zawierać fałszywe trafienia.”

---

*Dokument przygotowany jako konspekt inżynieryjny – punkt wyjścia do dalszego projektowania i implementacji.  
Ostatnia aktualizacja: 21 listopada 2026 — dodano moduł wykrywania treści AI i doprecyzowano ograniczenia ORPPD.*
