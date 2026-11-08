"""Glassbox Tiny Thinker - a ~4.2 MB in-process cognitive triage layer.

What it IS:  int8 BERT-Tiny (prajjwal1/bert-tiny, 2 layers, 128 hidden) run via
             ONNX Runtime in-process. Semantic embeddings + cosine gates for:
             relevance ranking, dedup, contradiction candidates.
What it is NOT: a reasoning engine. It does cheap cognitive triage so the
             expensive model spends its tokens on what matters. No "thinking"
             happens without the real LLM in the loop.

Zero network at runtime. Models live in python/models/.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import BertWordPieceTokenizer

HERE = Path(__file__).resolve().parent
MODEL = HERE / "models" / "thinker.int8.onnx"
VOCAB = HERE / "models" / "thinker-vocab.txt"

_NEGATION = {"not", "never", "no", "none", "without", "cannot", "n't", "nor", "neither", "deny", "refute", "impossible"}


class TinyThinker:
    def __init__(self) -> None:
        if not MODEL.exists() or not VOCAB.exists():
            raise FileNotFoundError(
                f"Tiny Thinker model missing at {MODEL}. Run: python {HERE / 'setup_thinker.py'}"
            )
        self._tok = BertWordPieceTokenizer(str(VOCAB), lowercase=True, unk_token="[UNK]",
                                           cls_token="[CLS]", sep_token="[SEP]", pad_token="[PAD]")
        self._tok.enable_truncation(max_length=128)
        self._tok.enable_padding(pad_id=0, pad_token="[PAD]")
        self._sess = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])  # outputs[0] = tiny_thinker_embedding

    def embed(self, texts: list[str]) -> np.ndarray:
        enc = self._tok.encode_batch(texts)
        maxlen = max(len(e.ids) for e in enc)
        ids = np.array([e.ids + [0] * (maxlen - len(e.ids)) for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask + [0] * (maxlen - len(e.attention_mask)) for e in enc], dtype=np.int64)
        out = self._sess.run(None, {"input_ids": ids, "attention_mask": mask})[0]
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-12)

    @staticmethod
    def _cosine_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a @ b.T

    def relevance(self, task: str, items: list[str]) -> list[dict]:
        """Score each item against the task. Items under threshold are noise candidates."""
        if not items:
            return []
        emb = self.embed([task] + items)
        task_emb, item_emb = emb[:1], emb[1:]
        sims = (task_emb @ item_emb.T)[0]
        return sorted(
            [{"index": i, "score": round(float(s), 4), "text": items[i]} for i, s in enumerate(sims)],
            key=lambda r: r["score"], reverse=True,
        )

    def duplicates(self, items: list[str], threshold: float = 0.86) -> list[list[int]]:
        """Cluster near-duplicate items (indices)."""
        if len(items) < 2:
            return []
        emb = self.embed(items)
        sim = self._cosine_matrix(emb, emb)
        parent = list(range(len(items)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if sim[i, j] >= threshold:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj
        clusters: dict[int, list[int]] = {}
        for i in range(len(items)):
            clusters.setdefault(find(i), []).append(i)
        return [sorted(c) for c in clusters.values() if len(c) > 1]

    def contradiction_candidates(self, items: list[str], sim_floor: float = 0.55) -> list[dict]:
        """Semantically-related item pairs where one side negates. A HINT for the big model,
        not a verdict - the LLM decides what's actually contradictory."""
        if len(items) < 2:
            return []
        lowered = [t.lower() for t in items]
        emb = self.embed(items)
        sim = self._cosine_matrix(emb, emb)
        out = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if sim[i, j] < sim_floor:
                    continue
                toks_i = set(re.findall(r"[a-z']+", lowered[i]))
                toks_j = set(re.findall(r"[a-z']+", lowered[j]))
                neg_i = bool(toks_i & _NEGATION)
                neg_j = bool(toks_j & _NEGATION)
                if neg_i != neg_j:
                    out.append({"pair": [i, j], "similarity": round(float(sim[i, j]), 4),
                                "hint": f"one of these negates the other (sim {sim[i, j]:.2f}) - check with the LLM"})
        return out

    def think(self, task: str, findings: list[str], keep_threshold: float = 0.60) -> dict:
        """Full triage pass: rank by relevance, drop noise, flag duplicates + contradictions."""
        relevance = self.relevance(task, findings)
        ranked = [r for r in relevance if r["score"] >= keep_threshold]
        dropped = [r for r in relevance if r["score"] < keep_threshold]
        kept_texts = [r["text"] for r in ranked]
        kept_idx = [r["index"] for r in ranked]
        dups = self.duplicates(kept_texts) if kept_texts else []
        # map dup clusters back to original indices
        dups = [[kept_idx[i] for i in cluster] for cluster in dups]
        contra = self.contradiction_candidates(kept_texts) if kept_texts else []
        contra = [{"pair": [kept_idx[c["pair"][0]], kept_idx[c["pair"][1]]], "similarity": c["similarity"], "hint": c["hint"]}
                  for c in contra]
        return {
            "model": "bert-tiny-int8 (4.21 MB)",
            "kept": [{"index": r["index"], "score": r["score"]} for r in ranked],
            "dropped": [{"index": r["index"], "score": r["score"], "text": r["text"][:120]} for r in dropped],
            "duplicate_clusters": dups,
            "contradiction_candidates": contra,
            "verdict": f"kept {len(ranked)}/{len(findings)} findings as relevant; "
                       f"{len(dups)} duplicate cluster(s); {len(contra)} contradiction candidate(s) "
                       "- all hints for the real model, none are conclusions.",
        }


_thinker: TinyThinker | None = None


def thinker() -> TinyThinker:
    global _thinker
    if _thinker is None:
        _thinker = TinyThinker()
    return _thinker


if __name__ == "__main__":
    import json, sys
    task = sys.argv[1] if len(sys.argv) > 1 else "design a login rate-limiter"
    findings = sys.argv[2:] or [
        "Token bucket is correct for burst control",
        "Use express-rate-limit middleware",
        "Bananas grow on banana trees",
        "Counters reset on process restart - accept this risk",
        "Restart does not reset counters in memory",
        "Add 429 alerting and saturation metrics",
    ]
    print(json.dumps(thinker().think(task, findings), indent=2))
