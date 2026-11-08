"""Adversarial GB1 test: agent outputs authored by the LLM in-session, with
deliberately messy formatting (fences, intro prose, CRLF) to prove the parser
survives contact with a real model.
"""
import json, threading, os, sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = {
    "facts": 'Here are the facts you asked for.\r\n```\nGB1/1\nFACT|95|In-memory token bucket is O(1) and correct for burst control at single-VPS scale\nFACT|90|Node process restarts lose in-memory counters (acceptable if documented, or persist)\nFACT|85|Standard lib hits 10k+ req/s on one core; network stack is the limit\nEND\n```\nLet me know if you need more.',
    "prior": 'GB1/1\nFACT|90|express-rate-limit (in-memory, battle-tested), 40M weekly downloads\nFACT|80|@upstash/ratelimit, Redis-backed, overkill for single VPS\nFACT|75|rate-limiter-flexible, supports all stores, steeper API\nEND',
    "failmodes": 'GB1/1\nRISK|h|Restart wipes counters for an active attacker|document accept-or-persist decision before prod|\nRISK|h|X-Forwarded-For spoofing when not behind a trusted proxy|key on req.socket.remoteAddress, never the header|\nRISK|m|False-positive lockouts for shared IPs (CGNAT, offices)|generous bucket + per-account secondary limit|\nRISK|m|Memory growth if keys never expire|TTL on all bucket keys|\nEND',
    "corr": 'GB1/1\nFACT|90|Token bucket mathematically correct for burst smoothing\nRISK|m|Date.now() rollback can leak tokens|use monotonic clock where available|\nEND',
    "sec": 'GB1/1\nRISK|h|Header-based keying bypass (spoofed XFF)|always req.ip with trust proxy env-gated + validate|\nRISK|m|Login endpoint needs strict bucket (5/min), general endpoints looser|split limiter tiers|\nRISK|l|Timing side-channel on 429 responses|constant-time 429 body, identical for valid/invalid user|\nEND',
    "perf": 'GB1/1\nFACT|92|In-memory ops far below the network hot path\nRISK|l|Microsecond-level bucket update per request|no action at this scale|\nEND',
    "maint": 'GB1/1\nRISK|m|Magic numbers (5/min) hardcoded|central limiter config module + docs|\nRISK|l|No tests for the 429 path|add supertest coverage incl. bucket refill timing|\nEND',
    "risk": 'GB1/1\nRISK|m|Library misconfig causing lockouts at launch|dry-run in shadow mode (log-only) for 48h first|\nRISK|h|Peak-hour attack during enable|enable during lowest-traffic window with alerting on|\nEND',
    "arch": 'GB1/1\nSTEP|1|Add express-rate-limit with two tiers: login 5/min per IP, general API 100/min per IP|split limits per security analysis; library battle-tested per prior-art|burst 429 integration tests + shadow mode 48h log review|medium|\nSTEP|2|Key on req.socket.remoteAddress; XFF honored only when TRUST_PROXY is set|closes XFF spoofing per failure-modes and security|spoofed-XFF test must NOT bypass; header only honored behind the proxy|low|\nSTEP|3|Central config module with TTL on bucket keys; document restart counter-loss as accepted risk + Redis swap point|maintainability + restart risk|config review + documented RTO in README|low|\nSTEP|4|Shadow mode first (log would-block, do not block) for 48h; enable enforcement only after clean logs|risk-cost: enable in lowest traffic with alerts|alert on would-block rate >1%; dashboard panel|low|2\nSTEP|5|Alerting + runbook: 429 rate, saturation, kill-switch env to disable limiter instantly|operability and rollback|kill-switch tested in staging; rollback = one env var flip|medium|3\nEND',
    "revised": 'Here is the revised plan:\nGB1/1\nSTEP|1|Add express-rate-limit with two tiers: login 5/min per IP, general API 100/min per IP|per security analysis|burst 429 integration tests + shadow mode 48h|medium|\nSTEP|2|Key on req.socket.remoteAddress; XFF honored only when TRUST_PROXY lists the proxy|closes XFF spoofing|spoofed-XFF test must NOT bypass|low|\nSTEP|3|Central config module with TTL on bucket keys; document restart counter-loss as accepted risk + Redis swap point|maintainability + restart risk|config review + documented RTO|low|\nSTEP|4|Shadow mode 48h: log rate_limit_would_block_total, enforce only after clean logs; alert >1% would-block rate|risk-cost launch path|Grafana panel on rate_limit_would_block_total|low|2\nSTEP|5|Kill-switch RATE_LIMIT_ENABLED=false disables limiter; alert on 429 saturation; runbook rollback|operability|kill-switch test in staging verified pre-launch|medium|3\nEND',
}

verifier_calls = {"n": 0}

class Mock(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or "{}")
        sysname = body["messages"][0]["content"]
        user = body["messages"][1]["content"]
        if "VERIFIER" in sysname:
            verifier_calls["n"] += 1
            if verifier_calls["n"] == 1:
                payload = "GB1/1\nGV|REVISE|Shadow-mode lacks a named metric and the kill-switch has no test\nRISK|l|Vague observability|name concrete metric rate_limit_would_block_total + alert threshold|\nRISK|l|Rollback untested|add kill-switch test to the verify column|\nEND"
            else:
                payload = "GB1/1\nGV|PASS|feedback addressed: named metric, kill-switch verified, shadow-then-enforce path sound\nEND"
        elif "ARCHITECT" in sysname:
            payload = OUT["revised"] if "REVISION FEEDBACK" in user else OUT["arch"]
        elif "SCOUT-FACTS" in sysname: payload = OUT["facts"]
        elif "PRIOR-ART" in sysname: payload = OUT["prior"]
        elif "FAILURE-MODES" in sysname: payload = OUT["failmodes"]
        elif "ANALYST-CORRECTNESS" in sysname: payload = OUT["corr"]
        elif "ANALYST-SECURITY" in sysname: payload = OUT["sec"]
        elif "ANALYST-PERFORMANCE" in sysname: payload = OUT["perf"]
        elif "ANALYST-MAINTAINABILITY" in sysname: payload = OUT["maint"]
        elif "ANALYST-RISK-COST" in sysname: payload = OUT["risk"]
        else: payload = "GB1/1\nFACT|50|mock\nEND"
        data = json.dumps({"choices": [{"message": {"content": payload}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


srv = HTTPServer(("127.0.0.1", 0), Mock)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["GLASSBOX_LLM_BASE"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"
os.environ["GLASSBOX_LLM_MODEL"] = "claude-authored-test"
os.environ["GLASSBOX_LLM_KEY"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
os.environ.setdefault("GLASSBOX_PYTHON", sys.executable)
import glassbox_swarm as sw

out = sw.swarm("Design a login rate-limiter for a Node.js API on a single VPS",
               "Express 4, no Redis yet, ~2k req/s peak", max_passes=3)
print("converged:", out["converged"], "| passes:", out["passes"], "| agents_run:", out["agents_run"])
for h in out["pass_history"]:
    print(f"  pass {h['pass']}: {h['verdict']} | {h['reason']}")
print("trust:", out["trust_report"]["score"], "-", out["trust_report"]["verdict"])
print("steps:", len(out["synthesized_plan"]["steps"]), "| risks:", len(out["synthesized_plan"]["risks"]))
srv.shutdown()
