# Glassbox

**An explainability and planning layer for AI coding tools.** Glassbox doesn't replace the model — it wraps it: it forces explicit plans, verifies them for structural flaws, and renders the reasoning in plain language, tables, and graphs.

Written in **Lua** (the reasoning core) + **Python** (the MCP adapter so any AI CLI can call it).

## Why

AI tools produce answers. Glassbox produces *auditable* answers:

- **Plans, not vibes** — every plan carries explicit assumptions, step rationale, verification per step, and a definition of done.
- **Receipts** — the plain-language explanation lists every assumption; if one is wrong, the plan changes, and you can see exactly which.
- **Structural self-check** — dependency cycles, duplicate IDs, dangling deps, high-risk steps without rollback, single points of failure.
- **Trust score** — 0–100 with a plain-English verdict (`SOLID` / `WORKABLE` / `FRAGILE` / `DO NOT EXECUTE`).
- **Output you can paste anywhere** — ASCII tables, Mermaid flowcharts, plain-language walkthroughs.

## Layout

```
glassbox/
  core/glassbox.lua          # pure-Lua core: validate/verify/trust/render/explain (zero deps)
  python/glassbox_server.py  # MCP server exposing the core as tools
  examples/staging-api-plan.json
```

## Install

Requires Python 3.10+ and the `mcp` package:

```powershell
pip install mcp
```

For the native Lua backend (optional — a Python fallback ships in the server):

```powershell
winget install --id BrianSidebotham.Lua   # or any Lua 5.3+
```

If `lua` is on PATH, the Lua core is authoritative. Set `GLASSBOX_FORCE_PYTHON=1` to force the fallback.

## Use it with an MCP-capable AI CLI

Add to your MCP client config (OpenCode / Claude Code / Cursor / others — same shape):

```json
{
  "mcpServers": {
    "glassbox": {
      "command": "python",
      "args": ["C:\\Users\\RYLOY\\glassbox\\python\\glassbox_server.py"]
    }
  }
}
```

## Tools exposed over MCP

| Tool | What it does |
|---|---|
| `glassbox_status` | Which backend is active (lua / python-fallback) |
| `glassbox_plan_skeleton` | Empty structured plan for a goal — the AI fills it |
| `glassbox_validate_plan` | Structural check: required fields, dup IDs, dangling deps |
| `glassbox_verify_plan` | Deep check: cycles, high-risk steps, SPOFs, rollback coverage |
| `glassbox_trust_report` | 0–100 score + verdict + full issue list |
| `glassbox_render` | Render as `table` (ASCII), `mermaid` (flowchart TD), or `explain` |
| `glassbox_explain` | Plain-language walkthrough with receipts (assumptions) |
| `glassbox_swarm` | **Iron Swarm** — 3 scouts ∥ → 5 analysts ∥ → 2 architects ∥ → lead arbitration, in GB1 wire format |

The intended flow: AI fills a skeleton → `glassbox_verify_plan` → fix issues → `glassbox_explain` presented to the user. For hard problems, use `glassbox_swarm` — parallel subagents do the heavy lifting and return receipts from every agent.

## Try it without any AI client

```powershell
Get-Content examples\staging-api-plan.json | python -c "import sys,json;print(json.dumps(json.load(sys.stdin)))" # sanity check
```

Or call the tools from Python:

```python
import json, sys
sys.path.insert(0, "python")
import glassbox_server as g
plan = json.load(open("examples/staging-api-plan.json"))
print(g.glassbox_trust_report(json.dumps(plan)))
print(g.glassbox_render(json.dumps(plan), "mermaid"))
```

## Iron Swarm v2 (recursive 10-agent engine, pure Lua)

`core/iron_swarm.lua` is the brain. `python/llm_bridge.py` is the transport (concurrent HTTP to any OpenAI-compatible endpoint). `glassbox_swarm(task, context, max_passes)` drives it over MCP.

Per pass:
```
┌─ 3 Scouts ∥ ─┐   ┌─ 5 Analysts ∥ ─┐   ┌─ Architect ─┐   ┌─ Verifier ─┐
│ facts        │   │ correctness    │   │ unified GB1 │   │ GV|PASS or │
│ prior-art    │ → │ security       │ → │ STEP plan   │ → │ GV|REVISE  │
│ failure-modes│   │ performance    │   │             │   │            │
└──────────────┘   │ maintainability│   └─────────────┘   └─────┬──────┘
                   │ risk-cost     │         ▲                 │
                   └───────────────┘         └── REVISE feedback┘
                            (loop until PASS or max_passes, default 3)
```

10 agents per pass. Converges past the verifier or exhausts budget — either way it reports exactly what happened. The final artifact is parsed back into the Glassbox plan schema and trust-scored, so **swarm output is auditable by the same validator as hand-written plans**.

**GB1 wire format** — agents do not speak English prose between themselves; they speak tagged lines:

```
GB1/1
FACT|92|Token bucket is correct for burst control
RISK|h|X-Forwarded-For spoofing|key on peer IP, not the header
GV|PASS|plan covers spoofing, restart and observability
STEP|1|Token bucket middleware keyed on peer IP|lean+config|spoofed-IP test|low|
END
```

Honest numbers: GB1 removes *prose framing* from agent traffic — typically ~60–80% fewer tokens on the wire between agents. It cannot make knowledge work "almost zero tokens"; the model still pays to read findings and produce analysis. What GB1 does eliminate is rambling, hedging, and markdown fluff between agents.

**Backend:** set `GLASSBOX_LLM_BASE` (e.g. `http://localhost:11434/v1` for Ollama, or `https://api.openai.com/v1`), `GLASSBOX_LLM_MODEL`, `GLASSBOX_LLM_KEY`. Lua 5.4 required (already installed at `C:\Users\RYLOY\AppData\Local\Programs\Lua\bin\lua.exe`, auto-detected). Without a backend, `glassbox_swarm` returns scaffold mode: the full pipeline, every prompt, the GB1 spec.

**Honesty policy:** `glassbox_swarm` returns `agents_run`, `passes`, per-pass receipts (`pass_history`, `receipts`), and a synthesized trust report. It does not pretend one model did everything.

## Roadmap

- [ ] GB2 wire format — single-letter opcodes (`F|92|...`, `R|h|...`, `V|P|...`) for the tightest possible inter-agent dialect
- [ ] `glassbox_interview` — AI questions the user to surface hidden assumptions *before* the swarm runs
- [ ] HTML export — self-contained interactive plan report (steps, trust score, per-pass receipts)
- [ ] Per-host adapters/prompt packs tuned for OpenCode, Claude Code, Cursor, Aider
- [ ] Cryptographic plan receipts (hash of plan + assumptions + agent outputs) for audit trails
- [ ] Semantic dedup across passes (skip re-analysis when findings didn't change)
