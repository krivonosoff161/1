from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

DOCS_ROOT = Path("docs")
REPORT_DATE = "2026-02-21"

KEEP_IN_ROOT = {
    "README.md",
    "PROJECT_ROADMAP.md",
    f"DOCUMENTATION_AUDIT_{REPORT_DATE}.md",
    f"DOCUMENTATION_AUDIT_{REPORT_DATE}.json",
}

ROOT_TARGETS: Dict[str, Path] = {
    "analysis": DOCS_ROOT / "archive" / "root" / "analysis",
    "fixes": DOCS_ROOT / "archive" / "root" / "fixes",
    "plans": DOCS_ROOT / "archive" / "root" / "plans",
    "reports": DOCS_ROOT / "archive" / "root" / "reports",
    "misc": DOCS_ROOT / "archive" / "root" / "misc",
}


@dataclass
class AuditResult:
    total_files_before: int
    total_files_after: int
    total_size_mb_before: float
    total_size_mb_after: float
    moved_files: List[Tuple[str, str]]
    removed_zero_files: List[str]
    removed_duplicates: List[Tuple[str, str]]
    exact_duplicate_groups_before: int
    exact_duplicate_groups_after: int


def _iter_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _duplicate_groups(root: Path) -> List[List[Path]]:
    groups: Dict[str, List[Path]] = {}
    for p in _iter_files(root):
        groups.setdefault(_file_sha256(p), []).append(p)
    return [v for v in groups.values() if len(v) > 1]


