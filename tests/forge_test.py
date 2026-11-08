"""Forge end-to-end: generate candidates (Lua) -> rank with Tiny Thinker (Python)."""
import json, os, subprocess, sys, shutil
from pathlib import Path

LUA = os.environ.get("GLASSBOX_LUA") or shutil.which("lua") or r"C:\Users\RYLOY\AppData\Local\Programs\Lua\bin\lua.exe"
PY = sys.executable
ROOT = Path(__file__).resolve().parent.parent
CORE = str(ROOT / "core" / "forge.lua")
GATE = str(ROOT / "python" / "forge_gate.py")

task = sys.argv[1] if len(sys.argv) > 1 else "invent a new passwordless login humans actually want to use"
seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42

gen = subprocess.run([LUA, CORE, "run"], input=json.dumps({"task": task, "seed": seed, "per_family": 3}),
                     capture_output=True, text=True, encoding="utf-8",
                     env={**__import__("os").environ, "GLASSBOX_PYTHON": sys.executable})
if gen.returncode != 0:
    print("forge failed:", gen.stderr)
    sys.exit(1)
dossier = json.loads(gen.stdout)
print(f"generated {dossier['idea_count']} scaffolds (seed={seed})\n")

gate = subprocess.run([PY, GATE], input=json.dumps({"task": task, "ideas": dossier["ideas"], "top": 8}),
                      capture_output=True, text=True, encoding="utf-8")
if gate.returncode != 0:
    print("gate failed:", gate.stderr)
    sys.exit(1)
ranked = json.loads(gate.stdout)
print("=== FORGE RANKING (coherence + 0.1*fertility) ===")
for r in ranked["ranked"]:
    print(f"#{r['rank']} [{r['forge_score']:.3f}] {r['operator']:16s} coherence={r['coherence']:.3f} ferrility={r.get('fertility')}")
    print(f"      spark: {r['spark'][:130]}")
