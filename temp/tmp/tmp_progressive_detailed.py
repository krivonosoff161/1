#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ДЕТАЛЬНЫЙ РАСЧЕТ ПРОГРЕССИВНОЙ АДАПТАЦИИ И PER-SYMBOL МНОЖИТЕЛЕЙ"""

leverage = 5
max_positions = 5

print("=" * 100)
print("ДЕТАЛЬНЫЙ РАСЧЕТ ПРОГРЕССИВНОЙ АДАПТАЦИИ")
print("=" * 100)

# Профили с прогрессивной адаптацией
profiles_config = {
    "micro": {
        "threshold": 500.0,
        "min_balance": 100.0,
        "size_at_min": 30.0,  # При балансе $100
        "size_at_max": 50.0,  # При балансе $500
        "max_positions": 5,
    },
    "small": {
        "threshold": 1500.0,
        "min_balance": 500.0,
        "size_at_min": 50.0,  # При балансе $500
        "size_at_max": 150.0,  # При балансе $1500
        "max_positions": 5,
    },
    "medium": {
        "threshold": 3000.0,
        "min_balance": 1500.0,
        "size_at_min": 150.0,  # При балансе $1500
        "size_at_max": 200.0,  # При балансе $3000
        "max_positions": 5,
    },
    "large": {
        "threshold": 999999.0,
        "min_balance": 3000.0,
        "max_balance": 10000.0,  # При балансе $10000
        "size_at_min": 200.0,  # При балансе $3000
        "size_at_max": 300.0,  # При балансе $10000
        "max_positions": 5,
    },
}


def calculate_progressive_size(balance, profile_name):
    """Расчет прогрессивного размера позиции"""
    profile = profiles_config[profile_name]

    if profile_name == "micro":
        if balance <= profile["min_balance"]:
            return profile["size_at_min"]
        elif balance >= profile["threshold"]:
            return profile["size_at_max"]
        else:
            progress = (balance - profile["min_balance"]) / (
                profile["threshold"] - profile["min_balance"]
            )
            return (
                profile["size_at_min"]
                + (profile["size_at_max"] - profile["size_at_min"]) * progress
            )

    elif profile_name == "small":
        if balance <= profile["min_balance"]:
            return profile["size_at_min"]
        elif balance >= profile["threshold"]:
            return profile["size_at_max"]
        else:
            progress = (balance - profile["min_balance"]) / (
                profile["threshold"] - profile["min_balance"]
            )
            return (
                profile["size_at_min"]
                + (profile["size_at_max"] - profile["size_at_min"]) * progress
            )

    elif profile_name == "medium":
        if balance <= profile["min_balance"]:
            return profile["size_at_min"]
        elif balance >= profile["threshold"]:
            return profile["size_at_max"]
        else:
            progress = (balance - profile["min_balance"]) / (
                profile["threshold"] - profile["min_balance"]
            )
            return (
                profile["size_at_min"]
                + (profile["size_at_max"] - profile["size_at_min"]) * progress
            )

    else:  # large
        if balance <= profile["min_balance"]:
            return profile["size_at_min"]
        elif balance >= profile["max_balance"]:
            return profile["size_at_max"]
        else:
            progress = (balance - profile["min_balance"]) / (
                profile["max_balance"] - profile["min_balance"]
            )
            return (
                profile["size_at_min"]
                + (profile["size_at_max"] - profile["size_at_min"]) * progress
            )


# Тестовые балансы
test_balances = [
    200,
    300,
    400,
    500,
    600,
    800,
    1018,
    1200,
    1500,
    1800,
    2000,
    2500,
    3000,
    4000,
    5000,
    7500,
    10000,
]

print(
    f"\n{'Баланс':<10} {'Профиль':<10} {'Размер':<12} {'Маржа (5поз)':<15} {'Использование':<15} {'Запас':<15} {'Нот. объем':<15} {'Прибыль/мес':<15}"
)
print("-" * 100)

