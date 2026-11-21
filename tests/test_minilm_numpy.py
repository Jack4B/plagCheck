"""Zgodność enkodera numpy (telefon) z referencją: transformers (model) i tokenizers (Unigram).

Wymaga torch + transformers + tokenizers (pomijany, gdy ich nie ma — np. profil CT8).
Prawdziwy model paraphrase-multilingual-MiniLM sprawdza CI: mobile/model/verify.py.
"""
import json

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
tokenizers = pytest.importorskip("tokenizers")

from app.services.minilm_numpy import NumpyEncoder, UnigramTokenizer, save_model  # noqa: E402
from samples import AI_LIKE, HUMAN_LIKE, SOURCE_ARTICLE, STUDENT_WITH_COPY  # noqa: E402

CORPUS = [s for t in (SOURCE_ARTICLE, STUDENT_WITH_COPY, AI_LIKE, HUMAN_LIKE) for s in t.replace("\n", " ").split(". ") if s]
TEST_SENTENCES = [
    "Mikołaj Kopernik studiował w Krakowie i Padwie.",
    "Sztuczna inteligencja odgrywa kluczową rolę w edukacji naukowej.",
    "Wczoraj poszliśmy z Kaśką na koncert, było super!",
    "Teoria heliocentryczna zakładała, że Słońce znajduje się w centrum.",
    "Zażółć gęślą jaźń — przykład z polskimi znakami.",
]


@pytest.fixture(scope="module")
def trained_tokenizer():
    from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, trainers

    tok = Tokenizer(models.Unigram())
    from tokenizers import Regex

    # jak w XLM-R: NFKC + zwijanie wielokrotnych spacji
    tok.normalizer = normalizers.Sequence([normalizers.NFKC(), normalizers.Replace(Regex(" {2,}"), " "), normalizers.Strip()])
    tok.pre_tokenizer = pre_tokenizers.Metaspace()
    trainer = trainers.UnigramTrainer(
        vocab_size=600, special_tokens=["<s>", "<pad>", "</s>", "<unk>"], unk_token="<unk>", shrinking_factor=0.75
    )
    tok.train_from_iterator(CORPUS * 3, trainer)
    vocab = json.loads(tok.to_str())["model"]["vocab"]
    return tok, [p for p, _ in vocab], np.array([s for _, s in vocab], dtype=np.float32)


def test_unigram_tokenizer_matches_huggingface(trained_tokenizer):
    tok, pieces, scores = trained_tokenizer
    ours = UnigramTokenizer(pieces, scores, unk_id=3, bos_id=0, eos_id=2, pad_id=1)
    for text in CORPUS[:40] + TEST_SENTENCES:
        expected = tok.encode(text).ids
        assert ours.encode(text, max_len=512)[1:-1] == expected, text


def test_numpy_forward_matches_transformers(tmp_path, trained_tokenizer):
    _, pieces, scores = trained_tokenizer
    torch.manual_seed(0)
    cfg = transformers.BertConfig(
        vocab_size=len(pieces), hidden_size=64, num_hidden_layers=2, num_attention_heads=4,
        intermediate_size=128, max_position_embeddings=64, pad_token_id=1, hidden_act="gelu",
    )
    model = transformers.BertModel(cfg, add_pooling_layer=False).eval()
    state = {k: v.detach().numpy() for k, v in model.state_dict().items()}
    save_model(tmp_path, config={
        "model_name": "test-bert", "hidden": 64, "layers": 2, "heads": 4, "eps": cfg.layer_norm_eps,
        "position_offset": 0, "max_len": 64, "unk_id": 3, "bos_id": 0, "eos_id": 2, "pad_id": 1,
    }, state=state, pieces=pieces, scores=scores)
    enc = NumpyEncoder(tmp_path, batch_size=2)

    ours = enc.encode(TEST_SENTENCES)
    # referencja: ten sam tokenizer, PyTorch, mean pooling z maską, normalizacja
    ids = [enc.tokenizer.encode(t, 64) for t in TEST_SENTENCES]
    L = max(map(len, ids))
    input_ids = torch.tensor([i + [1] * (L - len(i)) for i in ids])
    mask = torch.tensor([[1] * len(i) + [0] * (L - len(i)) for i in ids])
    with torch.no_grad():
        hidden = model(input_ids=input_ids, attention_mask=mask).last_hidden_state
    pooled = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdim=True)
    ref = torch.nn.functional.normalize(pooled, dim=1).numpy()

    cos = (ours * ref).sum(1)
    assert ours.shape == ref.shape
    assert cos.min() > 0.999, cos  # różnice tylko z kwantyzacji int8/fp16 wag
    # kolejność w batchu i dopełnienie nie mogą zmieniać wyników
    single = np.vstack([enc.encode([t]) for t in TEST_SENTENCES])
    assert np.allclose(single, ours, atol=1e-5)
