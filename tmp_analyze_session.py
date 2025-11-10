#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Анализ торговой сессии бота"""

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

log_file = Path("logs/futures/futures_main_2025-11-10.log")

if not log_file.exists():
    print(f"❌ Файл {log_file} не найден!")
    exit(1)

print(f"📊 Анализ лога: {log_file.name}\n")

# Статистика
stats = {
    "start_time": None,
    "end_time": None,
    "signals_generated": 0,
    "signals_blocked": defaultdict(int),
    "positions_opened": 0,
    "positions_closed": 0,
    "orders_placed": 0,
    "orders_filled": 0,
    "blocks_by_filter": defaultdict(int),
    "blocks_by_symbol": defaultdict(lambda: defaultdict(int)),
    "regime_detections": defaultdict(int),
    "mtf_blocks": 0,
    "orderflow_blocks": 0,
    "liquidity_blocks": 0,
    "fail_open_activations": defaultdict(int),
}

# Паттерны
time_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
signal_pattern = re.compile(r"✅.*сигнал.*для (\w+-\w+)")
block_pattern = re.compile(r"⛔.*?(\w+Filter|MTF|OrderFlow|Liquidity).*?(\w+-\w+)")
position_open_pattern = re.compile(r"📈.*?Открыта.*?(\w+-\w+)")
position_close_pattern = re.compile(r"📉.*?Закрыта.*?(\w+-\w+)")
order_pattern = re.compile(r"📝.*?Ордер.*?(\w+-\w+)")
regime_pattern = re.compile(r"Detected: (\w+)")
fail_open_pattern = re.compile(r"🔓.*?fail-open.*?(\w+Filter).*?(\w+-\w+)")

print("⏳ Обработка лога...")

with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        # Время
        time_match = time_pattern.search(line)
        if time_match:
            time_str = time_match.group(1)
            if not stats["start_time"]:
                stats["start_time"] = time_str
            stats["end_time"] = time_str
        
        # Сигналы
        if "✅" in line and "сигнал" in line:
            stats["signals_generated"] += 1
            match = signal_pattern.search(line)
            if match:
                symbol = match.group(1)
                stats["signals_blocked"][symbol] += 0  # Инициализация
        
        # Блокировки
        if "⛔" in line:
            match = block_pattern.search(line)
            if match:
                filter_name = match.group(1)
                symbol = match.group(2) if len(match.groups()) > 1 else "unknown"
                stats["blocks_by_filter"][filter_name] += 1
                stats["blocks_by_symbol"][symbol][filter_name] += 1
                
                if "MTF" in filter_name or "multi_timeframe" in line.lower():
                    stats["mtf_blocks"] += 1
                if "OrderFlow" in filter_name or "order_flow" in line.lower():
                    stats["orderflow_blocks"] += 1
                if "Liquidity" in filter_name or "liquidity" in line.lower():
                    stats["liquidity_blocks"] += 1
        
        # Позиции
        if "📈" in line and "Открыта" in line:
            stats["positions_opened"] += 1
        if "📉" in line and "Закрыта" in line:
            stats["positions_closed"] += 1
        
        # Ордера
        if "📝" in line and "Ордер" in line:
            stats["orders_placed"] += 1
        if "✅" in line and "исполнен" in line.lower():
            stats["orders_filled"] += 1
        
        # Режимы
        match = regime_pattern.search(line)
        if match:
            regime = match.group(1)
            stats["regime_detections"][regime] += 1
        
        # Fail-open
        match = fail_open_pattern.search(line)
        if match:
            filter_name = match.group(1)
            symbol = match.group(2) if len(match.groups()) > 1 else "unknown"
            stats["fail_open_activations"][f"{filter_name}:{symbol}"] += 1

# Вывод результатов
print("\n" + "="*60)
print("📈 СТАТИСТИКА ТОРГОВОЙ СЕССИИ")
print("="*60)

if stats["start_time"] and stats["end_time"]:
    try:
        start = datetime.strptime(stats["start_time"], "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(stats["end_time"], "%Y-%m-%d %H:%M:%S")
        duration = end - start
        print(f"\n⏱️  Время работы: {stats['start_time']} → {stats['end_time']}")
        print(f"   Длительность: {duration}")
    except:
        pass

print(f"\n📊 Сигналов сгенерировано: {stats['signals_generated']}")
print(f"📈 Позиций открыто: {stats['positions_opened']}")
print(f"📉 Позиций закрыто: {stats['positions_closed']}")
print(f"📝 Ордеров размещено: {stats['orders_placed']}")
print(f"✅ Ордеров исполнено: {stats['orders_filled']}")

print(f"\n🚫 БЛОКИРОВКИ ПО ФИЛЬТРАМ:")
for filter_name, count in sorted(stats["blocks_by_filter"].items(), key=lambda x: -x[1]):
    print(f"   {filter_name}: {count}")

print(f"\n🚫 БЛОКИРОВКИ ПО СИМВОЛАМ:")
for symbol in sorted(stats["blocks_by_symbol"].keys()):
    total = sum(stats["blocks_by_symbol"][symbol].values())
    print(f"   {symbol}: {total} блокировок")
    for filter_name, count in stats["blocks_by_symbol"][symbol].items():
        print(f"      - {filter_name}: {count}")

print(f"\n🧠 РЕЖИМЫ РЫНКА:")
for regime, count in sorted(stats["regime_detections"].items(), key=lambda x: -x[1]):
    print(f"   {regime}: {count}")

print(f"\n🔓 FAIL-OPEN АКТИВАЦИИ:")
if stats["fail_open_activations"]:
    for key, count in sorted(stats["fail_open_activations"].items(), key=lambda x: -x[1]):
        print(f"   {key}: {count}")
else:
    print("   Нет активаций")

print(f"\n📊 ДЕТАЛЬНАЯ СТАТИСТИКА БЛОКИРОВОК:")
print(f"   MTF блокировки: {stats['mtf_blocks']}")
print(f"   OrderFlow блокировки: {stats['orderflow_blocks']}")
print(f"   Liquidity блокировки: {stats['liquidity_blocks']}")

print("\n" + "="*60)

