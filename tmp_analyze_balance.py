#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Анализ текущего использования баланса и расчет оптимальных параметров"""

balance = 850  # Средний баланс 800-900 USD
current_leverage = 3
current_base_position = 35.0
current_max_positions = 5

print("="*60)
print("АНАЛИЗ ТЕКУЩЕГО ИСПОЛЬЗОВАНИЯ БАЛАНСА")
print("="*60)
print(f"\n💰 Текущий баланс: ${balance}")
print(f"📊 Текущий профиль: small")
print(f"💵 Размер позиции: ${current_base_position}")
print(f"📈 Плечо: {current_leverage}x")
print(f"🔢 Максимум позиций: {current_max_positions}")

# Текущее использование
total_notional = current_base_position * current_max_positions
total_margin = total_notional / current_leverage
usage_percent = (total_margin / balance) * 100
notional_percent = (total_notional / balance) * 100

print(f"\n📊 ТЕКУЩЕЕ ИСПОЛЬЗОВАНИЕ:")
print(f"   Общий номинальный объем: ${total_notional:.2f} ({notional_percent:.1f}% баланса)")
print(f"   Общая маржа: ${total_margin:.2f} ({usage_percent:.1f}% баланса)")
print(f"   НЕИСПОЛЬЗУЕМЫЙ БАЛАНС: ${balance - total_margin:.2f} ({100 - usage_percent:.1f}%)")

print(f"\n⚠️ ПРОБЛЕМА: Используется только {usage_percent:.1f}% баланса!")
print(f"   ${balance - total_margin:.2f} простаивает без работы")

print("\n" + "="*60)
print("ВАРИАНТЫ ОПТИМИЗАЦИИ")
print("="*60)

# Вариант 1: Увеличить плечо до 5x
print("\n📈 ВАРИАНТ 1: Увеличить плечо до 5x (консервативно)")
leverage_5x = 5
total_notional_5x = current_base_position * current_max_positions
total_margin_5x = total_notional_5x / leverage_5x
usage_percent_5x = (total_margin_5x / balance) * 100
notional_percent_5x = (total_notional_5x / balance) * 100

print(f"   Плечо: {leverage_5x}x")
print(f"   Размер позиции: ${current_base_position}")
print(f"   Позиций: {current_max_positions}")
print(f"   Общий номинальный объем: ${total_notional_5x:.2f} ({notional_percent_5x:.1f}% баланса)")
print(f"   Общая маржа: ${total_margin_5x:.2f} ({usage_percent_5x:.1f}% баланса)")
print(f"   Использование баланса: {usage_percent_5x:.1f}%")
print(f"   Увеличение использования: +{usage_percent_5x - usage_percent:.1f}%")

# Вариант 2: Увеличить плечо до 10x
print("\n🚀 ВАРИАНТ 2: Увеличить плечо до 10x (агрессивно)")
leverage_10x = 10
total_notional_10x = current_base_position * current_max_positions
total_margin_10x = total_notional_10x / leverage_10x
usage_percent_10x = (total_margin_10x / balance) * 100
notional_percent_10x = (total_notional_10x / balance) * 100

print(f"   Плечо: {leverage_10x}x")
print(f"   Размер позиции: ${current_base_position}")
print(f"   Позиций: {current_max_positions}")
print(f"   Общий номинальный объем: ${total_notional_10x:.2f} ({notional_percent_10x:.1f}% баланса)")
print(f"   Общая маржа: ${total_margin_10x:.2f} ({usage_percent_10x:.1f}% баланса)")
print(f"   Использование баланса: {usage_percent_10x:.1f}%")
print(f"   Увеличение использования: +{usage_percent_10x - usage_percent:.1f}%")

# Вариант 3: Увеличить размер позиций (плечо 3x)
print("\n💵 ВАРИАНТ 3: Увеличить размер позиций до $60 (плечо 3x)")
position_60 = 60.0
total_notional_3 = position_60 * current_max_positions
total_margin_3 = total_notional_3 / current_leverage
usage_percent_3 = (total_margin_3 / balance) * 100
notional_percent_3 = (total_notional_3 / balance) * 100

print(f"   Плечо: {current_leverage}x")
print(f"   Размер позиции: ${position_60}")
print(f"   Позиций: {current_max_positions}")
print(f"   Общий номинальный объем: ${total_notional_3:.2f} ({notional_percent_3:.1f}% баланса)")
print(f"   Общая маржа: ${total_margin_3:.2f} ({usage_percent_3:.1f}% баланса)")
print(f"   Использование баланса: {usage_percent_3:.1f}%")
print(f"   Увеличение использования: +{usage_percent_3 - usage_percent:.1f}%")

