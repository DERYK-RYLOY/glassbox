"""Generate assets/marquee.svg - AI CLI icons floating in open space, drifting.
No panel, no frame, no background - icons + soft glow only. Self-contained SMIL.
Sources: @lobehub/icons (MIT) and aider.chat/assets/logo.svg.
"""
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "assets" / "icons"
OUT = ROOT / "assets" / "marquee.svg"

W, H = 1440, 84
Y_ICON = 26

ITEMS = [
    ("opencode.svg",   150, 34), ("claudecode.svg", 200, 34), ("codex.svg", 155, 34),
    ("copilot.svg",    155, 34), ("cursor.svg",     150, 34), ("geminicli.svg", 200, 34),
    ("windsurf.svg",   160, 34), ("mcp.svg",        125, 34), ("aider.svg", 190, 24),
]

XS, HALF = [], 0
for _, w, _ in ITEMS:
    XS.append(HALF)
    HALF += w

def cell(it, x):
    f, w, iw = it
    data = base64.b64encode((ICONS / f).read_bytes()).decode()
    ix, iy = x + (w - iw) / 2, Y_ICON + (36 - iw * 0.85) / 2
    ih = iw
    ih *= 0.85 if f != "aider.svg" else 1.0
    iy = Y_ICON + (34 - ih) / 2 + 4
    float_dur = 5 + (sum(f.encode()) % 4)
    return f"""    <g>
      <image x="{ix}" y="{iy}" width="{iw}" height="{ih}" filter="url(#soft)" href="data:image/svg+xml;base64,{data}">
        <animate attributeName="y" values="{iy};{iy - 7};{iy}" dur="{float_dur}s"
                 repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.6 1;0.4 0 0.6 1"/>
      </image>
    </g>"""

row1 = "\n".join(cell(it, x) for it, x in zip(ITEMS, XS))
row2 = "\n".join(f'    <g transform="translate({HALF},0)">{cell(it, x)}</g>' for it, x in zip(ITEMS, XS))

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="AI CLIs Glassbox works with">
  <defs>
    <filter id="soft" x="-40%" y="-40%" width="180%" height="180%">
      <feDropShadow dx="0" dy="0" stdDeviation="7" flood-color="#8b5cf6" flood-opacity="0.55"/>
    </filter>

  </defs>


  <g>
    <g>
      <animateTransform attributeName="transform" type="translate" from="0 0" to="-{HALF} 0"
                        dur="100s" repeatCount="indefinite" calcMode="linear"/>
{row1}
{row2}
    </g>
  </g>
</svg>
"""

OUT.write_text(svg, encoding="utf-8")
print("written", OUT, len(svg), "bytes | half", HALF)
