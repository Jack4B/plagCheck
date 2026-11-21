from app.services.phrases import generate_phrases
from app.services.preprocessor import PreprocessOptions, preprocess, split_sentences
from app.services.textutils import fold, stem
from samples import SOURCE_ARTICLE, STUDENT_WITH_COPY


def sentences(text):
    return [text[a:b] for a, b in split_sentences(text, 0, len(text))]


def test_fold_and_stem():
    assert fold("Zażółć GĘŚLĄ") == "zazolc gesla"
    assert stem("analizą") == stem("analiza") == stem("analizy")
    assert stem("plagiatów") == stem("plagiat")


def test_sentence_split_respects_abbreviations():
    text = "Badanie prowadził prof. Nowak, m.in. w Krakowie. Wyniki opisano np. w tab. 3. Kolejne zdanie J. Kowalskiego."
    result = sentences(text)
    assert result == [
        "Badanie prowadził prof. Nowak, m.in. w Krakowie.",
        "Wyniki opisano np. w tab. 3.",
        "Kolejne zdanie J. Kowalskiego.",
    ]


def test_quotes_are_excluded():
    doc = preprocess("Autor pisze: „To jest cytat z książki”. A to już mój tekst.")
    excluded = [t.text for t in doc.tokens if t.excluded == "quote"]
    assert excluded == ["To", "jest", "cytat", "z", "książki"]
    assert doc.tokens[-1].excluded is None


def test_quotes_can_be_included():
    doc = preprocess("Autor pisze: „To jest cytat”.", PreprocessOptions(exclude_quotes=False))
    assert all(t.excluded is None for t in doc.tokens)


def test_bibliography_excluded_only_last_heading():
    text = (
        "Spis treści\n\n1. Wstęp ..... 3\n\nBibliografia ..... 20\n\n"
        + "To jest właściwa treść pracy, w której opisuję wyniki badań i wnioski z nich płynące. " * 3
        + "\n\nRozdział drugi zawiera więcej treści merytorycznej i analiz źródeł, które omawiam.\n\n"
        "Bibliografia\n\nNowak A., Tytuł książki, Kraków 2001.\n\nKowalski B., Inna pozycja, Warszawa 2005."
    )
    doc = preprocess(text)
    reasons = {t.text: t.excluded for t in doc.tokens}
    assert reasons["Nowak"] == "bibliography"
    assert reasons["Kowalski"] == "bibliography"
    assert reasons["właściwa"] is None
    assert reasons["Wstęp"] == "toc"


def test_legal_exclusion_optional():
    text = "Zgodnie z art. 5 ustawy (Dz.U. 2020 poz. 1) przepis obowiązuje. Moje zdanie jest inne."
    assert preprocess(text).eligible_token_count == len(preprocess(text).tokens)
    doc = preprocess(text, PreprocessOptions(exclude_legal=True))
    assert doc.tokens[0].excluded == "legal"
    assert doc.tokens[-1].excluded is None


def test_phrases_length_and_coverage():
    doc = preprocess(SOURCE_ARTICLE + "\n\n" + STUDENT_WITH_COPY)
    phrases = generate_phrases(doc, limit=4, min_words=10, max_words=15)
    assert 1 <= len(phrases) <= 4
    for p in phrases:
        assert 10 <= len(p.text.split()) <= 15
        assert p.query.startswith('"') and p.google_url.startswith("https://www.google.com/search?q=")
    # frazy rozłożone po dokumencie, nie tylko z początku
    assert phrases[-1].sentence > phrases[0].sentence


def test_phrases_skip_excluded_text():
    doc = preprocess("„" + "słowo " * 20 + "”")
    assert generate_phrases(doc, limit=5) == []


def test_bibliography_section_ends_at_appendix():
    body = "To jest właściwa treść pracy, w której opisuję wyniki badań i wnioski z nich płynące. " * 4
    text = body + "\n\nBibliografia\n\nNowak A., Tytuł, Kraków 2001.\n\nZałącznik 1. Ankieta\n\nPytanie pierwsze dotyczy nawyków."
    reasons = {t.text: t.excluded for t in preprocess(text).tokens}
    assert reasons["Nowak"] == "bibliography"
    assert reasons["Pytanie"] is None
