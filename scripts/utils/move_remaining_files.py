#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перемещение оставшихся файлов"""

import shutil
from pathlib import Path

ROOT = Path(".")

moves = [
    ("ANALYSIS_IMPROVEMENTS_AND_FIXES.md", "docs/fixes/completed/2025-12/"),
    ("REORGANIZATION_SUCCESS_REPORT.md", "docs/reports/2025-12/"),
    ("АНАЛИЗ_УСПЕШНОГО_ЗАКРЫТИЯ_DOGE_ОТ_ГРОКА.md", "docs/analysis/reports/2025-12/"),
    ("ИТОГОВЫЙ_СПИСОК_ЗАДАЧ_ОТ_ГРОКА_ФИНАЛЬНЫЙ.md", "docs/plans/2025-12/"),
    ("ИТОГОВЫЙ_СПИСОК_ЗАДАЧ_ОТ_ГРОКА.md", "docs/plans/2025-12/"),
    ("ПЛАН_ОРГАНИЗАЦИИ_ДОКУМЕНТОВ_27_12_2025.md", "docs/plans/2025-12/"),
    ("ФИНАЛЬНЫЙ_АНАЛИЗ_И_ИСПРАВЛЕНИЯ.md", "docs/analysis/reports/2025-12/"),
]

for src, dst in moves:
    src_path = ROOT / src
    dst_path = ROOT / dst / src

    if src_path.exists():
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        print(f"Moved: {src} -> {dst}")
    else:
        print(f"Not found: {src}")
