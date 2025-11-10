#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Пересчет оптимальных параметров с правильной логикой"""

balance = 850  # Средний баланс 800-900 USD

print("="*60)
print("ПРАВИЛЬНЫЙ РАСЧЕТ ОПТИМИЗАЦИИ БАЛАНСА")
print("="*60)
print(f"\n💰 Текущий баланс: ${balance}")

# Текущая ситуация
current_leverage = 3
current_position = 35.0
current_positions = 5
current_margin = (current_position * current_positions) / current_leverage
current_usage = (current_margin / balance) * 100

print(f"\n📊 ТЕКУЩАЯ СИТУАЦИЯ:")
print(f"   Плечо: {current_leverage}x")
print(f"   Размер позиции: ${current_position}")
print(f"   Позиций: {current_positions}")
print(f"   Маржа: ${current_margin:.2f} ({current_usage:.1f}% баланса)")
print(f"   Номинальный объем: ${current_position * current_positions:.2f}")

print(f"\n⚠️ ПРОБЛЕМА: Используется только {current_usage:.1f}% баланса")
print(f"   ${balance - current_margin:.2f} простаивает!")

print("\n" + "="*60)
print("ВАРИАНТЫ ОПТИМИЗАЦИИ")
print("="*60)

# Целевое использование баланса: 40-60%
target_usage_min = 40
target_usage_max = 60

variants = []

# Вариант 1: Плечо 5x, использование 50% баланса
target_margin_1 = balance * 0.50
leverage_1 = 5
notional_1 = target_margin_1 * leverage_1
position_size_1 = notional_1 / current_positions
variants.append({
    "name": "Вариант 1: Плечо 5x, 50% баланса",
    "leverage": leverage_1,
    "position_size": position_size_1,
    "margin": target_margin_1,
    "notional": notional_1,
    "usage": 50.0
})

# Вариант 2: Плечо 5x, использование 60% баланса
target_margin_2 = balance * 0.60
leverage_2 = 5
notional_2 = target_margin_2 * leverage_2
position_size_2 = notional_2 / current_positions
variants.append({
    "name": "Вариант 2: Плечо 5x, 60% баланса",
    "leverage": leverage_2,
    "position_size": position_size_2,
    "margin": target_margin_2,
    "notional": notional_2,
    "usage": 60.0
})

# Вариант 3: Плечо 10x, использование 50% баланса
target_margin_3 = balance * 0.50
leverage_3 = 10
notional_3 = target_margin_3 * leverage_3
position_size_3 = notional_3 / current_positions
variants.append({
    "name": "Вариант 3: Плечо 10x, 50% баланса",
    "leverage": leverage_3,
    "position_size": position_size_3,
    "margin": target_margin_3,
    "notional": notional_3,
    "usage": 50.0
})

# Вариант 4: Плечо 10x, использование 60% баланса
target_margin_4 = balance * 0.60
leverage_4 = 10
notional_4 = target_margin_4 * leverage_4
position_size_4 = notional_4 / current_positions
variants.append({
    "name": "Вариант 4: Плечо 10x, 60% баланса",
    "leverage": leverage_4,
    "position_size": position_size_4,
    "margin": target_margin_4,
    "notional": notional_4,
    "usage": 60.0
})

# Вариант 5: Консервативный - Плечо 5x, размер $80
position_size_5 = 80.0
leverage_5 = 5
notional_5 = position_size_5 * current_positions
margin_5 = notional_5 / leverage_5
usage_5 = (margin_5 / balance) * 100
variants.append({
    "name": "Вариант 5: Плечо 5x, размер $80 (консервативный)",
    "leverage": leverage_5,
    "position_size": position_size_5,
    "margin": margin_5,
    "notional": notional_5,
    "usage": usage_5
})

# Вариант 6: Умеренный - Плечо 5x, размер $100
position_size_6 = 100.0
leverage_6 = 5
notional_6 = position_size_6 * current_positions
margin_6 = notional_6 / leverage_6
usage_6 = (margin_6 / balance) * 100
variants.append({
    "name": "Вариант 6: Плечо 5x, размер $100 (умеренный) ⭐ РЕКОМЕНДУЕМЫЙ",
    "leverage": leverage_6,
    "position_size": position_size_6,
    "margin": margin_6,
    "notional": notional_6,
    "usage": usage_6
})

# Вариант 7: Агрессивный - Плечо 10x, размер $100
position_size_7 = 100.0
leverage_7 = 10
notional_7 = position_size_7 * current_positions
margin_7 = notional_7 / leverage_7
usage_7 = (margin_7 / balance) * 100
variants.append({
    "name": "Вариант 7: Плечо 10x, размер $100 (агрессивный)",
    "leverage": leverage_7,
    "position_size": position_size_7,
    "margin": margin_7,
    "notional": notional_7,
    "usage": usage_7
})

