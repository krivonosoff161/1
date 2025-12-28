#!/usr/bin/env python3
"""
Скрипт для извлечения и анализа логов за 21.12.2025

Извлекает логи из архива и выполняет базовый анализ:
- Поиск значений SL/TP/PH
- Поиск закрытий по -0.2%
- Поиск calculate_leverage
- Поиск ошибок datetime
"""

import os
import re
import zipfile
from datetime import datetime
from pathlib import Path

# Пути
ARCHIVE_PATH = Path("logs/futures/archived/logs_2025-12-21_23-42-26.zip")
EXTRACT_PATH = Path("logs/futures/archived/logs_2025-12-21_extracted")
LOG_FILES = [
    "futures_main_2025-12-21.log",
    "info_2025-12-21.log",
    "errors_2025-12-21.log",
]


def extract_archive():
    """Извлечь архив с логами"""
    if not ARCHIVE_PATH.exists():
        print(f"❌ Архив не найден: {ARCHIVE_PATH}")
        return False

    print(f"📦 Извлечение архива: {ARCHIVE_PATH}")
    EXTRACT_PATH.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(ARCHIVE_PATH, "r") as zip_ref:
            zip_ref.extractall(EXTRACT_PATH)
        print(f"✅ Архив извлечен в: {EXTRACT_PATH}")
        return True
    except Exception as e:
        print(f"❌ Ошибка извлечения архива: {e}")
        return False


def analyze_log_file(log_path: Path, pattern: str, description: str):
    """Анализ лог-файла по паттерну"""
    if not log_path.exists():
        print(f"⚠️ Файл не найден: {log_path}")
        return []

    print(f"\n🔍 Анализ: {description}")
    print(f"   Файл: {log_path}")
    print(f"   Паттерн: {pattern}")

    matches = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    matches.append((line_num, line.strip()))

        print(f"   Найдено совпадений: {len(matches)}")
        if matches:
            print(f"   Первые 5 совпадений:")
            for line_num, line in matches[:5]:
                print(f"      Строка {line_num}: {line[:100]}...")

        return matches
    except Exception as e:
        print(f"❌ Ошибка чтения файла: {e}")
        return []


def main():
    """Основная функция"""
    print("=" * 80)
    print("АНАЛИЗ ЛОГОВ ЗА 21.12.2025")
    print("=" * 80)

    # Шаг 1: Извлечение архива
    if not extract_archive():
        print("\n⚠️ Пропуск анализа логов (архив не найден)")
        return

    # Шаг 2: Анализ каждого лог-файла
    results = {}

    for log_file in LOG_FILES:
        log_path = EXTRACT_PATH / log_file

        # Поиск значений SL/TP/PH
        results[f"{log_file}_sl_tp_ph"] = analyze_log_file(
            log_path,
            r"sl_percent|tp_percent|ph_threshold|ph_margin",
            f"SL/TP/PH значения в {log_file}",
        )

        # Поиск закрытий по -0.2%
        results[f"{log_file}_close_02"] = analyze_log_file(
            log_path,
            r"-0\.2|sl_reached|profit_harvest",
            f"Закрытия по -0.2% в {log_file}",
        )

        # Поиск calculate_leverage
        results[f"{log_file}_leverage"] = analyze_log_file(
            log_path,
            r"calculate_leverage|ADAPTIVE_LEVERAGE|leverage.*20",
            f"Расчет левериджа в {log_file}",
        )

        # Поиск ошибок datetime (только в errors.log)
        if "errors" in log_file:
            results[f"{log_file}_datetime_errors"] = analyze_log_file(
                log_path,
                r"UnboundLocalError|datetime|TypeError.*datetime",
                f"Ошибки datetime в {log_file}",
            )

    # Шаг 3: Сводка
    print("\n" + "=" * 80)
    print("СВОДКА АНАЛИЗА")
    print("=" * 80)

    total_matches = sum(len(matches) for matches in results.values())
    print(f"\nВсего найдено совпадений: {total_matches}")

    for key, matches in results.items():
        if matches:
            print(f"  {key}: {len(matches)} совпадений")

    print("\n✅ Анализ завершен!")
    print(f"📁 Результаты сохранены в: {EXTRACT_PATH}")


if __name__ == "__main__":
    main()




