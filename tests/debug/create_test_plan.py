"""
План комплексного тестирования всей системы
Тестирование каждого режима + пары с индивидуальными параметрами
"""

import csv
import json
from pathlib import Path
from typing import Dict, List


def create_comprehensive_test_plan() -> Dict:
    """Создание плана комплексного тестирования"""

    print("📋 ПЛАН КОМПЛЕКСНОГО ТЕСТИРОВАНИЯ СИСТЕМЫ")
    print("=" * 50)

    # Определение всех режимов и пар
    regimes = ["ranging", "bullish", "bearish", "sideways", "volatile"]
    pairs = ["XRP-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT", "BTC-USDT"]

    # Системы для тестирования
    systems = ["base", "big_profit", "rebounds", "time_based", "adaptive"]

    print(f"🎯 Режимы: {regimes}")
    print(f"📊 Пары: {pairs}")
    print(f"⚙️ Системы: {systems}")

    # Создание матрицы тестирования
    test_matrix = {}
    test_id = 1

    for regime in regimes:
        for pair in pairs:
            for system in systems:
                test_key = f"{regime}_{pair}_{system}"
                test_matrix[test_key] = {
                    "test_id": test_id,
                    "regime": regime,
                    "pair": pair,
                    "system": system,
                    "parameters": get_default_parameters(regime, pair, system),
                    "expected_results": get_expected_results(regime, pair, system),
                    "status": "pending",
                }
                test_id += 1

    print(f"\n📊 Создана матрица тестирования: {len(test_matrix)} комбинаций")

    # Сохранение плана
    plan_file = "tests/comprehensive_test_plan.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump(test_matrix, f, indent=2, ensure_ascii=False)

    print(f"💾 План сохранен в: {plan_file}")

    return test_matrix


def get_default_parameters(regime: str, pair: str, system: str) -> Dict:
    """Получение параметров по умолчанию для комбинации"""

    # Базовые параметры
    base_params = {
        "risk_per_trade": 0.01,  # 1% от баланса
        "max_open_positions": 3,
        "min_volume": 1000,
        "max_slippage": 0.001,
    }

    # Параметры по режимам
    regime_params = {
        "ranging": {
            "tp_sl_ratio": 1.5,
            "min_holding_time": 300,  # 5 мин
            "atr_multiplier": 1.0,
            "trend_strength_min": 0.3,
        },
        "bullish": {
            "tp_sl_ratio": 2.0,
            "min_holding_time": 600,  # 10 мин
            "atr_multiplier": 1.2,
            "trend_strength_min": 0.5,
        },
        "bearish": {
            "tp_sl_ratio": 2.0,
            "min_holding_time": 600,
            "atr_multiplier": 1.2,
            "trend_strength_min": 0.5,
        },
        "volatile": {
            "tp_sl_ratio": 3.0,
            "min_holding_time": 180,  # 3 мин
            "atr_multiplier": 1.5,
            "trend_strength_min": 0.7,
        },
        "sideways": {
            "tp_sl_ratio": 1.2,
            "min_holding_time": 900,  # 15 мин
            "atr_multiplier": 0.8,
            "trend_strength_min": 0.1,
        },
    }

    # Параметры по парам
    pair_params = {
        "XRP-USDT": {
            "leverage_max": 10,
            "position_size_min": 10,
            "volatility_factor": 1.2,
        },
        "ETH-USDT": {
            "leverage_max": 5,
            "position_size_min": 0.01,
            "volatility_factor": 1.0,
        },
        "SOL-USDT": {
            "leverage_max": 8,
            "position_size_min": 0.1,
            "volatility_factor": 1.5,
        },
        "DOGE-USDT": {
            "leverage_max": 15,
            "position_size_min": 100,
            "volatility_factor": 2.0,
        },
        "BTC-USDT": {
            "leverage_max": 3,
            "position_size_min": 0.001,
            "volatility_factor": 0.8,
        },
    }

    # Параметры по системам
    system_params = {
        "base": {},
        "big_profit": {
            "profit_target_multiplier": 3.0,
            "max_holding_time": 3600,  # 1 час
            "trailing_stop": True,
        },
        "rebounds": {
            "rebound_strength_min": 0.6,
            "entry_delay": 30,  # секунд
            "confirmation_period": 60,
        },
        "time_based": {
            "optimal_entry_hours": [8, 12, 16, 20],
            "avoid_hours": [2, 6, 14, 18],
            "session_weight": 1.5,
        },
        "adaptive": {
            "dynamic_tp_sl": True,
            "volatility_adjustment": True,
            "market_regime_filter": True,
        },
    }

    # Комбинирование параметров
    params = {}
    params.update(base_params)
    params.update(regime_params.get(regime, {}))
    params.update(pair_params.get(pair, {}))
    params.update(system_params.get(system, {}))

    return params


