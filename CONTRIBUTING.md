# Contributing to Glassbox

Thanks for wanting to make Glassbox better. The bar here is simple: **no claim without a receipt.**

## The rules of the house

1. **Honesty over hype.** If something doesn't work yet, the README and code say so. No verdict may be produced by vibes — only by deterministic code or an explicit, surfaced model call.
2. **Every tool call must never crash the host CLI.** Tools return structured `{"error", "hint"}` JSON instead of raising. Keep it that way.
3. **GB1 travels on the wire** between agents. Output must stay ASCII-safe and byte-clean; no clever Unicode unless you tested it in a raw `cmd.exe`.
4. **The Lua core stays zero-dependency.** Pure Lua 5.4, no luarocks. Python may use `mcp`, `onnxruntime`, `tokenizers` only.
5. **Tests prove behavior, not aesthetics.** Add one when you fix a bug.

## Dev setup

```bash
python -m pip install mcp onnxruntime tokenizers
winget install DEVCOM.Lua    # or: apt install lua5.4 / brew install lua
```

Run the test suite:

```bash
python tests/adversarial_gb1.py   # mock-LLM recursion test
python tests/thinker_gate_test.py # Tiny Thinker noise-filtering test
python tests/forge_test.py        # Forge generation + ranking test
```

## PR checklist

- [ ] `python -m py_compile python/*.py` passes
- [ ] `python python/glassbox_cli.py --list` lists all tools
- [ ] Adversarial/recursive tests pass locally
- [ ] README tools table updated if you added/renamed a tool
- [ ] No secrets, no API keys, ever

Open an issue first for anything that changes the trust-scoring contract — that's the public API of the project.
