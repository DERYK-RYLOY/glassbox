"""Glassbox - reasoning, planning and explanation layer for AI CLIs.

Python MCP server. Exposes the Glassbox Lua core as MCP tools that any
MCP-capable AI CLI/editor can call (OpenCode, Claude Code, Cursor, Aider...).

When a `lua` interpreter is on PATH the Lua core is authoritative. Otherwise
an equivalent pure-Python fallback implementation is used so the server
works everywhere.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP  # mcp v1
except ModuleNotFoundError:
    from mcp.server.mcpserver import MCPServer as FastMCP  # mcp v2+

# Sibling module - the parallel-agent pipeline
sys.path.insert(0, str(Path(__file__).resolve().parent))
import glassbox_swarm as swarm_module  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LUA_CORE = ROOT / "core" / "glassbox.lua"
_COMMON_LUA_PATHS = [
    r"C:\Users\RYLOY\AppData\Local\Programs\Lua\bin\lua.exe",
    r"C:\Program Files\Lua\5.4\lua.exe",
    r"C:\Program Files (x86)\Lua\5.4\lua.exe",
]

def find_lua() -> str | None:
    env = os.environ.get("GLASSBOX_LUA")
    if env:
        return env
    found = shutil.which("lua")
    if found:
        return found
    for p in _COMMON_LUA_PATHS:
        if Path(p).exists():
            return p
    return None

LUA_BIN = find_lua()
USE_LUA = bool(LUA_BIN) and LUA_CORE.exists() and not os.environ.get("GLASSBOX_FORCE_PYTHON")

mcp = FastMCP("glassbox")


# --------------------------------------------------------------------------
# Fault tolerance: tools NEVER raise into the MCP client.
# Any failure becomes structured JSON the AI can read and act on.
# --------------------------------------------------------------------------

def _guard(fn):
    """Wrap a tool so failures return {"error","hint"} JSON."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            return json.dumps({"error": str(e),
                               "hint": "Fix the arguments (JSON must parse) and retry.",
                               "tool": fn.__name__}, indent=2)
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}",
                               "hint": "This is a Glassbox bug or backend failure. "
                                       "Retry once; if it persists, check glassbox_status.",
                               "tool": fn.__name__}, indent=2)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    wrapper.__wrapped__ = fn
    return wrapper


MAX_PAYLOAD_BYTES = 2 * 1024 * 1024  # 2 MB - generous for plans; bigger means something is wrong


