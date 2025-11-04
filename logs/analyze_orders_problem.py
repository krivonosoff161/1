#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализ проблем с ордерами и позициями
"""
import re
from collections import defaultdict
from pathlib import Path

logs_dir = Path("logs/extracted")

# Статистика
orders_placed = []
orders_cancelled = []
orders_filled = []
positions_opened = []
errors = []

print("🔍 АНАЛИЗ ПРОБЛЕМ С ОРДЕРАМИ И ПОЗИЦИЯМИ")
print("=" * 80)

for log_file in sorted(logs_dir.glob("*.log")):
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            # Ищем размещенные ордера
            if "Лимитный ордер размещен" in line or "Рыночный ордер размещен" in line:
                time_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                order_match = re.search(r"(\d{15,})", line)
                symbol_match = re.search(r"(\w+-\w+)", line)
                if time_match and order_match:
                    orders_placed.append(
                        {
                            "time": time_match.group(1),
                            "order_id": order_match.group(1),
                            "symbol": symbol_match.group(1) if symbol_match else "N/A",
                            "line": line.strip()[:200],
                        }
                    )

            # Ищем отмененные ордера
            if (
                "отменен" in line.lower()
                or "cancelled" in line.lower()
                or "cancel" in line.lower()
            ):
                time_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                if time_match and (
                    "22:4[0-9]" in line or "22:5[0-7]" in line or "23:0" in line
                ):
                    orders_cancelled.append(
                        {"time": time_match.group(1), "line": line.strip()[:200]}
                    )

            # Ищем исполненные ордера
            if (
                "исполнен" in line.lower()
                or "filled" in line.lower()
                or "✅ Позиция открыта" in line
            ):
                time_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                if time_match:
                    orders_filled.append(
                        {"time": time_match.group(1), "line": line.strip()[:200]}
                    )

            # Ищем открытые позиции
            if "✅ Позиция открыта" in line or "Позиция.*открыта" in line:
                time_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                if time_match:
                    positions_opened.append(
                        {"time": time_match.group(1), "line": line.strip()[:200]}
                    )

            # Ищем ошибки размещения
            if (
                "Ошибка размещения" in line
                or "API error" in line
                or "code.*1" in line.lower()
            ):
                time_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                if time_match and ("22:" in line or "23:0" in line):
                    errors.append(
                        {"time": time_match.group(1), "line": line.strip()[:300]}
                    )

print(f"\n📊 СТАТИСТИКА:")
print(f"  Размещено ордеров: {len(orders_placed)}")
print(f"  Отменено ордеров: {len(orders_cancelled)}")
print(f"  Исполнено ордеров: {len(orders_filled)}")
print(f"  Открыто позиций: {len(positions_opened)}")
print(f"  Ошибок размещения: {len(errors)}")

# Группируем по символам
by_symbol = defaultdict(list)
for order in orders_placed:
    by_symbol[order["symbol"]].append(order)

print(f"\n📈 ОРДЕРА ПО СИМВОЛАМ:")
for symbol, orders in by_symbol.items():
    print(f"  {symbol}: {len(orders)} ордеров")

# Проверяем задвоение
print(f"\n🔍 ПРОВЕРКА ЗАДВОЕНИЯ:")
duplicates = []
for symbol, orders in by_symbol.items():
    if len(orders) > 3:
        # Проверяем ордера в одном временном окне (например, за 1 минуту)
        time_groups = defaultdict(list)
        for order in orders:
            time_key = order["time"][:16]  # До минуты
            time_groups[time_key].append(order)

        for time_key, group in time_groups.items():
            if len(group) > 1:
                duplicates.append((symbol, time_key, len(group)))
                print(f"  ⚠️ {symbol} в {time_key}: {len(group)} ордеров за 1 минуту")

print(f"\n❌ ОШИБКИ РАЗМЕЩЕНИЯ (22:48-23:06):")
for error in errors[-20:]:
    print(f"  {error['time']}: {error['line']}")

print(f"\n📋 ПОСЛЕДНИЕ РАЗМЕЩЕННЫЕ ОРДЕРА:")
for order in orders_placed[-30:]:
    print(f"  {order['time']}: {order['symbol']} - {order['order_id']}")
