#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
from pathlib import Path

logs_dir = Path("logs/extracted")
equities = []

print("🔍 Поиск equity в логах...")

for log_file in sorted(logs_dir.glob("*.log")):
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            # Ищем equity в строках с временем сессии
            if re.search(r"2025-11-03 (18:0[3-9]|19:|20:|21:|22:|23:0[0-6]):", line):
                # Ищем equity=число
                match = re.search(r"equity=([0-9]+\.?[0-9]*)", line, re.I)
                if match:
                    try:
                        equity = float(match.group(1))
                        # Фильтруем разумные значения
                        if 500 < equity < 2000:
                            time_match = re.search(
                                r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line
                            )
                            if time_match:
                                equities.append((time_match.group(1), equity))
                    except:
                        pass

if equities:
    # Первая запись в начале сессии
    start_equity = None
    for time, equity in equities:
        if "18:0[3-9]" in time:
            start_equity = equity
            start_time = time
            break

    # Последняя запись в конце сессии
    end_equity = None
    for time, equity in reversed(equities):
        if "23:0[0-6]" in time:
            end_equity = equity
            end_time = time
            break

    # Если не нашли в конце, берем последнюю запись
    if not end_equity and equities:
        end_time, end_equity = equities[-1]

    # Если не нашли в начале, берем первую запись
    if not start_equity and equities:
        start_time, start_equity = equities[0]

    print("\n" + "=" * 80)
    print("💰 ФИНАНСОВЫЙ РЕЗУЛЬТАТ СЕССИИ:")
    print("=" * 80)

    if start_equity and end_equity:
        profit = end_equity - start_equity
        profit_percent = (profit / start_equity) * 100

        print(f"⏰ Начало сессии: {start_time}")
        print(f"💰 Начальный баланс (equity): ${start_equity:.2f}")
        print(f"\n⏰ Конец сессии: {end_time}")
        print(f"💰 Конечный баланс (equity): ${end_equity:.2f}")
        print(f"\n{'='*80}")
        if profit > 0:
            print(f"✅ ПРИБЫЛЬ: ${profit:.2f} (+{profit_percent:.2f}%)")
        elif profit < 0:
            print(f"❌ УБЫТОК: ${abs(profit):.2f} ({profit_percent:.2f}%)")
        else:
            print(f"⚪ БЕЗ ИЗМЕНЕНИЙ")
    else:
        print(
            f"⚠️ Найдено {len(equities)} записей equity, но не удалось определить начало/конец"
        )
        if equities:
            print(f"Первая запись: {equities[0][0]} - ${equities[0][1]:.2f}")
            print(f"Последняя запись: {equities[-1][0]} - ${equities[-1][1]:.2f}")
else:
    print("⚠️ Не найдено записей equity в логах")
