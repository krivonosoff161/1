#!/usr/bin/env python3
"""
Диагностика проблемы с адаптивными параметрами
"""

import sys
import yaml
from pathlib import Path

sys.path.insert(0, '.')

def diagnose_adaptive_params():
    print("🔍 Диагностика адаптивных параметров")
    print("=" * 50)

    try:
        # 1. Проверяем загрузку конфигурации
        print("1. Загрузка конфигурации...")
        config_path = Path('config/config_futures.yaml')
        if not config_path.exists():
            print("❌ Файл конфигурации не найден!")
            return

        with open(config_path, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)

        print("✅ Конфигурация загружена")

        # 2. Проверяем adaptive_exit_params
        print("\n2. Проверка adaptive_exit_params...")
        adaptive_config = raw_config.get('adaptive_exit_params', {})
        if not adaptive_config:
            print("❌ adaptive_exit_params не найден в конфигурации!")
            return

        enabled = adaptive_config.get('enabled', False)
        print(f"✅ adaptive_exit_params найден, enabled: {enabled}")

        if not enabled:
            print("⚠️ Адаптивные параметры отключены в конфигурации")
            return

        # 3. Проверяем balance_adaptation
        print("\n3. Проверка balance_adaptation...")
        balance_config = adaptive_config.get('balance_adaptation', {})
        if not balance_config:
            print("❌ balance_adaptation не найден!")
            return

        print(f"✅ balance_adaptation найден: {list(balance_config.keys())}")

        # 4. Проверяем пороги
        small_threshold = balance_config.get('small_threshold')
        large_threshold = balance_config.get('large_threshold')
        print(f"✅ Пороги: small_threshold={small_threshold}, large_threshold={large_threshold}")

        # 5. Проверяем коэффициенты
        small = balance_config.get('small', {})
        medium = balance_config.get('medium', {})
        large = balance_config.get('large', {})

        print(f"✅ Коэффициенты small: {small}")
        print(f"✅ Коэффициенты medium: {medium}")
        print(f"✅ Коэффициенты large: {large}")

        # 6. Тест расчетов
        print("\n4. Тест расчетов адаптации...")
        from src.strategies.scalping.futures.config.parameter_provider import ParameterProvider
        from src.config import BotConfig
        from src.strategies.scalping.futures.config.config_manager import ConfigManager

        config = BotConfig('config/config_futures.yaml')
        config_manager = ConfigManager(config, raw_config_dict=raw_config)
        provider = ParameterProvider(config_manager=config_manager)

        # Тест метода _calculate_balance_adaptation_factors
        test_balances = [500, 1000, 2000, 4000, 5000]
        for balance in test_balances:
            tp_factor, sl_factor = provider._calculate_balance_adaptation_factors(balance)
            print(f"  ${balance}: TP ×{tp_factor:.3f}, SL ×{sl_factor:.3f}")

        # Тест get_exit_params с адаптацией
        print("\n5. Тест get_exit_params с адаптацией...")
        params = provider.get_exit_params(
            symbol="BTC-USDT",
            regime="trending",
            balance=1000.0,
            current_pnl=2.0,
            drawdown=1.0
        )

        tp_multiplier = params.get('tp_atr_multiplier', 0)
        sl_multiplier = params.get('sl_atr_multiplier', 0)
        print(f"✅ Результат: TP={tp_multiplier:.3f}, SL={sl_multiplier:.3f}")

        if tp_multiplier == 0 or sl_multiplier == 0:
            print("❌ ОШИБКА: Параметры равны 0!")
        else:
            print("✅ Параметры корректны!")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    diagnose_adaptive_params()