#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Быстрая статистика по логам"""

from pathlib import Path


def count_in_file(filepath, pattern):
    count = 0
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if pattern in line:
                    count += 1
    except:
        pass
    return count


logs = list(Path("logs/temp_analysis").glob("*.log"))

print("=" * 60)
print("📊 СТАТИСТИКА ПО СЕССИЯМ")
print("=" * 60)

total_adx = 0
total_mtf = 0
total_opened = 0
total_closed = 0

for log in logs:
    adx = count_in_file(log, "ADX BLOCKED")
    mtf = count_in_file(log, "не подтвержден")
    opened = count_in_file(log, "POSITION OPENED")
    closed = count_in_file(log, "POSITION CLOSED")

    total_adx += adx
    total_mtf += mtf
    total_opened += opened
    total_closed += closed

    print(f"\n{log.name[:35]}...")
    print(f"  🚫 ADX блокировок: {adx}")
    print(f"  🚫 MTF блокировок: {mtf}")
    print(f"  ✅ Позиций открыто: {opened}")
    print(f"  🏁 Позиций закрыто: {closed}")

print("\n" + "=" * 60)
print("📈 ИТОГО ЗА ВСЕ СЕССИИ:")
print("=" * 60)
print(f"🚫 ADX заблокировал: {total_adx} сигналов")
print(f"🚫 MTF заблокировал: {total_mtf} сигналов")
print(f"✅ Позиций открыто: {total_opened}")
print(f"🏁 Позиций закрыто: {total_closed}")
print("=" * 60)

# Проверяем параметры
print("\n🔍 ПРОВЕРКА ПАРАМЕТРОВ В ПЕРВОМ ЛОГЕ:")
with open(logs[0], "r", encoding="utf-8") as f:
    lines = f.readlines()
    for i, line in enumerate(lines[:50]):
        if "ADX Filter initialized" in line:
            print(f"  Строка {i}: {line.strip()}")
        if "Threshold: $" in line:
            print(f"  Строка {i}: {line.strip()}")

print("\n🔍 ПРИМЕРЫ ADX БЛОКИРОВОК:")
with open(logs[0], "r", encoding="utf-8") as f:
    count = 0
    for line in f:
        if "ADX BLOCKED" in line and count < 5:
            print(f"  {line.strip()}")
            count += 1
