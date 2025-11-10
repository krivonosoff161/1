#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка работы прогрессивной адаптации и per-symbol множителей"""

import re
from collections import defaultdict

log_file = "logs/futures/futures_main_2025-11-10.log"

print("="*80)
print("ПРОВЕРКА РАБОТЫ ВАРИАНТА B")
print("="*80)

# Читаем лог
with open(log_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Ищем записи о прогрессивной адаптации
progressive_records = []
multiplier_records = []
calculation_records = []

for line in lines:
    if "Прогрессивная адаптация" in line:
        progressive_records.append(line.strip())
    if "Per-symbol multiplier" in line:
        multiplier_records.append(line.strip())
    if "Расчет: balance=" in line and "profile=" in line:
        calculation_records.append(line.strip())

print(f"\n📊 НАЙДЕНО:")
print(f"   Прогрессивная адаптация: {len(progressive_records)} записей")
print(f"   Per-symbol множители: {len(multiplier_records)} записей")
print(f"   Расчеты размера: {len(calculation_records)} записей")

# Анализ прогрессивной адаптации
print(f"\n{'='*80}")
print("ПРОГРЕССИВНАЯ АДАПТАЦИЯ")
print(f"{'='*80}")

if progressive_records:
    # Берем последние 5 записей
    for record in progressive_records[-5:]:
        # Извлекаем баланс и размер
        balance_match = re.search(r'баланс \$([\d.]+)', record)
        size_match = re.search(r'размер \$([\d.]+)', record)
        if balance_match and size_match:
            balance = float(balance_match.group(1))
            size = float(size_match.group(1))
            print(f"   Баланс: ${balance:.2f} → Размер: ${size:.2f}")
else:
    print("   ⚠️ Записи не найдены")

# Анализ per-symbol множителей
print(f"\n{'='*80}")
print("PER-SYMBOL МНОЖИТЕЛИ")
print(f"{'='*80}")

if multiplier_records:
    symbol_multipliers = defaultdict(list)
    for record in multiplier_records:
        # Извлекаем символ, множитель и размеры
        symbol_match = re.search(r'для (\w+-\w+):', record)
        multiplier_match = re.search(r'(\d+\.\d+)x', record)
        sizes_match = re.search(r'\$([\d.]+) → \$([\d.]+)', record)
        
        if symbol_match and multiplier_match and sizes_match:
            symbol = symbol_match.group(1)
            multiplier = float(multiplier_match.group(1))
            size_before = float(sizes_match.group(1))
            size_after = float(sizes_match.group(2))
            
            symbol_multipliers[symbol].append({
                'multiplier': multiplier,
                'size_before': size_before,
                'size_after': size_after
            })
    
    for symbol, data_list in symbol_multipliers.items():
        if data_list:
            latest = data_list[-1]
            print(f"   {symbol}:")
            print(f"      Множитель: {latest['multiplier']}x")
            print(f"      Размер: ${latest['size_before']:.2f} → ${latest['size_after']:.2f}")
            print(f"      Всего применений: {len(data_list)}")
else:
    print("   ⚠️ Записи не найдены")

# Анализ расчетов размера позиции
print(f"\n{'='*80}")
print("РАСЧЕТЫ РАЗМЕРА ПОЗИЦИИ")
print(f"{'='*80}")

if calculation_records:
    # Берем последние 5 записей
    for record in calculation_records[-5:]:
        # Извлекаем информацию
        balance_match = re.search(r'balance=\$([\d.]+)', record)
        profile_match = re.search(r'profile=(\w+)', record)
        margin_match = re.search(r'margin=\$([\d.]+)', record)
        notional_match = re.search(r'notional=\$([\d.]+)', record)
        
        if balance_match and profile_match and margin_match and notional_match:
            balance = float(balance_match.group(1))
            profile = profile_match.group(1)
            margin = float(margin_match.group(1))
            notional = float(notional_match.group(1))
            
            print(f"   Баланс: ${balance:.2f}, Профиль: {profile}")
            print(f"      Маржа: ${margin:.2f}, Номинальный объем: ${notional:.2f}")
            print(f"      Использование: {(margin/balance)*100:.2f}%")
else:
    print("   ⚠️ Записи не найдены")

# Проверка ожидаемых значений
print(f"\n{'='*80}")
print("ПРОВЕРКА ОЖИДАЕМЫХ ЗНАЧЕНИЙ")
print(f"{'='*80}")

balance = 1019.0
expected_base_size = 50.0 + ((balance - 500.0) / 1000.0) * 100.0  # Формула для small
print(f"\n💰 Баланс: ${balance}")
print(f"   Ожидаемый базовый размер: ${expected_base_size:.2f}")

expected_multipliers = {
    "BTC-USDT": 1.2,
    "ETH-USDT": 1.0,
    "SOL-USDT": 0.9,
    "DOGE-USDT": 0.8,
    "XRP-USDT": 0.8,
}

print(f"\n📊 Ожидаемые размеры с множителями:")
for symbol, multiplier in expected_multipliers.items():
    expected_size = expected_base_size * multiplier
    print(f"   {symbol}: ${expected_size:.2f} (базовый ${expected_base_size:.2f} × {multiplier}x)")

# Итоговая проверка
print(f"\n{'='*80}")
print("ИТОГОВАЯ ПРОВЕРКА")
print(f"{'='*80}")

if len(progressive_records) > 0:
    print("✅ Прогрессивная адаптация: РАБОТАЕТ")
else:
    print("❌ Прогрессивная адаптация: НЕ НАЙДЕНО")

if len(multiplier_records) > 0:
    print("✅ Per-symbol множители: РАБОТАЮТ")
    print(f"   Найдено применений: {len(multiplier_records)}")
else:
    print("❌ Per-symbol множители: НЕ НАЙДЕНО")

if len(calculation_records) > 0:
    print("✅ Расчеты размера позиции: РАБОТАЮТ")
else:
    print("❌ Расчеты размера позиции: НЕ НАЙДЕНО")

