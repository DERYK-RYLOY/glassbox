"""Iron Swarm + Tiny Thinker gate: scout emits 3 relevant lines + 1 junk line;
analysts must NOT receive the junk line (checked at the HTTP layer)."""
import json, os, sys, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = {
    "facts": "GB1/1\nFACT|95|Token bucket is O(1) and correct for bursts\nFACT|10|Bananas are berries botanically\nEND",
    "prior": "GB1/1\nFACT|90|express-rate-limit is the prior art here\nEND",
    "failmodes": "GB1/1\nRISK|h|XFF spoofing bypass|key on peer IP|\nEND",
    "corr": "GB1/1\nFACT|88|Token bucket is consistent\nEND",
    "sec": "GB1/1\nRISK|h|XFF bypass|use socket IP|\nEND",
    "perf": "GB1/1\nFACT|80|O(1) per request is fine\nEND",
    "maint": "GB1/1\nRISK|m|Magic numbers|central config|\nEND",
    "risk": "GB1/1\nRISK|m|Lockout launch risk|shadow mode 48h|\nEND",
    "arch": "GB1/1\nSTEP|1|express-rate-limit two tiers|prior-art+security|burst tests|medium|\nEND",
}

seen_users = []

class Mock(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or "{}")
        s = body["messages"][0]["content"]
        user = body["messages"][1]["content"]
        if "ANALYST" in s:
            seen_users.append((s.split(".")[0], user))
        if "VERIFIER" in s:
            payload = "GB1/1\nGV|PASS|adequate\nEND"
        elif "ARCHITECT" in s: payload = OUT["arch"]
        elif "SCOUT-FACTS" in s: payload = OUT["facts"]
        elif "PRIOR-ART" in s: payload = OUT["prior"]
        elif "FAILURE-MODES" in s: payload = OUT["failmodes"]
        elif "ANALYST-CORRECTNESS" in s: payload = OUT["corr"]
        elif "ANALYST-SECURITY" in s: payload = OUT["sec"]
        elif "ANALYST-PERFORMANCE" in s: payload = OUT["perf"]
        elif "ANALYST-MAINTAINABILITY" in s: payload = OUT["maint"]
        elif "ANALYST-RISK-COST" in s: payload = OUT["risk"]
        else: payload = "GB1/1\nFACT|50|mock\nEND"
        data = json.dumps({"choices": [{"message": {"content": payload}}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass

srv = HTTPServer(("127.0.0.1", 0), Mock)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["GLASSBOX_LLM_BASE"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"
os.environ["GLASSBOX_LLM_MODEL"] = "test"
os.environ["GLASSBOX_LLM_KEY"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
os.environ.setdefault("GLASSBOX_PYTHON", sys.executable)
import glassbox_swarm as sw

out = sw.swarm("Design a login rate-limiter for a Node.js API on a single VPS",
               "Express 4, no Redis", max_passes=1, use_thinker=True)
stats = out["receipts"][0].get("thinker")
print("converged:", out["converged"], "| agents_run:", out["agents_run"])
print("thinker gate:", json.dumps(stats, indent=2)[:600] if stats else "NOT RUN")
leaked = [role for role, user in seen_users if "Bananas" in user]
print("analysts who saw the banana line (should be none):", leaked if leaked else "NONE — filtered")
n_fact = sum("Token bucket is O(1)" in user for _, user in seen_users)
print("analysts who saw the relevant FACT (>=1 expected):", n_fact)
srv.shutdown()
