"""
Parameter Testing Framework - Тестирование параметров через ParameterProvider API

КОНЦЕПЦИЯ:
1. Использует ParameterProvider для получения/override параметров
2. Симулирует торговлю на исторических данных с разными параметрами
3. Сравнивает результаты без изменения основного кода бота
4. Находит оптимальные параметры для каждой комбинации режим+пара+система

НЕ МЕНЯЕТ ОСНОВНОЙ КОД - только тестирует параметры!
"""

import asyncio
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

from src.config import BotConfig
from src.strategies.scalping.futures.config.config_manager import ConfigManager
from src.strategies.scalping.futures.config.parameter_provider import ParameterProvider


class ParameterTester:
    """
    Тестер параметров через ParameterProvider API.

    Тестирует разные комбинации параметров на исторических данных
    без изменения основного кода бота.
    """

    def __init__(self, config_path: str = "config/config_futures.yaml"):
        """
        Инициализация тестера параметров.

        Args:
            config_path: Путь к конфигурационному файлу
        """
        self.config_path = config_path
        self.config = None
        self.config_manager = None
        self.parameter_provider = None
        self.test_results = {}

        logger.info("✅ ParameterTester инициализирован")

    async def initialize(self):
        """Инициализация компонентов"""
        # Загружаем конфигурацию
        self.config = BotConfig.load_from_file(self.config_path)

        # Создаем ConfigManager
        self.config_manager = ConfigManager(self.config)

        # Создаем ParameterProvider
        self.parameter_provider = ParameterProvider(self.config_manager)

        logger.info("✅ Компоненты инициализированы")

    def load_test_plan(self) -> Optional[Dict[str, Any]]:
        """
        Загрузить план тестирования из файла.

        Returns:
            План тестирования или None если файл не найден
        """
        test_plan_path = Path("tests/comprehensive_test_plan.json")

        if not test_plan_path.exists():
            logger.error(f"❌ Файл плана тестирования не найден: {test_plan_path}")
            return None

        try:
            with open(test_plan_path, "r", encoding="utf-8") as f:
                test_plan_data = json.load(f)

            # Конвертируем структуру объекта в массив комбинаций
            if isinstance(test_plan_data, dict):
                combinations = []
                for key, value in test_plan_data.items():
                    if isinstance(value, dict) and "test_id" in value:
                        combinations.append(value)

                test_plan = {"combinations": combinations}
            else:
                test_plan = test_plan_data

            logger.info(
                f"✅ План тестирования загружен: {len(test_plan.get('combinations', []))} комбинаций"
            )
            return test_plan

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки плана тестирования: {e}")
            return None

    def get_test_combinations(self) -> List[Dict[str, Any]]:
        """
        Получить комбинации параметров для тестирования.

        Returns:
            Список комбинаций параметров
        """
        combinations = []

        # Режимы для тестирования
        regimes = ["ranging", "trending", "choppy"]

        # Пары для тестирования
        pairs = ["XRP-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT", "BTC-USDT"]

        # Параметры для тестирования (TP/SL ratios)
        tp_sl_combinations = [
            {"tp_ratio": 1.5, "sl_ratio": 1.0},
            {"tp_ratio": 2.0, "sl_ratio": 1.0},
            {"tp_ratio": 2.5, "sl_ratio": 1.5},
            {"tp_ratio": 3.0, "sl_ratio": 1.5},
        ]

        # Создаем комбинации
        for regime in regimes:
            for pair in pairs:
                for params in tp_sl_combinations:
                    combination = {
                        "regime": regime,
                        "pair": pair,
                        "test_id": f"{regime}_{pair}_{params['tp_ratio']}_{params['sl_ratio']}",
                        "parameters": {
                            "tp_atr_multiplier": params["tp_ratio"],
                            "sl_atr_multiplier": params["sl_ratio"],
                            "max_holding_minutes": 15 if regime == "ranging" else 30,
                            "min_holding_minutes": 1.0,
                        },
                        "expected_win_rate": 0.0,
                        "expected_pnl": 0.0,
                    }
                    combinations.append(combination)

        logger.info(f"📊 Созданы {len(combinations)} комбинаций для тестирования")
        return combinations

    async def test_combination(self, combination: Dict[str, Any]) -> Dict[str, Any]:
        """
        Тестировать одну комбинацию параметров.

        ПОДХОД: Упрощенная симуляция на основе исторических сделок
        - Берем реальные сделки из логов
        - Симулируем выходы с новыми TP/SL параметрами
        - Не запускаем полный цикл генерации сигналов
        """

        test_id = combination["test_id"]
        logger.info(f"🧪 Тестирование комбинации: {test_id}")

        # ЗАГРУЗКА ИСТОРИЧЕСКИХ ДАННЫХ
        # Используем реальные сделки из логов вместо генерации сигналов
        historical_trades = await self.load_historical_trades(combination["pair"])

        if not historical_trades:
            logger.warning(f"⚠️ Нет исторических данных для {combination['pair']}")
            return self.create_empty_result(combination)

        # СИМУЛЯЦИЯ С НОВЫМИ ПАРАМЕТРАМИ
        simulated_results = await self.simulate_with_new_params(
            historical_trades, combination["parameters"], combination["regime"]
        )

        result = {
            "test_id": test_id,
            "regime": combination["regime"],
            "pair": combination["pair"],
            "parameters": combination["parameters"],
            "metrics": simulated_results,
            "timestamp": datetime.now().isoformat(),
        }

        return result

    async def load_historical_trades(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Загрузить исторические сделки для символа из CSV файла.

        ИСПОЛЬЗУЕТ: Реальные логи бота из all_data_*.csv файла
        """
        try:
            # Ищем последний CSV файл с данными
            log_dir = Path("logs/futures/archived")
            if not log_dir.exists():
                return []

            # Находим все директории с логами
            log_dirs = [d for d in log_dir.iterdir() if d.is_dir()]
            if not log_dirs:
                return []

            # Берем самую свежую директорию
            latest_dir = max(log_dirs, key=lambda x: x.stat().st_mtime)

            # Извлекаем дату из имени директории (формат: logs_YYYY-MM-DD_HH-MM-SS)
            dir_name = latest_dir.name
            if "_" in dir_name:
                date_part = dir_name.split("_")[1]  # YYYY-MM-DD
                csv_file = latest_dir / f"all_data_{date_part}.csv"
            else:
                csv_file = latest_dir / "all_data.csv"

            if not csv_file.exists():
                logger.warning(f"❌ CSV файл не найден: {csv_file}")
                return []

            logger.info(f"📂 Используем CSV файл: {csv_file}")

            # Читаем сделки для символа
            trades = []
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if (
                        row.get("record_type") == "trades"
                        and row.get("symbol") == symbol
                    ):
                        trades.append(row)

            logger.info(f"📊 Загружено {len(trades)} исторических сделок для {symbol}")
            return trades

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки исторических данных: {e}")
            return []

    async def simulate_with_new_params(
        self,
        historical_trades: List[Dict[str, Any]],
        new_params: Dict[str, Any],
        regime: str,
    ) -> Dict[str, Any]:
        """
        Симулировать торговлю с новыми параметрами.

        ПОДХОД: Берем реальные входы, симулируем выходы с новыми TP/SL
        """
        if not historical_trades:
            return self.create_empty_metrics()

        total_pnl = 0.0
        wins = 0
        losses = 0
        max_drawdown = 0.0
        peak_pnl = 0.0
        current_drawdown = 0.0

        for trade in historical_trades:
            try:
                # Берем реальные данные входа
                entry_price = float(trade.get("entry_price", 0))
                exit_price = float(trade.get("exit_price", 0))
                side = trade.get("side", "long")
                size = float(trade.get("size", 1))

                if entry_price == 0:
                    continue

                # СИМУЛИРУЕМ НОВЫЕ ПАРАМЕТРЫ ВЫХОДА
                # Используем ATR-like расчет (упрощенная модель)
                atr_estimate = entry_price * 0.015  # 1.5% ATR

                # Новые TP/SL уровни
                tp_multiplier = new_params.get("tp_atr_multiplier", 2.0)
                sl_multiplier = new_params.get("sl_atr_multiplier", 1.0)

                if side == "long":
                    tp_price = entry_price + (atr_estimate * tp_multiplier)
                    sl_price = entry_price - (atr_estimate * sl_multiplier)
                else:
                    tp_price = entry_price - (atr_estimate * tp_multiplier)
                    sl_price = entry_price + (atr_estimate * sl_multiplier)

                # СИМУЛИРУЕМ ВЫХОД
                # Определяем, куда попал бы выход с новыми уровнями
                if side == "long":
                    if exit_price >= tp_price:
                        # TP hit - берем полный TP профит
                        trade_pnl = size * (tp_price - entry_price)
                        wins += 1
                    elif exit_price <= sl_price:
                        # SL hit - фиксируем SL лосс
                        trade_pnl = size * (sl_price - entry_price)
                        losses += 1
                    else:
                        # Обычный выход - используем реальный P&L
                        trade_pnl = float(trade.get("net_pnl", 0))
                        if trade_pnl > 0:
                            wins += 1
                        else:
                            losses += 1
                else:
                    # Аналогично для short
                    if exit_price <= tp_price:
                        trade_pnl = size * (entry_price - tp_price)
                        wins += 1
                    elif exit_price >= sl_price:
                        trade_pnl = size * (entry_price - sl_price)
                        losses += 1
                    else:
                        trade_pnl = float(trade.get("net_pnl", 0))
                        if trade_pnl > 0:
                            wins += 1
                        else:
                            losses += 1

                total_pnl += trade_pnl

                # Расчет drawdown
                if total_pnl > peak_pnl:
                    peak_pnl = total_pnl
                    current_drawdown = 0
                else:
                    current_drawdown = peak_pnl - total_pnl
                    max_drawdown = max(max_drawdown, current_drawdown)

            except (ValueError, KeyError) as e:
                logger.warning(f"⚠️ Ошибка обработки сделки: {e}")
                continue

        total_trades = wins + losses
        win_rate = wins / total_trades if total_trades > 0 else 0
        avg_trade_pnl = total_pnl / total_trades if total_trades > 0 else 0

        # Profit Factor
        gross_profit = sum(
            float(trade.get("net_pnl", 0))
            for trade in historical_trades
            if float(trade.get("net_pnl", 0)) > 0
        )
        gross_loss = abs(
            sum(
                float(trade.get("net_pnl", 0))
                for trade in historical_trades
                if float(trade.get("net_pnl", 0)) < 0
            )
        )
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_trade_pnl": avg_trade_pnl,
            "max_drawdown": max_drawdown,
            "profit_factor": profit_factor,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
        }

    def create_empty_result(self, combination: Dict[str, Any]) -> Dict[str, Any]:
        """Создать пустой результат для комбинации без данных"""
        return {
            "test_id": combination["test_id"],
            "regime": combination["regime"],
            "pair": combination["pair"],
            "parameters": combination["parameters"],
            "metrics": self.create_empty_metrics(),
            "timestamp": datetime.now().isoformat(),
        }

    def create_empty_metrics(self) -> Dict[str, Any]:
        """Создать пустые метрики"""
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_trade_pnl": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
        }

    async def run_parameter_tests(self) -> Dict[str, Any]:
        """
        Запустить тестирование всех комбинаций параметров.

        Returns:
            Результаты всех тестов
        """
        logger.info("🚀 Запуск тестирования параметров...")

        # Получаем комбинации для тестирования
        combinations = self.get_test_combinations()

        # Тестируем каждую комбинацию
        results = {}
        for combination in combinations:
            try:
                result = await self.test_combination(combination)
                results[combination["test_id"]] = result

                # Сохраняем промежуточные результаты
                self.save_results(results)

            except Exception as e:
                logger.error(f"❌ Ошибка тестирования {combination['test_id']}: {e}")
                continue

        # Анализируем результаты
        analysis = self.analyze_results(results)

        logger.info("✅ Тестирование параметров завершено")
        return {
            "results": results,
            "analysis": analysis,
            "timestamp": datetime.now().isoformat(),
        }

    def analyze_results(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Анализ результатов тестирования.

        Args:
            results: Результаты тестирования

        Returns:
            Анализ результатов
        """
        if not results:
            return {}

        # Находим лучшие результаты по разным метрикам
        best_by_pnl = max(results.values(), key=lambda x: x["metrics"]["total_pnl"])
        best_by_win_rate = max(results.values(), key=lambda x: x["metrics"]["win_rate"])
        best_by_profit_factor = max(
            results.values(), key=lambda x: x["metrics"]["profit_factor"]
        )

        # Анализ по режимам
        regime_analysis = {}
        for result in results.values():
            regime = result["regime"]
            if regime not in regime_analysis:
                regime_analysis[regime] = []
            regime_analysis[regime].append(result["metrics"]["total_pnl"])

        for regime in regime_analysis:
            pnl_values = regime_analysis[regime]
            regime_analysis[regime] = {
                "avg_pnl": sum(pnl_values) / len(pnl_values),
                "best_pnl": max(pnl_values),
                "worst_pnl": min(pnl_values),
                "tests_count": len(pnl_values),
            }

        # Анализ по парам
        pair_analysis = {}
        for result in results.values():
            pair = result["pair"]
            if pair not in pair_analysis:
                pair_analysis[pair] = []
            pair_analysis[pair].append(result["metrics"]["total_pnl"])

        for pair in pair_analysis:
            pnl_values = pair_analysis[pair]
            pair_analysis[pair] = {
                "avg_pnl": sum(pnl_values) / len(pnl_values),
                "best_pnl": max(pnl_values),
                "worst_pnl": min(pnl_values),
                "tests_count": len(pnl_values),
            }

        return {
            "best_by_pnl": best_by_pnl,
            "best_by_win_rate": best_by_win_rate,
            "best_by_profit_factor": best_by_profit_factor,
            "regime_analysis": regime_analysis,
            "pair_analysis": pair_analysis,
            "total_tests": len(results),
        }

    def save_results(self, results: Dict[str, Any]):
        """Сохранить результаты тестирования"""
        output_file = Path("tests/parameter_test_results.json")

        # Добавляем timestamp
        data = {"results": results, "last_updated": datetime.now().isoformat()}

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"💾 Результаты сохранены в {output_file}")

    def get_optimal_parameters(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Получить оптимальные параметры на основе анализа.

        Args:
            analysis: Результаты анализа

        Returns:
            Оптимальные параметры для применения или пустой dict
        """
        if not analysis or "regime_analysis" not in analysis:
            return {}

        optimal = {}

        # Оптимальные параметры по режимам
        for regime, stats in analysis.get("regime_analysis", {}).items():
            # Находим лучшие параметры для этого режима
            regime_results = [
                r for r in self.test_results.values() if r["regime"] == regime
            ]
            if regime_results:
                best_result = max(
                    regime_results, key=lambda x: x["metrics"]["total_pnl"]
                )
                optimal[regime] = {
                    "parameters": best_result["parameters"],
                    "expected_pnl": best_result["metrics"]["total_pnl"],
                    "expected_win_rate": best_result["metrics"]["win_rate"],
                }

        return optimal

    async def run_all_tests(self) -> Dict[str, Any]:
        """
        Запустить все тестовые комбинации.

        Returns:
            Полные результаты тестирования
        """
        logger.info("🚀 НАЧИНАЕМ ПОЛНОЕ ТЕСТИРОВАНИЕ ПАРАМЕТРОВ")

        # Загружаем план тестирования
        test_plan = self.load_test_plan()
        if not test_plan:
            raise ValueError("❌ Не найден план тестирования")

        results = {}
        total_tests = len(test_plan["combinations"])
        completed = 0

        logger.info(f"📋 Всего тестов: {total_tests}")

        for combination in test_plan["combinations"]:
            test_id = combination["test_id"]
            regime = combination["regime"]
            pair = combination["pair"]

            try:
                logger.info(
                    f"🔄 Тест {completed+1}/{total_tests}: {test_id} ({regime} - {pair})"
                )

                # Запускаем тест
                result = await self.test_combination(combination)
                results[test_id] = result
                self.test_results[test_id] = result  # Сохраняем в классе для анализа

                # Сохраняем промежуточные результаты каждые 10 тестов
                if completed % 10 == 0:
                    self.save_results(results)

                completed += 1

            except Exception as e:
                logger.error(f"❌ Ошибка в тесте {test_id}: {e}")
                results[test_id] = self.create_empty_result(combination)
                completed += 1

        # Финальное сохранение
        self.save_results(results)
        logger.info(f"✅ Все тесты завершены! Сохранено {len(results)} результатов")

        return results

    def save_results(self, results: Dict[str, Any]) -> None:
        """Сохранить результаты тестирования"""
        output_file = Path("tests/parameter_test_results.json")

        # Создаем директорию если нужно
        output_file.parent.mkdir(exist_ok=True)

        # Сохраняем с timestamp
        data = {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(results),
            "results": results,
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"💾 Результаты сохранены в {output_file}")


async def main():
    """Основная функция тестирования параметров"""

    # Создаем тестер
    tester = ParameterTester()

    try:
        # Инициализируем
        await tester.initialize()

        # Запускаем тестирование
        test_results = await tester.run_all_tests()

        # Анализируем результаты
        analysis = tester.analyze_results(test_results)

        print("\n" + "=" * 60)
        print("📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ ПАРАМЕТРОВ")
        print("=" * 60)

        print(f"\n🏆 ЛУЧШИЕ РЕЗУЛЬТАТЫ:")
        if "best_by_pnl" in analysis:
            print(
                f"По P&L: {analysis['best_by_pnl']['test_id']} - {analysis['best_by_pnl']['metrics']['total_pnl']:.2f}"
            )
        else:
            print("По P&L: Нет данных")

        if "best_by_win_rate" in analysis:
            print(
                f"По Win Rate: {analysis['best_by_win_rate']['test_id']} - {analysis['best_by_win_rate']['metrics']['win_rate']:.1%}"
            )
        else:
            print("По Win Rate: Нет данных")

        if "best_by_profit_factor" in analysis:
            print(
                f"По Profit Factor: {analysis['best_by_profit_factor']['test_id']} - {analysis['best_by_profit_factor']['metrics']['profit_factor']:.2f}"
            )
        else:
            print("По Profit Factor: Нет данных")

        print(f"\n📈 АНАЛИЗ ПО РЕЖИМАМ:")
        regime_analysis = analysis.get("regime_analysis", {})
        if regime_analysis:
            for regime, stats in regime_analysis.items():
                print(
                    f"{regime.upper()}: Avg P&L {stats['avg_pnl']:.2f}, Best {stats['best_pnl']:.2f} ({stats['tests_count']} тестов)"
                )
        else:
            print("Нет данных по режимам")

        print(f"\n📊 АНАЛИЗ ПО ПАРАМ:")
        pair_analysis = analysis.get("pair_analysis", {})
        if pair_analysis:
            for pair, stats in pair_analysis.items():
                print(
                    f"{pair}: Avg P&L {stats['avg_pnl']:.2f}, Best {stats['best_pnl']:.2f} ({stats['tests_count']} тестов)"
                )
        else:
            print("Нет данных по парам")

        # Получаем оптимальные параметры
        optimal_params = tester.get_optimal_parameters(analysis)

        print(f"\n💡 РЕКОМЕНДУЕМЫЕ ПАРАМЕТРЫ:")
        if optimal_params:
            for regime, params in optimal_params.items():
                tp_ratio = params["parameters"].get("tp_sl_ratio", "N/A")
                print(
                    f"{regime.upper()}: TP/SL Ratio {tp_ratio}, Ожидаемый P&L: {params['expected_pnl']:.2f}"
                )
        else:
            print("Нет данных для рекомендаций параметров")

        print(
            f"\n✅ Тестирование завершено! Результаты сохранены в tests/parameter_test_results.json"
        )

    except Exception as e:
        logger.error(f"❌ Ошибка тестирования: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
