"""Build the Glassbox Tiny Thinker: prajjwal1/bert-tiny -> ONNX -> int8 (~4-5 MB).

Run once:  python setup_thinker.py
Produces models/thinker.onnx + tokenizer files next to this script.
The artifact ships with Glassbox; runtime needs only onnxruntime + tokenizers.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_ID = "prajjwal1/bert-tiny"
OUT_DIR = HERE / "models"
ONNX_PATH = OUT_DIR / "thinker.onnx"
INT8_PATH = OUT_DIR / "thinker.int8.onnx"

import torch  # noqa: E402
from huggingface_hub import hf_hub_download  # noqa: E402
from tokenizers import BertWordPieceTokenizer  # noqa: E402
from transformers import BertModel  # noqa: E402
import onnx  # noqa: E402
from onnxruntime.quantization import quantize_dynamic, QuantType  # noqa: E402

OUT_DIR.mkdir(parents=True, exist_ok=True)
vocab_file = hf_hub_download(MODEL_ID, "vocab.txt")
tok_wp = BertWordPieceTokenizer(vocab_file, lowercase=True, strip_accents=False,
                                unk_token="[UNK]", cls_token="[CLS]", sep_token="[SEP]", pad_token="[PAD]")
tok_wp.enable_truncation(max_length=128)
tok_wp.enable_padding(pad_id=0, pad_token="[PAD]")
tok_wp.save_model(str(OUT_DIR), "thinker")
import json as _json  # noqa: E402
from transformers import BertConfig  # noqa: E402
_cfg = _json.load(open(hf_hub_download(MODEL_ID, "config.json")))
_cfg["model_type"] = "bert"
model = BertModel.from_pretrained(MODEL_ID, config=BertConfig(**_cfg))
model.eval()


class _Tok:
    """Thin shim so the export path matches BertWordPieceTokenizer's output."""
    def __init__(self, wp):
        self.wp = wp
    def __call__(self, texts, return_tensors="pt", padding=True, truncation=True, max_length=128):
        enc = self.wp.encode_batch(texts)
        import torch as _torch
        return {
            "input_ids": _torch.tensor([e.ids for e in enc], dtype=_torch.long),
            "attention_mask": _torch.tensor([e.attention_mask for e in enc], dtype=_torch.long),
        }

tok = _Tok(tok_wp)

class BertTinyEncoder(torch.nn.Module):
    """ONNX-exportable wrapper: input_ids -> attention-pooled embedding."""
    def __init__(self, backbone):
        super().__init__()
        self.backbone = backbone

    def forward(self, input_ids, attention_mask):
        out = self.backbone(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        mask = attention_mask.unsqueeze(-1).float()
        summed = (out * mask).sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1e-9)
        return summed / counts


wrapped = BertTinyEncoder(model)
wrapped.eval()

dummy = tok(["hello world", "glassbox tiny thinker"], return_tensors="pt", padding=True, truncation=True, max_length=128)

torch.onnx.export(
    wrapped,
    (dummy["input_ids"], dummy["attention_mask"]),
    str(ONNX_PATH),
    input_names=["input_ids", "attention_mask"],
    output_names=["tiny_thinker_embedding"],
    dynamic_axes={"input_ids": {0: "batch", 1: "seq"}, "attention_mask": {0: "batch", 1: "seq"}, "tiny_thinker_embedding": {0: "batch"}},
    opset_version=17,
)
# tokenizer files (thinker-vocab.txt + thinker-tokenizer.json) already saved via save_model()

if not os.environ.get("SKIP_QUANTIZE"):
    quantize_dynamic(str(ONNX_PATH), str(INT8_PATH), weight_type=QuantType.QInt8)
    os.remove(ONNX_PATH)
print(f"done. int8 size: {INT8_PATH.stat().st_size / (1024*1024):.2f} MB -> {INT8_PATH}")
