#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Пересчет с правильным балансом и вариантами для разных балансов"""

balances = [200, 500, 1018]
current_leverage = 5  # После изменений
current_base_position = 100.0  # После изменений
current_positions = 5

print("=" * 70)
print("ПЕРЕСЧЕТ С ПРАВИЛЬНЫМ БАЛАНСОМ И ВАРИАНТАМИ")
print("=" * 70)

for balance in balances:
    print(f"\n{'='*70}")
    print(f"💰 БАЛАНС: ${balance}")
    print(f"{'='*70}")

    # Текущие настройки (после изменений)
    margin_current = (current_base_position * current_positions) / current_leverage
    usage_current = (margin_current / balance) * 100
    notional_current = current_base_position * current_positions

    print(f"\n📊 ТЕКУЩИЕ НАСТРОЙКИ (после изменений):")
    print(f"   Плечо: {current_leverage}x")
    print(f"   Размер позиции: ${current_base_position}")
    print(f"   Позиций: {current_positions}")
    print(f"   Маржа: ${margin_current:.2f} ({usage_current:.1f}% баланса)")
    print(
        f"   Номинальный объем: ${notional_current:.2f} ({(notional_current/balance)*100:.1f}% баланса)"
    )
    print(
        f"   Запас: ${balance - margin_current:.2f} ({((balance - margin_current)/balance)*100:.1f}%)"
    )

    # Варианты оптимизации
    print(f"\n📈 ВАРИАНТЫ ОПТИМИЗАЦИИ:")

    variants = []

    # Вариант 1: Плечо 5x, использование 40% баланса
    target_margin_1 = balance * 0.40
    leverage_1 = 5
    notional_1 = target_margin_1 * leverage_1
    position_size_1 = notional_1 / current_positions
    variants.append(
        {
            "name": "Вариант 1: Плечо 5x, 40% баланса",
            "leverage": leverage_1,
            "position_size": position_size_1,
            "margin": target_margin_1,
            "notional": notional_1,
            "usage": 40.0,
        }
    )

    # Вариант 2: Плечо 5x, использование 50% баланса
    target_margin_2 = balance * 0.50
    leverage_2 = 5
    notional_2 = target_margin_2 * leverage_2
    position_size_2 = notional_2 / current_positions
    variants.append(
        {
            "name": "Вариант 2: Плечо 5x, 50% баланса",
            "leverage": leverage_2,
            "position_size": position_size_2,
            "margin": target_margin_2,
            "notional": notional_2,
            "usage": 50.0,
        }
    )

    # Вариант 3: Плечо 10x, использование 40% баланса
    target_margin_3 = balance * 0.40
    leverage_3 = 10
    notional_3 = target_margin_3 * leverage_3
    position_size_3 = notional_3 / current_positions
    variants.append(
        {
            "name": "Вариант 3: Плечо 10x, 40% баланса",
            "leverage": leverage_3,
            "position_size": position_size_3,
            "margin": target_margin_3,
            "notional": notional_3,
            "usage": 40.0,
        }
    )

    # Вариант 4: Плечо 10x, использование 50% баланса
    target_margin_4 = balance * 0.50
    leverage_4 = 10
    notional_4 = target_margin_4 * leverage_4
    position_size_4 = notional_4 / current_positions
    variants.append(
        {
            "name": "Вариант 4: Плечо 10x, 50% баланса",
            "leverage": leverage_4,
            "position_size": position_size_4,
            "margin": target_margin_4,
            "notional": notional_4,
            "usage": 50.0,
        }
    )

    # Вариант 5: Фиксированный размер $50 (для малых балансов)
    if balance <= 500:
        position_size_5 = 50.0
        leverage_5 = 5
        notional_5 = position_size_5 * current_positions
        margin_5 = notional_5 / leverage_5
        usage_5 = (margin_5 / balance) * 100
        variants.append(
            {
                "name": "Вариант 5: Плечо 5x, размер $50 (для малых балансов)",
                "leverage": leverage_5,
                "position_size": position_size_5,
                "margin": margin_5,
                "notional": notional_5,
                "usage": usage_5,
            }
        )

    # Вариант 6: Фиксированный размер $100 (для средних балансов)
    if balance >= 500:
        position_size_6 = 100.0
        leverage_6 = 5
        notional_6 = position_size_6 * current_positions
        margin_6 = notional_6 / leverage_6
        usage_6 = (margin_6 / balance) * 100
        variants.append(
            {
                "name": "Вариант 6: Плечо 5x, размер $100 (текущий)",
                "leverage": leverage_6,
                "position_size": position_size_6,
                "margin": margin_6,
                "notional": notional_6,
                "usage": usage_6,
            }
        )

    # Вариант 7: Фиксированный размер $150 (для больших балансов)
    if balance >= 1000:
        position_size_7 = 150.0
        leverage_7 = 5
        notional_7 = position_size_7 * current_positions
        margin_7 = notional_7 / leverage_7
        usage_7 = (margin_7 / balance) * 100
        variants.append(
            {
                "name": "Вариант 7: Плечо 5x, размер $150 (для баланса 1000+)",
                "leverage": leverage_7,
                "position_size": position_size_7,
                "margin": margin_7,
                "notional": notional_7,
                "usage": usage_7,
            }
        )

    # Вывод вариантов
    for v in variants:
        print(f"\n{v['name']}:")
        print(f"   Плечо: {v['leverage']}x")
        print(f"   Размер позиции: ${v['position_size']:.2f}")
        print(f"   Маржа: ${v['margin']:.2f} ({v['usage']:.1f}% баланса)")
        print(
            f"   Номинальный объем: ${v['notional']:.2f} ({(v['notional']/balance)*100:.1f}% баланса)"
        )
        print(
            f"   Запас: ${balance - v['margin']:.2f} ({((balance - v['margin'])/balance)*100:.1f}%)"
        )

        # Расчет прибыли
        trades_per_day = 10
        avg_profit_percent = 0.5
        profit_gross = (v["notional"] * avg_profit_percent) / 100
        commission = (v["notional"] * 0.0009) * 2
        profit_net = profit_gross - commission
        daily_profit = profit_net * trades_per_day
        monthly_profit = daily_profit * 30
        roi_monthly = (monthly_profit / balance) * 100

        print(f"   Прибыль/месяц: ${monthly_profit:.2f} ({roi_monthly:.1f}% ROI)")

print("\n" + "=" * 70)
print("РЕКОМЕНДАЦИИ ПО БАЛАНСАМ")
print("=" * 70)

print("\n💰 БАЛАНС $200:")
print("   ✅ Рекомендуется: Вариант 5 (плечо 5x, размер $50)")
print("   - Использование: ~25% баланса")
print("   - Запас прочности: ~75%")
print("   - Потенциальная прибыль: ~$240/месяц (120% ROI)")

print("\n💰 БАЛАНС $500:")
print("   ✅ Рекомендуется: Вариант 6 (плечо 5x, размер $100)")
print("   - Использование: ~20% баланса")
print("   - Запас прочности: ~80%")
print("   - Потенциальная прибыль: ~$480/месяц (96% ROI)")

print("\n💰 БАЛАНС $1018:")
print("   ✅ Рекомендуется: Вариант 7 (плечо 5x, размер $150)")
print("   - Использование: ~14.7% баланса")
print("   - Запас прочности: ~85.3%")
print("   - Потенциальная прибыль: ~$720/месяц (70.7% ROI)")
print("   ⚠️ ИЛИ: Вариант 2 (плечо 5x, 50% баланса = размер $203)")
print("   - Использование: 50% баланса")
print("   - Потенциальная прибыль: ~$1224/месяц (120% ROI)")
