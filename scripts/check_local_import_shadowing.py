#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass
class ShadowViolation:
    path: Path
    line: int
    name: str
    import_line: int
    function_name: str


class _FunctionBodyScanner(ast.NodeVisitor):
    """Scan only the current function body without entering nested scopes."""

    def __init__(self) -> None:
        self.import_lines: Dict[str, int] = {}
        self.name_loads: List[Tuple[str, int]] = []

    def _record_import(self, name: str, lineno: int) -> None:
        if not name:
            return
        if name not in self.import_lines:
            self.import_lines[name] = lineno

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".")[0]
            self._record_import(local_name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                continue
            local_name = alias.asname or alias.name
            self._record_import(local_name, node.lineno)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.name_loads.append((node.id, node.lineno))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Nested scope: skip.
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # Nested scope: skip.
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Nested scope: skip.
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # Nested scope: skip.
        return


def _iter_python_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            yield path
            continue
        if path.is_dir():
            for child in path.rglob("*.py"):
                yield child


def _check_file(path: Path) -> List[ShadowViolation]:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8-sig")
    source = source.lstrip("\ufeff")
    tree = ast.parse(source, filename=str(path))
    violations: List[ShadowViolation] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        scanner = _FunctionBodyScanner()
        for stmt in node.body:
            scanner.visit(stmt)
        for name, line in scanner.name_loads:
            import_line = scanner.import_lines.get(name)
            if import_line is None:
                continue
            if line < import_line:
                violations.append(
                    ShadowViolation(
                        path=path,
                        line=line,
                        name=name,
                        import_line=import_line,
                        function_name=node.name,
                    )
                )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail when a function uses a name before local import shadows it."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["src"],
        help="Files/directories to scan (default: src).",
    )
    args = parser.parse_args()

    all_violations: List[ShadowViolation] = []
    for file_path in _iter_python_files(Path(p) for p in args.paths):
        try:
            all_violations.extend(_check_file(file_path))
        except SyntaxError as exc:
            print(f"{file_path}:{exc.lineno}: syntax error: {exc.msg}", file=sys.stderr)
            return 2

    if not all_violations:
        return 0

    for violation in sorted(
        all_violations, key=lambda v: (str(v.path), v.line, v.name)
    ):
        print(
            f"{violation.path}:{violation.line}: "
            f"'{violation.name}' used before local import at line "
            f"{violation.import_line} in function '{violation.function_name}'"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
