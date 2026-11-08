"""Glassbox Universal CLI - the escape hatch so Glassbox works in ANY AI CLI.

No MCP, no protocol, no config magic. Any agent that can run a shell command
can use every Glassbox tool.

usage:
    python glassbox_cli.py --list
    python glassbox_cli.py <tool> '<json-args>'        # args as JSON object
    python glassbox_cli.py <tool>                       # args read from stdin
    python glassbox_cli.py <tool> --key value --key2 '{"k":"v"}'  # kwargs

output: raw tool output on stdout (JSON where applicable). exit 0 always;
failures print {"error": ...} JSON (never a traceback).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import glassbox_server as _srv  # noqa: E402

TOOLS = {name: getattr(_srv, name) for name in dir(_srv) if name.startswith("glassbox_")}


def _coerce(v: str):
    v = v.strip()
    if v.startswith("{") or v.startswith("["):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def _banner() -> str:
    """TrueColor gradient emblem - only when attached to a tty."""
    word = "GLASSBOX"
    def hue(i, n):
        # cyan (51) -> violet (135) across the word
        return 51 + round((135 - 51) * (i / max(1, n - 1)))
    line = ""
    for i, ch in enumerate(word):
        line += f"\033[38;5;{hue(i, len(word))};1m{ch}\033[0m"
    bar = "".join(f"\033[38;5;{hue(i, 40)}m\u2588\033[0m" for i in range(40))
    return (
        "\n" + bar + "\n"
        + line + "\n"
        + "\033[38;5;97m  ELIMINATE THE BLACK BOX - EVERY CLAIM AUDITED\033[0m\n"
        + bar + "\n"
    )


def main() -> None:
    argv = sys.argv[1:]
    if sys.stdout.isatty() and not os.environ.get("GLASSBOX_NO_BANNER"):
        print(_banner())
    if not argv or argv[0] in ("--list", "-l"):
        print(json.dumps({"tools": sorted(TOOLS), "usage": __doc__.strip()}, indent=2))
        return
    tool = argv[0]
    fn = TOOLS.get(tool)
    if fn is None:
        print(json.dumps({"error": f"unknown tool: {tool}", "hint": "run --list"}))
        return
    args, kwargs = argv[1:], {}

    import inspect

    orig = getattr(fn, "__wrapped__", fn)
    try:
        params = list(inspect.signature(orig).parameters)
    except (TypeError, ValueError):
        params = []

    def normalize(payload):
        """Match pasted JSON onto the tool's actual parameters.

        Precedence: keys matching parameters -> spread (normal MCP semantics).
        Otherwise, if the tool takes exactly one parameter, the whole object is
        that parameter's value (e.g. a raw plan pasted for glassbox_* tools).
        """
        if not isinstance(payload, dict):
            return {params[0]: payload} if params else {"task": str(payload)}
        if any(k in payload for k in params):
            return payload
        if "plan_json" in params and "steps" in payload and "goal" in payload:
            # raw plan pasted for a two-arg tool (plan_json + flag)
            return {"plan_json": payload}
        if len(params) == 1:
            return {params[0]: payload}
        return payload

    if args and args[0].startswith("--"):
        for i in range(0, len(args), 2):
            val = args[i + 1]
            if val.startswith("@"):
                try:
                    val = open(val[1:], encoding="utf-8").read()
                except OSError as e:
                    print(json.dumps({"error": f"cannot read {val[1:]}: {e}"}))
                    return
            kwargs[args[i][2:]] = _coerce(val)
        # piped plan on stdin + flags on argv: fill plan_json from stdin if missing
        if "plan_json" not in kwargs and not sys.stdin.isatty():
            raw = sys.stdin.read().strip()
            if raw:
                kwargs["plan_json"] = raw
    elif args:
        try:
            payload = json.loads(args[0])
            kwargs = normalize(payload)
        except json.JSONDecodeError:
            kwargs = {params[0]: args[0]} if len(params) == 1 else {"task": args[0]}
    else:
        raw = sys.stdin.read().strip()
        if raw:
            try:
                payload = json.loads(raw)
                kwargs = normalize(payload)
            except json.JSONDecodeError:
                kwargs = {params[0]: raw} if len(params) == 1 else {"task": raw}
    try:
        out = fn(**kwargs)
    except Exception as e:  # double safety net; _guard already covers most
        out = json.dumps({"error": f"{type(e).__name__}: {e}", "tool": tool})
    print(out)


if __name__ == "__main__":
    main()
