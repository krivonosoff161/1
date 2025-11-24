#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Глубокий анализ всех логов и кода"""

import os
import re
import zipfile
from collections import defaultdict
from pathlib import Path


def analyze_all_logs():
    """Анализирует все логи включая архивы"""

    print("=" * 80)
    print("ГЛУБОКИЙ АНАЛИЗ ВСЕХ ЛОГОВ И КОДА")
    print("=" * 80)

    # Пути
    futures_logs_dir = Path("logs/futures")
    current_log = futures_logs_dir / "futures_main_2025-11-24.log"

    # Статистика ошибок
    errors = defaultdict(list)
    critical_closes = []
    zero_duration_issues = []

    # Анализируем текущий лог
    if current_log.exists():
        print(f"\n📄 Анализ текущего лога: {current_log.name}")
        analyze_log_file(current_log, errors, critical_closes, zero_duration_issues)

    # Анализируем архивы
    zip_files = list(futures_logs_dir.glob("*.zip"))
    print(f"\n📦 Найдено архивов: {len(zip_files)}")

    analyzed_count = 0
    for zip_file in sorted(zip_files, key=lambda x: x.stat().st_mtime, reverse=True)[
        :20
    ]:
        try:
            with zipfile.ZipFile(zip_file, "r") as z:
                for log_name in z.namelist():
                    if log_name.endswith(".log"):
                        with z.open(log_name) as f:
                            # Читаем небольшой кусок для анализа
                            content = f.read(10000).decode("utf-8", errors="ignore")
                            analyze_log_content(
                                content, errors, critical_closes, zero_duration_issues
                            )
                            analyzed_count += 1
        except Exception as e:
            print(f"⚠️ Ошибка чтения {zip_file.name}: {e}")

    print(f"\n✅ Проанализировано логов: {analyzed_count}")

    # Результаты
    print("\n" + "=" * 80)
    print("РЕЗУЛЬТАТЫ АНАЛИЗА")
    print("=" * 80)

    if errors:
        print(f"\n❌ Найдено типов ошибок: {len(errors)}")
        for error_type, occurrences in sorted(
            errors.items(), key=lambda x: len(x[1]), reverse=True
        )[:10]:
            print(f"  {error_type}: {len(occurrences)}")

    return errors, critical_closes, zero_duration_issues


def analyze_log_file(log_path, errors, critical_closes, zero_duration_issues):
    """Анализирует один лог файл"""
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            # Читаем по частям
            chunk_size = 10000
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                analyze_log_content(
                    chunk, errors, critical_closes, zero_duration_issues
                )
    except Exception as e:
        print(f"⚠️ Ошибка чтения {log_path}: {e}")


def analyze_log_content(content, errors, critical_closes, zero_duration_issues):
    """Анализирует содержимое лога"""
    # Ищем ошибки
    error_patterns = [
        (r"ERROR|CRITICAL", "ERROR/CRITICAL"),
        (r"Exception", "Exception"),
        (r"Traceback", "Traceback"),
        (r"❌", "Критическая ошибка"),
    ]

    for pattern, error_type in error_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            errors[error_type].extend(matches)

    # Ищем критические закрытия
    if "critical_loss_cut_2x" in content:
        critical_closes.append("found")

    # Ищем проблемы с duration
    if "duration_sec.*0\.0|duration.*0" in content:
        zero_duration_issues.append("found")


if __name__ == "__main__":
    errors, critical_closes, zero_duration_issues = analyze_all_logs()
