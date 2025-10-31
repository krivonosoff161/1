#!/usr/bin/env python3
"""
Скрипт для очистки проекта - перемещение файлов в правильные места
"""

import os
import shutil
from pathlib import Path

# Корневая директория проекта
ROOT = Path(__file__).parent.parent

# Создаем структуру архивов
ARCHIVE_STATUSES = ROOT / "docs" / "archive" / "statuses"
ARCHIVE_OLD_FILES = ROOT / "docs" / "archive" / "old_files"
ARCHIVE_STATUSES.mkdir(parents=True, exist_ok=True)
ARCHIVE_OLD_FILES.mkdir(parents=True, exist_ok=True)

# Файлы, которые должны остаться в корне
KEEP_IN_ROOT = {
    "README.md",
    "PROJECT_RULES.md",
    "CODING_STANDARDS.md",
    "requirements.txt",
    "start.bat",
    "stop_bot.bat",
    "stop_all.bat",
    "view_logs.bat",
    "run.py",  # CLI launcher
    "config.yaml",  # Если используется
}

import io
# -*- coding: utf-8 -*-
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

print("[START] Начало очистки проекта...\n")

# 1. Перемещаем все .md из корня (кроме исключений)
print("1. Перемещение .md файлов из корня...")
moved_md = 0
for md_file in ROOT.glob("*.md"):
    if md_file.name not in KEEP_IN_ROOT:
        dest = ARCHIVE_STATUSES / md_file.name
        shutil.move(str(md_file), str(dest))
        print(f"   [OK] {md_file.name} -> docs/archive/statuses/")
        moved_md += 1
print(f"   [INFO] Перемещено {moved_md} файлов\n")

# 2. Перемещаем тестовые файлы
print("2. Перемещение тестовых файлов...")
test_files = [
    ("test_futures_bot_2min.py", "tests/futures/"),
    ("test_futures_connection.py", "tests/futures/"),
]
for src_name, dest_dir in test_files:
    src = ROOT / src_name
    if src.exists():
        dest = ROOT / dest_dir / src_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        print(f"   [OK] {src_name} -> {dest_dir}")

# 3. Перемещаем скрипты
print("\n3. Перемещение скриптов...")
script_files = [
    ("check_env.py", "scripts/"),
    ("fix_test_imports.py", "scripts/"),
    ("clear_cache.bat", "scripts/"),
    ("monitor_logs.ps1", "scripts/"),
]
for src_name, dest_dir in script_files:
    src = ROOT / src_name
    if src.exists():
        dest = ROOT / dest_dir / src_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        print(f"   [OK] {src_name} -> {dest_dir}")

# 4. Перемещаем старые файлы кода
print("\n4. Перемещение старых файлов кода...")
old_files = [
    ("fix_oco_sign.patch", ARCHIVE_OLD_FILES),
    ("run_bot.py", ARCHIVE_OLD_FILES),
    ("src/main.py", ARCHIVE_OLD_FILES),
    ("src/indicators.py", ARCHIVE_OLD_FILES),
    ("src/strategies/scalping_old.py", ARCHIVE_OLD_FILES),
]
for src_path, dest_dir in old_files:
    src = ROOT / src_path
    if src.exists():
        dest = dest_dir / src.name
        shutil.move(str(src), str(dest))
        print(f"   [OK] {src_path} -> docs/archive/old_files/")

print("\n[DONE] Очистка завершена!")
print(f"\n[RESULT] Результат:")
print(f"   - Перемещено .md файлов: {moved_md}")
print(f"   - Перемещено тестовых файлов: {len(test_files)}")
print(f"   - Перемещено скриптов: {len(script_files)}")
print(f"   - Перемещено старых файлов: {len(old_files)}")
