"""Generate assets/marquee.svg - slow infinite glassmorphism marquee of AI CLIs.
Real icons, embedded as base64 data URIs (self-contained, animates on GitHub).
Sources: @lobehub/icons (MIT) and aider.chat/assets/logo.svg.
"""
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "assets" / "icons"
OUT = ROOT / "assets" / "marquee.svg"

ITEMS = [  # (file, label, cell width, icon width, icon height)
    ("opencode.svg",   "OPENCODE",    150, 30, 30),
    ("claudecode.svg", "CLAUDE CODE", 175, 30, 30),
    ("codex.svg",      "CODEX CLI",   155, 30, 30),
    ("copilot.svg",    "COPILOT",     150, 30, 30),
    ("cursor.svg",     "CURSOR",      140, 30, 30),
    ("geminicli.svg",  "GEMINI CLI",  175, 30, 30),
    ("windsurf.svg",   "WINDSURF",    160, 30, 30),
    ("mcp.svg",        "MCP",         125, 30, 30),
    ("aider.svg",      "AIDER",       175, 66, 20),
]

H = 92
Y_ICON, Y_TEXT = 14, 74

def x_positions():
    xs, acc = [], 0
    for _, _, w, _, _ in ITEMS:
        xs.append(acc)
        acc += w
    return xs, acc

XS, HALF = x_positions()
W = HALF

def cell(it, x):
    f, label, w, iw, ih = it
    data = base64.b64encode((ICONS / f).read_bytes()).decode()
    ix = x + (w - iw) / 2
    ly = Y_ICON + 34 if ih == 30 else Y_ICON + (34 - ih) / 2 + ih / 2 + 12
    return f"""    <g>
      <image x="{ix}" y="{Y_ICON + (30 - ih) / 2 if ih != 30 else Y_ICON}" width="{iw}" height="{ih}"
             href="data:image/svg+xml;base64,{data}"/>
      <text x="{x + w / 2}" y="{Y_TEXT}" text-anchor="middle"
            font-family="Consolas,Menlo,monospace" font-size="8.5" fill="#c9d6ff"
            fill-opacity="0.95" letter-spacing="2">{label}</text>
    </g>"""

row1 = "\n".join(cell(it, x) for it, x in zip(ITEMS, XS))
row2 = "\n".join(f'    <g transform="translate({HALF},0)">{cell(it, x)}</g>' for it, x in zip(ITEMS, XS))

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="AI CLIs Glassbox works with">
  <defs>
    <linearGradient id="frame" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#00e5ff"/><stop offset="0.5" stop-color="#8b5cf6"/><stop offset="1" stop-color="#00e5ff"/>
    </linearGradient>
    <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.14"/>
      <stop offset="0.5" stop-color="#ffffff" stop-opacity="0.03"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="fadeL" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#070b16"/><stop offset="1" stop-color="#070b16" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="fadeR" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#070b16" stop-opacity="0"/><stop offset="1" stop-color="#070b16"/>
    </linearGradient>
    <clipPath id="win"><rect x="10" y="4" width="{W-20}" height="{H-8}" rx="14"/></clipPath>
  </defs>

  <rect x="1.5" y="1.5" width="{W-3}" height="{H-3}" rx="16" fill="#070b16" fill-opacity="0.94"
        stroke="url(#frame)" stroke-opacity="0.6" stroke-width="1.3"/>
  <rect x="10" y="4" width="{W-20}" height="{H//2.6}" rx="14" fill="url(#sheen)" opacity="0.6" clip-path="url(#win)"/>

  <g clip-path="url(#win)">
    <g>
      <animateTransform attributeName="transform" type="translate" from="0 0" to="-{HALF} 0"
                        dur="90s" repeatCount="indefinite" calcMode="linear"/>
{row1}
{row2}
    </g>
    <rect x="0" y="0" width="64" height="{H}" fill="url(#fadeL)"/>
    <rect x="{W-64}" y="0" width="64" height="{H}" fill="url(#fadeR)"/>
  </g>
</svg>
"""

OUT.write_text(svg, encoding="utf-8")
print("written", OUT, len(svg), "bytes | half-width", HALF)
