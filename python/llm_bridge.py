"""Glassbox LLM bridge — the Iron Swarm's transport layer.

Reads {"agents": [{"role", "system", "user"}, ...]} on stdin, calls the
configured OpenAI-compatible chat endpoint for all agents CONCURRENTLY,
writes {"results": {"<role>": "<content>"}} on stdout. Never raises on a
per-agent failure; that agent's value becomes a GB1 RISK line instead.

Config via env: GLASSBOX_LLM_BASE, GLASSBOX_LLM_MODEL, GLASSBOX_LLM_KEY.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

LLM_BASE = os.environ.get("GLASSBOX_LLM_BASE", "http://localhost:11434/v1").rstrip("/")
_api_key = os.environ.get("GLASSBOX_LLM_KEY")
_openai = os.environ.get("OPENAI_API_KEY")
API_KEY = _api_key or _openai or "ollama"
MODEL = os.environ.get("GLASSBOX_LLM_MODEL") or ("gpt-4o-mini" if _openai and not _api_key else "llama3.1")
if _openai and not _api_key and not os.environ.get("GLASSBOX_LLM_BASE"):
    LLM_BASE = "https://api.openai.com/v1"


def call_one(agent: dict) -> tuple[str, str]:
    role = agent.get("role", "unknown")
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": agent.get("system", "")},
            {"role": "user", "content": agent.get("user", "")},
        ],
        "temperature": 0.3,
        "max_tokens": int(agent.get("max_tokens", 1200)),
    }).encode()
    req = urllib.request.Request(
        f"{LLM_BASE}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
        return role, data["choices"][0]["message"]["content"]
    except Exception as e:
        return role, f"GB1/1\nRISK|h|agent {role} call failed: {e}|escalate to user, do not fabricate|\nEND"


def main() -> None:
    req = json.load(sys.stdin)
    agents = req.get("agents", [])
    with ThreadPoolExecutor(max_workers=max(1, len(agents))) as pool:
        results = dict(pool.map(call_one, agents))
    json.dump({"results": results, "model": MODEL, "base": LLM_BASE}, sys.stdout)


if __name__ == "__main__":
    main()
