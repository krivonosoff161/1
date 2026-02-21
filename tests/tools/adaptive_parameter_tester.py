"""
Adaptive Parameter Testing Framework - Тестирование адаптивных параметров TP/SL

РАСШИРЕНИЕ parameter_tester.py для тестирования адаптивных параметров.

КОНЦЕПЦИЯ:
1. Тестирует адаптивные параметры на основе контекста (баланс, P&L, просадка)
2. Создает сценарии с разными состояниями аккаунта/позиций
3. Симулирует торговлю с адаптивными TP/SL
4. Сравнивает эффективность адаптивных vs статических параметров

НЕ МЕНЯЕТ ОСНОВНОЙ КОД - только тестирует адаптации!
"""

import asyncio
import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

# Импорт компонентов (без проблемных модулей)
from src.config import BotConfig


@dataclass
class AdaptiveContext:
    """Контекст для адаптивных параметров"""

    balance: float
    current_pnl: float  # Текущий P&L позиции в %
    drawdown: float  # Текущая просадка в %
    position_size: float
    margin_used: float
    regime: str


class AdaptiveParameterTester:
    """
    Тестер адаптивных параметров.

    Тестирует адаптивные параметры TP/SL в разных контекстах.
    """

    def __init__(self, config_path: str = "config/config_futures.yaml"):
        self.config_path = config_path
        self.config = None
        self.test_results = {}
        self.adaptive_scenarios = self._create_adaptive_scenarios()

        logger.info("✅ AdaptiveParameterTester инициализирован")

    def _create_adaptive_scenarios(self) -> List[AdaptiveContext]:
        """
        Создать сценарии для тестирования адаптивных параметров.

        ПЛАВНАЯ АДАПТАЦИЯ: балансы от $500 до $5000 с шагом $500
        """
        scenarios = []

        # Балансы для тестирования (плавная адаптация)
        balances = [500, 800, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 5000]

        # P&L позиции (%)
        pnl_levels = [-5.0, -2.0, 0.0, 2.0, 5.0, 8.0]

        # Просадки (%)
        drawdowns = [0.0, 3.0, 7.0, 10.0]

        # Режимы
        regimes = ["ranging", "trending", "choppy"]

        for balance in balances:
            for pnl in pnl_levels:
                for drawdown in drawdowns:
                    for regime in regimes:
                        position_size = self._calculate_adaptive_position_size(balance)
                        margin_used = balance * 0.15

                        scenario = AdaptiveContext(
                            balance=balance,
                            current_pnl=pnl,
                            drawdown=drawdown,
                            position_size=position_size,
                            margin_used=margin_used,
                            regime=regime,
                        )
                        scenarios.append(scenario)

        logger.info(
            f"🎭 Создано {len(scenarios)} адаптивных сценариев (плавная адаптация)"
        )
        return scenarios

        for balance in balances:
            for pnl in pnl_levels:
                for drawdown in drawdowns:
                    for regime in regimes:
                        position_size = self._calculate_adaptive_position_size(balance)
                        margin_used = balance * 0.15

                        scenario = AdaptiveContext(
                            balance=balance,
                            current_pnl=pnl,
                            drawdown=drawdown,
                            position_size=position_size,
                            margin_used=margin_used,
                            regime=regime,
                        )
                        scenarios.append(scenario)

        logger.info(f"🎭 Создано {len(scenarios)} адаптивных сценариев")
        return scenarios

    def _calculate_adaptive_position_size(self, balance: float) -> float:
        """Расчет размера позиции по балансу"""
        if balance < 1500:
            return 50
        elif balance < 3500:
            return 150
        else:
            return 300

    async def initialize(self):
        """Инициализация компонентов"""
        self.config = BotConfig.load_from_file(self.config_path)
        logger.info("✅ Конфигурация загружена")

    def get_adaptive_test_combinations(self) -> List[Dict[str, Any]]:
        """Получить комбинации для тестирования адаптивных параметров."""
        combinations = []
        symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT"]

        base_params = {
            "tp_atr_multiplier": 2.0,
            "sl_atr_multiplier": 1.5,
            "max_holding_minutes": 30,
            "min_holding_minutes": 1.0,
        }

        for symbol in symbols:
            for scenario in self.adaptive_scenarios:
                combination = {
                    "test_id": f"adaptive_{symbol}_{scenario.balance}_{scenario.current_pnl}_{scenario.drawdown}_{scenario.regime}",
                    "symbol": symbol,
                    "scenario": scenario,
                    "base_params": base_params,
                    "adaptive_enabled": True,
                }
                combinations.append(combination)

        logger.info(f"📊 Создано {len(combinations)} адаптивных комбинаций")
        return combinations

    async def load_historical_trades(self, symbol: str) -> List[Dict[str, Any]]:
        """Загрузить исторические сделки для символа."""
        try:
            log_dir = Path("logs/futures/archived")
            if not log_dir.exists():
                return []

            log_dirs = [d for d in log_dir.iterdir() if d.is_dir()]
            if not log_dirs:
                return []

            latest_dir = max(log_dirs, key=lambda x: x.stat().st_mtime)
            dir_name = latest_dir.name
            if "_" in dir_name:
                date_part = dir_name.split("_")[1]
                csv_file = latest_dir / f"all_data_{date_part}.csv"
            else:
                csv_file = latest_dir / "all_data.csv"

            if not csv_file.exists():
                logger.warning(f"❌ CSV файл не найден: {csv_file}")
                return []

            trades = []
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if (
                        row.get("record_type") == "trades"
                        and row.get("symbol") == symbol
                    ):
                        trades.append(row)

            logger.info(f"📊 Загружено {len(trades)} сделок для {symbol}")
            return trades

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки данных: {e}")
            return []

    def simulate_adaptive_params(
        self, scenario: AdaptiveContext, base_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Симулировать адаптивные параметры на основе сценария.

        ПЛАВНАЯ АДАПТАЦИЯ по балансу (интерполяция между порогами)
        """
        # Базовые параметры
        tp_base = base_params.get("tp_atr_multiplier", 2.0)
        sl_base = base_params.get("sl_atr_multiplier", 1.5)

        # ПЛАВНАЯ АДАПТАЦИЯ ПО БАЛАНСУ
        # Пороги из документа: small < $1500, medium $1500-$3500, large > $3500
        (
            balance_factor_tp,
            balance_factor_sl,
        ) = self._calculate_balance_adaptation_factors(scenario.balance)

        # Адаптация по P&L
        pnl_factor = self._calculate_pnl_adaptation_factor(scenario.current_pnl)

        # Адаптация по просадке
        drawdown_factor = self._calculate_drawdown_adaptation_factor(scenario.drawdown)

        # Расчет адаптивных параметров
        adaptive_tp = tp_base * balance_factor_tp * pnl_factor
        adaptive_sl = sl_base * balance_factor_sl * drawdown_factor

        # Ограничения (из документа)
        adaptive_tp = min(max(adaptive_tp, 1.0), 5.0)  # 1.0 - 5.0
        adaptive_sl = min(max(adaptive_sl, 0.5), 3.0)  # 0.5 - 3.0

        return {
            "tp_atr_multiplier": adaptive_tp,
            "sl_atr_multiplier": adaptive_sl,
            "adaptations": {
                "balance_factor_tp": balance_factor_tp,
                "balance_factor_sl": balance_factor_sl,
                "pnl_factor": pnl_factor,
                "drawdown_factor": drawdown_factor,
            },
        }

    def _calculate_balance_adaptation_factors(
        self, balance: float
    ) -> tuple[float, float]:
        """
        Рассчитать коэффициенты адаптации по балансу (плавная интерполяция).

        Returns:
            (tp_factor, sl_factor)
        """
        # Пороги из документа
        SMALL_THRESHOLD = 1500  # < $1500
        LARGE_THRESHOLD = 3500  # >= $3500

        # Коэффициенты для каждого диапазона
        SMALL_TP = 0.9  # Консервативный TP
        SMALL_SL = 0.9  # Ужесточенный SL
        MEDIUM_TP = 1.0  # Стандартный TP
        MEDIUM_SL = 1.0  # Стандартный SL
        LARGE_TP = 1.1  # Агрессивный TP
        LARGE_SL = 1.0  # Стандартный SL

        if balance < SMALL_THRESHOLD:
            # От 0 до SMALL_THRESHOLD: интерполяция от 0.8 до 0.9 (еще консервативнее при очень низком балансе)
            if balance <= 500:
                tp_factor = 0.8
                sl_factor = 0.8
            else:
                # Линейная интерполяция от 0.8 до 0.9
                ratio = (balance - 500) / (SMALL_THRESHOLD - 500)
                tp_factor = 0.8 + (SMALL_TP - 0.8) * ratio
                sl_factor = 0.8 + (SMALL_SL - 0.8) * ratio

        elif balance < LARGE_THRESHOLD:
            # От SMALL_THRESHOLD до LARGE_THRESHOLD: интерполяция от 0.9 до 1.0
            ratio = (balance - SMALL_THRESHOLD) / (LARGE_THRESHOLD - SMALL_THRESHOLD)
            tp_factor = SMALL_TP + (MEDIUM_TP - SMALL_TP) * ratio
            sl_factor = SMALL_SL + (MEDIUM_SL - SMALL_SL) * ratio

        else:
            # От LARGE_THRESHOLD и выше: интерполяция от 1.0 до 1.1 (до баланса $5000)
            if balance >= 5000:
                tp_factor = LARGE_TP
                sl_factor = LARGE_SL
            else:
                ratio = (balance - LARGE_THRESHOLD) / (5000 - LARGE_THRESHOLD)
                tp_factor = MEDIUM_TP + (LARGE_TP - MEDIUM_TP) * ratio
                sl_factor = MEDIUM_SL + (LARGE_SL - MEDIUM_SL) * ratio

        return tp_factor, sl_factor

    def _calculate_pnl_adaptation_factor(self, current_pnl: float) -> float:
        """
        Рассчитать коэффициент адаптации по P&L позиции.
        """
        # Из документа: расширение TP при сильном P&L
        if current_pnl > 5.0:  # > 5%
            extension = min((current_pnl - 5.0) * 0.3, 0.5)  # Макс +0.5x
            return 1.0 + extension
        return 1.0

    def _calculate_drawdown_adaptation_factor(self, drawdown: float) -> float:
        """
        Рассчитать коэффициент адаптации по просадке.
        """
        # Из документа: ужесточение SL при просадке
        if drawdown > 5.0:  # > 5%
            tightening = min((drawdown - 5.0) * 0.1, 0.3)  # Макс +0.3x
            return 1.0 + tightening
        return 1.0

    async def test_adaptive_combination(
        self, combination: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Тестировать адаптивную комбинацию."""
        scenario = combination["scenario"]

        logger.info(f"🧪 Тестирование: {combination['test_id']}")

        # Загружаем исторические данные
        historical_trades = await self.load_historical_trades(combination["symbol"])

        if not historical_trades:
            return self._create_empty_result(combination)

        # Получаем адаптивные параметры
        adaptive_params = self.simulate_adaptive_params(
            scenario, combination["base_params"]
        )

        # Симулируем торговлю
        results = self._simulate_adaptive_trading(
            historical_trades, adaptive_params, scenario
        )

        return {
            "test_id": combination["test_id"],
            "symbol": combination["symbol"],
            "scenario": {
                "balance": scenario.balance,
                "current_pnl": scenario.current_pnl,
                "drawdown": scenario.drawdown,
                "position_size": scenario.position_size,
                "margin_used": scenario.margin_used,
                "regime": scenario.regime,
            },
            "base_params": combination["base_params"],
            "adaptive_params": adaptive_params,
            "metrics": results,
            "timestamp": datetime.now().isoformat(),
        }

    def _simulate_adaptive_trading(
        self,
        trades: List[Dict[str, Any]],
        adaptive_params: Dict[str, Any],
        scenario: AdaptiveContext,
    ) -> Dict[str, Any]:
        """Симулировать торговлю с адаптивными параметрами."""
        total_pnl = 0.0
        wins = 0
        losses = 0
        max_drawdown = 0.0
        peak_pnl = 0.0

        tp_mult = adaptive_params.get("tp_atr_multiplier", 2.0)
        sl_mult = adaptive_params.get("sl_atr_multiplier", 1.5)

        for trade in trades:
            try:
                entry_price = float(trade.get("entry_price", 0))
                exit_price = float(trade.get("exit_price", 0))
                side = trade.get("side", "long")
                size = float(trade.get("size", 1))

                if entry_price == 0:
                    continue

                # ATR estimate
                atr_estimate = entry_price * 0.015

                # Adaptive TP/SL levels
                if side == "long":
                    tp_price = entry_price + (atr_estimate * tp_mult)
                    sl_price = entry_price - (atr_estimate * sl_mult)
                else:
                    tp_price = entry_price - (atr_estimate * tp_mult)
                    sl_price = entry_price + (atr_estimate * sl_mult)

                # Determine trade outcome
                if side == "long":
                    if exit_price >= tp_price:
                        pnl = size * (tp_price - entry_price)
                        wins += 1
                    elif exit_price <= sl_price:
                        pnl = size * (sl_price - entry_price)
                        losses += 1
                    else:
                        pnl = float(trade.get("net_pnl", 0))
                        if pnl > 0:
                            wins += 1
                        else:
                            losses += 1
                else:
                    if exit_price <= tp_price:
                        pnl = size * (entry_price - tp_price)
                        wins += 1
                    elif exit_price >= sl_price:
                        pnl = size * (entry_price - sl_price)
                        losses += 1
                    else:
                        pnl = float(trade.get("net_pnl", 0))
                        if pnl > 0:
                            wins += 1
                        else:
                            losses += 1

                total_pnl += pnl

                # Drawdown calculation
                if total_pnl > peak_pnl:
                    peak_pnl = total_pnl
                max_drawdown = max(max_drawdown, peak_pnl - total_pnl)

            except Exception as e:
                logger.warning(f"⚠️ Ошибка обработки сделки: {e}")
                continue

        total_trades = wins + losses
        win_rate = wins / total_trades if total_trades > 0 else 0

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_trade_pnl": total_pnl / total_trades if total_trades > 0 else 0,
            "max_drawdown": max_drawdown,
        }

    def _create_empty_result(self, combination: Dict[str, Any]) -> Dict[str, Any]:
        """Создать пустой результат для случая отсутствия данных."""
        return {
            "test_id": combination["test_id"],
            "symbol": combination["symbol"],
            "scenario": {},
            "base_params": combination["base_params"],
            "adaptive_params": {},
            "metrics": {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_trade_pnl": 0.0,
                "max_drawdown": 0.0,
            },
            "timestamp": datetime.now().isoformat(),
        }

    async def run_adaptive_tests(self, max_tests: int = 200) -> Dict[str, Any]:
        """Запустить тестирование адаптивных параметров."""
        logger.info("🚀 Запуск тестирования адаптивных параметров (ПЛАВНАЯ АДАПТАЦИЯ)")

        await self.initialize()

        combinations = self.get_adaptive_test_combinations()

        # Ограничение для теста - выбираем равномерно по балансам
        if len(combinations) > max_tests:
            # Группируем по балансам
            balance_groups = {}
            for combo in combinations:
                balance = combo["scenario"].balance
                if balance not in balance_groups:
                    balance_groups[balance] = []
                balance_groups[balance].append(combo)

            # Выбираем равное количество из каждой группы балансов
            selected_combinations = []
            balances = list(balance_groups.keys())
            per_balance = max(1, max_tests // len(balances))

            for balance in balances:
                group_combos = balance_groups[balance]
                selected_count = min(per_balance, len(group_combos))
                selected_combinations.extend(group_combos[:selected_count])

            # Если не хватило, добавляем еще из первых групп
            if len(selected_combinations) < max_tests:
                remaining = max_tests - len(selected_combinations)
                for balance in balances:
                    if remaining <= 0:
                        break
                    group_combos = balance_groups[balance]
                    available = len(group_combos) - per_balance
                    if available > 0:
                        add_count = min(remaining, available)
                        selected_combinations.extend(
                            group_combos[per_balance : per_balance + add_count]
                        )
                        remaining -= add_count

            combinations = selected_combinations[:max_tests]

        logger.info(
            f"📊 Тестируем {len(combinations)} комбинаций (из {len(self.adaptive_scenarios) * 4} доступных)"
        )

        results = []

        for i, combination in enumerate(combinations):
            logger.info(f"📈 Прогресс: {i+1}/{len(combinations)}")

            result = await self.test_adaptive_combination(combination)
            results.append(result)

        # Анализ результатов
        analysis = self.analyze_adaptive_results(results)

        final_results = {
            "results": results,
            "analysis": analysis,
            "timestamp": datetime.now().isoformat(),
        }

        # Сохранение результатов
        self._save_results(final_results, "adaptive_test_results.json")

        logger.info("✅ Тестирование адаптивных параметров завершено")
        return final_results

    def analyze_adaptive_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Анализировать результаты тестирования."""
        # Фильтруем пустые результаты
        valid_results = [r for r in results if r["metrics"]["total_trades"] > 0]

        if not valid_results:
            return {"error": "Нет валидных результатов для анализа"}

        # Анализ по балансу
        balance_analysis = {}
        for result in valid_results:
            balance = result["scenario"]["balance"]
            if balance not in balance_analysis:
                balance_analysis[balance] = []
            balance_analysis[balance].append(result)

        # Группировка по диапазонам для плавного анализа
        balance_ranges = {
            "very_low": [],  # $500-$800
            "low": [],  # $1000-$1500
            "medium": [],  # $2000-$3000
            "high": [],  # $3500-$5000
        }

        for balance, results_list in balance_analysis.items():
            if balance <= 800:
                balance_ranges["very_low"].extend(results_list)
            elif balance <= 1500:
                balance_ranges["low"].extend(results_list)
            elif balance <= 3000:
                balance_ranges["medium"].extend(results_list)
            else:
                balance_ranges["high"].extend(results_list)

        # Анализ по диапазонам
        range_analysis = {}
        for range_name, group_results in balance_ranges.items():
            if group_results:
                win_rates = [r["metrics"]["win_rate"] for r in group_results]
                pnls = [r["metrics"]["total_pnl"] for r in group_results]
                tp_multipliers = [
                    r["adaptive_params"]["tp_atr_multiplier"] for r in group_results
                ]

                range_analysis[range_name] = {
                    "count": len(group_results),
                    "avg_win_rate": sum(win_rates) / len(win_rates),
                    "avg_pnl": sum(pnls) / len(pnls),
                    "avg_tp_multiplier": sum(tp_multipliers) / len(tp_multipliers),
                    "balance_range": self._get_balance_range_description(range_name),
                }

        # Топ результатов
        sorted_results = sorted(
            valid_results, key=lambda x: x["metrics"]["total_pnl"], reverse=True
        )

        return {
            "balance_analysis": range_analysis,
            "top_performers": sorted_results[:5],
            "total_tests": len(results),
            "valid_tests": len(valid_results),
        }

    def _save_results(self, results: Dict[str, Any], filename: str):
        """Сохранить результаты в файл."""
        output_path = Path("tests/results") / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        logger.info(f"💾 Результаты сохранены: {output_path}")

    def _get_balance_range_description(self, range_name: str) -> str:
        """Получить описание диапазона баланса."""
        descriptions = {
            "very_low": "$500-$800 (очень низкий)",
            "low": "$1000-$1500 (низкий)",
            "medium": "$2000-$3000 (средний)",
            "high": "$3500-$5000 (высокий)",
        }
        return descriptions.get(range_name, range_name)


async def run_adaptive_parameter_tests():
    """Запустить тестирование адаптивных параметров"""
    tester = AdaptiveParameterTester()
    results = await tester.run_adaptive_tests(
        max_tests=20
    )  # Ограничено для быстрого теста

    # Вывод основных результатов
    analysis = results["analysis"]

    print("\n📊 АНАЛИЗ РЕЗУЛЬТАТОВ АДАПТИВНОГО ТЕСТИРОВАНИЯ")
    print("=" * 60)

    if "error" in analysis:
        print(f"❌ {analysis['error']}")
        return results

    print(f"📈 Всего тестов: {analysis['total_tests']}")
    print(f"✅ Валидных тестов: {analysis['valid_tests']}")

    print("\n💰 АНАЛИЗ ПО ДИАПАЗОНАМ БАЛАНСА (ПЛАВНАЯ АДАПТАЦИЯ):")
    for range_name, metrics in analysis["balance_analysis"].items():
        print(f"{metrics['balance_range']}:")
        print(f"  Количество тестов: {metrics['count']}")
        print(f"  Средний Win Rate: {metrics['avg_win_rate']:.2f}")
        print(f"  Средний P&L: ${metrics['avg_pnl']:.2f}")
        print(f"  Средний TP множитель: {metrics['avg_tp_multiplier']:.2f}")
        print()

    print("🏆 ТОП-5 ЛУЧШИХ СЦЕНАРИЕВ:")
    for i, result in enumerate(analysis["top_performers"][:3], 1):
        scenario = result["scenario"]
        metrics = result["metrics"]
        print(
            f"{i}. Баланс:${scenario['balance']}, P&L:{scenario['current_pnl']}%, "
            f"Режим:{scenario['regime']}, Win Rate:{metrics['win_rate']:.2f}, "
            f"P&L:${metrics['total_pnl']:.2f}"
        )

    return results


if __name__ == "__main__":
    asyncio.run(run_adaptive_parameter_tests())
