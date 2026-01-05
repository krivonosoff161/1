#!/usr/bin/env python3
"""
Тест адаптивных параметров - интеграционный тест ParameterProvider
"""

import yaml

from src.config import BotConfig
from src.strategies.scalping.futures.config.config_manager import ConfigManager
from src.strategies.scalping.futures.config.parameter_provider import \
    ParameterProvider


def test_adaptive_integration():
    """Интеграционный тест адаптивных параметров"""
    print("🧪 Интеграционный тест адаптивных параметров")
    print("=" * 60)

    try:
        # Загружаем конфигурацию
        config = BotConfig("config/config_futures.yaml")
        print("✅ BotConfig загружен")

        # Загружаем raw config для ConfigManager
        with open("config/config_futures.yaml", "r", encoding="utf-8") as f:
            raw_config_dict = yaml.safe_load(f)

        # Создаем ConfigManager с raw config
        config_manager = ConfigManager(config, raw_config_dict=raw_config_dict)
        print("✅ ConfigManager инициализирован")

        # Создаем ParameterProvider
        parameter_provider = ParameterProvider(config_manager=config_manager)
        print("✅ ParameterProvider инициализирован")

        # Тестируем адаптивные параметры
        print("\n🎯 Тест адаптивных параметров выхода:")

        test_cases = [
            {
                "balance": 500,
                "pnl": 2.0,
                "drawdown": 1.0,
                "expected_tp": "~0.80",
                "expected_sl": "~0.80",
            },
            {
                "balance": 1000,
                "pnl": 2.0,
                "drawdown": 1.0,
                "expected_tp": "~0.85",
                "expected_sl": "~0.85",
            },
            {
                "balance": 2000,
                "pnl": 2.0,
                "drawdown": 1.0,
                "expected_tp": "~1.00",
                "expected_sl": "~1.00",
            },
            {
                "balance": 4000,
                "pnl": 2.0,
                "drawdown": 1.0,
                "expected_tp": "~1.03",
                "expected_sl": "~1.00",
            },
            {
                "balance": 5000,
                "pnl": 2.0,
                "drawdown": 1.0,
                "expected_tp": "~1.10",
                "expected_sl": "~1.00",
            },
        ]

        for case in test_cases:
            # Получаем адаптивные параметры
            adaptive_params = parameter_provider.get_exit_params(
                symbol="BTC-USDT",
                regime="trending",
                balance=case["balance"],
                current_pnl=case["pnl"],
                drawdown=case["drawdown"],
            )

            tp_multiplier = adaptive_params.get("tp_atr_multiplier", 0)
            sl_multiplier = adaptive_params.get("sl_atr_multiplier", 0)

            print(
                f"  ${case['balance']:4d}: TP ×{tp_multiplier:.3f}, SL ×{sl_multiplier:.3f} | Expected: {case['expected_tp']}, {case['expected_sl']}"
            )

            # Проверяем, что параметры не равны 0
            if tp_multiplier == 0 or sl_multiplier == 0:
                print(
                    f"  ❌ ОШИБКА: Параметры равны 0! TP={tp_multiplier}, SL={sl_multiplier}"
                )
            else:
                print(f"  ✅ OK: Параметры корректны")

        print("\n✅ Тест завершен успешно!")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_adaptive_integration()
