#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ОЧЕНЬ ДЕТАЛЬНЫЙ РАСЧЕТ РИСКОВ И ПРИБЫЛЬНОСТИ"""

import math

# Параметры
leverage = 5
max_positions = 5
balances = [200, 500, 1018, 1500, 2000, 3000, 5000]

print("="*100)
print("ДЕТАЛЬНЫЙ РАСЧЕТ РИСКОВ И ПРИБЫЛЬНОСТИ ДЛЯ ВАРИАНТА B")
print("="*100)

# Варианты размеров позиций для тестирования
position_size_options = {
    "conservative": 100.0,  # Консервативно
    "moderate": 120.0,      # Умеренно
    "recommended": 150.0,   # Рекомендуется
    "aggressive": 200.0,    # Агрессивно
}

print(f"\n📊 ПАРАМЕТРЫ:")
print(f"   Плечо: {leverage}x")
print(f"   Максимум позиций: {max_positions}")
print(f"   Варианты размеров: {list(position_size_options.values())} USD")

print("\n" + "="*100)
print("РАСЧЕТ ДЛЯ БАЛАНСА $1018 (ВАШ ТЕКУЩИЙ)")
print("="*100)

balance = 1018

for variant_name, position_size in position_size_options.items():
    print(f"\n{'='*100}")
    print(f"💰 ВАРИАНТ: {variant_name.upper()} - Размер позиции ${position_size}")
    print(f"{'='*100}")
    
    # Расчет для одной позиции
    notional_per_position = position_size
    margin_per_position = notional_per_position / leverage
    
    # Расчет для 5 позиций (максимум)
    total_notional = notional_per_position * max_positions
    total_margin = margin_per_position * max_positions
    
    # Процент использования баланса
    margin_usage_percent = (total_margin / balance) * 100
    notional_percent = (total_notional / balance) * 100
    
    # Запас прочности
    available_margin = balance - total_margin
    available_percent = (available_margin / balance) * 100
    
    print(f"\n📊 ОДНА ПОЗИЦИЯ:")
    print(f"   Номинальный объем: ${notional_per_position:.2f}")
    print(f"   Маржа: ${margin_per_position:.2f} ({(margin_per_position/balance)*100:.2f}% баланса)")
    
    print(f"\n📊 МАКСИМУМ ПОЗИЦИЙ ({max_positions}):")
    print(f"   Номинальный объем: ${total_notional:.2f} ({notional_percent:.2f}% баланса)")
    print(f"   Маржа: ${total_margin:.2f} ({margin_usage_percent:.2f}% баланса)")
    print(f"   Запас: ${available_margin:.2f} ({available_percent:.2f}% баланса)")
    
    # Расчет риска ликвидации
    # При плече 5x ликвидация происходит при падении цены на ~20% (1/leverage * 100)
    # Но это для одной позиции! При нескольких позициях риск выше
    
    liquidation_price_drop = (1 / leverage) * 100  # В процентах
    liquidation_margin_call = total_margin * 0.2  # Маржин-колл при падении на 20%
    
    print(f"\n⚠️ РИСК ЛИКВИДАЦИИ:")
    print(f"   Падение цены для ликвидации: ~{liquidation_price_drop:.1f}% (теоретически)")
    print(f"   Но при нескольких позициях риск выше!")
    print(f"   Если все 5 позиций уйдут в убыток одновременно:")
    print(f"   - Убыток на позицию при -10%: ${notional_per_position * 0.10:.2f}")
    print(f"   - Общий убыток (5 позиций): ${total_notional * 0.10:.2f}")
    print(f"   - Это {(total_notional * 0.10 / balance) * 100:.1f}% от баланса!")
    print(f"   - Маржа: ${total_margin:.2f}, убыток ${total_notional * 0.10:.2f}")
    print(f"   - Остаток баланса: ${balance - total_notional * 0.10:.2f}")
    
    # Сценарии убытков
    print(f"\n📉 СЦЕНАРИИ УБЫТКОВ:")
    loss_scenarios = [0.05, 0.10, 0.15, 0.20]
    for loss_percent in loss_scenarios:
        loss_amount = total_notional * loss_percent
        remaining_balance = balance - loss_amount
        remaining_percent = (remaining_balance / balance) * 100
        margin_coverage = (total_margin / loss_amount) * 100 if loss_amount > 0 else 0
        
        status = "✅ Безопасно" if remaining_percent > 80 else "⚠️ Риск" if remaining_percent > 50 else "❌ Критично"
        
        print(f"   При падении на {loss_percent*100:.0f}%:")
        print(f"      Убыток: ${loss_amount:.2f} ({(loss_amount/balance)*100:.1f}% баланса)")
        print(f"      Остаток: ${remaining_balance:.2f} ({remaining_percent:.1f}%) {status}")
        print(f"      Маржа покрывает: {margin_coverage:.1f}% убытка")
    
    # Расчет прибыльности
    print(f"\n📈 ПРИБЫЛЬНОСТЬ:")
    trades_per_day = 10
    avg_profit_percent = 0.5
    commission_rate = 0.0009  # 0.09% для limit orders
    
    # Прибыль на одну сделку
    profit_gross_per_trade = (notional_per_position * avg_profit_percent) / 100
    commission_per_trade = (notional_per_position * commission_rate) * 2  # Вход + выход
    profit_net_per_trade = profit_gross_per_trade - commission_per_trade
    
    # Дневная прибыль (10 сделок)
    daily_profit = profit_net_per_trade * trades_per_day
    
    # Месячная прибыль
    monthly_profit = daily_profit * 30
    roi_monthly = (monthly_profit / balance) * 100
    
    # При 5 позициях (если все открыты)
    daily_profit_5_pos = profit_net_per_trade * trades_per_day * max_positions
    monthly_profit_5_pos = daily_profit_5_pos * 30
    roi_monthly_5_pos = (monthly_profit_5_pos / balance) * 100
    
    print(f"   Прибыль на сделку: ${profit_net_per_trade:.2f} (валовая ${profit_gross_per_trade:.2f}, комиссия ${commission_per_trade:.2f})")
    print(f"   Дневная прибыль (10 сделок): ${daily_profit:.2f}")
    print(f"   Месячная прибыль: ${monthly_profit:.2f} ({roi_monthly:.1f}% ROI)")
    print(f"   При 5 открытых позициях (все торгуют):")
    print(f"      Дневная прибыль: ${daily_profit_5_pos:.2f}")
    print(f"      Месячная прибыль: ${monthly_profit_5_pos:.2f} ({roi_monthly_5_pos:.1f}% ROI)")
    
    # Соотношение риск/прибыль
    print(f"\n⚖️ СООТНОШЕНИЕ РИСК/ПРИБЫЛЬ:")
    risk_amount = total_notional * 0.10  # Риск при -10%
    reward_amount = monthly_profit
    risk_reward_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
    print(f"   Риск (при -10%): ${risk_amount:.2f}")
    print(f"   Прибыль (месяц): ${reward_amount:.2f}")
    print(f"   Соотношение: 1:{risk_reward_ratio:.2f}")
    
    if risk_reward_ratio > 2:
        print(f"   ✅ Хорошее соотношение (прибыль > 2x риска)")
    elif risk_reward_ratio > 1:
        print(f"   ⚠️ Умеренное соотношение (прибыль > риска)")
    else:
        print(f"   ❌ Плохое соотношение (риск > прибыли)")

