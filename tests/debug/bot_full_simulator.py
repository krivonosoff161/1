#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔬 ПОЛНЫЙ СИМУЛЯТОР БОТА - Каждый чих, каждый параметр, каждый режим!
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Добавляем корень проекта в путь (из tests/debug идем на 2 уровня вверх)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config import get_config, load_config
from src.okx_client import OKXClient
from src.strategies.scalping.orchestrator import ScalpingOrchestrator


class FullBotSimulator:
    """Полный симулятор торгового бота с детальным выводом"""

    def __init__(self):
        self.config = None
        self.client = None
        self.orchestrator = None
        self.issues = []
        self.step_num = 0

    def header(self, text: str):
        """Красивый заголовок"""
        print("\n" + "=" * 100)
        print(f"{'='*40} {text} {'='*40}")
        print("=" * 100 + "\n")

    def step(self, text: str):
        """Шаг выполнения"""
        self.step_num += 1
        print(f"\n{'▶'*3} ШАГ {self.step_num}: {text} {'▶'*3}")

    def info(self, text: str, indent=0):
        """Информация"""
        prefix = "  " * indent
        print(f"{prefix}ℹ️  {text}")

    def success(self, text: str, indent=0):
        """Успех"""
        prefix = "  " * indent
        print(f"{prefix}✅ {text}")

    def warning(self, text: str, indent=0):
        """Предупреждение"""
        prefix = "  " * indent
        print(f"{prefix}⚠️  {text}")

    def error(self, text: str, indent=0):
        """Ошибка"""
        prefix = "  " * indent
        print(f"{prefix}❌ {text}")
        self.issues.append(text)

    def data(self, label: str, value: any, indent=0):
        """Вывод данных"""
        prefix = "  " * indent
        print(f"{prefix}📊 {label}: {value}")

    async def run_full_simulation(self):
        """Запуск полной симуляции"""
        self.header("🔬 ПОЛНАЯ СИМУЛЯЦИЯ ТОРГОВОГО БОТА")
        self.info(f"Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            # ШАГ 1: Загрузка конфигурации
            await self.simulate_config_loading()

            # ШАГ 2: Подключение к API
            await self.simulate_api_connection()

            # ШАГ 3: Инициализация оркестратора
            await self.simulate_orchestrator_init()

            # ШАГ 4: Проверка параметров ADX
            await self.simulate_adx_params_check()

            # ШАГ 5: Проверка параметров PH
            await self.simulate_ph_params_check()

            # ШАГ 6: Симуляция полного TICK цикла
            await self.simulate_full_tick_cycle("BTC-USDT")

            # ШАГ 7: Тест всех ARM режимов
            await self.simulate_all_arm_regimes()

            # ШАГ 8: Тест фильтров с реальными данными из логов
            await self.simulate_filters_with_real_data()

            # ИТОГИ
            self.print_final_report()

        except Exception as e:
            self.error(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
            import traceback

            traceback.print_exc()
        finally:
            if self.client:
                await self.client.session.close()

    async def simulate_config_loading(self):
        """Шаг 1: Загрузка конфигурации"""
        self.step("ЗАГРУЗКА КОНФИГУРАЦИИ")

        try:
            self.config = load_config("config.yaml")
            self.success("Конфигурация загружена")

            # Проверяем базовый ADX параметр (это словарь Dict)
            adx_cfg = self.config.scalping.adx_filter
            self.data("ADX Filter (базовый)", "", 1)
            self.data("  adx_threshold", adx_cfg.get("adx_threshold"), 2)
            self.data("  di_difference", adx_cfg.get("di_difference"), 2)
            self.data("  adx_period", adx_cfg.get("adx_period"), 2)

            if adx_cfg.get("di_difference") == 5.0:
                self.error("БАЗОВЫЙ di_difference = 5.0 (СТАРОЕ ЗНАЧЕНИЕ!)", 2)
            elif adx_cfg.get("di_difference") == 1.5:
                self.success("БАЗОВЫЙ di_difference = 1.5 (правильно)", 2)

            # Проверяем ARM режимы (это тоже словарь Dict)
            arm_cfg = self.config.scalping.adaptive_regime
            self.data("ARM режимы", "", 1)

            for regime in ["trending", "ranging", "choppy"]:
                regime_cfg = arm_cfg.get(regime, {})
                modules = regime_cfg.get("modules", {})
                adx_module = modules.get("adx_filter", {})

                self.data(f"{regime.upper()}", "", 2)
                self.data("ph_threshold", f"${regime_cfg.get('ph_threshold')}", 3)
                self.data("adx_di_difference", adx_module.get("adx_di_difference"), 3)

                # Проверяем значения
                expected = {"trending": 7.0, "ranging": 1.5, "choppy": 1.0}
                actual = adx_module.get("adx_di_difference")

                if actual == expected[regime]:
                    self.success(f"{regime}: adx_di_difference корректно ({actual})", 3)
                else:
                    self.error(
                        f"{regime}: adx_di_difference = {actual}, ожидалось {expected[regime]}",
                        3,
                    )

        except Exception as e:
            self.error(f"Ошибка загрузки конфигурации: {e}")
            raise

    async def simulate_api_connection(self):
        """Шаг 2: Подключение к API"""
        self.step("ПОДКЛЮЧЕНИЕ К OKX API")

        try:
            # OKXClient ждет APIConfig, а не BotConfig
            okx_api_config = self.config.get_okx_config()
            self.client = OKXClient(okx_api_config)
            await self.client.connect()
            self.success("OKX клиент подключен")

            # Проверяем баланс (get_balance возвращает float напрямую!)
            balance = await self.client.get_balance("USDT")
            self.data("Баланс USDT", f"${balance:.2f}", 1)

            if balance < 100:
                self.warning(f"Низкий баланс: ${balance:.2f}", 1)
            else:
                self.success(f"Баланс достаточен: ${balance:.2f}", 1)

        except Exception as e:
            self.error(f"Ошибка подключения к API: {e}")
            raise

    async def simulate_orchestrator_init(self):
        """Шаг 3: Инициализация оркестратора"""
        self.step("ИНИЦИАЛИЗАЦИЯ ORCHESTRATOR")

        try:
            # ScalpingOrchestrator(client, scalping_config, risk_config)
            self.orchestrator = ScalpingOrchestrator(
                self.client, self.config.scalping, self.config.risk
            )
            self.success("Orchestrator инициализирован")

            # Проверяем ADX фильтр
            if (
                hasattr(self.orchestrator, "adx_filter")
                and self.orchestrator.adx_filter
            ):
                adx_cfg = self.orchestrator.adx_filter.config
                self.data("ADX Filter (после init)", "", 1)
                self.data("adx_threshold", adx_cfg.adx_threshold, 2)
                self.data("di_difference", adx_cfg.di_difference, 2)
                self.data("adx_period", adx_cfg.adx_period, 2)

                if adx_cfg.di_difference == 5.0:
                    self.error("ADX di_difference = 5.0 (СТАРОЕ!)", 2)
                elif adx_cfg.di_difference == 1.5:
                    self.success("ADX di_difference = 1.5 (правильно)", 2)

            # Проверяем ARM
            if hasattr(self.orchestrator, "arm") and self.orchestrator.arm:
                self.data("ARM Manager", "✅ Инициализирован", 1)
                self.data("Текущий режим", self.orchestrator.arm.current_regime, 2)

            # Проверяем PositionManager
            if hasattr(self.orchestrator, "position_manager"):
                self.data("Position Manager", "✅ Инициализирован", 1)

            # Проверяем SignalGenerator
            if hasattr(self.orchestrator, "signal_generator"):
                self.data("Signal Generator", "✅ Инициализирован", 1)

        except Exception as e:
            self.error(f"Ошибка инициализации orchestrator: {e}")
            import traceback

            traceback.print_exc()
            raise

    async def simulate_adx_params_check(self):
        """Шаг 4: Детальная проверка параметров ADX"""
        self.step("ДЕТАЛЬНАЯ ПРОВЕРКА ПАРАМЕТРОВ ADX")

        # Проверяем что параметры попадают в SignalGenerator
        if hasattr(self.orchestrator, "signal_generator"):
            sg = self.orchestrator.signal_generator

            self.data("SignalGenerator.module_params", "", 1)

            if hasattr(sg, "module_params") and sg.module_params:
                if "adx_filter" in sg.module_params:
                    adx_params = sg.module_params["adx_filter"]
                    self.data("adx_threshold", adx_params.get("adx_threshold"), 2)
                    self.data(
                        "adx_di_difference", adx_params.get("adx_di_difference"), 2
                    )

                    di_diff = adx_params.get("adx_di_difference")
                    if di_diff == 5.0:
                        self.error(
                            f"SignalGenerator использует di_difference={di_diff} (СТАРОЕ!)",
                            2,
                        )
                    else:
                        self.success(
                            f"SignalGenerator использует di_difference={di_diff}", 2
                        )
                else:
                    self.warning("adx_filter не найден в module_params", 2)
            else:
                self.warning("module_params пуст или не существует", 2)

    async def simulate_ph_params_check(self):
        """Шаг 5: Проверка параметров Profit Harvesting"""
        self.step("ПРОВЕРКА ПАРАМЕТРОВ PROFIT HARVESTING")

        if hasattr(self.orchestrator, "position_manager"):
            pm = self.orchestrator.position_manager

            self.data("PositionManager PH settings", "", 1)

            if hasattr(pm, "ph_enabled"):
                self.data("ph_enabled", pm.ph_enabled, 2)

            if hasattr(pm, "ph_threshold"):
                self.data("ph_threshold", f"${pm.ph_threshold}", 2)

                # Проверяем значение
                if pm.ph_threshold == 0.20:
                    self.error(f"PH threshold = ${pm.ph_threshold} (СТАРОЕ!)", 2)
                elif pm.ph_threshold in [0.10, 0.12, 0.15]:
                    self.success(f"PH threshold = ${pm.ph_threshold} (правильно)", 2)

            if hasattr(pm, "ph_time_limit"):
                self.data("ph_time_limit", f"{pm.ph_time_limit}s", 2)

    async def simulate_full_tick_cycle(self, symbol: str):
        """Шаг 6: Симуляция полного TICK цикла"""
        self.step(f"СИМУЛЯЦИЯ ПОЛНОГО TICK ЦИКЛА ДЛЯ {symbol}")

        try:
            # 6.1: Получение свечей
            self.info(f"Получение свечей 5m для {symbol}", 1)
            candles = await self.client.get_candles(symbol, "5m", limit=200)
            if not candles:
                self.error(f"Не удалось получить свечи для {symbol}", 1)
                return

            self.success(f"Получено {len(candles)} свечей", 1)
            self.data(
                "Последняя свеча",
                f"O:{candles[0][1]}, H:{candles[0][2]}, L:{candles[0][3]}, C:{candles[0][4]}",
                2,
            )

            # 6.2: Получение текущей цены
            self.info(f"Получение тикера для {symbol}", 1)
            ticker = await self.client.get_ticker(symbol)
            if not ticker:
                self.error(f"Не удалось получить тикер для {symbol}", 1)
                return

            current_price = float(ticker["data"][0]["last"])
            self.success(f"Текущая цена: ${current_price:.2f}", 1)

            # 6.3: Обновление данных в orchestrator
            self.info("Обновление market_data в orchestrator", 1)
            if symbol not in self.orchestrator.market_data:
                self.orchestrator.market_data[symbol] = {}

            self.orchestrator.market_data[symbol]["candles"] = candles
            self.orchestrator.market_data[symbol]["current_price"] = current_price
            self.success("market_data обновлен", 1)

            # 6.4: Расчет индикаторов
            self.info("Расчет индикаторов", 1)
            indicators = self.orchestrator.indicators.calculate_all(candles)
            self.success(f"Индикаторы рассчитаны: {len(indicators)} шт.", 1)

            # Выводим ключевые индикаторы
            self.data("RSI", f"{indicators.get('rsi', 'N/A'):.2f}", 2)
            self.data("ATR", f"{indicators.get('atr', 'N/A'):.4f}", 2)
            self.data("Volume Ratio", f"{indicators.get('volume_ratio', 'N/A'):.2f}", 2)

            # 6.5: Определение режима ARM
            self.info("Определение режима рынка (ARM)", 1)
            if self.orchestrator.arm:
                regime_info = self.orchestrator.arm.detect_regime(candles, indicators)
                regime = regime_info["regime"]
                confidence = regime_info["confidence"]
                reason = regime_info.get("reason", "N/A")

                self.success(f"Режим: {regime} (уверенность: {confidence:.1f}%)", 1)
                self.data("Причина", reason, 2)
                self.data("ADX proxy", regime_info.get("adx_proxy", "N/A"), 2)
                self.data(
                    "Volatility", f"{regime_info.get('volatility', 0)*100:.2f}%", 2
                )
                self.data("Reversals", regime_info.get("reversals", "N/A"), 2)

                # 6.6: Обновление параметров для режима
                self.info(f"Обновление параметров для режима {regime}", 1)
                arm_params = (
                    self.orchestrator.signal_generator.update_regime_parameters(regime)
                )

                self.data("Параметры для режима", regime, 2)
                self.data(
                    "score_threshold", f"{arm_params.get('score_threshold')}/12", 3
                )
                self.data("tp_atr_multiplier", arm_params.get("tp_atr_multiplier"), 3)
                self.data("sl_atr_multiplier", arm_params.get("sl_atr_multiplier"), 3)
                self.data("ph_threshold", f"${arm_params.get('ph_threshold')}", 3)

                if "modules" in arm_params and "adx_filter" in arm_params["modules"]:
                    adx_p = arm_params["modules"]["adx_filter"]
                    self.data("ADX adx_threshold", adx_p.get("adx_threshold"), 3)
                    self.data(
                        "ADX adx_di_difference", adx_p.get("adx_di_difference"), 3
                    )

                    di_diff = adx_p.get("adx_di_difference")
                    if di_diff == 5.0:
                        self.error(f"ARM вернул di_difference={di_diff} (СТАРОЕ!)", 3)
                    else:
                        self.success(f"ARM вернул di_difference={di_diff} ✅", 3)

            # 6.7: Генерация сигнала
            self.info("Генерация сигнала", 1)
            signal = self.orchestrator.signal_generator.generate_signal(
                symbol, candles, indicators, current_price
            )

            if signal:
                self.success("СИГНАЛ СГЕНЕРИРОВАН!", 1)
                self.data("Направление", signal.direction, 2)
                self.data("Score", f"{signal.score}/{signal.total_possible_score}", 2)
                self.data("Причина", signal.reason, 2)
                self.data("Entry Price", f"${signal.entry_price:.2f}", 2)
                self.data("TP", f"${signal.take_profit:.2f}", 2)
                self.data("SL", f"${signal.stop_loss:.2f}", 2)
            else:
                self.warning("Сигнал не сгенерирован (заблокирован фильтрами)", 1)

        except Exception as e:
            self.error(f"Ошибка в TICK цикле: {e}", 1)
            import traceback

            traceback.print_exc()

    async def simulate_all_arm_regimes(self):
        """Шаг 7: Тест всех ARM режимов"""
        self.step("ТЕСТ ВСЕХ ARM РЕЖИМОВ")

        regimes = ["trending", "ranging", "choppy"]

        for regime in regimes:
            self.info(f"Тестирование режима: {regime.upper()}", 1)

            # Обновляем параметры для режима
            arm_params = self.orchestrator.signal_generator.update_regime_parameters(
                regime
            )

            self.data("Score threshold", f"{arm_params.get('score_threshold')}/12", 2)
            self.data("TP multiplier", arm_params.get("tp_atr_multiplier"), 2)
            self.data("SL multiplier", arm_params.get("sl_atr_multiplier"), 2)
            self.data("PH threshold", f"${arm_params.get('ph_threshold')}", 2)

            if "modules" in arm_params and "adx_filter" in arm_params["modules"]:
                adx_p = arm_params["modules"]["adx_filter"]
                self.data("ADX threshold", adx_p.get("adx_threshold"), 2)
                self.data("ADX di_difference", adx_p.get("adx_di_difference"), 2)

                expected_di = {"trending": 7.0, "ranging": 1.5, "choppy": 1.0}
                actual_di = adx_p.get("adx_di_difference")

                if actual_di == expected_di[regime]:
                    self.success(f"{regime}: di_difference={actual_di} ✅", 2)
                else:
                    self.error(
                        f"{regime}: di_difference={actual_di}, ожидалось {expected_di[regime]}",
                        2,
                    )

            expected_ph = {"trending": 0.10, "ranging": 0.12, "choppy": 0.15}
            actual_ph = arm_params.get("ph_threshold")

            if actual_ph == expected_ph[regime]:
                self.success(f"{regime}: ph_threshold=${actual_ph} ✅", 2)
            else:
                self.error(
                    f"{regime}: ph_threshold=${actual_ph}, ожидалось ${expected_ph[regime]}",
                    2,
                )

    async def simulate_filters_with_real_data(self):
        """Шаг 8: Тест фильтров с реальными данными из логов"""
        self.step("ТЕСТ ФИЛЬТРОВ С ДАННЫМИ ИЗ ЛОГОВ")

        # Реальные данные из логов, которые были заблокированы
        test_cases = [
            {
                "name": "BTC-USDT LONG (заблокирован в логах)",
                "symbol": "BTC-USDT",
                "direction": "LONG",
                "plus_di": 12.7,
                "minus_di": 14.6,
                "adx": 15.0,
                "score": 7,
            },
            {
                "name": "BTC-USDT LONG (заблокирован в логах)",
                "symbol": "BTC-USDT",
                "direction": "LONG",
                "plus_di": 16.4,
                "minus_di": 13.9,
                "adx": 20.0,
                "score": 5,
            },
            {
                "name": "ETH-USDT SHORT (заблокирован в логах)",
                "symbol": "ETH-USDT",
                "direction": "SHORT",
                "plus_di": 29.5,
                "minus_di": 14.1,
                "adx": 25.0,
                "score": 8,
            },
        ]

        self.info("Тестируем с разными порогами di_difference", 1)

        for test in test_cases:
            self.data("Test case", test["name"], 2)
            self.data("Direction", test["direction"], 3)
            self.data("+DI", test["plus_di"], 3)
            self.data("-DI", test["minus_di"], 3)
            self.data("Score", f"{test['score']}/12", 3)

            # Тестируем с разными порогами
            thresholds = [5.0, 1.5, 1.0]

            for threshold in thresholds:
                if test["direction"] == "LONG":
                    diff = test["plus_di"] - test["minus_di"]
                    required = test["minus_di"] + threshold
                    passed = test["plus_di"] >= required
                else:  # SHORT
                    diff = test["minus_di"] - test["plus_di"]
                    required = test["plus_di"] + threshold
                    passed = test["minus_di"] >= required

                status = "✅ ПРОШЕЛ" if passed else "❌ ЗАБЛОКИРОВАН"
                self.data(
                    f"Порог {threshold}",
                    f"diff={diff:.1f}, нужно {threshold} → {status}",
                    4,
                )

            print()

    def print_final_report(self):
        """Финальный отчет"""
        self.header("📋 ИТОГОВЫЙ ОТЧЕТ")

        if not self.issues:
            self.success("🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ! БОТ ГОТОВ К РАБОТЕ!")
        else:
            self.error(f"НАЙДЕНО {len(self.issues)} ПРОБЛЕМ:")
            for i, issue in enumerate(self.issues, 1):
                print(f"  {i}. {issue}")
            print()
            self.warning("ИСПРАВЬ ЭТИ ПРОБЛЕМЫ ПЕРЕД ЗАПУСКОМ БОТА!")


async def main():
    simulator = FullBotSimulator()
    await simulator.run_full_simulation()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Симуляция прервана пользователем")
    except Exception as e:
        print(f"\n\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback

        traceback.print_exc()