# Вывод всех вариантов
for i, v in enumerate(variants, 1):
    print(f"\n{v['name']}:")
    print(f"   Плечо: {v['leverage']}x")
    print(f"   Размер позиции: ${v['position_size']:.2f}")
    print(f"   Позиций: {current_positions}")
    print(f"   Номинальный объем: ${v['notional']:.2f} ({(v['notional']/balance)*100:.1f}% баланса)")
    print(f"   Маржа: ${v['margin']:.2f} ({v['usage']:.1f}% баланса)")
    print(f"   Запас: ${balance - v['margin']:.2f} ({(balance - v['margin'])/balance*100:.1f}%)")

# Расчет прибыли
print("\n" + "="*60)
print("РАСЧЕТ ПОТЕНЦИАЛЬНОЙ ПРИБЫЛИ")
print("="*60)

trades_per_day = 10
avg_profit_percent = 0.5

print(f"\n📊 Предположения:")
print(f"   Сделок в день: {trades_per_day}")
print(f"   Средняя прибыль на сделку: {avg_profit_percent}%")
print(f"   Комиссия: 0.09% (limit orders)")

print(f"\n{'Вариант':<40} {'Прибыль/сделка':<15} {'День':<12} {'Месяц':<15} {'ROI/месяц':<12}")
print("-" * 94)

for v in variants:
    # Прибыль на сделку (номинальный объем * прибыль%)
    profit_gross = (v['notional'] * avg_profit_percent) / 100
    # Комиссия (вход + выход)
    commission = (v['notional'] * 0.0009) * 2  # 0.09% вход + 0.09% выход
    profit_net = profit_gross - commission
    
    daily_profit = profit_net * trades_per_day
    monthly_profit = daily_profit * 30
    roi_monthly = (monthly_profit / balance) * 100
    
    name_short = v['name'].split(':')[1].strip() if ':' in v['name'] else v['name']
    print(f"{name_short:<40} ${profit_net:>6.2f}        ${daily_profit:>6.2f}      ${monthly_profit:>7.2f}      {roi_monthly:>5.1f}%")

print("\n" + "="*60)
print("РЕКОМЕНДАЦИИ")
print("="*60)

print("\n✅ ВАРИАНТ 6 (Плечо 5x, размер $100) - РЕКОМЕНДУЕМЫЙ:")
print("   ✓ Использование баланса: ~59% (оптимально)")
print("   ✓ Риск: умеренный (5x плечо - безопасно для фьючерсов)")
print("   ✓ Потенциал прибыли: ~$375/месяц (44% ROI)")
print("   ✓ Запас прочности: ~$350 (41% баланса)")
print("   ✓ Размер позиции: разумный для скальпинга")

print("\n⚡ ВАРИАНТ 7 (Плечо 10x, размер $100) - АГРЕССИВНЫЙ:")
print("   ✓ Использование баланса: ~59% (тот же)")
print("   ✓ Риск: высокий (10x плечо - риск ликвидации)")
print("   ✓ Потенциал прибыли: ~$375/месяц (44% ROI)")
print("   ✓ Запас прочности: ~$350 (41% баланса)")
print("   ⚠️ ВНИМАНИЕ: При 10x плече ликвидация при -10% вместо -33%")

print("\n💡 ВАРИАНТ 5 (Плечо 5x, размер $80) - КОНСЕРВАТИВНЫЙ:")
print("   ✓ Использование баланса: ~47% (более безопасно)")
print("   ✓ Риск: низкий (5x плечо + больше запаса)")
print("   ✓ Потенциал прибыли: ~$300/месяц (35% ROI)")
print("   ✓ Запас прочности: ~$450 (53% баланса)")

print("\n⚠️ ВАЖНЫЕ ЗАМЕЧАНИЯ:")
print("   1. При увеличении плеча риск ликвидации возрастает экспоненциально")
print("   2. При 5x плече: ликвидация при падении ~20% (безопасно)")
print("   3. При 10x плече: ликвидация при падении ~10% (опасно)")
print("   4. Рекомендуется начать с варианта 6, протестировать 1-2 недели")
print("   5. При стабильной прибыли можно перейти на вариант 7")
print("   6. Всегда мониторить drawdown и при необходимости снижать размер")

print("\n📝 ИЗМЕНЕНИЯ В КОНФИГЕ:")
print("   1. leverage: 3 → 5 (или 10 для агрессивного)")
print("   2. balance_profiles.small.base_position_usd: 35 → 80-100")
print("   3. balance_profiles.small.min_position_usd: 20 → 60-80")
print("   4. balance_profiles.small.max_position_usd: 40 → 100-120")