print("\n" + "="*100)
print("РАСЧЕТ ДЛЯ РАЗНЫХ БАЛАНСОВ С ПРОГРЕССИВНОЙ АДАПТАЦИЕЙ")
print("="*100)

def calculate_progressive_size(balance, profile_name, profile_config):
    """Расчет прогрессивного размера позиции"""
    threshold = profile_config["threshold"]
    
    if profile_name == "micro":
        # Micro: $50 фиксированный
        return 50.0
    elif profile_name == "small":
        # Small: от $50 при $500 до $150 при $1500
        min_balance = 500.0
        min_size = 50.0
        max_size = 150.0
        if balance <= min_balance:
            return min_size
        elif balance >= threshold:
            return max_size
        else:
            progress = (balance - min_balance) / (threshold - min_balance)
            return min_size + (max_size - min_size) * progress
    elif profile_name == "medium":
        # Medium: от $150 при $1500 до $200 при $3000
        min_balance = 1500.0
        min_size = 150.0
        max_size = 200.0
        if balance <= min_balance:
            return min_size
        elif balance >= threshold:
            return max_size
        else:
            progress = (balance - min_balance) / (threshold - min_balance)
            return min_size + (max_size - min_size) * progress
    else:  # large
        # Large: от $200 при $3000 до $300 при $10000
        min_balance = 3000.0
        max_balance = 10000.0
        min_size = 200.0
        max_size = 300.0
        if balance <= min_balance:
            return min_size
        elif balance >= max_balance:
            return max_size
        else:
            progress = (balance - min_balance) / (max_balance - min_balance)
            return min_size + (max_size - min_size) * progress