for balance in test_balances:
    # Определяем профиль
    if balance <= profiles_config["micro"]["threshold"]:
        profile_name = "micro"
    elif balance <= profiles_config["small"]["threshold"]:
        profile_name = "small"
    elif balance <= profiles_config["medium"]["threshold"]:
        profile_name = "medium"
    else:
        profile_name = "large"

    profile = profiles_config[profile_name]
    position_size = calculate_progressive_size(balance, profile_name)
    max_pos = profile["max_positions"]

    # Расчеты
    total_notional = position_size * max_pos
    total_margin = total_notional / leverage
    usage_percent = (total_margin / balance) * 100
    available = balance - total_margin

    # Прибыль
    profit_per_trade = ((position_size * 0.5) / 100) - ((position_size * 0.0009) * 2)
    monthly_profit = profit_per_trade * 10 * 30 * max_pos

    print(
        f"${balance:<9} {profile_name:<10} ${position_size:<11.2f} ${total_margin:<14.2f} {usage_percent:>6.2f}%        ${available:<14.2f} ${total_notional:<14.2f} ${monthly_profit:>7.2f}"
    )

print("\n" + "=" * 100)
print("PER-SYMBOL МНОЖИТЕЛИ")
print("=" * 100)

# Базовые размеры для символов (на основе ликвидности и волатильности)
symbol_multipliers = {
    "BTC-USDT": 1.2,  # Высокая ликвидность, можно больше
    "ETH-USDT": 1.0,  # Стандарт
    "SOL-USDT": 0.9,  # Средняя ликвидность, чуть меньше
    "DOGE-USDT": 0.8,  # Низкая ликвидность, меньше
    "XRP-USDT": 0.8,  # Низкая ликвидность, меньше
}

print("\n📊 БАЗОВЫЕ МНОЖИТЕЛИ (на основе ликвидности):")
for symbol, multiplier in symbol_multipliers.items():
    print(f"   {symbol}: {multiplier}x")

balance = 1018
base_size = calculate_progressive_size(balance, "small")

print(f"\n💰 БАЛАНС: ${balance}")
print(f"   Базовый размер (small): ${base_size:.2f}")

print(
    f"\n{'Символ':<15} {'Множитель':<12} {'Размер позиции':<18} {'Маржа':<12} {'% от баланса':<15}"
)
print("-" * 70)

for symbol, multiplier in symbol_multipliers.items():
    symbol_size = base_size * multiplier
    symbol_margin = (symbol_size * max_positions) / leverage
    symbol_percent = (symbol_margin / balance) * 100

    print(
        f"{symbol:<15} {multiplier:<12.2f} ${symbol_size:<17.2f} ${symbol_margin:<11.2f} {symbol_percent:>6.2f}%"
    )

print("\n" + "=" * 100)
print("РАСЧЕТ ДЛЯ БАЛАНСА $1018 С PER-SYMBOL МНОЖИТЕЛЯМИ")
print("=" * 100)

balance = 1018
base_size = calculate_progressive_size(balance, "small")

print(f"\n💰 БАЛАНС: ${balance}")
print(f"   Базовый размер: ${base_size:.2f}")
print(f"   Плечо: {leverage}x")
print(f"   Максимум позиций: {max_positions}")

# Расчет для каждого символа
total_notional_all = 0
total_margin_all = 0

print(
    f"\n{'Символ':<15} {'Размер':<12} {'Нот. объем':<15} {'Маржа':<12} {'% баланса':<12}"
)
print("-" * 70)

for symbol, multiplier in symbol_multipliers.items():
    symbol_size = base_size * multiplier
    symbol_notional = symbol_size  # На одну позицию
    symbol_margin = symbol_notional / leverage
    symbol_percent = (symbol_margin / balance) * 100

    total_notional_all += symbol_notional
    total_margin_all += symbol_margin

    print(
        f"{symbol:<15} ${symbol_size:<11.2f} ${symbol_notional:<14.2f} ${symbol_margin:<11.2f} {symbol_percent:>6.2f}%"
    )

print(f"\n📊 ИТОГО (все 5 позиций открыты):")
print(
    f"   Общий номинальный объем: ${total_notional_all:.2f} ({(total_notional_all/balance)*100:.2f}% баланса)"
)
print(
    f"   Общая маржа: ${total_margin_all:.2f} ({(total_margin_all/balance)*100:.2f}% баланса)"
)
print(
    f"   Запас: ${balance - total_margin_all:.2f} ({((balance - total_margin_all)/balance)*100:.2f}% баланса)"
)

