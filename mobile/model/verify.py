"""Weryfikacja: enkoder numpy (telefon) vs oryginalny sentence-transformers.

    python mobile/model/verify.py MODEL_DIR [--model NAZWA]

Kończy się błędem, jeśli:
  * tokenizacja różni się od oryginału w więcej niż 2% zdań testowych,
  * minimalny cosinus embeddingów < 0,99 albo średni < 0,995,
  * parafrazy nie są bliżej siebie niż zdania niepowiązane.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

SENTENCES = [
    "Mikołaj Kopernik był astronomem, matematykiem i ekonomistą.",
    "Kopernik kształcił się w Krakowie, Bolonii, Padwie i Ferrarze.",
    "Według teorii heliocentrycznej w centrum wszechświata znajduje się Słońce.",
    "Teoria heliocentryczna zakładała, że to Słońce, a nie Ziemia, jest w centrum.",
    "Fotosynteza zachodzi w chloroplastach roślin zielonych.",
    "W dzisiejszych czasach sztuczna inteligencja odgrywa kluczową rolę.",
    "Wczoraj poszliśmy z Kaśką na koncert, było super!",
    "Zażółć gęślą jaźń — test polskich znaków: ąćęłńóśźż ĄĆĘŁŃÓŚŹŻ.",
    "Art. 5 ust. 2 ustawy z dnia 4 lutego 1994 r. (Dz.U. 2022 poz. 2509).",
    "The heliocentric model places the Sun at the centre of the Solar System.",
    "Kierowca jechał samochodem szybko po pustej drodze nocą.",
    "Szofer pędził pojazdem po opustoszałej szosie wieczorem.",
    "W rezultacie organizacje muszą wypracować kompleksowe strategie zarządzania.",
    "Bez tego zjawiska życie na Ziemi w obecnej formie nie byłoby możliwe.",
    "  Wiele   spacji\toraz\ttabulatory  ",
    "Cudzysłów „polski” i \"angielski\", nawiasy (test) oraz liczby 1543, 3.14.",
]
PARAPHRASES = [(2, 3), (10, 11)]
UNRELATED = [(2, 6), (10, 4)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("--model", default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    args = ap.parse_args()

    import numpy as np
    from sentence_transformers import SentenceTransformer

    from app.services.minilm_numpy import NumpyEncoder
    from samples import AI_LIKE, HUMAN_LIKE, SOURCE_ARTICLE, STUDENT_WITH_COPY

    corpus = SENTENCES + [s for t in (SOURCE_ARTICLE, STUDENT_WITH_COPY, AI_LIKE, HUMAN_LIKE)
                          for s in t.replace("\n", " ").split(". ") if s.strip()]
    st = SentenceTransformer(args.model, device="cpu")
    enc = NumpyEncoder(args.model_dir)

    mismatches = 0
    for text in corpus:
        ref_ids = st.tokenizer(text, truncation=True, max_length=enc.max_len)["input_ids"]
        ours = enc.tokenizer.encode(text, enc.max_len)
        if ref_ids != ours:
            mismatches += 1
            print(f"[tokenizacja] różnica: {text[:60]!r}\n  ref={ref_ids[:24]}\n  my ={ours[:24]}")
    rate = mismatches / len(corpus)
    print(f"Tokenizacja: {len(corpus) - mismatches}/{len(corpus)} zgodnych ({100 * (1 - rate):.1f}%)")

    ref = st.encode(corpus, normalize_embeddings=True, convert_to_numpy=True)
    ours = enc.encode(corpus)
    cos = (ref * ours).sum(1)
    print(f"Cosinus z oryginałem: min {cos.min():.5f}, średnio {cos.mean():.5f}")

    sims = ours @ ours.T
    for a, b in PARAPHRASES:
        print(f"parafraza {a}-{b}: {sims[a, b]:.3f}")
    for a, b in UNRELATED:
        print(f"niezwiązane {a}-{b}: {sims[a, b]:.3f}")

    ok = True
    if rate > 0.02:
        print("BŁĄD: zbyt wiele różnic w tokenizacji"); ok = False
    if cos.min() < 0.99 or cos.mean() < 0.995:
        print("BŁĄD: embeddingi odbiegają od oryginału"); ok = False
    if min(sims[a, b] for a, b in PARAPHRASES) <= max(sims[a, b] for a, b in UNRELATED):
        print("BŁĄD: parafrazy nie są bliżej niż zdania niezwiązane"); ok = False
    print("WERYFIKACJA OK" if ok else "WERYFIKACJA NIEUDANA")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
