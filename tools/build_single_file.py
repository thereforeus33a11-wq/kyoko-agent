"""Bundle the social_bridge package into one copy-pasteable file: dist/social_bridge.py

    python tools/build_single_file.py
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "social_bridge"
OUT = ROOT / "dist" / "social_bridge.py"
sys.path.insert(0, str(ROOT))


def adapter_modules():
    src = (PKG / "adapters" / "__init__.py").read_text()
    names = ast.literal_eval(re.search(r"_MODULES = (\[.*?\])", src, re.S).group(1))
    return [PKG / "adapters" / f"{n}.py" for n in names]


def strip(path):
    lines = []
    for line in path.read_text().splitlines():
        if re.match(r"\s*from \.+[\w.]* import ", line) or re.match(r"\s*from \. import ", line):
            continue
        if line.startswith("__all__"):
            continue
        lines.append(line)
    text = "\n".join(lines).strip()
    # drop the module docstring (kept as a comment header instead)
    doc = ast.get_docstring(ast.parse(text))
    if doc and text.startswith(('"""', "'''")):
        end = text.index(text[:3], 3) + 3
        text = text[end:].lstrip()
    rel = path.relative_to(ROOT)
    header = f"# {'=' * 76}\n# {rel}" + (f" — {doc.splitlines()[0]}" if doc else "") + f"\n# {'=' * 76}\n"
    return header + text + "\n"


def main():
    order = [PKG / "base.py", *adapter_modules(), PKG / "core.py", PKG / "dashboard.py", PKG / "server.py",
             PKG / "__main__.py"]
    head = ('#!/usr/bin/env python3\n'
            '"""Social Bridge (single-file build) — lets an AI post, comment and DM across social platforms,\n'
            'with a live oversight dashboard.  Requires: pip install requests\n\n'
            '    python social_bridge.py init      # writes social_bridge.json\n'
            '    python social_bridge.py check     # logs in to each enabled platform\n'
            '    python social_bridge.py serve     # API + dashboard on http://127.0.0.1:8765\n'
            '    python social_bridge.py tools     # tool definitions for your AI\n'
            '"""\n')
    body = "\n\n".join(strip(p) for p in order)
    # `from . import adapters` style lines are already removed; the __main__ guard is kept at the end.
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(head + body)
    compile(OUT.read_text(), str(OUT), "exec")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(OUT.read_text().splitlines())} lines, {len(order) - 5} adapters)")


if __name__ == "__main__":
    main()
