"""Thinker gate for the Iron Swarm: read {"task","items","keep_threshold"} on stdin,
print {"kept_indices":[...],"stats":{...}}. Fail-open semantics are handled by the caller.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from thinker import thinker  # noqa: E402

req = json.load(sys.stdin)
items = req.get("items", [])

def payload_of(line: str) -> str:
    f = line.split("|")
    if f[0] == "FACT" and len(f) >= 3:
        return "|".join(f[2:])
    if f[0] == "RISK" and len(f) >= 4:
        return " | ".join(f[2:4])
    return line

clean = [payload_of(str(i)) for i in items]
if not items:
    print(json.dumps({"kept_indices": [], "stats": {"note": "no items"}}))
    sys.exit(0)

threshold = float(req.get("keep_threshold", 0.60))
result = thinker().think(req.get("task", ""), clean, keep_threshold=threshold)
print(json.dumps({
    "kept_indices": [k["index"] for k in result["kept"]],
    "stats": {
        "model": result["model"],
        "kept": len(result["kept"]),
        "dropped": [d for d in result["dropped"]],
        "duplicate_clusters": result["duplicate_clusters"],
        "contradiction_candidates": result["contradiction_candidates"],
    },
}))
