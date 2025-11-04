#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка баланса за сессию 18:03-23:06
"""
import re
from datetime import datetime
from pathlib import Path

logs_dir = Path("logs/extracted")
time_pattern_start = re.compile(r"2025-11-03 18:0[3-9]:")
time_pattern_end = re.compile(r"2025-11-03 23:0[0-6]:")

# Паттерны для поиска баланса
balance_patterns = [
    re.compile(r"equity[=:]\s*([0-9]+\.?[0-9]*)", re.I),
    re.compile(r"баланс[=:]\s*([0-9]+\.?[0-9]*)", re.I),
    re.compile(r"\$([0-9]+\.?[0-9]*)", re.I),
    re.compile(r"balance[=:]\s*([0-9]+\.?[0-9]*)", re.I),
    re.compile(r"equity\s*([0-9]+\.?[0-9]*)", re.I),
    re.compile(r"margin[=:]\s*([0-9]+\.?[0-9]*)", re.I),
]

start_balance = None
end_balance = None
start_time = None
end_time = None

print("🔍 Поиск баланса в начале и конце сессии...")
print("=" * 80)

# Ищем баланс в начале сессии (18:03-18:09)
for log_file in sorted(logs_dir.glob("*.log")):
    if "18:0" not in log_file.name and "17:42" not in log_file.name:
        continue

    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line_num, line in enumerate(f, 1):
            if time_pattern_start.search(line) or "18:0[3-9]" in line:
                for pattern in balance_patterns:
                    match = pattern.search(line)
                    if match:
                        try:
                            balance = float(match.group(1))
                            if balance > 10 and balance < 100000:  # Разумный диапазон
                                if start_balance is None or balance < start_balance:
                                    start_balance = balance
                                    time_match = re.search(
                                        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line
                                    )
                                    if time_match:
                                        start_time = time_match.group(1)
                                    print(
                                        f"✅ Начальный баланс: ${start_balance:.2f} ({start_time})"
                                    )
                                    break
                        except:
                            pass

# Ищем баланс в конце сессии (23:00-23:06)
for log_file in sorted(logs_dir.glob("*.log")):
    if "23:0" not in log_file.name:
        continue

    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
        # Ищем в последних 5000 строках
        for line in lines[-5000:]:
            if time_pattern_end.search(line) or "23:0[0-6]" in line:
                for pattern in balance_patterns:
                    match = pattern.search(line)
                    if match:
                        try:
                            balance = float(match.group(1))
                            if balance > 10 and balance < 100000:  # Разумный диапазон
                                if end_balance is None or balance > end_balance:
                                    end_balance = balance
                                    time_match = re.search(
                                        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line
                                    )
                                    if time_match:
                                        end_time = time_match.group(1)
                                    print(
                                        f"✅ Конечный баланс: ${end_balance:.2f} ({end_time})"
                                    )
                        except:
                            pass

# Ищем упоминания баланса в логах
print("\n" + "=" * 80)
print("📊 Поиск упоминаний баланса в логах...")

# Ищем get_balance() результаты
balance_logs = []
for log_file in sorted(logs_dir.glob("*.log")):
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if ("get_balance" in line.lower() or "equity" in line.lower()) and (
                "18:0[3-9]" in line
                or "23:0[0-6]" in line
                or time_pattern_start.search(line)
                or time_pattern_end.search(line)
            ):
                # Ищем числа в строке
                numbers = re.findall(r"\d+\.?\d*", line)
                for num in numbers:
                    try:
                        val = float(num)
                        if 10 < val < 100000:
                            time_match = re.search(
                                r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line
                            )
                            if time_match:
                                balance_logs.append(
                                    (time_match.group(1), val, line.strip()[:150])
                                )
                    except:
                        pass

if balance_logs:
    print(f"\nНайдено {len(balance_logs)} упоминаний баланса:")
    for time, balance, line in sorted(balance_logs)[:10]:
        print(f"  {time}: ${balance:.2f} - {line}")

print("\n" + "=" * 80)
print("💰 ИТОГОВЫЙ РЕЗУЛЬТАТ:")
print("=" * 80)

if start_balance and end_balance:
    profit = end_balance - start_balance
    profit_percent = (profit / start_balance) * 100 if start_balance > 0 else 0

    print(f"Начальный баланс (18:03): ${start_balance:.2f}")
    print(f"Конечный баланс (23:06): ${end_balance:.2f}")
    print(f"\n{'='*80}")
    if profit > 0:
        print(f"✅ ПРИБЫЛЬ: ${profit:.2f} (+{profit_percent:.2f}%)")
    elif profit < 0:
        print(f"❌ УБЫТОК: ${abs(profit):.2f} ({profit_percent:.2f}%)")
    else:
        print(f"⚪ БЕЗ ИЗМЕНЕНИЙ: ${profit:.2f}")
else:
    print("⚠️ Не удалось найти баланс в логах")
    if start_balance:
        print(f"Начальный баланс: ${start_balance:.2f}")
    if end_balance:
        print(f"Конечный баланс: ${end_balance:.2f}")