def _classify_root_file(name: str) -> str:
    n = name.lower()
    if any(
        k in n
        for k in (
            "план",
            "roadmap",
            "todo",
            "action_items",
            "что_делать",
            "start",
            "старт",
        )
    ):
        return "plans"
    if any(
        k in n
        for k in (
            "fix",
            "исправ",
            "выполнено",
            "заверш",
            "коммит",
            "commit",
            "чеклист",
            "checklist",
            "status",
            "статус",
        )
    ):
        return "fixes"
    if any(
        k in n
        for k in (
            "report",
            "отчет",
            "отчёт",
            "резюме",
            "summary",
            "сводка",
            "финальный",
            "final",
            "итог",
        )
    ):
        return "reports"
    if any(
        k in n
        for k in (
            "analysis",
            "анализ",
            "audit",
            "диагност",
            "problem",
            "проблем",
            "post-mortem",
        )
    ):
        return "analysis"
    return "misc"


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    idx = 2
    while True:
        candidate = parent / f"{stem}__dup{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def _move_root_files() -> List[Tuple[str, str]]:
    moved: List[Tuple[str, str]] = []
    for p in sorted(DOCS_ROOT.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        if p.name in KEEP_IN_ROOT:
            continue
        category = _classify_root_file(p.name)
        target_dir = ROOT_TARGETS[category]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = _next_available_path(target_dir / p.name)
        shutil.move(str(p), str(target))
        moved.append((str(p.as_posix()), str(target.as_posix())))
    return moved


def _remove_zero_files() -> List[str]:
    removed: List[str] = []
    for p in _iter_files(DOCS_ROOT):
        if p.stat().st_size == 0:
            p.unlink()
            removed.append(str(p.as_posix()))
    return removed


def _choose_canonical(paths: List[Path]) -> Path:
    preferred_prefixes = [
        ("docs", "architecture"),
        ("docs", "plans"),
        ("docs", "reports"),
        ("docs", "analysis"),
        ("docs", "fixes"),
        ("docs", "current"),
        ("docs", "archive"),
    ]

    def score(p: Path) -> Tuple[int, int, str]:
        parts = p.parts
        prefix_rank = len(preferred_prefixes)
        for idx, pref in enumerate(preferred_prefixes):
            if parts[: len(pref)] == pref:
                prefix_rank = idx
                break
        in_archive = 1 if "archive" in parts else 0
        depth = len(p.parts)
        return (prefix_rank, in_archive, depth, p.as_posix())

    return sorted(paths, key=score)[0]


def _remove_exact_duplicates() -> List[Tuple[str, str]]:
    removed: List[Tuple[str, str]] = []
    for group in _duplicate_groups(DOCS_ROOT):
        canonical = _choose_canonical(group)
        for p in group:
            if p == canonical:
                continue
            p.unlink()
            removed.append((str(p.as_posix()), str(canonical.as_posix())))
    return removed


def _docs_stats(root: Path) -> Tuple[int, float]:
    files = _iter_files(root)
    total_size = sum(p.stat().st_size for p in files)
    return len(files), round(total_size / 1024 / 1024, 2)


def run_cleanup() -> AuditResult:
    before_files, before_mb = _docs_stats(DOCS_ROOT)
    dup_before = len(_duplicate_groups(DOCS_ROOT))

    moved = _move_root_files()
    removed_zero = _remove_zero_files()
    removed_dups = _remove_exact_duplicates()

    after_files, after_mb = _docs_stats(DOCS_ROOT)
    dup_after = len(_duplicate_groups(DOCS_ROOT))

    return AuditResult(
        total_files_before=before_files,
        total_files_after=after_files,
        total_size_mb_before=before_mb,
        total_size_mb_after=after_mb,
        moved_files=moved,
        removed_zero_files=removed_zero,
        removed_duplicates=removed_dups,
        exact_duplicate_groups_before=dup_before,
        exact_duplicate_groups_after=dup_after,
    )


def write_reports(result: AuditResult) -> None:
    md_path = DOCS_ROOT / f"DOCUMENTATION_AUDIT_{REPORT_DATE}.md"
    json_path = DOCS_ROOT / f"DOCUMENTATION_AUDIT_{REPORT_DATE}.json"

    md_lines = [
        "# Аудит документации",
        "",
        f"Дата: {REPORT_DATE}",
        "",
        "## Итоги",
        f"- Файлов до: {result.total_files_before}",
        f"- Файлов после: {result.total_files_after}",
        f"- Размер до: {result.total_size_mb_before} MB",
        f"- Размер после: {result.total_size_mb_after} MB",
        f"- Перемещено из корня docs: {len(result.moved_files)}",
        f"- Удалено пустых файлов: {len(result.removed_zero_files)}",
        f"- Удалено точных дублей: {len(result.removed_duplicates)}",
        f"- Групп точных дублей до: {result.exact_duplicate_groups_before}",
        f"- Групп точных дублей после: {result.exact_duplicate_groups_after}",
        "",
        "## Где теперь roadmap проекта",
        "- Основной файл: `docs/PROJECT_ROADMAP.md`",
        "- Исходники roadmap: `docs/audit/AUDIT_ROADMAP.md`, `docs/current/ПОЛНОЕ_ОПИСАНИЕ_СТРАТЕГИИ_И_АРХИТЕКТУРЫ.md`",
        "",
        "## Архив перенесённых root-файлов",
        "- `docs/archive/root/analysis/`",
        "- `docs/archive/root/fixes/`",
        "- `docs/archive/root/plans/`",
        "- `docs/archive/root/reports/`",
        "- `docs/archive/root/misc/`",
        "",
        "## Удалённые пустые файлы",
    ]
    if result.removed_zero_files:
        md_lines.extend(f"- `{p}`" for p in result.removed_zero_files)
    else:
        md_lines.append("- нет")

    md_lines.extend(["", "## Удалённые точные дубли"])
    if result.removed_duplicates:
        md_lines.extend(
            f"- `{dup}` (оставлен `{keep}`)" for dup, keep in result.removed_duplicates
        )
    else:
        md_lines.append("- нет")

    md_lines.extend(["", "## Перемещённые root-файлы"])
    if result.moved_files:
        md_lines.extend(f"- `{src}` -> `{dst}`" for src, dst in result.moved_files)
    else:
        md_lines.append("- нет")

    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(result.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_root_docs() -> None:
    readme = DOCS_ROOT / "README.md"
    roadmap = DOCS_ROOT / "PROJECT_ROADMAP.md"

    readme.write_text(
        "\n".join(
            [
                "# Документация проекта",
                "",
                "## Структура",
                "- `docs/PROJECT_ROADMAP.md` — текущая дорожная карта проекта",
                "- `docs/architecture/` — архитектура и технический дизайн",
                "- `docs/current/` — актуальные рабочие материалы",
                "- `docs/plans/` — активные и завершённые планы",
                "- `docs/fixes/` — реализованные исправления",
                "- `docs/reports/` — отчёты по сессиям и проверкам",
                "- `docs/analysis/` — аналитика, причины проблем, выводы",
                "- `docs/archive/` — архив исторических документов",
                "",
                "## Правила",
                "- Все новые документы добавлять в тематические папки, не в корень `docs/`.",
                "- Для отчётов использовать формат имени: `YYYY-MM-DD_<topic>.md`.",
                "- Для roadmap использовать только `docs/PROJECT_ROADMAP.md`.",
                "",
                "## Последний аудит",
                f"- `docs/DOCUMENTATION_AUDIT_{REPORT_DATE}.md`",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    roadmap.write_text(
        "\n".join(
            [
                "# PROJECT ROADMAP",
                "",
                "## Где смотреть",
                "- Основной roadmap по аудиту и приоритетам: `docs/audit/AUDIT_ROADMAP.md`",
                "- Дорожная карта архитектуры и внедрения: `docs/current/ПОЛНОЕ_ОПИСАНИЕ_СТРАТЕГИИ_И_АРХИТЕКТУРЫ.md`",
                "",
                "## Текущий приоритетный контур",
                "1. Качество данных цены (stale/reconnect/fallback).",
                "2. Устойчивость exit-пайплайна и PnL consistency.",
                "3. Снижение churn и комиссионных потерь.",
                "4. Стабилизация маржи и адаптивного sizing.",
                "5. Контрольные SLO и регрессионные replay-проверки.",
                "",
                "## Правило актуализации",
                "- Обновлять только этот файл как точку входа.",
                "- Детали и артефакты хранить в профильных папках (`plans`, `reports`, `analysis`).",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    if not DOCS_ROOT.exists():
        raise SystemExit("docs directory not found")

    write_root_docs()
    result = run_cleanup()
    write_reports(result)
    print(json.dumps(result.__dict__, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