def get_expected_results(regime: str, pair: str, system: str) -> Dict:
    """Ожидаемые результаты для комбинации"""

    # На основе текущих данных
    current_performance = {
        "ranging_XRP-USDT_base": {"win_rate": 18.2, "pnl": -2.35, "trades": 11},
        "ranging_ETH-USDT_base": {"win_rate": 31.6, "pnl": -10.53, "trades": 19},
        "ranging_SOL-USDT_base": {"win_rate": 37.5, "pnl": 0.27, "trades": 8},
        "ranging_DOGE-USDT_base": {"win_rate": 20.0, "pnl": 2.68, "trades": 5},
        "ranging_BTC-USDT_base": {"win_rate": 0.0, "pnl": -0.54, "trades": 2},
    }

    # Базовые ожидания
    base_expectations = {
        "min_win_rate": 25.0,
        "min_pnl_per_trade": -1.0,
        "max_drawdown": 5.0,
        "min_trades": 10,
        "max_holding_time": 1800,  # 30 мин
        "profit_factor": 1.1,
    }

    # Корректировка по режиму
    regime_multipliers = {
        "ranging": {"win_rate_mult": 0.8, "pnl_mult": 0.7},
        "bullish": {"win_rate_mult": 1.2, "pnl_mult": 1.3},
        "bearish": {"win_rate_mult": 1.1, "pnl_mult": 1.1},
        "volatile": {"win_rate_mult": 0.9, "pnl_mult": 1.5},
        "sideways": {"win_rate_mult": 1.0, "pnl_mult": 0.8},
    }

    # Корректировка по паре
    pair_multipliers = {
        "XRP-USDT": {"win_rate_mult": 0.9, "pnl_mult": 0.8},
        "ETH-USDT": {"win_rate_mult": 1.0, "pnl_mult": 0.9},
        "SOL-USDT": {"win_rate_mult": 1.1, "pnl_mult": 1.1},
        "DOGE-USDT": {"win_rate_mult": 0.8, "pnl_mult": 1.2},
        "BTC-USDT": {"win_rate_mult": 1.2, "pnl_mult": 0.7},
    }

    # Корректировка по системе
    system_multipliers = {
        "base": {"win_rate_mult": 1.0, "pnl_mult": 1.0},
        "big_profit": {"win_rate_mult": 0.8, "pnl_mult": 1.5},
        "rebounds": {"win_rate_mult": 1.1, "pnl_mult": 1.2},
        "time_based": {"win_rate_mult": 1.0, "pnl_mult": 1.1},
        "adaptive": {"win_rate_mult": 1.3, "pnl_mult": 1.4},
    }

    # Расчет ожиданий
    r_mult = regime_multipliers.get(regime, {"win_rate_mult": 1.0, "pnl_mult": 1.0})
    p_mult = pair_multipliers.get(pair, {"win_rate_mult": 1.0, "pnl_mult": 1.0})
    s_mult = system_multipliers.get(system, {"win_rate_mult": 1.0, "pnl_mult": 1.0})

    expected_win_rate = (
        base_expectations["min_win_rate"]
        * r_mult["win_rate_mult"]
        * p_mult["win_rate_mult"]
        * s_mult["win_rate_mult"]
    )
    expected_pnl = (
        base_expectations["min_pnl_per_trade"]
        * r_mult["pnl_mult"]
        * p_mult["pnl_mult"]
        * s_mult["pnl_mult"]
    )

    return {
        "expected_win_rate": round(expected_win_rate, 1),
        "expected_pnl_per_trade": round(expected_pnl, 2),
        "expected_min_trades": base_expectations["min_trades"],
        "expected_max_drawdown": base_expectations["max_drawdown"],
        "expected_profit_factor": base_expectations["profit_factor"],
    }


def create_test_execution_script(test_matrix: Dict):
    """Создание скрипта для выполнения тестирования"""

    script_content = '''"""
Скрипт выполнения комплексного тестирования
"""

import json
import subprocess
import time
from pathlib import Path

def run_test(test_config: Dict) -> Dict:
    """Запуск одного теста"""

    print(f"🧪 Запуск теста {test_config['test_id']}: {test_config['regime']}_{test_config['pair']}_{test_config['system']}")

    # Здесь будет логика запуска теста с конкретными параметрами
    # Пока заглушка

    result = {
        'test_id': test_config['test_id'],
        'status': 'completed',
        'actual_win_rate': 0.0,
        'actual_pnl': 0.0,
        'actual_trades': 0,
        'passed': False
    }

    return result

def execute_test_plan():
    """Выполнение плана тестирования"""

    # Загрузка плана
    with open('tests/comprehensive_test_plan.json', 'r') as f:
        test_plan = json.load(f)

    results = {}

    for test_key, test_config in test_plan.items():
        if test_config['status'] == 'pending':
            result = run_test(test_config)
            results[test_key] = result

            # Сохранение прогресса
            with open('tests/test_results.json', 'w') as f:
                json.dump(results, f, indent=2)

            time.sleep(1)  # Задержка между тестами

    return results

if __name__ == "__main__":
    execute_test_plan()
'''

    with open("tests/run_comprehensive_tests.py", "w", encoding="utf-8") as f:
        f.write(script_content)

    print("📝 Создан скрипт выполнения: tests/run_comprehensive_tests.py")


def print_test_summary(test_matrix: Dict):
    """Вывод сводки по тестам"""

    print(f"\n📊 СВОДКА ПО ТЕСТИРОВАНИЮ:")
    print(f"   Всего комбинаций: {len(test_matrix)}")

    # Статистика по режимам
    regime_count = {}
    for test in test_matrix.values():
        regime = test["regime"]
        regime_count[regime] = regime_count.get(regime, 0) + 1

    print(f"   По режимам: {regime_count}")

    # Статистика по парам
    pair_count = {}
    for test in test_matrix.values():
        pair = test["pair"]
        pair_count[pair] = pair_count.get(pair, 0) + 1

    print(f"   По парам: {pair_count}")

    # Статистика по системам
    system_count = {}
    for test in test_matrix.values():
        system = test["system"]
        system_count[system] = system_count.get(system, 0) + 1

    print(f"   По системам: {system_count}")


if __name__ == "__main__":
    test_matrix = create_comprehensive_test_plan()
    create_test_execution_script(test_matrix)
    print_test_summary(test_matrix)
