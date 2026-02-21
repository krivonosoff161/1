from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

DOCS_ROOT = Path("docs")
ARCHIVE_ROOT = DOCS_ROOT / "archive" / "deduplicated"
RUN_TS = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")

TEXT_EXTS = {".md", ".txt"}

DATE_RE = re.compile(r"(20\d{2}[-./]\d{2}[-./]\d{2})")
WS_RE = re.compile(r"\s+")
NON_WORD_RE = re.compile(r"[^a-zA-Zа-яА-Я0-9]+")
NUM_TOKEN_RE = re.compile(r"\b\d+\b")
STOP_TOKENS = {
    "final",
    "report",
    "summary",
    "analysis",
    "docs",
    "doc",
    "итог",
    "итоговый",
    "финальный",
    "анализ",
    "отчет",
    "отчёт",
    "проверка",
    "план",
    "проект",
    "fix",
    "fixes",
}


@dataclass
class DocFile:
    path: Path
    rel: str
    ext: str
    size: int
    mtime: float
    sha256: str
    text_norm: str
    name_tokens: Set[str]
    content_dates: Set[str]
    filename_dates: Set[str]
    shingle_set: Set[int]


@dataclass
class RunConfig:
    mode: str
    similarity_threshold: float
    min_shared_tokens: int
    max_size_ratio: float
    skip_archive: bool


def iter_docs_files(skip_archive: bool) -> Iterable[Path]:
    for p in DOCS_ROOT.rglob("*"):
        if not p.is_file():
            continue
        if ARCHIVE_ROOT in p.parents:
            continue
        if skip_archive and "archive" in p.parts:
            continue
        if p.suffix.lower() in TEXT_EXTS:
            yield p


def read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return path.read_text(encoding=enc, errors="strict")
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def normalize_text(text: str) -> str:
    text = text.lower()
    text = WS_RE.sub(" ", text).strip()
    return text


def tokenize_name(path: Path) -> Set[str]:
    stem = path.stem.lower()
    stem = DATE_RE.sub(" ", stem)
    stem = NON_WORD_RE.sub(" ", stem)
    stem = NUM_TOKEN_RE.sub(" ", stem)
    tokens = {t for t in stem.split() if len(t) >= 3}
    return {t for t in tokens if t not in STOP_TOKENS}


def extract_dates(text: str) -> Set[str]:
    return set(DATE_RE.findall(text))


def extract_dates_from_name(path: Path) -> Set[str]:
    return set(DATE_RE.findall(path.stem))


def make_shingles(text_norm: str, window: int = 5, limit_words: int = 8000) -> Set[int]:
    words = text_norm.split()
    if len(words) > limit_words:
        words = words[:limit_words]
    if len(words) < window:
        if not words:
            return set()
        return {hash(" ".join(words))}
    out: Set[int] = set()
    for i in range(0, len(words) - window + 1):
        out.add(hash(" ".join(words[i : i + window])))
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_docfile(path: Path) -> DocFile:
    text = read_text(path)
    text_norm = normalize_text(text)
    return DocFile(
        path=path,
        rel=str(path.relative_to(DOCS_ROOT)).replace("\\", "/"),
        ext=path.suffix.lower(),
        size=path.stat().st_size,
        mtime=path.stat().st_mtime,
        sha256=sha256_file(path),
        text_norm=text_norm,
        name_tokens=tokenize_name(path),
        content_dates=extract_dates(text),
        filename_dates=extract_dates_from_name(path),
        shingle_set=make_shingles(text_norm),
    )


