#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка состояния фильтров и других модулей при старте"""

import re
from pathlib import Path

log_file = Path("logs/futures/futures_main_2025-11-10.log")

print("🔍 ПРОВЕРКА СОСТОЯНИЯ ПРИ СТАРТЕ БОТА\n")

# Ищем записи о старте и инициализации
start_pattern = re.compile(r"Запуск|Start|Initialize|инициализац")
filter_init_pattern = re.compile(r"(LiquidityFilter|OrderFlowFilter|CorrelationFilter|MaxSizeLimiter).*?(инициализ|init|reset|clear)")
position_sync_pattern = re.compile(r"Синхронизац.*?позиц|активных=|позиций.*?найдено")
max_size_pattern = re.compile(r"MaxSizeLimiter.*?(позиций|positions|size)")

print("⏳ Анализ лога...\n")

with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

# Ищем записи о старте
start_lines = []
for i, line in enumerate(lines[:500]):  # Первые 500 строк
    if any(x in line.lower() for x in ["запуск", "start", "инициализац"]):
        start_lines.append((i+1, line.strip()[:150]))

print("📊 ЗАПИСИ О СТАРТЕ И ИНИЦИАЛИЗАЦИИ:")
for line_num, line_text in start_lines[:20]:
    print(f"   Строка {line_num}: {line_text}")

# Ищем первую синхронизацию позиций
print(f"\n🔁 ПЕРВАЯ СИНХРОНИЗАЦИЯ ПОЗИЦИЙ:")
sync_found = False
for i, line in enumerate(lines):
    if "Синхронизация позиций завершена" in line:
        print(f"   Строка {i+1}: {line.strip()}")
        sync_found = True
        # Проверяем следующие строки на предмет блокировок
        for j in range(i+1, min(i+50, len(lines))):
            if "Уже открыто" in lines[j] or "позиций, лимит" in lines[j]:
                print(f"   ⚠️ Строка {j+1}: {lines[j].strip()[:150]}")
                break
        break

if not sync_found:
    print("   ❌ Не найдено записей о синхронизации")

# Ищем записи о MaxSizeLimiter
print(f"\n💰 ЗАПИСИ О MAXSIZELIMITER:")
max_size_found = False
for i, line in enumerate(lines[:1000]):
    if "MaxSizeLimiter" in line and ("позиций" in line or "positions" in line or "очищен" in line or "reset" in line.lower()):
        print(f"   Строка {i+1}: {line.strip()[:150]}")
        max_size_found = True

if not max_size_found:
    print("   ❌ Не найдено записей о MaxSizeLimiter")

# Ищем блокировки до первой синхронизации
print(f"\n🚫 БЛОКИРОВКИ ДО ПЕРВОЙ СИНХРОНИЗАЦИИ:")
first_sync_line = None
for i, line in enumerate(lines):
    if "Синхронизация позиций завершена" in line:
        first_sync_line = i + 1
        break

if first_sync_line:
    blocks_before_sync = []
    for i, line in enumerate(lines[:first_sync_line]):
        if "Уже открыто" in line or "позиций, лимит" in line or "блокировк" in line.lower():
            blocks_before_sync.append((i+1, line.strip()[:150]))
    
    if blocks_before_sync:
        print(f"   Найдено {len(blocks_before_sync)} блокировок до синхронизации:")
        for line_num, line_text in blocks_before_sync[:10]:
            print(f"   Строка {line_num}: {line_text}")
    else:
        print("   ✅ Блокировок до синхронизации не найдено")
else:
    print("   ⚠️ Не найдена первая синхронизация")

print("\n" + "="*60)