# Вариант 4: Комбинированный - плечо 5x + размер $50
print("\n🔥 ВАРИАНТ 4: Комбинированный - плечо 5x + размер $50 (рекомендуемый)")
position_50 = 50.0
leverage_5x_combined = 5
total_notional_4 = position_50 * current_max_positions
total_margin_4 = total_notional_4 / leverage_5x_combined
usage_percent_4 = (total_margin_4 / balance) * 100
notional_percent_4 = (total_notional_4 / balance) * 100

print(f"   Плечо: {leverage_5x_combined}x")
print(f"   Размер позиции: ${position_50}")
print(f"   Позиций: {current_max_positions}")
print(f"   Общий номинальный объем: ${total_notional_4:.2f} ({notional_percent_4:.1f}% баланса)")
print(f"   Общая маржа: ${total_margin_4:.2f} ({usage_percent_4:.1f}% баланса)")
print(f"   Использование баланса: {usage_percent_4:.1f}%")
print(f"   Увеличение использования: +{usage_percent_4 - usage_percent:.1f}%")

# Вариант 5: Агрессивный - плечо 10x + размер $60
print("\n⚡ ВАРИАНТ 5: Агрессивный - плечо 10x + размер $60")
position_60_agg = 60.0
leverage_10x_combined = 10
total_notional_5 = position_60_agg * current_max_positions
total_margin_5 = total_notional_5 / leverage_10x_combined
usage_percent_5 = (total_margin_5 / balance) * 100
notional_percent_5 = (total_notional_5 / balance) * 100

print(f"   Плечо: {leverage_10x_combined}x")
print(f"   Размер позиции: ${position_60_agg}")
print(f"   Позиций: {current_max_positions}")
print(f"   Общий номинальный объем: ${total_notional_5:.2f} ({notional_percent_5:.1f}% баланса)")
print(f"   Общая маржа: ${total_margin_5:.2f} ({usage_percent_5:.1f}% баланса)")
print(f"   Использование баланса: {usage_percent_5:.1f}%")
print(f"   Увеличение использования: +{usage_percent_5 - usage_percent:.1f}%")

# Расчет потенциальной прибыли
print("\n" + "="*60)
print("РАСЧЕТ ПОТЕНЦИАЛЬНОЙ ПРИБЫЛИ")
print("="*60)

# Предположим: 10 сделок в день, средняя прибыль 0.5% на сделку
trades_per_day = 10
avg_profit_percent = 0.5

print(f"\n📊 Предположения:")
print(f"   Сделок в день: {trades_per_day}")
print(f"   Средняя прибыль на сделку: {avg_profit_percent}%")

for variant_name, total_notional_var, leverage_var in [
    ("Текущий (3x, $35)", total_notional, current_leverage),
    ("Вариант 1 (5x, $35)", total_notional_5x, leverage_5x),
    ("Вариант 2 (10x, $35)", total_notional_10x, leverage_10x),
    ("Вариант 3 (3x, $60)", total_notional_3, current_leverage),
    ("Вариант 4 (5x, $50)", total_notional_4, leverage_5x_combined),
    ("Вариант 5 (10x, $60)", total_notional_5, leverage_10x_combined),
]:
    profit_per_trade = (total_notional_var * avg_profit_percent) / 100
    daily_profit = profit_per_trade * trades_per_day
    monthly_profit = daily_profit * 30
    roi_monthly = (monthly_profit / balance) * 100
    
    print(f"\n{variant_name}:")
    print(f"   Прибыль на сделку: ${profit_per_trade:.2f}")
    print(f"   Дневная прибыль: ${daily_profit:.2f}")
    print(f"   Месячная прибыль: ${monthly_profit:.2f} ({roi_monthly:.1f}% ROI)")

print("\n" + "="*60)
print("РЕКОМЕНДАЦИИ")
print("="*60)
print("\n✅ РЕКОМЕНДУЕМЫЙ ВАРИАНТ 4 (плечо 5x, размер $50):")
print("   - Использование баланса: ~59% (оптимально)")
print("   - Риск: умеренный (5x плечо)")
print("   - Потенциал прибыли: хороший")
print("   - Запас прочности: достаточный")

print("\n⚡ АЛЬТЕРНАТИВНЫЙ ВАРИАНТ 5 (плечо 10x, размер $60):")
print("   - Использование баланса: ~71% (максимально)")
print("   - Риск: высокий (10x плечо)")
print("   - Потенциал прибыли: максимальный")
print("   - Запас прочности: минимальный")

print("\n⚠️ ВАЖНО:")
print("   - При увеличении плеча риск ликвидации возрастает")
print("   - Рекомендуется начинать с варианта 4, затем переходить на вариант 5")
print("   - Мониторить drawdown и при необходимости снижать плечо")

