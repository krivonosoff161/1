#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Детальный анализ адаптивной системы баланса"""

# Текущие настройки из конфига
balance_profiles = {
    "small": {
        "threshold": 1500.0,
        "base_position_usd": 100.0,
        "min_position_usd": 60.0,
        "max_position_usd": 120.0,
        "max_open_positions": 5,
        "max_position_percent": 12.0
    },
    "medium": {
        "threshold": 3000.0,
        "base_position_usd": 100.0,
        "min_position_usd": 50.0,
        "max_position_usd": 125.0,
        "max_open_positions": 3,
        "max_position_percent": 6.0
    },
    "large": {
        "threshold": 999999.0,
        "base_position_usd": 150.0,
        "min_position_usd": 30.0,
        "max_position_usd": 250.0,
        "max_open_positions": 4,
        "max_position_percent": 8.0
    }
}

leverage = 5

print("="*80)
print("АНАЛИЗ АДАПТИВНОЙ СИСТЕМЫ БАЛАНСА")
print("="*80)

test_balances = [200, 500, 1018, 1500, 2000, 3000, 5000]

print("\n📊 ТЕКУЩАЯ РАБОТА СИСТЕМЫ:")
print("-"*80)

for balance in test_balances:
    # Определяем профиль
    if balance <= balance_profiles["small"]["threshold"]:
        profile = balance_profiles["small"]
        profile_name = "small"
    elif balance <= balance_profiles["medium"]["threshold"]:
        profile = balance_profiles["medium"]
        profile_name = "medium"
    else:
        profile = balance_profiles["large"]
        profile_name = "large"
    
    base_pos = profile["base_position_usd"]
    max_pos = profile["max_position_usd"]
    max_positions = profile["max_open_positions"]
    
    # Расчеты
    total_notional = base_pos * max_positions
    total_margin = total_notional / leverage
    usage_percent = (total_margin / balance) * 100
    notional_percent = (total_notional / balance) * 100
    
    print(f"\n💰 Баланс: ${balance}")
    print(f"   Профиль: {profile_name} (threshold: {profile['threshold']})")
    print(f"   Размер позиции: ${base_pos}")
    print(f"   Позиций: {max_positions}")
    print(f"   Маржа: ${total_margin:.2f} ({usage_percent:.1f}% баланса)")
    print(f"   Номинальный объем: ${total_notional:.2f} ({notional_percent:.1f}% баланса)")
    print(f"   Запас: ${balance - total_margin:.2f} ({100 - usage_percent:.1f}%)")
    
    if usage_percent > 50:
        print(f"   ⚠️ ПРОБЛЕМА: Используется {usage_percent:.1f}% баланса - слишком много!")
    elif usage_percent < 10:
        print(f"   ⚠️ ПРОБЛЕМА: Используется только {usage_percent:.1f}% баланса - слишком мало!")

print("\n" + "="*80)
print("ПРОБЛЕМЫ ТЕКУЩЕЙ СИСТЕМЫ")
print("="*80)

print("\n1. ❌ Баланс $200:")
print("   - Профиль: small")
print("   - Размер позиции: $100")
print("   - Использование: 50% баланса - СЛИШКОМ МНОГО!")
print("   - Риск: Высокий, мало запаса")

print("\n2. ⚠️ Баланс $1018:")
print("   - Профиль: small")
print("   - Размер позиции: $100")
print("   - Использование: 9.8% баланса - МАЛО!")
print("   - Проблема: $918 простаивает")

print("\n3. ❌ Баланс $1500:")
print("   - Профиль: medium (переключение на threshold 1500)")
print("   - Размер позиции: $100")
print("   - Позиций: 3 (было 5!)")
print("   - Использование: 4% баланса - ОЧЕНЬ МАЛО!")
print("   - Проблема: Резкое снижение активности при переходе в medium")

print("\n4. ❌ Баланс $3000:")
print("   - Профиль: large")
print("   - Размер позиции: $150")
print("   - Позиций: 4")
print("   - Использование: 1% баланса - КРИТИЧЕСКИ МАЛО!")

print("\n" + "="*80)
print("РАСЧЕТ ОПТИМАЛЬНОГО max_position_size_percent")
print("="*80)

# Для баланса $1018, позиция $100-150
balance = 1018
position_sizes = [100, 120, 150, 200]

print(f"\n💰 Баланс: ${balance}")
print(f"   Плечо: {leverage}x")
print(f"\n{'Размер позиции':<20} {'% от баланса':<15} {'max_position_size_percent':<30}")
print("-"*65)

for pos_size in position_sizes:
    percent = (pos_size / balance) * 100
    # max_position_size_percent должен быть больше, чем размер позиции в % от баланса
    recommended = max(percent * 1.2, percent + 5)  # +20% или +5% минимум
    print(f"${pos_size:<19} {percent:>6.2f}%        {recommended:>6.2f}% (рекомендуется)")

print("\n✅ РЕКОМЕНДАЦИЯ:")
print("   Для позиций $100-150 при балансе $1018:")
print("   - max_position_size_percent: 15-20% (безопасно)")
print("   - Или 20-25% (если хотим больше гибкости)")

print("\n" + "="*80)
print("ПРЕДЛОЖЕНИЯ ПО УЛУЧШЕНИЮ СИСТЕМЫ")
print("="*80)

