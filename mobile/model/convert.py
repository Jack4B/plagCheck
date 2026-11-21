"""Konwersja modelu sentence-transformers do formatu PlagCheck (numpy, dla telefonu).

Uruchamiane w CI (wymaga torch + sentence-transformers + dostępu do Hugging Face):
    python mobile/model/convert.py OUT_DIR [--model NAZWA]

Wynik: OUT_DIR/plagcheck_model.npz + OUT_DIR/config.json (~135 MB: embeddingi int8, reszta fp16).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DEFAULT = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--model", default=DEFAULT)
    args = ap.parse_args()

    from sentence_transformers import SentenceTransformer

    from app.services.minilm_numpy import save_model

    st = SentenceTransformer(args.model, device="cpu")
    transformer, pooling = st[0], st[1]
    mode = getattr(pooling, "pooling_mode", None)  # sentence-transformers ≥ 6
    if not (mode == "mean" or getattr(pooling, "pooling_mode_mean_tokens", False)):
        raise SystemExit("Obsługiwany jest tylko mean pooling.")
    hf, tok, cfg = transformer.auto_model, transformer.tokenizer, transformer.auto_model.config
    if cfg.hidden_act not in ("gelu",):
        raise SystemExit(f"Nieobsługiwana aktywacja: {cfg.hidden_act}")

    prefix = hf.base_model_prefix + "."
    state = {k[len(prefix):] if k.startswith(prefix) else k: v.detach().cpu().numpy() for k, v in hf.state_dict().items()}
    tj = json.loads(tok.backend_tokenizer.to_str())
    model = tj["model"]
    if model["type"] != "Unigram":
        raise SystemExit(f"Obsługiwany jest tylko tokenizer Unigram, a nie {model['type']}")
    pieces = [p for p, _ in model["vocab"]]
    scores = [s for _, s in model["vocab"]]
    # BERT: pozycje od 0; RoBERTa/XLM-R: od pad_token_id + 1
    offset = (cfg.pad_token_id + 1) if cfg.model_type in ("roberta", "xlm-roberta") else 0
    config = {
        "model_name": args.model.split("/")[-1],
        "hidden": cfg.hidden_size, "layers": cfg.num_hidden_layers, "heads": cfg.num_attention_heads,
        "eps": cfg.layer_norm_eps, "position_offset": offset, "max_len": int(st.max_seq_length),
        "unk_id": model.get("unk_id", tok.unk_token_id), "bos_id": tok.cls_token_id,
        "eos_id": tok.sep_token_id, "pad_id": tok.pad_token_id,
        "source": {"model_type": cfg.model_type, "normalizer": (tj.get("normalizer") or {}).get("type"),
                   "pre_tokenizer": (tj.get("pre_tokenizer") or {}).get("type")},
    }
    save_model(args.out_dir, config=config, state=state, pieces=pieces, scores=scores)
    size = sum(f.stat().st_size for f in Path(args.out_dir).iterdir()) / 1e6
    print(json.dumps(config, indent=2, ensure_ascii=False))
    print(f"Zapisano {args.out_dir} ({size:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