# Профили с прогрессивной адаптацией
profiles = {
    "micro": {
        "threshold": 500.0,
        "max_positions": 5,
    },
    "small": {
        "threshold": 1500.0,
        "max_positions": 5,
    },
    "medium": {
        "threshold": 3000.0,
        "max_positions": 5,
    },
    "large": {
        "threshold": 999999.0,
        "max_positions": 5,
    },
}

print(f"\n{'Баланс':<10} {'Профиль':<10} {'Размер':<10} {'Маржа':<12} {'Использование':<15} {'Запас':<12} {'Прибыль/мес':<15} {'ROI':<10}")
print("-"*100)

for balance in balances:
    # Определяем профиль
    if balance <= profiles["micro"]["threshold"]:
        profile_name = "micro"
    elif balance <= profiles["small"]["threshold"]:
        profile_name = "small"
    elif balance <= profiles["medium"]["threshold"]:
        profile_name = "medium"
    else:
        profile_name = "large"
    
    profile = profiles[profile_name]
    position_size = calculate_progressive_size(balance, profile_name, profile)
    max_pos = profile["max_positions"]
    
    # Расчеты
    total_notional = position_size * max_pos
    total_margin = total_notional / leverage
    usage_percent = (total_margin / balance) * 100
    available = balance - total_margin
    
    # Прибыль
    profit_per_trade = ((position_size * 0.5) / 100) - ((position_size * 0.0009) * 2)
    monthly_profit = profit_per_trade * 10 * 30 * max_pos
    roi = (monthly_profit / balance) * 100
    
    print(f"${balance:<9} {profile_name:<10} ${position_size:<9.2f} ${total_margin:<11.2f} {usage_percent:>6.2f}%        ${available:<11.2f} ${monthly_profit:>7.2f}      {roi:>5.1f}%")

print("\n" + "="*100)
print("АНАЛИЗ РИСКОВ ПРИ РАЗНЫХ СЦЕНАРИЯХ")
print("="*100)

balance = 1018
position_size = 150.0
max_positions = 5

print(f"\n💰 БАЛАНС: ${balance}")
print(f"   Размер позиции: ${position_size}")
print(f"   Позиций: {max_positions}")
print(f"   Плечо: {leverage}x")

total_notional = position_size * max_positions
total_margin = total_notional / leverage

print(f"\n📊 БАЗОВЫЕ РАСЧЕТЫ:")
print(f"   Номинальный объем: ${total_notional:.2f}")
print(f"   Маржа: ${total_margin:.2f} ({(total_margin/balance)*100:.2f}% баланса)")

print(f"\n⚠️ СЦЕНАРИИ РИСКА:")
print(f"\n1. ВСЕ 5 ПОЗИЦИЙ ОТКРЫТЫ ОДНОВРЕМЕННО:")
scenarios = [
    ("Все позиции в прибыли +5%", 0.05, True),
    ("Все позиции в убытке -5%", -0.05, False),
    ("Все позиции в убытке -10%", -0.10, False),
    ("Все позиции в убытке -15%", -0.15, False),
    ("Все позиции в убытке -20%", -0.20, False),
]

for scenario_name, change_percent, is_profit in scenarios:
    pnl = total_notional * change_percent
    new_balance = balance + pnl
    new_balance_percent = (new_balance / balance) * 100
    
    if is_profit:
        status = "✅"
    else:
        if new_balance_percent > 80:
            status = "⚠️"
        elif new_balance_percent > 50:
            status = "🔴"
        else:
            status = "❌ ЛИКВИДАЦИЯ"
    
    print(f"   {scenario_name}:")
    print(f"      PnL: ${pnl:+.2f} ({(pnl/balance)*100:+.2f}% баланса)")
    print(f"      Новый баланс: ${new_balance:.2f} ({new_balance_percent:.1f}%) {status}")

print(f"\n2. ЧАСТИЧНЫЙ УБЫТОК (3 из 5 позиций в убытке -10%):")
loss_positions = 3
profit_positions = 2
loss_per_position = position_size * 0.10
profit_per_position = position_size * 0.05  # Предполагаем прибыль на остальных

total_loss = loss_per_position * loss_positions
total_profit = profit_per_position * profit_positions
net_pnl = total_profit - total_loss
new_balance = balance + net_pnl

print(f"   Убыток (3 позиции): ${total_loss:.2f}")
print(f"   Прибыль (2 позиции): ${total_profit:.2f}")
print(f"   Чистый PnL: ${net_pnl:+.2f}")
print(f"   Новый баланс: ${new_balance:.2f} ({(new_balance/balance)*100:.1f}%)")

