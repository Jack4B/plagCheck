"""Enkoder zdań w czystym numpy — profil full bez PyTorcha (telefon / APK).

Implementuje forward pass modelu typu BERT (np. paraphrase-multilingual-MiniLM-L12-v2)
oraz tokenizer Unigram (sentencepiece, jak w XLM-R). Wagi i słownik pochodzą
z jednego pliku `plagcheck_model.npz` + `config.json`, które tworzy
`mobile/model/convert.py` (z modelu sentence-transformers). Zgodność z oryginałem
sprawdza `mobile/model/verify.py` w CI (cosinus z referencją ≥ 0,995).

Format npz:
  emb_q int8 [V,H] + emb_scale f16 [V]   — embeddingi słów, kwantyzacja wierszowa
  pos f16 [P,H], tok_type f16 [H], emb_ln_w/b
  l{i}.{q,k,v,o,i,o2}_w f16 (macierze transponowane: x @ W), *_b, ln1_w/b, ln2_w/b
  tok_pieces uint8 (UTF-8, rozdzielone \\x00), tok_scores f32
"""
from __future__ import annotations

import json
import math
import threading
import unicodedata
from pathlib import Path

import numpy as np

from .semantic import CONFIG_FILE, MODEL_FILE, is_model_dir  # noqa: F401 (re-eksport)

SPACE = "▁"  # ▁ — znacznik początku słowa w sentencepiece


# ----------------------------------------------------------------- tokenizer


class UnigramTokenizer:
    """Tokenizer Unigram (Viterbi po log-prawdopodobieństwach) z pre-tokenizacją Metaspace."""

    def __init__(self, pieces: list[str], scores: np.ndarray, unk_id: int, bos_id: int, eos_id: int, pad_id: int):
        self.vocab = {p: i for i, p in enumerate(pieces) if p}
        self.scores = scores.astype(np.float64)
        self.unk_id, self.bos_id, self.eos_id, self.pad_id = unk_id, bos_id, eos_id, pad_id
        self.max_piece = min(32, max(len(p) for p in pieces if p))
        self.unk_score = float(np.min(self.scores)) - 10.0
        self.specials = {i for i in (unk_id, bos_id, eos_id, pad_id)}

    @staticmethod
    def normalize(text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = "".join(" " if ch.isspace() else ch for ch in text if unicodedata.category(ch) != "Cc" or ch.isspace())
        return " ".join(text.split())

    def _viterbi(self, word: str) -> list[int]:
        n = len(word)
        best = [-math.inf] * (n + 1)
        back: list[tuple[int, int]] = [(0, -1)] * (n + 1)
        best[0] = 0.0
        vocab, scores = self.vocab, self.scores
        for end in range(1, n + 1):
            for start in range(max(0, end - self.max_piece), end):
                if best[start] == -math.inf:
                    continue
                pid = vocab.get(word[start:end])
                if pid is None or pid in self.specials:
                    continue
                cand = best[start] + scores[pid]
                if cand > best[end]:
                    best[end], back[end] = cand, (start, pid)
            if best[end] == -math.inf:  # znak spoza słownika → <unk>
                best[end], back[end] = best[end - 1] + self.unk_score, (end - 1, self.unk_id)
        ids, pos = [], n
        while pos > 0:
            start, pid = back[pos]
            ids.append(pid)
            pos = start
        ids.reverse()
        # kolejne <unk> łączymy w jeden (jak fuse_unk w tokenizers)
        fused: list[int] = []
        for i in ids:
            if i == self.unk_id and fused and fused[-1] == self.unk_id:
                continue
            fused.append(i)
        return fused

    def encode(self, text: str, max_len: int) -> list[int]:
        text = self.normalize(text)
        ids: list[int] = []
        for word in text.split(" "):
            if word:
                ids.extend(self._viterbi(SPACE + word))
            if len(ids) >= max_len - 2:
                break
        return [self.bos_id] + ids[: max_len - 2] + [self.eos_id]


# --------------------------------------------------------------------- model


def _erf(x: np.ndarray) -> np.ndarray:
    # Abramowitz & Stegun 7.1.26, błąd < 1.5e-7 — numpy nie ma erf, a GELU go wymaga
    sign = np.sign(x)
    x = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return sign * y


def _gelu(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (1.0 + _erf(x / math.sqrt(2.0)))


def _layer_norm(x: np.ndarray, w: np.ndarray, b: np.ndarray, eps: float) -> np.ndarray:
    mean = x.mean(-1, keepdims=True)
    var = ((x - mean) ** 2).mean(-1, keepdims=True)
    return (x - mean) / np.sqrt(var + eps) * w + b


class NumpyEncoder:
    """Interfejs zgodny z semantic.Encoder: encode(list[str]) -> ndarray (n, H), wiersze znormalizowane."""

    def __init__(self, model_dir: str | Path, batch_size: int = 16):
        model_dir = Path(model_dir)
        cfg = json.loads((model_dir / CONFIG_FILE).read_text(encoding="utf-8"))
        data = np.load(model_dir / MODEL_FILE)
        self.name = cfg.get("model_name", str(model_dir))
        self.hidden, self.layers, self.heads = cfg["hidden"], cfg["layers"], cfg["heads"]
        self.eps, self.offset, self.max_len = cfg["eps"], cfg["position_offset"], cfg["max_len"]
        self.batch_size = batch_size
        f32 = lambda k: data[k].astype(np.float32)  # noqa: E731
        self.emb_q = data["emb_q"]
        self.emb_scale = data["emb_scale"].astype(np.float32)
        self.pos, self.tok_type = f32("pos"), f32("tok_type")
        self.emb_ln = (f32("emb_ln_w"), f32("emb_ln_b"))
        self.W = [
            {name: f32(f"l{i}.{name}") for name in (
                "q_w", "q_b", "k_w", "k_b", "v_w", "v_b", "o_w", "o_b", "ln1_w", "ln1_b",
                "i_w", "i_b", "o2_w", "o2_b", "ln2_w", "ln2_b")}
            for i in range(self.layers)
        ]
        pieces = bytes(data["tok_pieces"]).decode("utf-8").split("\x00")
        self.tokenizer = UnigramTokenizer(
            pieces, data["tok_scores"], cfg["unk_id"], cfg["bos_id"], cfg["eos_id"], cfg["pad_id"]
        )
        self._lock = threading.Lock()

    def _embed(self, ids: np.ndarray) -> np.ndarray:
        return self.emb_q[ids].astype(np.float32) * self.emb_scale[ids][..., None]

    def forward(self, ids: np.ndarray, mask: np.ndarray) -> np.ndarray:
        B, L = ids.shape
        H, nh = self.hidden, self.heads
        dh = H // nh
        x = self._embed(ids) + self.pos[self.offset:self.offset + L][None] + self.tok_type[None, None]
        x = _layer_norm(x, *self.emb_ln, self.eps)
        bias = ((1.0 - mask[:, None, None, :]) * -1e9).astype(np.float32)
        for w in self.W:
            q = (x @ w["q_w"] + w["q_b"]).reshape(B, L, nh, dh).transpose(0, 2, 1, 3)
            k = (x @ w["k_w"] + w["k_b"]).reshape(B, L, nh, dh).transpose(0, 2, 3, 1)
            v = (x @ w["v_w"] + w["v_b"]).reshape(B, L, nh, dh).transpose(0, 2, 1, 3)
            att = (q @ k) / math.sqrt(dh) + bias
            att = np.exp(att - att.max(-1, keepdims=True))
            att /= att.sum(-1, keepdims=True)
            ctx = (att @ v).transpose(0, 2, 1, 3).reshape(B, L, H)
            x = _layer_norm(x + ctx @ w["o_w"] + w["o_b"], w["ln1_w"], w["ln1_b"], self.eps)
            h = _gelu(x @ w["i_w"] + w["i_b"])
            x = _layer_norm(x + h @ w["o2_w"] + w["o2_b"], w["ln2_w"], w["ln2_b"], self.eps)
        m = mask[..., None]
        pooled = (x * m).sum(1) / np.maximum(m.sum(1), 1e-9)
        return pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.hidden), dtype=np.float32)
        tokenized = [self.tokenizer.encode(t, self.max_len) for t in texts]
        order = sorted(range(len(texts)), key=lambda i: len(tokenized[i]))
        out = np.zeros((len(texts), self.hidden), dtype=np.float32)
        with self._lock:
            for s in range(0, len(order), self.batch_size):
                idx = order[s:s + self.batch_size]
                L = max(len(tokenized[i]) for i in idx)
                ids = np.full((len(idx), L), self.tokenizer.pad_id, dtype=np.int64)
                mask = np.zeros((len(idx), L), dtype=np.float32)
                for r, i in enumerate(idx):
                    ids[r, :len(tokenized[i])] = tokenized[i]
                    mask[r, :len(tokenized[i])] = 1.0
                out[idx] = self.forward(ids, mask)
        return out


