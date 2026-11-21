# 004 — Detekcja AI bez modelu językowego

**Problem.** Perplexity wymaga modelu językowego, a klasyfikator (Random Forest / DistilBERT) —
oznaczonego korpusu PL „AI vs człowiek”, którego nie mamy.

**Rozwiązanie.** Ensemble jawnych sygnałów stylometrycznych (`app/services/ai_detector.py`),
każdy przeskalowany do −1…+1, ważona suma + sigmoid. Wynik dla całości = średnia sygnału
dokumentu i ważonej średniej fragmentów (~250 słów). Raport pokazuje 3–5 najsilniejszych sygnałów
z opisem i frazy-markery. Wynik przycięty do 3–97 %, pewność zależna od długości, < 120 słów → brak oceny.

**Dalej.** Gdy powstanie korpus: wyliczyć te same cechy (`compute_signals(...).raw`) i wytrenować
regresję logistyczną/GBM — wagi `WEIGHTS` da się wtedy zastąpić wyuczonymi.
