# 011 — Aplikacja na Androida bez serwera (v1.4)

**Decyzja.** Rdzeń jest czystym Pythonem (od początku, dla CT8), więc w APK uruchamia go
Chaquopy, a interfejs to ten sam frontend w WebView. Serwer WSGI (`wsgiref` + `a2wsgi`)
nasłuchuje tylko na 127.0.0.1, na stałym porcie 47811 (localStorage WebView jest per adres
z portem). W trybie mobilnym wszystkie sprawdzenia mają jednego właściciela.

**Model parafraz bez PyTorcha.** `minilm_numpy.py`: forward pass BERT (MiniLM-L12, H=384)
i tokenizer Unigram (sentencepiece XLM-R: NFKC + zwijanie spacji + Metaspace + Viterbi).
Wagi: embeddingi int8 (kwantyzacja wierszowa), reszta fp16 → ~135 MB. GELU wymaga erf,
którego numpy nie ma — przybliżenie Abramowitza–Stegun (błąd < 1,5e-7).

**Weryfikacja (trzy poziomy):**
1. `tests/test_minilm_numpy.py` — losowy BertModel z `transformers` + tokenizer Unigram
   wytrenowany lokalnie: tokeny 1:1, cosinus > 0,999, niezależność od batchowania.
2. Lokalny przebieg `convert.py` → `verify.py` na modelu sentence-transformers z losowymi wagami
   (wyłapał 2 błędy: nowe API poolingu w ST 6.x i `normalizer: null`).
3. CI: `verify.py` na prawdziwym `paraphrase-multilingual-MiniLM-L12-v2` (HF zablokowany lokalnie).

**Pułapki Androida obsłużone w MainActivity:** wybór plików w WebView (onShowFileChooser),
brak pobierania `blob:` (zapis przez MediaStore do Pobranych), `window.print()` (PrintManager),
edge-to-edge w Android 15 (WindowInsets), linki zewnętrzne do przeglądarki, stały klucz podpisu.