# Риски
print(f"\n⚠️ РИСКИ:")
for loss_percent in [0.05, 0.10, 0.15, 0.20]:
    loss = total_notional_all * loss_percent
    remaining = balance - loss
    remaining_percent = (remaining / balance) * 100
    status = "✅" if remaining_percent > 85 else "⚠️" if remaining_percent > 70 else "🔴"
    print(
        f"   При убытке -{loss_percent*100:.0f}%: убыток ${loss:.2f}, остаток ${remaining:.2f} ({remaining_percent:.1f}%) {status}"
    )

# Прибыльность
profit_total = 0
for symbol, multiplier in symbol_multipliers.items():
    symbol_size = base_size * multiplier
    profit_per_trade = ((symbol_size * 0.5) / 100) - ((symbol_size * 0.0009) * 2)
    profit_total += profit_per_trade * 10 * 30  # 10 сделок в день, 30 дней

print(f"\n📈 ПРИБЫЛЬНОСТЬ:")
print(f"   Месячная прибыль (все символы): ${profit_total:.2f}")
print(f"   ROI: {(profit_total/balance)*100:.1f}%")

print("\n" + "=" * 100)
print("СЦЕНАРИИ ПРИ РОСТЕ БАЛАНСА")
print("=" * 100)

# Сценарий: баланс растет с $1018 до $1500 за 9 дней
initial_balance = 1018
target_balance = 1500
days = 9

print(
    f"\n📈 СЦЕНАРИЙ: Баланс растет с ${initial_balance} до ${target_balance} за {days} дней"
)
print(
    f"   Прирост: ${target_balance - initial_balance} ({((target_balance - initial_balance)/initial_balance)*100:.1f}%)"
)

# Рассчитываем промежуточные балансы
daily_gain = (target_balance - initial_balance) / days

print(
    f"\n{'День':<6} {'Баланс':<10} {'Профиль':<10} {'Размер':<12} {'Маржа (5поз)':<15} {'Использование':<15} {'Прибыль/мес':<15}"
)
print("-" * 80)

for day in range(0, days + 1):
    current_balance = initial_balance + (daily_gain * day)

    # Определяем профиль
    if current_balance <= profiles_config["micro"]["threshold"]:
        profile_name = "micro"
    elif current_balance <= profiles_config["small"]["threshold"]:
        profile_name = "small"
    elif current_balance <= profiles_config["medium"]["threshold"]:
        profile_name = "medium"
    else:
        profile_name = "large"

    position_size = calculate_progressive_size(current_balance, profile_name)
    total_notional = position_size * max_positions
    total_margin = total_notional / leverage
    usage_percent = (total_margin / current_balance) * 100

    profit_per_trade = ((position_size * 0.5) / 100) - ((position_size * 0.0009) * 2)
    monthly_profit = profit_per_trade * 10 * 30 * max_positions

    print(
        f"{day:<6} ${current_balance:<9.2f} {profile_name:<10} ${position_size:<11.2f} ${total_margin:<14.2f} {usage_percent:>6.2f}%        ${monthly_profit:>7.2f}"
    )

print("\n" + "=" * 100)
print("ФОРМУЛЫ ПРОГРЕССИВНОЙ АДАПТАЦИИ")
print("=" * 100)

print("\n📐 МАТЕМАТИЧЕСКИЕ ФОРМУЛЫ:")
print("\n1. ПРОФИЛЬ 'micro' ($100 - $500):")
print("   size = 30 + ((balance - 100) / 400) * 20")
print("   При балансе $100: size = $30")
print("   При балансе $500: size = $50")
print("   При балансе $300: size = $40")

print("\n2. ПРОФИЛЬ 'small' ($500 - $1500):")
print("   size = 50 + ((balance - 500) / 1000) * 100")
print("   При балансе $500:  size = $50")
print("   При балансе $1018: size = $101.80")
print("   При балансе $1500: size = $150")

print("\n3. ПРОФИЛЬ 'medium' ($1500 - $3000):")
print("   size = 150 + ((balance - 1500) / 1500) * 50")
print("   При балансе $1500: size = $150")
print("   При балансе $2000: size = $166.67")
print("   При балансе $3000: size = $200")

print("\n4. ПРОФИЛЬ 'large' ($3000+):")
print("   size = 200 + ((balance - 3000) / 7000) * 100")
print("   При балансе $3000:  size = $200")
print("   При балансе $5000:  size = $228.57")
print("   При балансе $10000: size = $300")