print(f"\n3. ПОСЛЕДОВАТЕЛЬНЫЕ УБЫТКИ (5 сделок подряд по -1.5%):")
loss_per_trade = (position_size * 0.015) * max_positions  # Предполагаем все позиции открыты
total_loss_sequence = loss_per_trade * 5
new_balance_sequence = balance - total_loss_sequence

print(f"   Убыток на сделку: ${loss_per_trade:.2f}")
print(f"   Общий убыток (5 сделок): ${total_loss_sequence:.2f}")
print(f"   Новый баланс: ${new_balance_sequence:.2f} ({(new_balance_sequence/balance)*100:.1f}%)")

print("\n" + "="*100)
print("РАСЧЕТ ЗАПАСА ПРОЧНОСТИ")
print("="*100)

balance = 1018
position_size = 150.0

print(f"\n💰 БАЛАНС: ${balance}")
print(f"   Размер позиции: ${position_size}")

# Запас прочности = сколько убытка может выдержать баланс
# При плече 5x ликвидация при падении на ~20%
# Но нужно учитывать несколько позиций

for num_positions in [1, 2, 3, 4, 5]:
    notional = position_size * num_positions
    margin = notional / leverage
    
    # Запас прочности при разных уровнях убытка
    print(f"\n📊 {num_positions} ПОЗИЦИЙ:")
    print(f"   Номинальный объем: ${notional:.2f}")
    print(f"   Маржа: ${margin:.2f} ({(margin/balance)*100:.2f}% баланса)")
    
    for loss_percent in [0.10, 0.15, 0.20]:
        loss = notional * loss_percent
        remaining = balance - loss
        remaining_percent = (remaining / balance) * 100
        
        if remaining_percent > 70:
            safety = "✅ Безопасно"
        elif remaining_percent > 50:
            safety = "⚠️ Риск"
        elif remaining_percent > 30:
            safety = "🔴 Высокий риск"
        else:
            safety = "❌ Критично"
        
        print(f"   При убытке -{loss_percent*100:.0f}%: убыток ${loss:.2f}, остаток ${remaining:.2f} ({remaining_percent:.1f}%) {safety}")

print("\n" + "="*100)
print("РЕКОМЕНДАЦИИ ПО РАЗМЕРУ ПОЗИЦИЙ")
print("="*100)

balance = 1018

print(f"\n💰 БАЛАНС: ${balance}")
print(f"   Плечо: {leverage}x")
print(f"   Максимум позиций: {max_positions}")

recommendations = [
    {
        "name": "Консервативный",
        "size": 100.0,
        "description": "Минимальный риск, хороший запас"
    },
    {
        "name": "Умеренный",
        "size": 120.0,
        "description": "Баланс риск/прибыль"
    },
    {
        "name": "Рекомендуемый",
        "size": 150.0,
        "description": "Оптимальный баланс"
    },
    {
        "name": "Агрессивный",
        "size": 200.0,
        "description": "Максимальная прибыль, высокий риск"
    },
]

print(f"\n{'Вариант':<15} {'Размер':<10} {'Маржа (5поз)':<15} {'Использование':<15} {'Запас':<15} {'Прибыль/мес':<15} {'Риск при -10%':<15}")
print("-"*100)

for rec in recommendations:
    size = rec["size"]
    notional = size * max_positions
    margin = notional / leverage
    usage = (margin / balance) * 100
    available = balance - margin
    
    profit_per_trade = ((size * 0.5) / 100) - ((size * 0.0009) * 2)
    monthly_profit = profit_per_trade * 10 * 30 * max_positions
    
    loss_10_percent = notional * 0.10
    remaining_after_loss = balance - loss_10_percent
    
    print(f"{rec['name']:<15} ${size:<9.2f} ${margin:<14.2f} {usage:>6.2f}%        ${available:<14.2f} ${monthly_profit:>7.2f}      ${loss_10_percent:>7.2f} (остаток ${remaining_after_loss:.0f})")

print("\n✅ ИТОГОВАЯ РЕКОМЕНДАЦИЯ:")
print("   Размер позиции: $150 (рекомендуемый)")
print("   - Маржа: $150 (14.7% баланса)")
print("   - Запас: $868 (85.3% баланса)")
print("   - Прибыль/месяц: ~$720 (70.7% ROI)")
print("   - Риск при -10%: $75 убыток, остаток $943 (92.6%)")
print("   - ✅ Безопасно при наличии фильтров защиты")

