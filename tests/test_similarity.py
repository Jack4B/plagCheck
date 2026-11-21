from app.services.preprocessor import preprocess
from app.services.similarity import DocumentIndex, compare
from samples import SOURCE_ARTICLE, STUDENT_WITH_COPY, UNRELATED


def matched_text(doc, token_ids):
    return " ".join(doc.tokens[i].text for i in sorted(token_ids))


def test_exact_copy_detected():
    doc = preprocess(STUDENT_WITH_COPY)
    result = compare(DocumentIndex(doc), SOURCE_ARTICLE)
    text = matched_text(doc, result.exact_tokens)
    assert "Norymberdze w roku 1543" in text
    assert "przewrót kopernikański" in text
    # własny fragment nie może zostać oznaczony
    assert "spacery" not in text


def test_single_word_substitution_is_bridged():
    doc = preprocess(STUDENT_WITH_COPY)
    result = compare(DocumentIndex(doc), SOURCE_ARTICLE)
    text = matched_text(doc, result.exact_tokens)
    # "kształcił się" zamiast "studiował" — luka wypełniona jako część dopasowania
    assert "Kopernik kształcił się w Krakowie Bolonii Padwie i Ferrarze" in text


def test_reordered_paraphrase_detected():
    doc = preprocess(STUDENT_WITH_COPY)
    result = compare(DocumentIndex(doc), SOURCE_ARTICLE, paraphrase_threshold=0.5)
    para_sentences = [doc.sentence_text(doc.sentences[i]) for i in result.paraphrase_sentences]
    assert any(s.startswith("Według teorii heliocentrycznej") for s in para_sentences)
    score, excerpt = next(iter(result.paraphrase_sentences.values()))
    assert 0.5 <= score <= 1.0 and "Słońce" in excerpt


def test_diacritics_insensitive():
    no_diacritics = "Jego dzielo O obrotach sfer niebieskich zostalo wydane w Norymberdze w roku 1543 i zapoczatkowalo przewrot kopernikanski w nauce."
    doc = preprocess(no_diacritics)
    assert len(compare(DocumentIndex(doc), SOURCE_ARTICLE).exact_tokens) >= 15


def test_unrelated_text_has_no_matches():
    doc = preprocess(UNRELATED)
    assert compare(DocumentIndex(doc), SOURCE_ARTICLE).is_empty


def test_short_common_phrase_not_flagged():
    # 6 wspólnych słów to za mało (min_run=8) — typowe zbitki nie są plagiatem
    doc = preprocess("Badania zakładały, że to Słońce, a nie Ziemia, było ważne dla autora.")
    assert compare(DocumentIndex(doc), SOURCE_ARTICLE).exact_tokens == set()