def jaccard(a: Set[int], b: Set[int]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    uni = len(a | b)
    return inter / uni if uni else 0.0


def similar_enough(a: DocFile, b: DocFile, cfg: RunConfig) -> bool:
    if a.ext != b.ext:
        return False
    if min(a.size, b.size) == 0:
        return False
    size_ratio = max(a.size, b.size) / max(1, min(a.size, b.size))
    if size_ratio > cfg.max_size_ratio:
        return False

    # If both have non-overlapping explicit dates, keep both.
    if a.content_dates and b.content_dates and not (a.content_dates & b.content_dates):
        return False
    # Same for filename dates.
    if (
        a.filename_dates
        and b.filename_dates
        and not (a.filename_dates & b.filename_dates)
    ):
        return False

    sim = jaccard(a.shingle_set, b.shingle_set)
    return sim >= cfg.similarity_threshold


def path_rank(rel: str) -> int:
    rel_low = rel.lower()
    if rel_low.startswith("current/"):
        return 0
    if rel_low.startswith("plans/active/"):
        return 1
    if rel_low.startswith("architecture/"):
        return 2
    if rel_low.startswith("specifications/"):
        return 3
    if rel_low.startswith("recommendations/"):
        return 4
    if rel_low.startswith("reports/"):
        return 5
    if rel_low.startswith("analysis/"):
        return 6
    if rel_low.startswith("fixes/"):
        return 7
    if rel_low.startswith("archive/"):
        return 10
    return 8


def pick_canonical(group: List[DocFile]) -> DocFile:
    return sorted(group, key=lambda d: (path_rank(d.rel), -d.mtime, len(d.rel), d.rel))[
        0
    ]


def unique_target(base: Path) -> Path:
    if not base.exists():
        return base
    idx = 2
    while True:
        candidate = base.with_name(f"{base.stem}__dup{idx}{base.suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


class DSU:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        pa, pb = self.find(a), self.find(b)
        if pa != pb:
            self.p[pb] = pa


def build_candidate_pairs(
    files: List[DocFile], min_shared_tokens: int
) -> Set[Tuple[int, int]]:
    token_index: Dict[str, List[int]] = defaultdict(list)
    for i, df in enumerate(files):
        for tok in df.name_tokens:
            token_index[tok].append(i)

    pair_counter: Dict[Tuple[int, int], int] = Counter()
    for tok, ids in token_index.items():
        if len(ids) > 120:
            # broad token, skip to avoid noisy quadratic pairs
            continue
        ids = sorted(ids)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                pair_counter[(a, b)] += 1

    return {pair for pair, c in pair_counter.items() if c >= min_shared_tokens}


def build_run_config(mode: str) -> RunConfig:
    if mode == "aggressive":
        return RunConfig(
            mode=mode,
            similarity_threshold=0.89,
            min_shared_tokens=1,
            max_size_ratio=1.55,
            skip_archive=False,
        )
    if mode == "archive-only":
        return RunConfig(
            mode=mode,
            similarity_threshold=0.90,
            min_shared_tokens=1,
            max_size_ratio=1.55,
            skip_archive=False,
        )
    return RunConfig(
        mode="safe",
        similarity_threshold=0.93,
        min_shared_tokens=2,
        max_size_ratio=1.35,
        skip_archive=False,
    )


def run(cfg: RunConfig) -> Dict[str, object]:
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_json = ARCHIVE_ROOT / f"manifest_{RUN_TS}_{cfg.mode}.json"
    manifest_md = ARCHIVE_ROOT / f"manifest_{RUN_TS}_{cfg.mode}.md"

    files = [build_docfile(p) for p in iter_docs_files(skip_archive=cfg.skip_archive)]
    before_count = len(files)

    # Exact duplicates by hash.
    by_hash: Dict[str, List[DocFile]] = defaultdict(list)
    for df in files:
        by_hash[df.sha256].append(df)
    exact_groups = [g for g in by_hash.values() if len(g) > 1]

    exact_moves = []
    for grp in exact_groups:
        canonical = pick_canonical(grp)
        for d in grp:
            if d.path == canonical.path:
                continue
            target = unique_target(ARCHIVE_ROOT / "exact" / d.rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d.path), str(target))
            exact_moves.append(
                {
                    "from": d.rel,
                    "to": str(target.relative_to(DOCS_ROOT)).replace("\\", "/"),
                    "canonical": canonical.rel,
                }
            )

    # Rebuild files after exact moves.
    files = [build_docfile(p) for p in iter_docs_files(skip_archive=cfg.skip_archive)]

    candidates = build_candidate_pairs(files, min_shared_tokens=cfg.min_shared_tokens)
    dsu = DSU(len(files))
    checked_pairs = 0
    similar_pairs = 0

    for a, b in sorted(candidates):
        if a >= len(files) or b >= len(files):
            continue
        checked_pairs += 1
        if similar_enough(files[a], files[b], cfg):
            similar_pairs += 1
            dsu.union(a, b)

    groups: Dict[int, List[int]] = defaultdict(list)
    for i in range(len(files)):
        groups[dsu.find(i)].append(i)
    near_groups = [ids for ids in groups.values() if len(ids) > 1]

    near_moves = []
    for ids in near_groups:
        group_files = [files[i] for i in ids]
        canonical = pick_canonical(group_files)
        for d in group_files:
            if d.path == canonical.path:
                continue
            target = unique_target(ARCHIVE_ROOT / "near" / d.rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d.path), str(target))
            near_moves.append(
                {
                    "from": d.rel,
                    "to": str(target.relative_to(DOCS_ROOT)).replace("\\", "/"),
                    "canonical": canonical.rel,
                }
            )

    after_count = sum(1 for _ in iter_docs_files(skip_archive=cfg.skip_archive))

    result = {
        "run_ts": RUN_TS,
        "mode": cfg.mode,
        "similarity_threshold": cfg.similarity_threshold,
        "min_shared_tokens": cfg.min_shared_tokens,
        "max_size_ratio": cfg.max_size_ratio,
        "before_docs_files": before_count,
        "after_docs_files": after_count,
        "exact_duplicate_groups": len(exact_groups),
        "exact_moved": len(exact_moves),
        "candidate_pairs_checked": checked_pairs,
        "similar_pairs": similar_pairs,
        "near_duplicate_groups": len(near_groups),
        "near_moved": len(near_moves),
        "exact_moves": exact_moves,
        "near_moves": near_moves,
    }

    manifest_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_lines = [
        "# Deep dedupe manifest",
        "",
        f"- Run: `{RUN_TS}`",
        f"- Before files: {before_count}",
        f"- After files: {after_count}",
        f"- Exact groups: {len(exact_groups)}",
        f"- Exact moved: {len(exact_moves)}",
        f"- Candidate pairs checked: {checked_pairs}",
        f"- Similar pairs: {similar_pairs}",
        f"- Near groups: {len(near_groups)}",
        f"- Near moved: {len(near_moves)}",
        "",
        "## Exact moves",
    ]
    if exact_moves:
        md_lines.extend(
            [
                f"- `{m['from']}` -> `{m['to']}` (keep `{m['canonical']}`)"
                for m in exact_moves
            ]
        )
    else:
        md_lines.append("- none")

    md_lines.extend(["", "## Near moves"])
    if near_moves:
        md_lines.extend(
            [
                f"- `{m['from']}` -> `{m['to']}` (keep `{m['canonical']}`)"
                for m in near_moves
            ]
        )
    else:
        md_lines.append("- none")

    manifest_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deep dedupe for docs")
    parser.add_argument(
        "--mode",
        choices=("safe", "aggressive", "archive-only"),
        default="safe",
        help="safe=консервативный, aggressive=более широкий поиск похожих документов",
    )
    args = parser.parse_args()
    cfg = build_run_config(args.mode)
    data = run(cfg)
    print(json.dumps(data, ensure_ascii=True, indent=2))