print("\n" + "=" * 100)
print("РЕАЛИЗАЦИЯ В КОДЕ")
print("=" * 100)

print("\n📝 ИЗМЕНЕНИЯ В КОНФИГЕ:")
print(
    """
balance_profiles:
  micro:
    threshold: 500.0
    min_balance: 100.0
    size_at_min: 30.0
    size_at_max: 50.0
    max_open_positions: 5
    max_position_percent: 25.0
    progressive: true
  
  small:
    threshold: 1500.0
    min_balance: 500.0
    size_at_min: 50.0
    size_at_max: 150.0
    max_open_positions: 5
    max_position_percent: 15.0
    progressive: true
  
  medium:
    threshold: 3000.0
    min_balance: 1500.0
    size_at_min: 150.0
    size_at_max: 200.0
    max_open_positions: 5
    max_position_percent: 12.0
    progressive: true
  
  large:
    threshold: 999999.0
    min_balance: 3000.0
    max_balance: 10000.0
    size_at_min: 200.0
    size_at_max: 300.0
    max_open_positions: 5
    max_position_percent: 10.0
    progressive: true
"""
)

print("\n📝 PER-SYMBOL МНОЖИТЕЛИ:")
print(
    """
symbol_profiles:
  BTC-USDT:
    position_multiplier: 1.2
  ETH-USDT:
    position_multiplier: 1.0
  SOL-USDT:
    position_multiplier: 0.9
  DOGE-USDT:
    position_multiplier: 0.8
  XRP-USDT:
    position_multiplier: 0.8
"""
)

print("\n📝 ИЗМЕНЕНИЯ В КОДЕ:")
print(
    """
1. В _get_balance_profile():
   - Добавить расчет прогрессивного размера если progressive: true
   - Формула: size = size_at_min + ((balance - min_balance) / (threshold - min_balance)) * (size_at_max - size_at_min)

2. В _calculate_position_size():
   - Применить per-symbol multiplier: final_size = base_size * symbol_multiplier
   - Учесть min/max ограничения

3. Обновить max_position_size_percent в risk:
   - Увеличить до 20%
"""
)

print("\n" + "=" * 100)
print("ИТОГОВЫЕ РЕКОМЕНДАЦИИ")
print("=" * 100)

print("\n✅ ДЛЯ БАЛАНСА $1018:")
print(f"   Базовый размер: ${base_size:.2f} (прогрессивная адаптация)")
print(f"   С per-symbol множителями:")
for symbol, multiplier in symbol_multipliers.items():
    symbol_size = base_size * multiplier
    print(f"      {symbol}: ${symbol_size:.2f}")

total_size = sum(base_size * m for m in symbol_multipliers.values())
total_margin = total_size / leverage

print(f"\n   При всех 5 позициях открыты:")
print(f"      Общий номинальный объем: ${total_size:.2f}")
print(
    f"      Общая маржа: ${total_margin:.2f} ({(total_margin/balance)*100:.2f}% баланса)"
)
print(
    f"      Запас: ${balance - total_margin:.2f} ({((balance - total_margin)/balance)*100:.2f}% баланса)"
)

print("\n✅ БЕЗОПАСНОСТЬ:")
print("   - При убытке -10%: убыток ~$50-75, остаток >90% баланса")
print("   - При убытке -15%: убыток ~$75-112, остаток >85% баланса")
print("   - При убытке -20%: убыток ~$100-150, остаток >80% баланса")
print("   - ✅ Все сценарии безопасны при наличии фильтров защиты")

print("\n✅ ПРИБЫЛЬНОСТЬ:")
profit_total = (
    sum(
        ((base_size * m * 0.5) / 100) - ((base_size * m * 0.0009) * 2)
        for m in symbol_multipliers.values()
    )
    * 10
    * 30
)
print(
    f"   Месячная прибыль: ~${profit_total:.2f} ({(profit_total/balance)*100:.1f}% ROI)"
)

print("\n✅ АДАПТАЦИЯ:")
print("   - При росте баланса размер автоматически увеличивается")
print("   - Плавный переход между профилями")
print("   - Per-symbol множители учитывают ликвидность")
