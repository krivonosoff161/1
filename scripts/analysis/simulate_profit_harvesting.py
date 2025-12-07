#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Симуляция работы Profit Harvesting для анализа проблем
"""


def simulate_ph_scenario(
    net_pnl_usd: float,
    ph_threshold: float,
    ph_time_limit: int,
    min_holding_minutes: float,
    time_since_open_seconds: float,
):
    """Симулирует проверку Profit Harvesting"""

    min_holding_seconds = min_holding_minutes * 60.0

    # Проверка 1: Экстремальная прибыль
    ignore_min_holding = False
    if net_pnl_usd >= ph_threshold * 2.0:
        ignore_min_holding = True
        print(
            f"✅ ЭКСТРЕМАЛЬНАЯ ПРИБЫЛЬ: ${net_pnl_usd:.4f} >= ${ph_threshold * 2.0:.2f} (2x порога)"
        )
        print(f"   → Игнорируем MIN_HOLDING")
    else:
        print(
            f"❌ НЕ экстремальная прибыль: ${net_pnl_usd:.4f} < ${ph_threshold * 2.0:.2f} (2x порога)"
        )

    # Проверка 2: MIN_HOLDING
    if not ignore_min_holding and time_since_open_seconds < min_holding_seconds:
        print(
            f"❌ MIN_HOLDING блокирует: {time_since_open_seconds:.1f}с < {min_holding_seconds:.1f}с"
        )
        return False, "BLOCKED_BY_MIN_HOLDING"
    else:
        print(
            f"✅ MIN_HOLDING пройден: {time_since_open_seconds:.1f}с >= {min_holding_seconds:.1f}с"
        )

    # Проверка 3: Условия закрытия
    should_close = False
    close_reason = ""

    if ignore_min_holding:
        # Экстремальная прибыль: игнорируем ph_time_limit
        if net_pnl_usd >= ph_threshold:
            should_close = True
            close_reason = "EXTREME_PROFIT"
            print(f"✅ ЗАКРЫТИЕ по экстремальной прибыли (игнорируем time_limit)")
        else:
            print(
                f"❌ Прибыль недостаточна для экстремального закрытия: ${net_pnl_usd:.4f} < ${ph_threshold:.2f}"
            )
    else:
        # Обычная прибыль: проверяем ph_time_limit
        if net_pnl_usd >= ph_threshold and time_since_open_seconds < ph_time_limit:
            should_close = True
            close_reason = "NORMAL_PROFIT"
            print(f"✅ ЗАКРЫТИЕ по обычной прибыли (в пределах time_limit)")
        else:
            if net_pnl_usd < ph_threshold:
                print(
                    f"❌ Прибыль недостаточна: ${net_pnl_usd:.4f} < ${ph_threshold:.2f}"
                )
            if time_since_open_seconds >= ph_time_limit:
                print(
                    f"❌ Превышен time_limit: {time_since_open_seconds:.1f}с >= {ph_time_limit}с"
                )

    return should_close, close_reason


def main():
    print("=" * 80)
    print("📊 СИМУЛЯЦИЯ PROFIT HARVESTING")
    print("=" * 80)
    print()

    # Параметры из конфига (ranging режим)
    ph_threshold = 0.15  # 0.15 USD
    ph_time_limit = 120  # 120 секунд (2 минуты)
    min_holding_minutes = 1.0  # 1 минута

    print(f"📋 Параметры конфигурации (ranging):")
    print(f"   ph_threshold: ${ph_threshold:.2f}")
    print(f"   ph_time_limit: {ph_time_limit}с ({ph_time_limit/60:.1f} мин)")
    print(f"   min_holding_minutes: {min_holding_minutes:.1f} мин")
    print()

    # Сценарии из реальных данных
    scenarios = [
        {
            "name": "XRP: Максимальная прибыль 1.37 USDT",
            "net_pnl_usd": 1.37,
            "time_since_open_seconds": 252,  # ~4 минуты (из анализа XRP)
        },
        {
            "name": "SOL: Максимальная прибыль 2.64 USDT",
            "net_pnl_usd": 2.64,
            "time_since_open_seconds": 300,  # ~5 минут
        },
        {
            "name": "BTC: Максимальная прибыль 2.07 USDT",
            "net_pnl_usd": 2.07,
            "time_since_open_seconds": 600,  # ~10 минут
        },
        {
            "name": "XRP: Ранняя прибыль 0.30 USDT (через 30 сек)",
            "net_pnl_usd": 0.30,
            "time_since_open_seconds": 30,
        },
        {
            "name": "XRP: Прибыль 0.20 USDT (через 60 сек)",
            "net_pnl_usd": 0.20,
            "time_since_open_seconds": 60,
        },
        {
            "name": "XRP: Прибыль 0.15 USDT (через 90 сек)",
            "net_pnl_usd": 0.15,
            "time_since_open_seconds": 90,
        },
    ]

    for i, scenario in enumerate(scenarios, 1):
        print(f"\n{'='*80}")
        print(f"Сценарий {i}: {scenario['name']}")
        print(f"{'='*80}")
        print(f"Прибыль: ${scenario['net_pnl_usd']:.4f}")
        print(
            f"Время в позиции: {scenario['time_since_open_seconds']:.1f}с ({scenario['time_since_open_seconds']/60:.1f} мин)"
        )
        print()

        should_close, reason = simulate_ph_scenario(
            net_pnl_usd=scenario["net_pnl_usd"],
            ph_threshold=ph_threshold,
            ph_time_limit=ph_time_limit,
            min_holding_minutes=min_holding_minutes,
            time_since_open_seconds=scenario["time_since_open_seconds"],
        )

        print()
        if should_close:
            print(f"✅ РЕЗУЛЬТАТ: ЗАКРЫТИЕ ({reason})")
        else:
            print(f"❌ РЕЗУЛЬТАТ: НЕ ЗАКРЫТО ({reason})")
        print()

    print("\n" + "=" * 80)
    print("📊 ВЫВОДЫ И РЕКОМЕНДАЦИИ")
    print("=" * 80)
    print()
    print("Проблемы:")
    print("1. При экстремальной прибыли (> 2x порога) позиции закрываются")
    print("2. При обычной прибыли (> порога, но < 2x) позиции НЕ закрываются, если:")
    print("   - Превышен ph_time_limit (120 сек = 2 мин)")
    print("   - Это основная причина упущенной прибыли!")
    print()
    print("Рекомендации:")
    print("1. Увеличить ph_time_limit для ranging до 300-600 сек (5-10 мин)")
    print("2. Или уменьшить порог экстремальной прибыли с 2x до 1.5x")
    print(
        "3. Или добавить проверку: если прибыль > 1.5x порога, игнорировать time_limit"
    )
    print("4. Добавить логирование всех попыток PH для отладки")


if __name__ == "__main__":
    main()
