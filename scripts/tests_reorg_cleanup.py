from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

TESTS_ROOT = Path("tests")
DATE = "2026-02-21"
RUN_TS = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")

KEEP_IN_ROOT = {
    "__init__.py",
    "README.md",
    f"TESTS_AUDIT_{DATE}.md",
    f"TESTS_AUDIT_{DATE}.json",
}

TARGETS: Dict[str, Path] = {
    "smoke": TESTS_ROOT / "smoke",
    "tools": TESTS_ROOT / "tools",
    "reports": TESTS_ROOT / "reports",
    "artifacts": TESTS_ROOT / "artifacts",
    "misc": TESTS_ROOT / "archive" / "reorganized" / "root_misc",
}

DEDUPE_ROOT = TESTS_ROOT / "archive" / "deduplicated"
MANIFEST_JSON = DEDUPE_ROOT / "manifest_latest.json"
MANIFEST_MD = DEDUPE_ROOT / "manifest_latest.md"


@dataclass
class Stats:
    before_files: int
    after_files: int
    root_files_before: int
    root_files_after: int
    moved_from_root: int
    zero_removed: int
    exact_removed: int
    near_removed: int


def iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_root_file(path: Path) -> str:
    n = path.name.lower()
    if path.suffix == ".py" and (n.startswith("test_") or n.startswith("smoke_")):
        return "smoke"
    if path.suffix == ".py" and ("tester" in n or n.startswith("run_")):
        return "tools"
    if path.suffix in {".json", ".txt"}:
        return "artifacts"
    if path.suffix == ".md":
        return "reports"
    return "misc"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    idx = 2
    while True:
        candidate = path.with_name(f"{path.stem}__dup{idx}{path.suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def move_root_files() -> List[Tuple[str, str]]:
    moved: List[Tuple[str, str]] = []
    for p in sorted(TESTS_ROOT.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        if p.name in KEEP_IN_ROOT:
            continue
        category = classify_root_file(p)
        target_dir = TARGETS[category]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = unique_path(target_dir / p.name)
        shutil.move(str(p), str(target))
        moved.append((str(p.as_posix()), str(target.as_posix())))
    return moved


def remove_zero_files() -> List[str]:
    removed: List[str] = []
    for p in iter_files(TESTS_ROOT):
        if p.name == "__init__.py":
            continue
        if p.stat().st_size == 0:
            p.unlink()
            removed.append(str(p.as_posix()))
    return removed


def path_rank(rel: str) -> int:
    r = rel.lower()
    if r.startswith("tests/unit/"):
        return 0
    if r.startswith("tests/integration/"):
        return 1
    if r.startswith("tests/futures/"):
        return 2
    if r.startswith("tests/smoke/"):
        return 3
    if r.startswith("tests/main/"):
        return 4
    if r.startswith("tests/tools/"):
        return 5
    if r.startswith("tests/reports/"):
        return 6
    if r.startswith("tests/archive/"):
        return 10
    return 7


def remove_exact_duplicates() -> List[Tuple[str, str]]:
    by_hash: Dict[str, List[Path]] = {}
    for p in iter_files(TESTS_ROOT):
        if DEDUPE_ROOT in p.parents:
            continue
        if p.name == "__init__.py":
            continue
        by_hash.setdefault(file_sha(p), []).append(p)

    removed: List[Tuple[str, str]] = []
    for group in by_hash.values():
        if len(group) < 2:
            continue
        canonical = sorted(
            group,
            key=lambda p: (
                path_rank(str(p.relative_to(Path("."))).replace("\\", "/")),
                -p.stat().st_mtime,
                len(str(p)),
            ),
        )[0]
        for p in group:
            if p == canonical:
                continue
            target = unique_path(
                DEDUPE_ROOT
                / "exact"
                / str(p.relative_to(TESTS_ROOT)).replace("\\", "/")
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(target))
            removed.append(
                (
                    str(p.as_posix()),
                    str(canonical.as_posix()),
                )
            )
    return removed


def norm_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            txt = path.read_text(encoding=enc)
            break
        except Exception:
            txt = ""
    return " ".join(txt.lower().split())


def shingle_set(text: str, width: int = 5, cap: int = 6000) -> Set[int]:
    words = text.split()[:cap]
    if not words:
        return set()
    if len(words) < width:
        return {hash(" ".join(words))}
    out: Set[int] = set()
    for i in range(len(words) - width + 1):
        out.add(hash(" ".join(words[i : i + width])))
    return out


def jaccard(a: Set[int], b: Set[int]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def remove_near_duplicates_md(threshold: float = 0.90) -> List[Tuple[str, str]]:
    # Only docs in tests, never Python tests.
    candidates = [
        p
        for p in iter_files(TESTS_ROOT)
        if p.suffix.lower() in {".md", ".txt"}
        and DEDUPE_ROOT not in p.parents
        and p.name not in KEEP_IN_ROOT
    ]

    items = []
    for p in candidates:
        txt = norm_text(p)
        items.append((p, shingle_set(txt), p.stat().st_size))

    removed: List[Tuple[str, str]] = []
    seen = set()
    for i in range(len(items)):
        p1, s1, sz1 = items[i]
        if p1 in seen:
            continue
        for j in range(i + 1, len(items)):
            p2, s2, sz2 = items[j]
            if p2 in seen:
                continue
            ratio = max(sz1, sz2) / max(1, min(sz1, sz2))
            if ratio > 1.6:
                continue
            sim = jaccard(s1, s2)
            if sim < threshold:
                continue

            rel1 = str(p1.relative_to(Path("."))).replace("\\", "/")
            rel2 = str(p2.relative_to(Path("."))).replace("\\", "/")
            if path_rank(rel1) <= path_rank(rel2):
                canonical, duplicate = p1, p2
            else:
                canonical, duplicate = p2, p1

            target = unique_path(
                DEDUPE_ROOT
                / "near"
                / str(duplicate.relative_to(TESTS_ROOT)).replace("\\", "/")
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(duplicate), str(target))
            seen.add(duplicate)
            removed.append((str(duplicate.as_posix()), str(canonical.as_posix())))
    return removed


def write_reports(
    stats: Stats,
    moved_root: List[Tuple[str, str]],
    zero_removed: List[str],
    exact_removed: List[Tuple[str, str]],
    near_removed: List[Tuple[str, str]],
) -> None:
    audit_md = TESTS_ROOT / f"TESTS_AUDIT_{DATE}.md"
    audit_json = TESTS_ROOT / f"TESTS_AUDIT_{DATE}.json"
    DEDUPE_ROOT.mkdir(parents=True, exist_ok=True)

    data = {
        "date": DATE,
        "stats": stats.__dict__,
        "moved_root": moved_root,
        "zero_removed": zero_removed,
        "exact_removed": exact_removed,
        "near_removed": near_removed,
    }
    audit_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# Tests audit",
        "",
        f"Date: {DATE}",
        "",
        "## Stats",
        f"- Files before: {stats.before_files}",
        f"- Files after: {stats.after_files}",
        f"- Root files before: {stats.root_files_before}",
        f"- Root files after: {stats.root_files_after}",
        f"- Moved from root: {stats.moved_from_root}",
        f"- Zero files removed: {stats.zero_removed}",
        f"- Exact duplicates archived: {stats.exact_removed}",
        f"- Near duplicates archived: {stats.near_removed}",
        "",
        "## Root destinations",
        "- `tests/smoke/`",
        "- `tests/tools/`",
        "- `tests/reports/`",
        "- `tests/artifacts/`",
        "- `tests/archive/reorganized/root_misc/`",
        "",
        "## Deduplicated archive",
        "- `tests/archive/deduplicated/exact/`",
        "- `tests/archive/deduplicated/near/`",
        "",
        "## Detailed manifests",
        f"- `{audit_json.as_posix()}`",
    ]
    audit_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    manifest = {
        "run_ts": RUN_TS,
        "exact_removed": exact_removed,
        "near_removed": near_removed,
    }
    MANIFEST_JSON.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    MANIFEST_MD.write_text(
        "# Tests dedupe manifest\n\n"
        + f"- Run: `{RUN_TS}`\n"
        + f"- Exact archived: {len(exact_removed)}\n"
        + f"- Near archived: {len(near_removed)}\n",
        encoding="utf-8",
    )


def count_files() -> int:
    return sum(1 for _ in iter_files(TESTS_ROOT))


def count_root_files() -> int:
    return sum(1 for p in TESTS_ROOT.iterdir() if p.is_file())


def main() -> None:
    before_files = count_files()
    root_before = count_root_files()

    moved_root = move_root_files()
    zero_removed = remove_zero_files()
    exact_removed = remove_exact_duplicates()
    near_removed = remove_near_duplicates_md(threshold=0.90)

    after_files = count_files()
    root_after = count_root_files()

    stats = Stats(
        before_files=before_files,
        after_files=after_files,
        root_files_before=root_before,
        root_files_after=root_after,
        moved_from_root=len(moved_root),
        zero_removed=len(zero_removed),
        exact_removed=len(exact_removed),
        near_removed=len(near_removed),
    )

    write_reports(stats, moved_root, zero_removed, exact_removed, near_removed)
    # Include files generated by this script itself in final counters.
    stats.after_files = count_files()
    stats.root_files_after = count_root_files()
    write_reports(stats, moved_root, zero_removed, exact_removed, near_removed)
    print(json.dumps(stats.__dict__, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
