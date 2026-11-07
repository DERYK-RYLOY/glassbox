"""Iron Swarm v2 bridge — drives core/iron_swarm.lua (the recursive Lua engine).

python is the transport (HTTP + concurrency, see llm_bridge.py); Lua is the
brain (agent orchestration, GB1 codec, the verify -> revise recursion,
plan synthesis, trust scoring).

Env:
  GLASSBOX_LUA     path to lua.exe (auto-detected if unset)
  GLASSBOX_PYTHON  python interpreter for the bridge (default: python)
  GLASSBOX_LLM_BASE / GLASSBOX_LLM_MODEL / GLASSBOX_LLM_KEY
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "core" / "iron_swarm.lua"

LLM_BASE = os.environ.get("GLASSBOX_LLM_BASE", "http://localhost:11434/v1").rstrip("/")
OPENAI = os.environ.get("OPENAI_API_KEY")
BACKEND_CONFIGURED = bool(
    os.environ.get("GLASSBOX_LLM_MODEL") or os.environ.get("GLASSBOX_LLM_BASE") or OPENAI
)

_COMMON_LUA_PATHS = [
    r"C:\Users\RYLOY\AppData\Local\Programs\Lua\bin\lua.exe",
    r"C:\Program Files\Lua\5.4\lua.exe",
    r"C:\Program Files (x86)\Lua\5.4\lua.exe",
]


def find_lua() -> str | None:
    if os.environ.get("GLASSBOX_LUA"):
        return os.environ["GLASSBOX_LUA"]
    found = shutil.which("lua")
    if found:
        return found
    for p in _COMMON_LUA_PATHS:
        if Path(p).exists():
            return p
    return None


def _scaffold(task: str, context: str) -> dict:
    brief = f"TASK T: {task}\nCONTEXT: {context or 'none provided'}"
    return {
        "mode": "scaffold",
        "reason": "No LLM backend configured (set GLASSBOX_LLM_BASE/GLASSBOX_LLM_MODEL/GLASSBOX_LLM_KEY).",
        "engine": str(ENGINE),
        "lua_engine_available": find_lua() is not None,
        "pipeline": [
            "PASS N: 3 scouts (parallel) -> 5 analysts (parallel) -> architect -> verifier",
            "verifier verdict GV|PASS ends loop; GV|REVISE feeds back into architect",
            "max_passes default 3; agents_run = 10 per pass",
        ],
        "agents": ["scout-facts", "scout-prior-art", "scout-failure-modes",
                   "analyst-correctness", "analyst-security", "analyst-performance",
                   "analyst-maintainability", "analyst-risk-cost", "architect", "verifier"],
        "gb1_spec": "GB1/1, TASK|<id>|<verb>|<payload>, FACT|<conf 0-100>|<stmt>, "
                    "RISK|<l|m|h>|<desc>|<mitigation>, GV|PASS|<why> / GV|REVISE|<why>, "
                    "STEP|<id>|<action>|<rationale>|<verify>|<risk>|<deps>, END",
        "wire_in": "Set GLASSBOX_LLM_BASE (e.g. http://localhost:11434/v1 for Ollama), "
                   "GLASSBOX_LLM_MODEL, GLASSBOX_LLM_KEY, then call glassbox_swarm again.",
    }


def swarm(task: str, context: str = "", max_passes: int = 3, use_thinker: bool = False) -> dict:
    if not BACKEND_CONFIGURED:
        # still allow mock/testing backends reachable on the default port? No: honest scaffold.
        return _scaffold(task, context)

    lua = find_lua()
    if not lua:
        raise RuntimeError(
            "lua.exe not found. Install Lua 5.4 (winget install DEVCOM.Lua) "
            "or set GLASSBOX_LUA to its path."
        )

    payload = json.dumps({"task": task, "context": context, "max_passes": int(max_passes),
                          "use_thinker": bool(use_thinker)})
    proc = subprocess.run([lua, str(ENGINE), "run"], input=payload,
                          capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"iron_swarm engine failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)
