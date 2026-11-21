from app.services.ai_detector import detect_ai
from app.services.preprocessor import preprocess
from samples import AI_LIKE, HUMAN_LIKE


def test_ai_like_text_scores_higher_than_human_text():
    ai = detect_ai(preprocess(AI_LIKE))
    human = detect_ai(preprocess(HUMAN_LIKE))
    assert ai["percent"] >= 65, ai
    assert human["percent"] <= 35, human
    assert ai["label"] == "podwyższone"
    assert human["label"] == "niskie"


def test_reasons_and_markers_explain_result():
    ai = detect_ai(preprocess(AI_LIKE))
    features = {r["feature"] for r in ai["reasons"]}
    assert "markers" in features
    assert {"ponadto", "co więcej", "podsumowując"} <= set(ai["markers"])
    assert ai["chunks"] and all(0 <= c["percent"] <= 100 for c in ai["chunks"])
    assert all(c["start"] < c["end"] for c in ai["chunks"])


def test_short_text_gives_no_verdict():
    result = detect_ai(preprocess("Krótki tekst. Za mało słów do oceny."))
    assert result["percent"] is None
    assert result["label"] == "za mało tekstu"
