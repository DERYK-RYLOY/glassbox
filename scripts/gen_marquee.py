"""Generate assets/marquee.svg - a slow, infinite, glassmorphism marquee of AI CLIs.
Fully self-contained SVG (SMIL) so it animates inside <img> on GitHub.
Glyphs are original monograms - not official trademarks.
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "assets" / "marquee.svg"

ITEMS = [
    ("OC", "OPENCODE",  "#22d3ee"),
    ("CC", "CLAUDE CODE", "#d97757"),
    ("CR", "CURSOR",    "#a5b4fc"),
    ("AD", "AIDER",     "#34d399"),
    ("GC", "GEMINI CLI","#4285f4"),
    ("CX", "CODEX CLI", "#10a37f"),
    ("CP", "COPILOT",   "#e6edf3"),
    ("WS", "WINDSURF",  "#fb923c"),
    ("MCP", "MCP",      "#8b5cf6"),
]

ITEM_W = 150
HALF = ITEM_W * len(ITEMS)
W, H = 1440, 116
Y_ICON = 22
Y_TEXT = 92

def chip(idx, key, label, color):
    x = idx * ITEM_W + 20
    cx = x + 23
    return f"""  <g>
    <rect x="{x}" y="{Y_ICON}" width="46" height="46" rx="12" fill="rgba(255,255,255,0.045)"
          stroke="{color}" stroke-opacity="0.85" stroke-width="1.6"/>
    <circle cx="{cx}" cy="{Y_ICON+23}" r="17.5" fill="{color}" fill-opacity="0.14"/>
    <text x="{cx}" y="{Y_ICON+27}" text-anchor="middle" font-family="Consolas,Menlo,monospace"
          font-size="13" font-weight="800" fill="{color}" letter-spacing="0.5">{key}</text>
    <text x="{x+23}" y="{Y_TEXT}" text-anchor="middle" font-family="Consolas,Menlo,monospace"
          font-size="9.5" fill="#dbe6ff" fill-opacity="0.92" letter-spacing="1.6">{label}</text>
  </g>"""

row = "\n".join(chip(i, *it) for i, it in enumerate(ITEMS))
row2 = "\n".join(f'<g transform="translate({HALF},0)">{chip(i, *it)}</g>' for i, it in enumerate(ITEMS))

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="AI CLIs Glassbox works with">
  <defs>
    <linearGradient id="frame" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#00e5ff" stop-opacity="0.55"/>
      <stop offset="0.5" stop-color="#8b5cf6" stop-opacity="0.55"/>
      <stop offset="1" stop-color="#00e5ff" stop-opacity="0.55"/>
    </linearGradient>
    <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.10"/>
      <stop offset="0.45" stop-color="#ffffff" stop-opacity="0.02"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0.0"/>
    </linearGradient>
    <clipPath id="win"><rect x="14" y="6" width="{W-28}" height="{H-12}" rx="18"/></clipPath>
    <linearGradient id="fadeL" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#0a0f1c" stop-opacity="1"/><stop offset="1" stop-color="#0a0f1c" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="fadeR" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#0a0f1c" stop-opacity="0"/><stop offset="1" stop-color="#0a0f1c" stop-opacity="1"/>
    </linearGradient>
  </defs>

  <rect x="2" y="2" width="{W-4}" height="{H-4}" rx="22" fill="#0a0f1c" fill-opacity="0.92"
        stroke="url(#frame)" stroke-width="1.6"/>
  <rect x="14" y="6" width="{W-28}" height="{H//2.6}" rx="18" fill="url(#sheen)" opacity="0.55" clip-path="url(#win)"/>

  <g clip-path="url(#win)">
    <g>
      <animateTransform attributeName="transform" type="translate" from="0 0" to="-{HALF} 0"
                        dur="70s" repeatCount="indefinite"/>
{row}
{row2}
    </g>
    <rect x="0" y="0" width="90" height="{H}" fill="url(#fadeL)"/>
    <rect x="{W-90}" y="0" width="90" height="{H}" fill="url(#fadeR)"/>
  </g>
</svg>
"""

OUT.write_text(svg, encoding="utf-8")
print("written", OUT, len(svg), "bytes")
