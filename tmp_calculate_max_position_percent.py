#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Расчет оптимального max_position_size_percent для разных вариантов"""

balance = 1018
leverage = 5
position_sizes = [100, 120, 150, 200]
max_position_percent_options = [15, 18, 20, 25]

print("="*80)
print("РАСЧЕТ ОПТИМАЛЬНОГО max_position_size_percent")
print("="*80)

print(f"\n💰 Баланс: ${balance}")
print(f"   Плечо: {leverage}x\n")

print(f"{'Размер позиции':<20} {'% от баланса':<15} {'15%':<12} {'18%':<12} {'20%':<12} {'25%':<12}")
print("-"*80)

for pos_size in position_sizes:
    percent = (pos_size / balance) * 100
    checks = []
    for max_percent in max_position_percent_options:
        if percent <= max_percent:
            checks.append("✅")
        else:
            checks.append("❌")
    
    print(f"${pos_size:<19} {percent:>6.2f}%        {checks[0]:<12} {checks[1]:<12} {checks[2]:<12} {checks[3]:<12}")

print("\n" + "="*80)
print("АНАЛИЗ ПРИБЫЛЬНОСТИ")
print("="*80)

trades_per_day = 10
avg_profit_percent = 0.5
commission_rate = 0.0009

print(f"\n📊 Предположения:")
print(f"   Сделок в день: {trades_per_day}")
print(f"   Средняя прибыль на сделку: {avg_profit_percent}%")
print(f"   Комиссия: {commission_rate * 100}% (limit orders)\n")

print(f"{'max_position_size_percent':<30} {'Размер $100':<20} {'Размер $150':<20} {'Размер $200':<20}")
print("-"*70)

for max_percent in max_position_percent_options:
    results = []
    for pos_size in [100, 150, 200]:
        # Проверяем, проходит ли позиция
        pos_percent = (pos_size / balance) * 100
        if pos_percent <= max_percent:
            # Расчет прибыли
            notional = pos_size * 5  # 5 позиций
            profit_gross = (notional * avg_profit_percent) / 100
            commission = (notional * commission_rate) * 2
            profit_net = profit_gross - commission
            daily_profit = profit_net * trades_per_day
            monthly_profit = daily_profit * 30
            roi = (monthly_profit / balance) * 100
            results.append(f"${monthly_profit:.0f} ({roi:.1f}%)")
        else:
            results.append("Блокируется")
    
    print(f"{max_percent}%{'':<26} {results[0]:<20} {results[1]:<20} {results[2]:<20}")

print("\n" + "="*80)
print("РЕКОМЕНДАЦИИ")
print("="*80)

print("\n✅ max_position_size_percent: 20%")
print("   Преимущества:")
print("   - Позволяет позиции $100-150 (основные)")
print("   - Позволяет позиции $200 при необходимости")
print("   - Безопасный запас")
print("   - Потенциальная прибыль: $480-720/месяц (47-71% ROI)")

print("\n⚡ max_position_size_percent: 25%")
print("   Преимущества:")
print("   - Максимальная гибкость")
print("   - Позволяет все варианты позиций")
print("   - Потенциальная прибыль: $480-960/месяц (47-94% ROI)")
print("   ⚠️ Риск: Меньше ограничений")

print("\n💡 ИТОГОВАЯ РЕКОМЕНДАЦИЯ:")
print("   max_position_size_percent: 20%")
print("   - Оптимальный баланс между гибкостью и безопасностью")
print("   - Покрывает все необходимые размеры позиций")
print("   - Оставляет запас для маневра")