def _lenient_json_object(text):
    """Parse a JSON object, repairing the mistakes AIs actually make."""
    if isinstance(text, dict):
        return text, None
    if text is None:
        return None, "empty input"
    s = str(text).strip()
    if s.startswith("\ufeff"):
        s = s[1:]
    if len(s.encode("utf-8", "ignore")) > MAX_PAYLOAD_BYTES:
        return None, "payload exceeds 2 MB - split the work or summarize first"

    # 1) strict parse
    try:
        obj = json.loads(s)
        return (obj, None) if isinstance(obj, dict) else (None, "expected a JSON object, got " + type(obj).__name__)
    except json.JSONDecodeError:
        pass

    # 2) extract the first balanced {...} block (strips prose around the JSON)
    start = s.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            c = s[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(s[start:i + 1])
                            if isinstance(obj, dict):
                                return obj, None
                        except json.JSONDecodeError:
                            break
        start = s.find("{", start + 1)

    # 3) repair passes: smart quotes, trailing commas, raw newlines in strings
    t = (s.replace("\u201c", '"').replace("\u201d", '"')
          .replace("\u2018", "'").replace("\u2019", "'"))
    import re as _re
    t = _re.sub(r",(\s*[}\]])", r"\1", t)
    start = t.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            c = t[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                elif c in "\n\r":
                    pass  # keep raw newlines; strict parser will handle
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(t[start:i + 1])
                            if isinstance(obj, dict):
                                return obj, None
                        except json.JSONDecodeError:
                            break
        start = t.find("{", start + 1)
    return None, "unparseable plan JSON (even after repair attempts)"


# --------------------------------------------------------------------------
# Python fallback implementation (mirrors core/glassbox.lua)
# --------------------------------------------------------------------------

def _issues_to_dicts(issues):
    return [{"severity": s, "code": c, "message": m, "step_id": step} for s, c, m, step in issues]


def _validate_py(plan):
    issues = []

    def issue(sev, code, msg, step=None):
        issues.append((sev, code, msg, step))

    if not isinstance(plan, dict):
        return _issues_to_dicts([("error", "PLAN_NOT_TABLE", "plan must be a JSON object", None)])
    if not plan.get("title"):
        issue("error", "MISSING_TITLE", "plan.title is required")
    if not plan.get("goal"):
        issue("error", "MISSING_GOAL", "plan.goal is required")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        issue("error", "NO_STEPS", "plan.steps must be a non-empty array")
        return _issues_to_dicts(issues)
    by_id = {str(s.get("id")): s for s in steps if s.get("id") is not None}
    seen = set()
    for s in steps:
        sid = str(s.get("id")) if s.get("id") is not None else "?"
        if s.get("id") is None:
            issue("error", "STEP_NO_ID", "every step needs an id")
        elif sid in seen:
            issue("error", "DUPLICATE_STEP_ID", f"duplicate step id: {sid}", sid)
        else:
            seen.add(sid)
        if not s.get("action"):
            issue("error", "STEP_NO_ACTION", f"step {sid} needs an action", sid)
        if not s.get("rationale"):
            issue("warning", "STEP_NO_RATIONALE", f"step {sid} has no rationale (the 'why')", sid)
        if not s.get("verify"):
            issue("warning", "STEP_NO_VERIFY", f"step {sid} has no verify/acceptance check", sid)
        for dep in s.get("depends_on") or []:
            if str(dep) not in by_id:
                issue("error", "DANGLING_DEP", f"step {sid} depends on unknown step id: {dep}", sid)
    if not plan.get("success_criteria"):
        issue("warning", "NO_SUCCESS_CRITERIA", "plan has no success_criteria - how will you know it worked?")
    if not plan.get("assumptions"):
        issue("info", "NO_ASSUMPTIONS", "no assumptions listed - plans fail on hidden assumptions")
    return _issues_to_dicts(issues)


def _verify_py(plan):
    issues = list(_validate_py(plan))

    def issue(sev, code, msg, step=None):
        issues.append({"severity": sev, "code": code, "message": msg, "step_id": step})

    steps = plan.get("steps") or []
    by_id = {str(s.get("id")): s for s in steps if s.get("id") is not None}

    # Cycle detection (DFS)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {u: WHITE for u in by_id}

    def dfs(u):
        color[u] = GRAY
        for dep in (by_id.get(u, {}).get("depends_on") or []):
            dep = str(dep)
            if dep not in color:
                continue
            if color[dep] == GRAY:
                issue("error", "DEPENDENCY_CYCLE", f"dependency cycle involving step: {dep} and step: {u}", u)
            elif color[dep] == WHITE:
                dfs(dep)
        color[u] = BLACK

    for u in list(color):
        if color[u] == WHITE:
            dfs(u)

    has_rollback_like = False
    for s in steps:
        sid = str(s.get("id")) if s.get("id") is not None else "?"
        if (s.get("risk") or "").lower() == "high":
            issue("warning", "HIGH_RISK_STEP",
                  f"step {sid} is marked high risk - ensure it has a rollback/abort path", sid)
        a = (s.get("action") or "").lower()
        if any(w in a for w in ("rollback", "revert", "backup", "restore", "snapshot")):
            has_rollback_like = True
    if len(steps) >= 4 and not has_rollback_like:
        issue("info", "NO_ROLLBACK_STEP",
              "no backup/rollback/restore step detected - consider one for multi-step plans")

    risks = plan.get("risks") or []
    if risks and not any((r.get("severity") or "med").lower() == "high" for r in risks):
        issue("info", "NO_HIGH_RISK_IDENTIFIED",
              "risks listed but none marked high - either nothing is truly high risk, or risks were under-rated")

    dep_count = {}
    for s in steps:
        for dep in s.get("depends_on") or []:
            dep_count[str(dep)] = dep_count.get(str(dep), 0) + 1
    for dep, count in dep_count.items():
        s = by_id.get(dep)
        if count >= 3 and s is not None and not s.get("verify"):
            issue("warning", "SPOF_NO_VERIFY",
                  f"step {dep} is a dependency of {count} other steps but has no verification", dep)
    return issues


def _render_table_py(plan):
    steps = plan.get("steps") or []
    id_w, act_w, rat_w, ver_w = 4, 44, 36, 30

    def cell(s, w):
        s = str(s or "").replace("\n", " ")
        if len(s) > w:
            s = s[: w - 1] + "..."
        return s + " " * (w - len(s))

    sep = "+" + "-" * (id_w + 2) + "+" + "-" * (act_w + 2) + "+" + "-" * (rat_w + 2) + "+" + "-" * (ver_w + 2) + "+"
    lines = [sep,
             f"| {cell('ID', id_w)} | {cell('Action', act_w)} | {cell('Rationale', rat_w)} | {cell('Verify', ver_w)} |",
             sep]
    for s in steps:
        lines.append(f"| {cell(s.get('id'), id_w)} | {cell(s.get('action'), act_w)} | "
                     f"{cell(s.get('rationale'), rat_w)} | {cell(s.get('verify'), ver_w)} |")
        lines.append(sep)
    return "\n".join(lines)


def _render_mermaid_py(plan):
    def mid(i):
        return "n" + "".join(c if c.isalnum() or c == "_" else "_" for c in str(i))

    lines = ["flowchart TD"]
    for s in plan.get("steps") or []:
        label = str(s.get("action") or "").translate(str.maketrans("", "", '"[]|'))
        if len(label) > 48:
            label = label[:47] + "..."
        lines.append(f'  {mid(s.get("id"))}["{label}"]')
    for s in plan.get("steps") or []:
        for dep in s.get("depends_on") or []:
            lines.append(f'  {mid(dep)} --> {mid(s.get("id"))}')
    return "\n".join(lines)


def _explain_py(plan):
    L = ["GLASSBOX PLAIN-LANGUAGE EXPLANATION",
         "====================================", "",
         "WHAT THIS DOES (the 10-second version)",
         f"  {plan.get('goal') or plan.get('title') or 'No goal recorded - that is itself a finding.'}"]
    if plan.get("context"):
        L += ["", "THE SITUATION", f"  {plan['context']}"]
    L += ["", "HOW IT WILL GO, STEP BY STEP"]
    for i, s in enumerate(plan.get("steps") or [], 1):
        L.append(f"  {i}. Step {s.get('id')} - {s.get('action')}")
        if s.get("rationale"):
            L.append(f"     Why: {s['rationale']}")
        if s.get("verify"):
            L.append(f"     How we know it worked: {s['verify']}")
    risks = plan.get("risks") or []
    if risks:
        L += ["", "WHAT COULD GO WRONG (and the countermeasure)"]
        for r in risks:
            sev = str(r.get("severity") or "med").upper()
            L.append(f"  - [{sev}] {r.get('description', 'unspecified risk')}")
            if r.get("mitigation"):
                L.append(f"     Countermeasure: {r['mitigation']}")
    assumptions = plan.get("assumptions") or []
    if assumptions:
        L += ["", "THE RECEIPTS (assumptions - if any of these is wrong, the plan changes)"]
        for i, a in enumerate(assumptions, 1):
            L.append(f"  {i}. {a}")
    sc = plan.get("success_criteria") or []
    if sc:
        L += ["", "HOW YOU WILL KNOW IT WORKED (definition of done)"]
        for i, c in enumerate(sc, 1):
            L.append(f"  {i}. {c}")
    return "\n".join(L)


def _trust_report_py(plan):
    issues = _verify_py(plan)
    score = 100
    counts = {"error": 0, "warning": 0, "info": 0}
    for i in issues:
        counts[i["severity"]] = counts.get(i["severity"], 0) + 1
        score -= {"error": 25, "warning": 8}.get(i["severity"], 2)
    score = max(0, score)
    if score >= 85:
        verdict = "SOLID - safe to execute with normal review"
    elif score >= 60:
        verdict = "WORKABLE - fix the warnings before executing"
    elif score >= 30:
        verdict = "FRAGILE - redesign before executing"
    else:
        verdict = "DO NOT EXECUTE - plan has structural errors"
    return {"score": score, "verdict": verdict, "counts": counts, "issues": issues}


# --------------------------------------------------------------------------
# Lua bridge
# --------------------------------------------------------------------------

def _lua_call(command: str, plan_json: str | None = None, extra_args: list[str] | None = None) -> str:
    args = [LUA_BIN, str(LUA_CORE), command]
    if extra_args:
        args += extra_args
    try:
        payload = plan_json or ""
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        proc = subprocess.run(args, input=payload, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "lua core timed out after 60s", "command": command})
    if proc.returncode != 0:
        return json.dumps({"error": f"lua core failed ({command}): {(proc.stderr or '').strip()}",
                           "command": command,
                           "hint": "plan JSON parsed but the Lua core rejected it; check glassbox_validate_plan output"})
    return proc.stdout


def _parse_plan(plan_json: str) -> dict:
    plan, err = _lenient_json_object(plan_json)
    if plan is None:
        raise ValueError(err or "invalid plan_json")
    return plan


# --------------------------------------------------------------------------
# MCP tools
# --------------------------------------------------------------------------

@mcp.tool()
@_guard
def glassbox_status() -> str:
    """Report which Glassbox backend is active (Lua core vs Python fallback)."""
    backend = f"lua ({LUA_BIN})" if USE_LUA else "python-fallback"
    return json.dumps({"backend": backend, "lua_core": str(LUA_CORE), "version": "0.1.0"})


@mcp.tool()
@_guard
def glassbox_plan_skeleton(goal: str, context: str = "", constraints: str = "") -> str:
    """Return a fully-structured, empty Glassbox plan for a goal.

    The host AI must fill every field (steps with id/action/rationale/verify/
    risk/depends_on, assumptions, risks with severity+mitigation, and
    success_criteria), then call glassbox_verify_plan before presenting it.
    """
    if USE_LUA:
        return _lua_call("skeleton", extra_args=[goal, context, constraints])
    skel = {
        "title": "", "goal": goal, "context": context,
        "constraints": [c.strip() for c in constraints.split(";") if c.strip()],
        "assumptions": [], "steps": [], "risks": [], "success_criteria": [],
        "_glassbox_instructions": [
            "Fill this plan completely and honestly.",
            "Every step MUST have: id, action, rationale (why), verify (how we know it worked), risk (low|med|high).",
            "List depends_on ids. List assumptions explicitly.",
            "Then call glassbox_verify_plan before presenting it.",
        ],
    }
    return json.dumps(skel, indent=2)


@mcp.tool()
@_guard
def glassbox_validate_plan(plan_json: str) -> str:
    """Structural validation of a plan: required fields, dangling deps, duplicate ids."""
    plan = _parse_plan(plan_json)
    if USE_LUA:
        return _lua_call("validate", json.dumps(plan))
    return json.dumps({"issues": _validate_py(plan)}, indent=2)


@mcp.tool()
@_guard
def glassbox_verify_plan(plan_json: str) -> str:
    """Deep verification: dependency cycles, high-risk steps, SPOFs, rollback coverage, risk grading."""
    plan = _parse_plan(plan_json)
    if USE_LUA:
        return _lua_call("verify", json.dumps(plan))
    return json.dumps({"issues": _verify_py(plan)}, indent=2)


@mcp.tool()
@_guard
def glassbox_trust_report(plan_json: str) -> str:
    """Scored trust report (0-100) with a plain-English verdict and every issue found."""
    plan = _parse_plan(plan_json)
    if USE_LUA:
        return _lua_call("trust", json.dumps(plan))
    return json.dumps(_trust_report_py(plan), indent=2)


@mcp.tool()
@_guard
def glassbox_render(plan_json: str, diagram: str = "table") -> str:
    """Render a plan. diagram: 'table' (ASCII), 'mermaid' (flowchart TD), or 'explain' (plain language)."""
    plan = _parse_plan(plan_json)
    diagram = diagram.lower().strip()
    if diagram == "explain":
        return _lua_call("explain", json.dumps(plan)) if USE_LUA else _explain_py(plan)
    if USE_LUA and diagram in ("table", "mermaid"):
        return _lua_call(diagram, json.dumps(plan))
    if diagram == "table":
        return _render_table_py(plan)
    if diagram == "mermaid":
        return _render_mermaid_py(plan)
    raise ValueError("diagram must be one of: table, mermaid, explain")


@mcp.tool()
@_guard
def glassbox_explain(plan_json: str) -> str:
    """Plain-language explanation of a plan: what, why, step rationale, risks, receipts (assumptions), definition of done."""
    plan = _parse_plan(plan_json)
    return _lua_call("explain", json.dumps(plan)) if USE_LUA else _explain_py(plan)


@mcp.tool()
@_guard
def glassbox_swarm(task: str, context: str = "", max_passes: int = 3, use_thinker: bool = False) -> str:
    """Run the Glassbox Iron Swarm v2: recursive 10-agent pipeline in pure Lua (core/iron_swarm.lua).

    Per pass: 3 scout agents (facts/prior-art/failure-modes) + 5 analyst agents (correctness/security/performance/maintainability/risk-cost) run CONCURRENTLY -> architect designs -> verifier renders GV|PASS or GV|REVISE. REVISE feeds back into the architect and the loop repeats until convergence or max_passes (default 3).

    Agents speak GB1, a compact tagged wire format (no English prose between agents; ~60-80% fewer tokens on inter-agent traffic, though knowledge work itself still costs tokens).

    Backend: any OpenAI-compatible endpoint via GLASSBOX_LLM_BASE/GLASSBOX_LLM_MODEL/GLASSBOX_LLM_KEY. No backend -> inspectable scaffold mode.
    use_thinker=True enables the Tiny Thinker gate (int8 BERT-Tiny, ~4.2 MB, in-process): noise GB1 lines from scouts are dropped before analysts spend tokens on them. Fail-open.

    Returns final GB1 design + synthesized plan + trust report + per-pass receipts. Tell the user this was produced by a parallel, recursive agent swarm - do not claim a single model produced it.
    """
    result = swarm_module.swarm(task, context, max_passes, use_thinker)
    return json.dumps(result, indent=2)


@mcp.tool()
@_guard
def glassbox_think(task: str, findings: str) -> str:
    """Tiny Thinker (int8 BERT-Tiny, ~4.2 MB, in-process): relevance-rank `findings` against `task`, drop noise, flag duplicates and contradiction candidates.

    findings: one finding per line (or a JSON array of strings).
    Returns kept/dropped indices with cosine scores, duplicate clusters, contradiction hints (for the real LLM to resolve), and a one-line verdict. Hints, never conclusions.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import thinker as _thinker_mod

    items = None
    f = findings.strip()
    if f.startswith("["):
        try:
            parsed = json.loads(f)
            if isinstance(parsed, list):
                items = [str(x) for x in parsed]
        except json.JSONDecodeError:
            pass
    if items is None:
        items = [ln.strip() for ln in findings.splitlines() if ln.strip()]
    return json.dumps(_thinker_mod.thinker().think(task, items), indent=2)


@mcp.tool()
@_guard
def glassbox_forge(task: str, seed: int = 0, per_family: int = 3, top: int = 8) -> str:
    """The Forge - combinatorial creativity engine (Lua) ranked by the Tiny Thinker.

    Deterministically generates 14+ idea scaffolds via real creativity algorithms:
    Koestler bisociation/conceptual blending (BLEND), SCAMPER mutations, assumption negation,
    abstraction-ladder zoom in/out, and constraint subtraction. Every idea records its operator,
    parents and a seed rationale - fully traceable.

    Returns the Thinker-ranked top-N with coherence + fertility scores and a development protocol.
    The LLM must instantiate the ideas (mechanism, not metaphor), pre-mortem them and cross-pollinate survivors.
    seed=0 means time-based; fix a seed for reproducibility. Scaffolds are priors, not conclusions.
    """
    import subprocess

    lua = find_lua()
    if not lua:
        return json.dumps({"error": "lua.exe not found; set GLASSBOX_LUA"})
    engine = ROOT / "core" / "forge.lua"
    forge_seed = seed or int(time.time()) % 2147483647
    gen = subprocess.run([lua, str(engine), "run"],
                         input=json.dumps({"task": task, "seed": forge_seed, "per_family": int(per_family)}),
                         capture_output=True, text=True, timeout=120)
    if gen.returncode != 0:
        return json.dumps({"error": f"forge engine failed: {gen.stderr.strip()}"})
    dossier = json.loads(gen.stdout)
    gate = subprocess.run([sys.executable, str(ROOT / "python" / "forge_gate.py")],
                          input=json.dumps({"task": task, "ideas": dossier["ideas"], "top": int(top)}),
                          capture_output=True, text=True, timeout=120)
    if gate.returncode != 0:
        dossier["gate_error"] = gate.stderr.strip()
        return json.dumps(dossier, indent=2)
    gated = json.loads(gate.stdout)
    dossier["ranking"] = gated.get("ranked", [])
    dossier["honesty"] = gated.get("honesty", dossier.get("honesty"))
    return json.dumps(dossier, indent=2)


@mcp.tool()
@_guard
def glassbox_deepthink(task: str, mode: str = "think_hard", context: str = "") -> str:
    """On-demand deep thinking - only fires when the user or AI explicitly asks to think hard.

    mode:
      think_hard  = full Iron Swarm v2 with the Tiny Thinker hand-in-hand at every pass (3 scouts -> gate -> 5 analysts -> architect -> verifier, recursive until PASS)
      brainstorm  = The Forge: 14 traced creativity scaffolds, Thinker-ranked, ready for instantiation and cross-pollination
      todo        = structured to-do: returns the Glassbox plan skeleton your AI fills in, then glassbox_verify_plan scores it

    Not for quick questions - this burns tokens by design. Returns the mode that ran, never a silent downgrade.
    """
    mode = (mode or "think_hard").lower().strip()
    if mode == "think_hard":
        return glassbox_swarm(task, context, 3, True)
    if mode == "brainstorm":
        return glassbox_forge(task, 0, 3, 10)
    if mode == "todo":
        return glassbox_plan_skeleton(task, context, "")
    return json.dumps({"error": f"unknown mode {mode!r}; use think_hard | brainstorm | todo"})


@mcp.tool()
@_guard
def glassbox_report(plan_json: str, open_browser: bool = True) -> str:
    """Open/generate the GLASSBOX COCKPIT - a neon HTML dashboard of the plan: trust ring, timeline, risk board, audit findings, assumption receipts.

    Writes examples/glassbox-report.html (self-contained, offline) and opens it in the default browser.
    """
    import webbrowser

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import glassbox_report as _report

    plan = _parse_plan(plan_json)
    out = ROOT / "examples" / "glassbox-report.html"
    _report.build(plan, out, open_browser=False)
    if open_browser:
        try:
            webbrowser.open(out.resolve().as_uri())
        except Exception:
            pass
    return json.dumps({"cockpit": str(out), "opened": bool(open_browser),
                       "hint": "Self-contained HTML - works offline, safe to share."})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