# ------------------------------------------------------------------ zapis


def save_model(model_dir: str | Path, *, config: dict, state: dict, pieces: list[str], scores) -> None:
    """Zapisuje model w formacie PlagCheck (używane przez convert.py i testy).

    state: nazwy jak w BertModel (bez prefiksu), wagi Linear w układzie (out, in) — jak w PyTorch.
    """
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    f16 = lambda a: np.asarray(a, dtype=np.float32).astype(np.float16)  # noqa: E731
    emb = np.asarray(state["embeddings.word_embeddings.weight"], dtype=np.float32)
    scale = np.maximum(np.abs(emb).max(1), 1e-8) / 127.0
    out = {
        "emb_q": np.clip(np.round(emb / scale[:, None]), -127, 127).astype(np.int8),
        "emb_scale": scale.astype(np.float16),
        "pos": f16(state["embeddings.position_embeddings.weight"]),
        "tok_type": f16(state["embeddings.token_type_embeddings.weight"][0]),
        "emb_ln_w": f16(state["embeddings.LayerNorm.weight"]),
        "emb_ln_b": f16(state["embeddings.LayerNorm.bias"]),
        "tok_pieces": np.frombuffer("\x00".join(pieces).encode("utf-8"), dtype=np.uint8),
        "tok_scores": np.asarray(scores, dtype=np.float32),
    }
    names = {
        "q": "attention.self.query", "k": "attention.self.key", "v": "attention.self.value",
        "o": "attention.output.dense", "i": "intermediate.dense", "o2": "output.dense",
    }
    for i in range(config["layers"]):
        p = f"encoder.layer.{i}."
        for short, long in names.items():
            out[f"l{i}.{short}_w"] = f16(np.asarray(state[p + long + ".weight"]).T)
            out[f"l{i}.{short}_b"] = f16(state[p + long + ".bias"])
        out[f"l{i}.ln1_w"] = f16(state[p + "attention.output.LayerNorm.weight"])
        out[f"l{i}.ln1_b"] = f16(state[p + "attention.output.LayerNorm.bias"])
        out[f"l{i}.ln2_w"] = f16(state[p + "output.LayerNorm.weight"])
        out[f"l{i}.ln2_b"] = f16(state[p + "output.LayerNorm.bias"])
    np.savez(model_dir / MODEL_FILE, **out)
    (model_dir / CONFIG_FILE).write_text(json.dumps(config, indent=2), encoding="utf-8")