print("\n1. ✅ ДОБАВИТЬ ПРОФИЛЬ 'micro' для балансов $100-500")
print("   - threshold: 500.0")
print("   - base_position_usd: 50.0")
print("   - min_position_usd: 30.0")
print("   - max_position_usd: 70.0")
print("   - max_open_positions: 5")
print("   - max_position_percent: 25.0")

print("\n2. ✅ УЛУЧШИТЬ ПРОФИЛЬ 'small' для балансов $500-1500")
print("   - threshold: 1500.0 (оставить)")
print("   - base_position_usd: 100.0 (оставить)")
print("   - НО: добавить адаптацию размера в зависимости от баланса")
print("   - При $500: $50-80")
print("   - При $1000: $100-150")
print("   - При $1500: $120-180")

print("\n3. ✅ УЛУЧШИТЬ ПРОФИЛЬ 'medium' для балансов $1500-3000")
print("   - threshold: 3000.0 (оставить)")
print("   - base_position_usd: увеличить до 150-200")
print("   - max_open_positions: увеличить до 4-5")

print("\n4. ✅ ДОБАВИТЬ ПРОГРЕССИВНУЮ АДАПТАЦИЮ")
print("   - Внутри профиля размер позиции адаптируется к балансу")
print("   - Формула: base_size * (balance / profile_threshold)")
print("   - Пример: при балансе $1018 в профиле small (threshold 1500):")
print("     base_size = 100 * (1018 / 1500) = $68")
print("   - Или: base_size = 100 + (balance - 500) * 0.1")

print("\n5. ✅ PER-SYMBOL АДАПТАЦИЯ")
print("   - BTC-USDT: больший размер (высокая ликвидность)")
print("   - DOGE-USDT: меньший размер (низкая ликвидность)")
print("   - Уже есть в конфиге, но нужно проверить логику")

print("\n" + "="*80)
print("ВАРИАНТЫ РЕАЛИЗАЦИИ")
print("="*80)

print("\n📋 ВАРИАНТ 1: Добавить профиль 'micro' (простой)")
print("   Плюсы:")
print("   - Простая реализация")
print("   - Четкие границы")
print("   Минусы:")
print("   - Резкие переходы между профилями")
print("   - Не учитывает промежуточные балансы")

print("\n📋 ВАРИАНТ 2: Прогрессивная адаптация внутри профиля (рекомендуется)")
print("   Плюсы:")
print("   - Плавная адаптация")
print("   - Учитывает все балансы")
print("   - Более гибкая система")
print("   Минусы:")
print("   - Нужно изменить логику расчета")
print("   - Более сложная формула")

print("\n📋 ВАРИАНТ 3: Гибридный (micro + прогрессивная)")
print("   Плюсы:")
print("   - Лучшее из обоих вариантов")
print("   - Четкие границы для малых балансов")
print("   - Плавная адаптация для больших")
print("   Минусы:")
print("   - Самая сложная реализация")

print("\n" + "="*80)
print("РАСЧЕТ ДЛЯ РАЗНЫХ БАЛАНСОВ С ПРОГРЕССИВНОЙ АДАПТАЦИЕЙ")
print("="*80)

def calculate_progressive_size(balance, profile_name, profile):
    """Расчет размера позиции с прогрессивной адаптацией"""
    threshold = profile["threshold"]
    base_size = profile["base_position_usd"]
    
    # Определяем нижний порог профиля
    if profile_name == "small":
        lower_threshold = 500.0  # Предполагаем, что micro будет до 500
    elif profile_name == "medium":
        lower_threshold = 1500.0
    else:
        lower_threshold = 3000.0
    
    # Прогрессивная формула
    if balance <= lower_threshold:
        return base_size * 0.5  # Минимум для начала профиля
    else:
        # Линейная интерполяция
        range_size = threshold - lower_threshold
        balance_in_range = balance - lower_threshold
        progress = balance_in_range / range_size
        # Размер от 50% до 100% base_size
        size_multiplier = 0.5 + (progress * 0.5)
        return base_size * size_multiplier

print("\n💰 ПРОГРЕССИВНАЯ АДАПТАЦИЯ:")
for balance in [200, 500, 800, 1018, 1200, 1500, 2000, 3000]:
    if balance <= 1500:
        profile = balance_profiles["small"]
        profile_name = "small"
    elif balance <= 3000:
        profile = balance_profiles["medium"]
        profile_name = "medium"
    else:
        profile = balance_profiles["large"]
        profile_name = "large"
    
    if profile_name == "small":
        # Для small: от $50 при $500 до $100 при $1500
        if balance <= 500:
            size = 50.0
        else:
            size = 50.0 + ((balance - 500) / 1000) * 50.0  # От $50 до $100
    elif profile_name == "medium":
        # Для medium: от $100 при $1500 до $150 при $3000
        size = 100.0 + ((balance - 1500) / 1500) * 50.0  # От $100 до $150
    else:
        size = profile["base_position_usd"]
    
    margin = (size * profile["max_open_positions"]) / leverage
    usage = (margin / balance) * 100
    
    print(f"   Баланс ${balance:>6}: профиль {profile_name:>6}, размер ${size:>6.2f}, использование {usage:>5.1f}%")

