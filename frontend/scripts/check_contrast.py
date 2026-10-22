"""Assert the palette's contrast floors, reading the tokens from the stylesheet.

The point is that a colour change cannot silently cost accessibility. The floors
here are the ones that actually apply:

- Body and label text: WCAG 1.4.3 at 4.5:1.
- The focus ring: WCAG 1.4.11 at 3:1 against the surface it sits on. The ring
  is what identifies a focused control, so it is held to the non-text floor.
- A divider: 1.3:1. A rule is decoration, not a control boundary, so it is
  not held to 3:1 -- but if it is invisible the layout stops reading.

`--rule-strong` is deliberately not held to 3:1: every one of its eleven uses
is a hover border, a decorative dot or a rule, and in all of them the label or
the state carries the meaning. The control boundary that *is* meaningful is the
focused input's border, which is `--signal`, and that is checked here.

    ../venv/Scripts/python.exe scripts/check_contrast.py
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOKENS = ROOT / "src" / "styles" / "tokens.css"


def parse_tokens() -> dict[str, str]:
    """Every colour token, hex or rgb().

    The focus ring is an alpha tint, so it cannot be read as a hex and then
    composited later -- the alpha is part of the token.
    """
    text = TOKENS.read_text(encoding="utf-8")
    found = dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", text))
    for name, value in re.findall(r"(--[a-z0-9-]+):\s*(rgb\([^)]*\))\s*;", text):
        found[name] = value
    if not found:
        raise SystemExit(f"no colour tokens found in {TOKENS}")
    return found


def channels(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def luminance(value: str) -> float:
    r, g, b = channels(value)
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        for c in (r, g, b)
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    high, low = max(la, lb), min(la, lb)
    return (high + 0.05) / (low + 0.05)


#: (foreground token, background token, minimum, what it is)
FLOORS = [
    ("--text", "--surface", 4.5, "body text on a card"),
    ("--text", "--canvas", 4.5, "body text on the page"),
    ("--text", "--surface-raised", 4.5, "body text on a raised surface"),
    ("--muted", "--surface", 4.5, "secondary text"),
    ("--muted", "--canvas", 4.5, "secondary text on the page"),
    ("--muted-strong", "--surface", 4.5, "labels"),
    ("--signal", "--surface", 4.5, "accent text"),
    ("--signal", "--canvas", 4.5, "accent text on the page"),
    ("--signal-dim", "--surface", 4.5, "accent label text"),
    ("--warning", "--surface", 4.5, "warning text"),
    ("--danger", "--surface", 4.5, "danger text"),
    ("--rule", "--surface", 1.3, "a divider"),
    ("--rule", "--canvas", 1.3, "a divider on the page"),
]

#: The focus ring is the one boundary held to the non-text floor.
FOCUS_FLOOR = 3.0


def main() -> int:
    tokens = parse_tokens()
    missing = sorted({t for pair in FLOORS for t in pair[:2]} - tokens.keys())
    if missing:
        print(f"  tokens missing from the stylesheet: {', '.join(missing)}", file=sys.stderr)
        return 1

    failures = 0
    for foreground, background, floor, what in FLOORS:
        ratio = contrast(tokens[foreground], tokens[background])
        ok = ratio >= floor
        failures += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {ratio:5.2f}:1  (>= {floor})  {foreground} on {background}  -- {what}")

    # The focus ring is an alpha tint over the surface, so it is composited
    # before it is measured. Read from the token so a change to the token is
    # followed rather than missed.
    ring = tokens.get("--signal-focus", "")
    match = re.match(r"rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*/\s*([\d.]+)%\s*\)", ring)
    if not match:
        print(f"  could not read --signal-focus ({ring!r})", file=sys.stderr)
        return 1
    r, g, b = (int(match.group(i)) for i in (1, 2, 3))
    alpha = float(match.group(4)) / 100
    backdrop = channels(tokens["--surface"])
    composited = tuple(
        alpha * (c / 255) + (1 - alpha) * bgc for c, bgc in zip((r, g, b), backdrop)
    )
    ring_hex = "#%02x%02x%02x" % tuple(round(c * 255) for c in composited)
    ratio = contrast(ring_hex, tokens["--surface"])
    ok = ratio >= FOCUS_FLOOR
    failures += 0 if ok else 1
    print(f"  {'ok  ' if ok else 'FAIL'} {ratio:5.2f}:1  (>= {FOCUS_FLOOR})  the focus ring on --surface")

    # A button's label is the canvas ink on the accent fill.
    ratio = contrast(tokens["--canvas"], tokens["--signal"])
    ok = ratio >= 4.5
    failures += 0 if ok else 1
    print(f"  {'ok  ' if ok else 'FAIL'} {ratio:5.2f}:1  (>= 4.5)  primary button label on --signal")

    if failures:
        print(f"  {failures} contrast floor(s) not met", file=sys.stderr)
        return 1
    print("  every contrast floor holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
