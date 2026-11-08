"""Forge gate: rank creative candidates with the Tiny Thinker.

Input  (stdin JSON): {"task": "...", "ideas": [{"id", "operator", "parents", "spark", "seed_rationale"}...], "top": 8}
Output (stdout JSON): same ideas + "coherence" per idea, sorted, tagged with
                      novelty hints for BLEND pairs (parent distance).

Scoring contract:
  coherence = cos(task, spark)          — is the idea pointed at the problem?
  fertility = cos(parentA, parentB)     — distance between parents; LOWEST distance
              is common knowledge; mid-range pairs produce the fertile collisions.
These are priors for the LLM, not verdicts.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from thinker import thinker  # noqa: E402

req = json.load(sys.stdin)
task = req.get("task", "")
ides = req.get("ideas", [])
top = int(req.get("top", 8))
if not ides:
    print(json.dumps({"ranked": [], "note": "no ideas"}))
    sys.exit(0)

t = thinker()
sparks = [str(i.get("spark", "")) for i in ides]
emb_task = t.embed([task])[0]
emb_sparks = t.embed(sparks)
cos = (emb_sparks * emb_task).sum(axis=1)

# fertility: distance between blend parents (higher = more foreign = more novel)
fertility = []
for i, idea in enumerate(ides):
    p = idea.get("parents") or []
    if len(p) == 2:
        a, b = t.embed([str(p[0]), str(p[1])])
        fertility.append(1.0 - float((a * b).sum()))
    else:
        fertility.append(None)

ranked = []
for i, idea in enumerate(ides):
    r = dict(idea)
    r["coherence"] = round(float(cos[i]), 4)
    r["fertility"] = round(fertility[i], 4) if fertility[i] is not None else None
    # composite: reward coherence; small bonus for fertility when present
    bonus = 0.10 * (fertility[i] or 0.0)
    r["forge_score"] = round(float(cos[i]) + bonus, 4)
    ranked.append(r)
ranked.sort(key=lambda r: r["forge_score"], reverse=True)
for rank, r in enumerate(ranked, 1):
    r["rank"] = rank

print(json.dumps({"task": task, "ranked": ranked[:top], "total_generated": len(ides),
                  "honesty": "forge_score = coherence + 0.1*fertility prior; the LLM instantiates and the verifier gates."}))
