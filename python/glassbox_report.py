"""Glassbox Cockpit - generates the signature Glassbox visual report.

A self-contained, offline HTML dashboard: trust ring, step timeline,
risk board, receipts, mermaid-free flow diagram. No CDNs, no network.

usage:
    python glassbox_report.py [plan.json] [--out path.html] [--open]
    (no args: reads plan JSON from stdin)
"""
from __future__ import annotations

import html
import json
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#05070f;--panel:rgba(18,24,44,.55);--line:rgba(120,220,255,.16);
      --neon:#00e5ff;--violet:#8b5cf6;--ink:#e6f1ff;--dim:#8a97b8;--ok:#34d399;--warn:#fbbf24;--bad:#fb7185}
body{background:radial-gradient(1200px 800px at 15% -10%,#141b3a 0%,transparent 60%),
               radial-gradient(1000px 700px at 110% 10%,#1b0f3a 0%,transparent 55%),var(--bg);
      color:var(--ink);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh;overflow-x:hidden}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
      background:repeating-linear-gradient(0deg,transparent 0 3px,rgba(255,255,255,.015) 3px 4px)}
main{max-width:1180px;margin:auto;padding:34px 26px 80px;position:relative;z-index:1}
.top{display:flex;align-items:center;gap:18px;padding:16px 22px;border:1px solid var(--line);
     border-radius:18px;background:linear-gradient(180deg,rgba(255,255,255,.04),transparent);backdrop-filter:blur(14px);
     box-shadow:0 0 60px rgba(0,229,255,.07),inset 0 1px 0 rgba(255,255,255,.06)}
.logo{width:52px;height:52px;border-radius:14px;display:grid;place-items:center;
      background:radial-gradient(circle at 50% 40%,rgba(139,92,246,.35),rgba(5,7,15,.2) 70%);
      box-shadow:0 0 26px rgba(0,229,255,.45);animation:pulse 3s ease-in-out infinite;overflow:hidden}
.logo img{width:100%;height:100%;object-fit:contain}
@keyframes pulse{0%,100%{box-shadow:0 0 18px rgba(0,229,255,.4)}50%{box-shadow:0 0 34px rgba(139,92,246,.65)}}
h1{font-size:21px;letter-spacing:.22em;font-weight:800}
.tag{color:var(--neon);font-size:11px;letter-spacing:.35em;text-transform:uppercase}
.goal{margin:22px 0 6px;color:var(--dim);font-size:13px;letter-spacing:.08em;text-transform:uppercase}
.goaltext{font-size:26px;font-weight:700;line-height:1.3;max-width:880px}
.grid{display:grid;grid-template-columns:380px 1fr;gap:22px;margin-top:28px}
.card{border:1px solid var(--line);border-radius:20px;background:var(--panel);
      backdrop-filter:blur(12px);padding:22px;box-shadow:inset 0 1px 0 rgba(255,255,255,.05)}
.ringwrap{display:flex;flex-direction:column;align-items:center;gap:12px}
.ring{filter:drop-shadow(0 0 18px rgba(0,229,255,.35))}
.ringbg{stroke:rgba(255,255,255,.07)}
.ringval{stroke:url(#grad);stroke-linecap:round;stroke-dasharray:565;stroke-dashoffset:565;
         transition:stroke-dashoffset 1.4s cubic-bezier(.2,.8,.2,1)}
.scorenum{font-size:56px;font-weight:800;fill:var(--ink)}
.scorelbl{fill:var(--dim);font-size:10px;letter-spacing:.3em;text-transform:uppercase}
.verdict{font-size:15px;font-weight:700;color:var(--ok);text-align:center;line-height:1.5}
.meta{width:100%;margin-top:8px;border-collapse:collapse;font-size:12px}
.meta td{padding:6px 4px;border-top:1px solid rgba(255,255,255,.06);color:var(--dim)}
.meta b{color:var(--ink);font-weight:600}
.timeline{display:flex;flex-direction:column;gap:14px}
.step{display:flex;gap:14px;align-items:flex-start;padding:14px 16px;border:1px solid rgba(255,255,255,.06);
      border-radius:14px;background:rgba(255,255,255,.03);transition:transform .2s,border-color .2s}
.step:hover{transform:translateX(6px);border-color:rgba(0,229,255,.4)}
.sid{min-width:34px;height:34px;border-radius:10px;display:grid;place-items:center;font-weight:800;
     background:linear-gradient(160deg,#0ea5e9,#8b5cf6);color:#05070f;font-size:14px}
.sbody{flex:1}
.saction{font-weight:600;font-size:14.5px}
.swhy{color:var(--dim);font-size:12px;margin-top:4px}
.sver{color:var(--neon);font-size:11.5px;margin-top:6px;font-family:Consolas,monospace}
.risk{font-size:10px;font-weight:800;letter-spacing:.08em;padding:3px 9px;border-radius:99px;margin-top:8px;display:inline-block}
.risk.low{background:rgba(52,211,153,.15);color:var(--ok)}
.risk.medium{background:rgba(251,191,36,.15);color:var(--warn)}
.risk.high{background:rgba(251,113,133,.18);color:var(--bad)}
h2{font-size:12px;letter-spacing:.28em;text-transform:uppercase;color:var(--dim);margin:26px 0 12px}
.riskrow{display:flex;gap:10px;align-items:flex-start;padding:10px 12px;border-left:3px solid var(--bad);
         background:rgba(251,113,133,.06);border-radius:8px;margin-bottom:8px;font-size:13px}
.riskrow.medium{border-color:var(--warn);background:rgba(251,191,36,.05)}
.riskrow .sev{font-weight:800;font-size:10px;letter-spacing:.1em;margin-right:6px}
pre.receipt{background:#070b18;border:1px solid var(--line);border-radius:12px;padding:14px;overflow:auto;
             font-size:11px;color:#9fd3ff;font-family:Consolas,monospace;max-height:280px}
.foot{margin-top:34px;text-align:center;color:var(--dim);font-size:11px;letter-spacing:.15em}
.foot b{color:var(--neon)}
@media(max-width:920px){.grid{grid-template-columns:1fr}}
"""

def score_color(v):
    if v >= 85:
        return "SOLID"
    if v >= 60:
        return "WORKABLE"
    if v >= 30:
        return "FRAGILE"
    return "DO NOT EXECUTE"

def ring_offset(score):
    frac = max(0, min(100, score)) / 100.0
    return str(round(565 * (1 - frac), 1))

def step_html(step):
    risk = str(step.get("risk", "medium")).lower()
    risk_cls = {"low": "low", "medium": "medium", "high": "high"}.get(risk, "medium")
    deps = step.get("depends_on") or []
    dep_s = f"<span class='sver'>after: {html.escape(', '.join(map(str, deps)))}</span>" if deps else ""
    return f"""<div class='step'><div class='sid'>{html.escape(str(step.get('id','?')))}</div>
      <div class='sbody'><div class='saction'>{html.escape(str(step.get('action','')))}</div>
      <div class='swhy'>why: {html.escape(str(step.get('rationale','')))}</div>
      {dep_s}
      <div class='sver'>verify: {html.escape(str(step.get('verify','')))}</div>
      <span class='risk {risk_cls}'>{risk_cls.upper()} RISK</span></div></div>"""

def report_html(plan, trust=None, receipts=None, source="GLASSBOX AUDIT", logo_data: str = ""):
    if not logo_data:
        logo_path = ROOT / "assets" / "logo.png"
        import base64
        logo_data = "data:image/png;base64," + base64.b64encode(logo_path.read_bytes()).decode()
    trust = trust or {"score": 0, "verdict": "UNSCORED", "counts": {}, "issues": []}
    score = int(trust.get("score", 0))
    risks = plan.get("risks", []) or []
    steps = plan.get("steps", []) or []
    assumptions = plan.get("assumptions", []) or []
    criteria = plan.get("success_criteria", []) or []
    issues = trust.get("issues", []) or []
    counts = trust.get("counts", {}) or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    risks_html = "".join(
        f"""<div class='riskrow {str(r.get('severity','medium')).lower()}'><div><span class='sev'>{html.escape(str(r.get('severity','med')).upper())}</span>{html.escape(str(r.get('description', r.get('description',''))))}<br><span style='color:var(--dim);font-size:12px'>countermeasure: {html.escape(str(r.get('mitigation','')))}</span></div></div>"""
        for r in risks) or "<div class='riskrow medium'>no risks declared - declare them.</div>"

    assumptions_html = "".join(f"<li style='margin:6px 0;color:var(--dim)'>{html.escape(str(a))}</li>" for a in assumptions)
    criteria_html = "".join(f"<li style='margin:6px 0;color:var(--dim)'>{html.escape(str(c))}</li>" for c in criteria)
    issues_html = "".join(f"<div class='riskrow medium'><div><span class='sev'>{html.escape(str(i.get('severity','')).upper())}</span>{html.escape(str(i.get('message','')))}</div></div>" for i in issues) or "<div class='riskrow medium'><div>clean - no issues raised by the verifier</div></div>"
    steps_html = "".join(step_html(s) for s in steps)
    receipt_json = html.escape(json.dumps(receipts or trust, indent=2)[:4000])

    verdict_color = "#34d399" if score >= 85 else ("#fbbf24" if score >= 60 else ("#fb923c" if score >= 30 else "#fb7185"))

    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<title>GLASSBOX COCKPIT - {html.escape(str(plan.get('goal','plan'))[:60])}</title>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<style>{CSS}</style></head><body><main>
<div class='top'><div class='logo'><img src='{logo_data}' alt='GLASSBOX'></div>
  <div><h1>GLASSBOX</h1><div class='tag'>cockpit // audited by code, not vibes</div></div>
  <div style='margin-left:auto;text-align:right'><div class='tag' style='color:var(--dim)'>scan</div><div style='font-family:Consolas;font-size:13px'>{html.escape(now)}</div></div>
</div>
<div class='goal'>mission goal</div>
<div class='goaltext'>{html.escape(str(plan.get('goal') or plan.get('title','')))}</div>
<div class='grid'>
  <div class='card ringwrap'>
    <svg class='ring' width='230' height='230' viewBox='0 0 200 200'>
      <defs><linearGradient id='grad' x1='0' y1='0' x2='1' y2='1'>
        <stop offset='0%' stop-color='#00e5ff'/><stop offset='100%' stop-color='#8b5cf6'/>
      </linearGradient></defs>
      <circle class='ringbg' cx='100' cy='100' r='90' stroke-width='14' fill='none'/>
      <circle class='ringval' cx='100' cy='100' r='90' stroke-width='14' fill='none'
              transform='rotate(-90 100 100)' stroke-dashoffset='{ring_offset(score)}' id='ringval'/>
      <text x='100' y='96' text-anchor='middle' class='scorenum'>{score}</text>
      <text x='100' y='122' text-anchor='middle' class='scorelbl'>trust / 100</text>
    </svg>
    <div class='verdict' style='color:{verdict_color}'>{html.escape(str(trust.get('verdict','')))}</div>
    <table class='meta'>
      <tr><td>errors</td><td><b>{counts.get('error', 0)}</b></td></tr>
      <tr><td>warnings</td><td><b>{counts.get('warning', 0)}</b></td></tr>
      <tr><td>info</td><td><b>{counts.get('info', 0)}</b></td></tr>
      <tr><td>source</td><td><b>{html.escape(source)}</b></td></tr>
    </table>
  </div>
  <div class='card'>
    <h2>execution timeline</h2>
    <div class='timeline'>{steps_html}</div>
  </div>
</div>
<h2>risk board</h2>{risks_html}
<h2>audit findings</h2>{issues_html}
<div style='display:grid;grid-template-columns:1fr 1fr;gap:18px'>
  <div class='card'><h2 style='margin-top:0'>assumption receipts</h2><ul style='padding-left:18px'>{assumptions_html or '<li style=color:var(--dim)>none declared - red flag</li>'}</ul></div>
  <div class='card'><h2 style='margin-top:0'>definition of done</h2><ul style='padding-left:18px'>{criteria_html or '<li style=color:var(--dim)>none declared</li>'}</ul></div>
</div>
<h2>receipts (raw)</h2><pre class='receipt'>{receipt_json}</pre>
<div class='foot'>GLASSBOX COCKPIT - <b>every claim auditable, every assumption receipted</b></div>
</main>
<script>requestAnimationFrame(()=>{{document.getElementById('ringval').style.strokeDashoffset='{ring_offset(score)}';}});</script>
</body></html>"""


def build(plan: dict, out_path: Path, open_browser: bool = True) -> Path:
    sys.path.insert(0, str(ROOT / "python"))
    import glassbox_server as srv  # late import: server must not run stdio on import
    trust_raw = srv.glassbox_trust_report(json.dumps(plan))
    try:
        trust = json.loads(trust_raw)
    except json.JSONDecodeError:
        trust = {"score": 0, "verdict": "unscored", "counts": {}, "issues": [{"severity": "error", "message": trust_raw[:400]}]}
    out_path = Path(out_path)
    out_path.write_text(report_html(plan, trust), encoding="utf-8")
    if open_browser:
        try:
            webbrowser.open(out_path.resolve().as_uri())
        except Exception:
            os.startfile(str(out_path))  # windows best-effort
    return out_path


def main() -> None:
    args = sys.argv[1:]
    open_flag = "--open" in args
    if open_flag:
        args.remove("--open")
    out = ROOT / "examples" / "glassbox-report.html"
    if "--out" in args:
        i = args.index("--out")
        out = Path(args[i + 1])
        del args[i:i + 2]
    if args:
        plan = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    else:
        plan = json.loads(sys.stdin.read())
    path = build(plan, out, open_browser=open_flag)
    print(str(path))


if __name__ == "__main__":
    main()
