from __future__ import annotations

import os
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(".")
DOCS_ROOT = PROJECT_ROOT / "docs"
OUTPUT = PROJECT_ROOT / "DOCUMENTATION_INDEX.md"


def iter_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def main() -> None:
    files = sorted(iter_files(DOCS_ROOT), key=lambda p: str(p).lower())
    by_dir = defaultdict(list)
    ext_counter = Counter()
    top_counter = Counter()

    for p in files:
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        rel_dir = p.parent.relative_to(PROJECT_ROOT).as_posix()
        top = (
            p.relative_to(DOCS_ROOT).parts[0]
            if len(p.relative_to(DOCS_ROOT).parts) > 1
            else "<root>"
        )
        by_dir[rel_dir].append(rel)
        ext_counter[p.suffix.lower() or "<none>"] += 1
        top_counter[top] += 1

    lines = [
        "# DOCUMENTATION INDEX",
        "",
        "Автогенерация полного оглавления документации проекта.",
        "",
        f"- Total files: **{len(files)}**",
        "",
        "## Быстрые входы",
        "- `docs/README.md`",
        "- `docs/PROJECT_ROADMAP.md`",
        "- `docs/development/DOCUMENTATION_STANDARDS.md`",
        "- `docs/DOCUMENTATION_AUDIT_2026-02-21.md`",
        "",
        "## Разделы верхнего уровня (`docs/*`)",
    ]

    for k in sorted(top_counter):
        lines.append(f"- `{k}`: {top_counter[k]} files")

    lines.extend(["", "## Типы файлов"])
    for ext, cnt in sorted(ext_counter.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"- `{ext}`: {cnt}")

    lines.extend(["", "## Полное оглавление по каталогам"])
    for directory in sorted(by_dir.keys()):
        lines.append("")
        lines.append(f"### `{directory}` ({len(by_dir[directory])})")
        for rel in by_dir[directory]:
            lines.append(f"- `{rel}`")

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Generated {OUTPUT.as_posix()} with {len(files)} files")


if __name__ == "__main__":
    main()
