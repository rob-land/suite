#!/usr/bin/env python3
"""Generate vendorable token files from tokens.yaml.

Outputs (checked in, so consumers can vendor without running this):
  out/tokens.css  — CSS custom properties (hearth web bits, GTK CSS)
  out/tokens.py   — flat Python constants (couch, zoetrope, hearth)

Names flatten as GROUP_KEY (py) / --suite-group-key (css).
"""
from __future__ import annotations

import pathlib

import yaml

HERE = pathlib.Path(__file__).parent
OUT = HERE / "out"


def _flat(tokens: dict) -> list[tuple[str, object]]:
    out = []
    for group, entries in tokens.items():
        for key, value in entries.items():
            out.append((f"{group}_{key}".replace("-", "_"), value))
    return out


def _css_value(value: object) -> str:
    if isinstance(value, list):
        return " / ".join(str(v) for v in value)
    return str(value)


def main() -> None:
    tokens = yaml.safe_load((HERE / "tokens.yaml").read_text())
    OUT.mkdir(exist_ok=True)
    flat = _flat(tokens)

    css = ["/* Generated from tokens.yaml — do not edit by hand. */", ":root {"]
    for name, value in flat:
        # Units are encoded in the token names (…_px, …_dmm, …_ms);
        # values emit verbatim.
        prop = "--suite-" + name.replace("_", "-")
        css.append(f"  {prop}: {_css_value(value)};")
    css.append("}")
    (OUT / "tokens.css").write_text("\n".join(css) + "\n")

    py = [
        '"""Generated from tokens.yaml — do not edit by hand."""',
        "",
    ]
    for name, value in flat:
        py.append(f"{name.upper()} = {value!r}")
    py.append("")
    (OUT / "tokens.py").write_text("\n".join(py))
    print(f"wrote {OUT/'tokens.css'} and {OUT/'tokens.py'} ({len(flat)} tokens)")


if __name__ == "__main__":
    main()
