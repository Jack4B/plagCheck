# 008 — Profil "full": parafrazy synonimiczne przez embeddingi (v1.1)

**Problem.** TF-IDF nie widzi synonimów („kierowca jechał samochodem” vs „szofer pędził pojazdem”).
Embeddingi zdaniowe wymagają torch (~1 GB RAM) — niemożliwe na CT8.

**Rozwiązanie.** Opcjonalny silnik `app/services/semantic.py`, aktywny gdy `SEMANTIC_MODEL` jest
ustawiony i biblioteki są dostępne (obraz Docker, `PROFILE=full`). Model
`paraphrase-multilingual-MiniLM-L12-v2` (trenowany na parafrazach, obsługuje polski, 384 wymiary).
Embeddingi zdań dokumentu liczone raz (`DocumentIndex.sentence_vectors`) i współdzielone przez
wszystkie źródła; zdania źródła — maks. 2000. Kandydaci: zdania nieobjęte dopasowaniem dosłownym
ani TF-IDF, ≥ 5 słów treściowych. Raport oznacza metodę (`semantic` / `tfidf`).

**Weryfikacja.** Logika sprawdzona testem z atrapą enkodera (pojęcia-synonimy → wspólny wymiar);
rozwiązanie zależności — `pip install --dry-run`. Prawdziwy model i obraz Dockera nie były
uruchamiane w środowisku budowy (brak dostępu do Hugging Face i demona Dockera).

**Strojenie.** Próg 0,8 to punkt wyjścia typowy dla tego modelu; przy fałszywych trafieniach
podnieść `SEMANTIC_THRESHOLD` do 0,85.
