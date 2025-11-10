#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Детальный анализ: почему сигналы не приводят к открытию позиций"""

import re
from collections import defaultdict
from pathlib import Path

log_file = Path("logs/futures/futures_main_2025-11-10.log")

print("🔍 ДЕТАЛЬНЫЙ АНАЛИЗ ПРИЧИН БЛОКИРОВОК\n")

# Собираем информацию о сигналах
signals = []
current_signal = None

# Паттерны
time_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
signal_pattern = re.compile(r"✅.*?(LONG|SHORT|BEARISH|BULLISH).*?сигнал.*?для (\w+-\w+)")
block_pattern = re.compile(r"⛔.*?(\w+Filter|MTF).*?(\w+-\w+).*?([^\n]+)")
pass_pattern = re.compile(r"✅.*?(\w+Filter|MTF|OrderFlow|Liquidity).*?(\w+-\w+)")
score_pattern = re.compile(r"Итоговый.*?score.*?(\d+\.?\d*)")
position_block_pattern = re.compile(r"(MaxSizeLimiter|CorrelationFilter|уже.*?позиция|лимит.*?позиций)")

with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

print("⏳ Анализ сигналов...\n")

# Ищем сигналы и их судьбу
for i, line in enumerate(lines):
    # Новый сигнал
    if "✅" in line and ("сигнал" in line or "MA" in line) and ("LONG" in line or "SHORT" in line or "BEARISH" in line or "BULLISH" in line):
        match = signal_pattern.search(line)
        if match:
            direction = match.group(1)
            symbol = match.group(2)
            current_signal = {
                "symbol": symbol,
                "direction": direction,
                "line_num": i + 1,
                "filters_passed": [],
                "filters_blocked": [],
                "final_score": None,
                "position_blocked": None,
            }
    
    # Фильтры прошли
    if current_signal and "✅" in line and current_signal["symbol"] in line:
        for filter_name in ["LiquidityFilter", "OrderFlowFilter", "FundingRateFilter", "VolatilityRegimeFilter", "MTF", "PivotPoints", "VolumeProfile"]:
            if filter_name.lower() in line.lower() and "проходит" in line.lower() or "подтверждён" in line.lower() or "разрешён" in line.lower() or "бонус" in line.lower():
                if filter_name not in current_signal["filters_passed"]:
                    current_signal["filters_passed"].append(filter_name)
    
    # Фильтры заблокировали
    if current_signal and "⛔" in line and current_signal["symbol"] in line:
        for filter_name in ["LiquidityFilter", "OrderFlowFilter", "FundingRateFilter", "VolatilityRegimeFilter", "MTF", "MaxSizeLimiter", "CorrelationFilter"]:
            if filter_name.lower() in line.lower():
                if filter_name not in current_signal["filters_blocked"]:
                    current_signal["filters_blocked"].append(filter_name)
                    # Извлекаем причину
                    if "объём" in line.lower() or "volume" in line.lower():
                        current_signal["block_reason"] = "Недостаточный объём ликвидности"
                    elif "delta" in line.lower():
                        current_signal["block_reason"] = "Несоответствие дельты"
                    elif "mtf" in line.lower() or "multi_timeframe" in line.lower():
                        current_signal["block_reason"] = "Нет подтверждения на старшем таймфрейме"
                    elif "maxsize" in line.lower() or "лимит" in line.lower():
                        current_signal["block_reason"] = "Превышен лимит размера/количества позиций"
                    elif "correlation" in line.lower():
                        current_signal["block_reason"] = "Высокая корреляция с открытыми позициями"
    
    # Итоговый score
    if current_signal and "Итоговый" in line and "score" in line.lower():
        match = score_pattern.search(line)
        if match:
            current_signal["final_score"] = float(match.group(1))
    
    # Блокировка на уровне позиции
    if current_signal and any(x in line.lower() for x in ["maxsize", "correlation", "уже.*?позиция", "лимит.*?позиций", "не.*?открыт"]):
        if current_signal["symbol"] in line:
            current_signal["position_blocked"] = line.strip()
    
    # Сохраняем сигнал, если нашли следующий или конец обработки
    if current_signal:
        # Проверяем, закончилась ли обработка этого сигнала
        if i < len(lines) - 1:
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            # Если следующий сигнал или прошло достаточно времени
            if ("✅" in next_line and ("сигнал" in next_line or "MA" in next_line)) or i > current_signal["line_num"] + 50:
                if current_signal["filters_passed"] or current_signal["filters_blocked"]:
                    signals.append(current_signal)
                current_signal = None

