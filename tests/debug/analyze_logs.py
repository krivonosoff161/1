#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Анализ логов торгового бота"""

import os
import re
from collections import Counter
from pathlib import Path


def analyze_log_file(filepath):
    """Анализирует один лог-файл"""
    stats = {
        "adx_blocks": 0,
        "mtf_blocks": 0,
        "signals_strong": 0,
        "positions_opened": 0,
        "positions_closed": 0,
        "profit_harvesting": 0,
        "errors": 0,
        "adx_params": [],
        "ph_params": [],
    }

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                # ADX блокировки
                if "ADX BLOCKED" in line:
                    stats["adx_blocks"] += 1
                    # Ищем параметр "need +DI > -DI + X"
                    match = re.search(r"need \+DI > -DI \+ ([\d.]+)", line)
                    if match:
                        stats["adx_params"].append(float(match.group(1)))

                # MTF блокировки
                if "MTF BLOCKED" in line or "не подтвержден" in line:
                    stats["mtf_blocks"] += 1

                # Сильные сигналы
                if "SIGNAL STRONG" in line or "SIGNAL GENERATED" in line:
                    stats["signals_strong"] += 1

                # Открытые позиции
                if "POSITION OPENED" in line or "Позиция открыта" in line:
                    stats["positions_opened"] += 1

                # Закрытые позиции
                if "POSITION CLOSED" in line or "Позиция закрыта" in line:
                    stats["positions_closed"] += 1

                # Profit Harvesting
                if "PROFIT HARVESTING" in line or "Profit harvesting" in line:
                    stats["profit_harvesting"] += 1

                # Ошибки
                if "ERROR" in line or "CRITICAL" in line:
                    stats["errors"] += 1

                # ADX параметры при инициализации
                if "ADX Filter initialized" in line:
                    match = re.search(r"DI diff: ([\d.]+)", line)
                    if match:
                        stats["adx_params"].append(float(match.group(1)))

                # PH параметры
                if "Threshold: $" in line:
                    match = re.search(r"Threshold: \$([\d.]+)", line)
                    if match:
                        stats["ph_params"].append(float(match.group(1)))

    except Exception as e:
        print(f"❌ Ошибка при чтении {filepath}: {e}")

    return stats


def main():
    logs_dir = Path("logs/temp_analysis")

    if not logs_dir.exists():
        print(f"❌ Папка {logs_dir} не найдена!")
        return

    all_stats = {
        "adx_blocks": 0,
        "mtf_blocks": 0,
        "signals_strong": 0,
        "positions_opened": 0,
        "positions_closed": 0,
        "profit_harvesting": 0,
        "errors": 0,
        "adx_params": [],
        "ph_params": [],
    }

    log_files = sorted(logs_dir.glob("*.log"))

    if not log_files:
        print(f"❌ Не найдено лог-файлов в {logs_dir}")
        return

    print("=" * 80)
    print("📊 АНАЛИЗ ЛОГОВ ТОРГОВОГО БОТА")
    print("=" * 80)
    print()

    for log_file in log_files:
        print(f"📄 Анализ: {log_file.name}")
        stats = analyze_log_file(log_file)

        # Суммируем
        for key in all_stats:
            if isinstance(all_stats[key], list):
                all_stats[key].extend(stats[key])
            else:
                all_stats[key] += stats[key]

        print(f"   ADX блокировок: {stats['adx_blocks']}")
        print(f"   MTF блокировок: {stats['mtf_blocks']}")
        print(f"   Позиций открыто: {stats['positions_opened']}")
        print(f"   Позиций закрыто: {stats['positions_closed']}")
        if stats["adx_params"]:
            print(f"   ADX параметры: {set(stats['adx_params'])}")
        if stats["ph_params"]:
            print(f"   PH параметры: ${set(stats['ph_params'])}")
        print()

    print("=" * 80)
    print("📈 ИТОГОВАЯ СТАТИСТИКА")
    print("=" * 80)
    print()
    print(f"🚫 ADX блокировок: {all_stats['adx_blocks']}")
    print(f"🚫 MTF блокировок: {all_stats['mtf_blocks']}")
    print(f"📊 Сильных сигналов: {all_stats['signals_strong']}")
    print(f"✅ Позиций открыто: {all_stats['positions_opened']}")
    print(f"🏁 Позиций закрыто: {all_stats['positions_closed']}")
    print(f"✨ Profit Harvesting: {all_stats['profit_harvesting']}")
    print(f"❌ Ошибок: {all_stats['errors']}")
    print()

    if all_stats["adx_params"]:
        adx_counter = Counter(all_stats["adx_params"])
        print(f"🔧 ADX параметры (DI diff):")
        for param, count in adx_counter.most_common():
            print(f"   {param} - использовано {count} раз(а)")
        print()

    if all_stats["ph_params"]:
        ph_counter = Counter(all_stats["ph_params"])
        print(f"💰 Profit Harvesting пороги:")
        for param, count in ph_counter.most_common():
            print(f"   ${param} - использовано {count} раз(а)")
        print()

    print("=" * 80)


if __name__ == "__main__":
    main()
