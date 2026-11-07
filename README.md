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
  core/iron_swarm.lua        # pure-Lua recursive 10-agent engine (Iron Swarm v2)
  python/glassbox_server.py  # MCP server exposing the core as tools
  python/glassbox_swarm.py   # bridge: drives the Lua engine from Python
  python/llm_bridge.py       # concurrent HTTP to OpenAI-compatible endpoints
  python/thinker.py          # Tiny Thinker: ~4.2 MB int8 BERT-Tiny, in-process
  python/thinker_gate.py     # gate used by Iron Swarm to filter scout noise
  python/setup_thinker.py    # rebuild the int8 model artifact
  python/models/             # thinker.int8.onnx (4.21 MB) + vocab
  examples/staging-api-plan.json
  tests/                     # adversarial_gb1.py, thinker_gate_test.py
```

## Install

Requires Python 3.10+ and the `mcp` package:

```powershell
pip install mcp
```

Lua 5.4+ recommended (already installed at `C:\Users\RYLOY\AppData\Local\Programs\Lua\bin\lua.exe` if you ran the installer). The server auto-detects it; without it the Python fallback runs. Set `GLASSBOX_LUA` to point at a specific `lua.exe`.

## Status & testing (as of v0.1)

This repo is git-tracked. Honesty section — what's proven vs. what isn't:

| Claim | Status |
|---|---|
| Lua core (validate/verify/trust/render/explain) | ✅ verified on this machine, Lua 5.4.6 |
| Iron Swarm v2 recursion (REVISE→feedback→PASS) | ✅ verified end-to-end |
| GB1 parser vs. *messy* LLM output (fences, CRLF, prose wrappers) | ✅ `tests/adversarial_gb1.py` — authored by an LLM in-session, not canned clean strings |
| Installed in OpenCode as MCP server `glassbox` | ✅ configured globally via `opencode mcp add`; live handshake tested; tools callable as `glassbox_*` in Code Mode |
| Swarm vs. a *real external* LLM at scale | ❌ not yet — every live test used mock/in-session output. First real run will likely surface prompt tuning needs |
| Parallelism | Python-side (thread pool per phase); Lua is sequential. "Agents run in parallel" = true within each bridge call |

**Backend resolution order:** `GLASSBOX_LUA` env → `lua` on PATH → common install paths (`...\AppData\Local\Programs\Lua\bin\lua.exe`) → Python fallback. Check with `glassbox_status`.

## Tiny Thinker (int8 BERT-Tiny, ~4.2 MB, in-process)

`GLASSBOX`'s cheapest cognitive layer — and an honest label matters here: **the Tiny Thinker does not reason.** It does instant semantic triage so the expensive model spends its tokens on signal:

- **Relevance gating** — scores every GB1 scout line against the task; noise below threshold (default 0.60) never reaches analysts. Measured in-session: the line `FACT|10|Bananas are berries botanically` scored 0.55 vs ~0.80 for real findings and was filtered; analysts saw none of it.
- **Dedup** — clusters near-duplicate findings so analysts don't re-read the same fact four times.
- **Contradiction hints** — flags same-meaning/opposite-polarity pairs (it caught `Counters reset on restart` vs `Restart does not reset counters`, sim 0.89). Hints for the LLM to resolve, never verdicts.

Sizes, because "5 MB" was the brief: `python/models/thinker.int8.onnx` = **4.21 MB** (prajjwal1/bert-tiny: 2 layers, 128 hidden, quantized dynamic-int8 via ONNX Runtime). Runs in-process on CPU, zero network. Rebuild with `python python/setup_thinker.py`.

**Wire it in:**

```python
tools.glassbox.glassbox_think({"task": "...", "findings": "line per finding, or JSON array"})
# or in the swarm:
tools.glassbox.glassbox_swarm({"task": "...", "context": "...", "use_thinker": true})
```

`use_thinker=true` runs the gate after scouts each pass. Fail-open: if the gate or model is missing, analysts get the unfiltered findings and the pass is marked accordingly.

**Honest limits:** bert-tiny's ranking separation is narrow (~0.55–0.82 for this task family) — the 0.60 threshold was tuned in-session, not validated across domains. Treat its verdicts as strong priors, not ground truth; contradiction output is heuristic (negation tokens + cosine). Upgrade path: swap `thinker.py`'s session for a larger int8 encoder without changing the gate API.

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

## OpenCode integration (already done on this machine)

```powershell
opencode mcp add glassbox --global -- python C:\Users\RYLOY\glassbox\python\glassbox_server.py
```

Verify: `opencode mcp list` (shows `glassbox`). Tools are exposed under the `glassbox` Code Mode group; if your session shows `pending`, open OpenCode and check `/mcps` — no restart needed.

To activate the swarm against a real model, give the server an endpoint. Add to the server's `environment` in `opencode.jsonc` or set before launching OpenCode:

```powershell
$env:GLASSBOX_LLM_BASE = "http://localhost:11434/v1"   # Ollama, or https://api.openai.com/v1
$env:GLASSBOX_LLM_MODEL = "llama3.1"
$env:GLASSBOX_LLM_KEY  = "ollama"
```

Or C:\Users\RYLOY\.config\opencode\opencode.jsonc:
```jsonc
{ "mcp": { "servers": { "glassbox": { "type": "local",
  "command": ["python", "C:\\Users\\RYLOY\\glassbox\\python\\glassbox_server.py"],
  "environment": { "GLASSBOX_LLM_BASE": "http://localhost:11434/v1",
                  "GLASSBOX_LLM_MODEL": "llama3.1",
                  "GLASSBOX_LLM_KEY": "ollama" } } } } }
```

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