# Добавляем последний сигнал
if current_signal and (current_signal["filters_passed"] or current_signal["filters_blocked"]):
    signals.append(current_signal)

# Статистика
print(f"📊 Всего обработано сигналов: {len(signals)}\n")

# Группируем по статусу
passed_all = [s for s in signals if not s["filters_blocked"] and len(s["filters_passed"]) >= 3]
blocked = [s for s in signals if s["filters_blocked"]]

print(f"✅ Сигналов, прошедших все фильтры: {len(passed_all)}")
print(f"🚫 Сигналов, заблокированных фильтрами: {len(blocked)}\n")

# Причины блокировок
block_reasons = defaultdict(int)
for s in blocked:
    if "block_reason" in s:
        block_reasons[s["block_reason"]] += 1
    else:
        block_reasons["Неизвестная причина"] += 1

print("🚫 ПРИЧИНЫ БЛОКИРОВОК:")
for reason, count in sorted(block_reasons.items(), key=lambda x: -x[1]):
    print(f"   {reason}: {count}")

# Блокировки по фильтрам
filter_blocks = defaultdict(int)
for s in blocked:
    for f in s["filters_blocked"]:
        filter_blocks[f] += 1

print(f"\n🚫 БЛОКИРОВКИ ПО ФИЛЬТРАМ:")
for filter_name, count in sorted(filter_blocks.items(), key=lambda x: -x[1]):
    print(f"   {filter_name}: {count}")

# Примеры успешных сигналов
if passed_all:
    print(f"\n✅ ПРИМЕРЫ СИГНАЛОВ, ПРОШЕДШИХ ВСЕ ФИЛЬТРЫ (первые 5):")
    for s in passed_all[:5]:
        print(f"   {s['symbol']} {s['direction']}: прошёл {len(s['filters_passed'])} фильтров")
        if s.get("final_score"):
            print(f"      Score: {s['final_score']}")
        if s.get("position_blocked"):
            print(f"      ⚠️ Блокировка на уровне позиции: {s['position_blocked'][:100]}")

# Детали по LiquidityFilter
liquidity_blocks = [s for s in blocked if "LiquidityFilter" in s["filters_blocked"]]
if liquidity_blocks:
    print(f"\n💧 ДЕТАЛИ БЛОКИРОВОК LIQUIDITY FILTER ({len(liquidity_blocks)}):")
    symbols = defaultdict(int)
    for s in liquidity_blocks:
        symbols[s["symbol"]] += 1
    for symbol, count in sorted(symbols.items(), key=lambda x: -x[1]):
        print(f"   {symbol}: {count} блокировок")

# Проверяем, были ли попытки открыть позиции
print(f"\n🔍 ПОИСК ПОПЫТОК ОТКРЫТИЯ ПОЗИЦИЙ:")
position_attempts = []
for i, line in enumerate(lines):
    if any(x in line.lower() for x in ["открыт", "позиция", "ордер", "размещён", "execute", "place"]):
        if "✅" in line or "📈" in line or "📝" in line:
            position_attempts.append((i + 1, line.strip()[:150]))

if position_attempts:
    print(f"   Найдено {len(position_attempts)} записей о позициях/ордерах:")
    for line_num, line_text in position_attempts[:10]:
        print(f"   Строка {line_num}: {line_text}")
else:
    print("   ❌ Не найдено записей об открытии позиций или размещении ордеров")

print("\n" + "="*60)

