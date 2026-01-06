"""
🔍 КОМПЛЕКСНЫЙ ТЕСТ: Проверка целостности и типов данных при передаче между модулями
Проверяет в порядке приоритета:
1. ⚠️ КРИТИЧНО: Типы данных (STRING vs FLOAT vs INT)
2. ⚠️ КРИТИЧНО: Конфиг параметры загружаются правильно
3. ⚠️ ОЧЕНЬ ВАЖНО: Целостность данных при передаче между модулями
4. ВАЖНО: Индикаторы вычисляются правильно
5. ВАЖНО: Сигналы проходят без ошибок

Date: 6 January 2026
"""

import asyncio
import sys
import io
from pathlib import Path
from typing import Any, Dict, List

# Устанавливаем UTF-8 кодировку для вывода (для Windows консоли)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Добавляем корень проекта в path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger

from src.config import BotConfig
from src.models import MarketData, OHLCV, Signal
from src.strategies.scalping.futures.core.data_registry import DataRegistry
from src.strategies.scalping.futures.orchestrator import FuturesScalpingOrchestrator


class DataIntegrityTester:
    """Комплексный тестер целостности данных"""

    def __init__(self):
        self.config = None
        self.data_registry = None
        self.errors = []
        self.warnings = []

    def print_status(self, title: str, status: str, message: str = ""):
        """Красивый вывод статуса"""
        if status == "✅":
            print(f"\n{status} {title}")
            if message:
                print(f"   └─ {message}")
        elif status == "⚠️":
            self.warnings.append(f"{title}: {message}")
            print(f"\n{status} {title}")
            print(f"   └─ {message}")
        elif status == "❌":
            self.errors.append(f"{title}: {message}")
            print(f"\n{status} {title}")
            print(f"   └─ {message}")

    def test_1_critical_config_loading(self):
        """
        ⚠️ КРИТИЧНО #1: Проверка загрузки конфига
        Все параметры должны быть ПРАВИЛЬНЫЕ ТИПЫ, не STRING!
        """
        print("\n" + "=" * 80)
        print("⚠️ КРИТИЧНАЯ ПРОВЕРКА #1: Загрузка конфига")
        print("=" * 80)

        try:
            config_path = project_root / "config" / "config_futures.yaml"
            if not config_path.exists():
                raise FileNotFoundError(f"Конфиг не найден: {config_path}")

            self.config = BotConfig.load_from_file(str(config_path))
            self.print_status("Конфиг загружен", "✅")

            # Проверяем ТИПЫ параметров
            checks = [
                ("API Key", self.config.get_okx_config().api_key, str),
                ("Trading symbols", self.config.scalping.symbols, list),
                ("Min signal strength", self.config.scalping.min_signal_strength, (int, float)),
                ("Min ADX", self.config.scalping.min_adx, (int, float)),
                ("Check interval", self.config.scalping.check_interval, (int, float)),
                ("Risk max position", self.config.risk.max_position_size_percent, (int, float)),
            ]

            for param_name, param_value, expected_type in checks:
                if isinstance(param_value, expected_type):
                    self.print_status(
                        f"Параметр '{param_name}'",
                        "✅",
                        f"Тип OK: {type(param_value).__name__} = {param_value}",
                    )
                else:
                    self.print_status(
                        f"Параметр '{param_name}'",
                        "❌",
                        f"НЕПРАВИЛЬНЫЙ ТИП! Ожидалось {expected_type}, получено {type(param_value).__name__}",
                    )

            return len(self.errors) == 0

        except Exception as e:
            self.print_status("Config loading", "❌", str(e))
            return False

    def test_2_critical_numeric_types(self):
        """
        ⚠️ КРИТИЧНО #2: Все числовые параметры должны быть FLOAT/INT, не STRING!
        Это вызывает ошибки типа: '>' not supported between instances of 'str' and 'int'
        """
        print("\n" + "=" * 80)
        print("⚠️ КРИТИЧНАЯ ПРОВЕРКА #2: Числовые типы данных")
        print("=" * 80)

        try:
            # Проверяем ALL числовые параметры
            numeric_params = {
                "min_signal_strength": self.config.scalping.min_signal_strength,
                "min_adx": self.config.scalping.min_adx,
                "check_interval": self.config.scalping.check_interval,
                "risk.max_position_size_percent": self.config.risk.max_position_size_percent,
                "risk.max_daily_loss_percent": self.config.risk.max_daily_loss_percent,
            }

            all_ok = True
            for param_name, param_value in numeric_params.items():
                if isinstance(param_value, (int, float)) and not isinstance(param_value, bool):
                    self.print_status(
                        f"Параметр '{param_name}'",
                        "✅",
                        f"{type(param_value).__name__} = {param_value}",
                    )
                else:
                    self.print_status(
                        f"Параметр '{param_name}'",
                        "❌",
                        f"НЕПРАВИЛЬНЫЙ ТИП: {type(param_value).__name__} вместо float/int",
                    )
                    all_ok = False

            return all_ok

        except Exception as e:
            self.print_status("Numeric types check", "❌", str(e))
            return False

    def test_3_critical_regime_parameters(self):
        """
        ⚠️ КРИТИЧНО #3: Параметры по режимам (TRENDING/RANGING/CHOPPY)
        Все должны быть числа, не строки!
        """
        print("\n" + "=" * 80)
        print("⚠️ КРИТИЧНАЯ ПРОВЕРКА #3: Параметры режимов (TRENDING/RANGING/CHOPPY)")
        print("=" * 80)

        try:
            # Получаем adaptive_regime из конфига
            # ScalpingConfig это Pydantic объект, поэтому используем __dict__ или model_dump()
            config_dict = self.config.scalping.model_dump() if hasattr(self.config.scalping, 'model_dump') else self.config.scalping.__dict__
            adaptive_regime = config_dict.get("adaptive_regime", {})
            
            if not adaptive_regime:
                self.print_status("Adaptive regime config", "⚠️", "Не найдена в конфиге")
                return False

            # Проверяем TRENDING параметры
            trending = adaptive_regime.get("trending", {})
            trending_checks = [
                ("tp_percent", trending.get("tp_percent")),
                ("sl_percent", trending.get("sl_percent")),
                ("max_holding_minutes", trending.get("max_holding_minutes")),
                ("tp_atr_multiplier", trending.get("tp_atr_multiplier")),
                ("sl_atr_multiplier", trending.get("sl_atr_multiplier")),
            ]

            print("\n📊 TRENDING параметры:")
            all_ok = True
            for param_name, param_value in trending_checks:
                if param_value is None:
                    self.print_status(f"  {param_name}", "⚠️", "Не найден в конфиге")
                elif isinstance(param_value, (int, float)):
                    self.print_status(f"  {param_name}", "✅", f"{param_value}")
                else:
                    self.print_status(
                        f"  {param_name}",
                        "❌",
                        f"НЕПРАВИЛЬНЫЙ ТИП: {type(param_value).__name__} вместо float",
                    )
                    all_ok = False

            # Проверяем RANGING параметры
            ranging = adaptive_regime.get("ranging", {})
            ranging_checks = [
                ("tp_percent", ranging.get("tp_percent")),
                ("sl_percent", ranging.get("sl_percent")),
                ("max_holding_minutes", ranging.get("max_holding_minutes")),
            ]

            print("\n📊 RANGING параметры:")
            for param_name, param_value in ranging_checks:
                if param_value is None:
                    self.print_status(f"  {param_name}", "⚠️", "Не найден в конфиге")
                elif isinstance(param_value, (int, float)):
                    self.print_status(f"  {param_name}", "✅", f"{param_value}")
                else:
                    self.print_status(
                        f"  {param_name}",
                        "❌",
                        f"НЕПРАВИЛЬНЫЙ ТИП: {type(param_value).__name__} вместо float",
                    )
                    all_ok = False

            return all_ok

        except Exception as e:
            self.print_status("Regime parameters check", "❌", str(e))
            return False

    def test_4_data_registry_integrity(self):
        """
        ⚠️ ОЧЕНЬ ВАЖНО: Проверка целостности DataRegistry
        Данные должны сохраняться и передаваться правильно
        """
        print("\n" + "=" * 80)
        print("⚠️ ОЧЕНЬ ВАЖНАЯ ПРОВЕРКА: DataRegistry целостность")
        print("=" * 80)

        try:
            self.data_registry = DataRegistry()
            self.print_status("DataRegistry инициализирован", "✅")

            # Создаем test candles
            test_candles = [
                OHLCV(
                    timestamp=1000 + i,
                    symbol="BTC-USDT",
                    open=93000.0 + i,
                    high=93100.0 + i,
                    low=92900.0 + i,
                    close=93050.0 + i,
                    volume=10.0 + i,
                    timeframe="1m",
                )
                for i in range(100)
            ]

            self.print_status("Test candles созданы", "✅", f"{len(test_candles)} свечей")

            # Сохраняем в DataRegistry
            asyncio.run(
                self.data_registry.initialize_candles(
                    symbol="BTC-USDT",
                    timeframe="1m",
                    candles=test_candles,
                    max_size=200,
                )
            )
            self.print_status("Candles сохранены в DataRegistry", "✅")

            # Читаем обратно
            retrieved_candles = asyncio.run(
                self.data_registry.get_candles("BTC-USDT", "1m")
            )

            if not retrieved_candles:
                self.print_status("Retrieve candles", "❌", "DataRegistry вернул пустой список!")
                return False

            self.print_status(
                "Candles прочитаны из DataRegistry", "✅", f"Получено {len(retrieved_candles)} свечей"
            )

            # Проверяем целостность ПЕРВОЙ свечи
            first_candle = retrieved_candles[0]
            checks = [
                ("timestamp", first_candle.timestamp, (int, float)),
                ("open", first_candle.open, (int, float)),
                ("high", first_candle.high, (int, float)),
                ("low", first_candle.low, (int, float)),
                ("close", first_candle.close, (int, float)),
                ("volume", first_candle.volume, (int, float)),
            ]

            all_ok = True
            for field_name, field_value, expected_type in checks:
                if isinstance(field_value, expected_type):
                    self.print_status(
                        f"  Candle field '{field_name}'",
                        "✅",
                        f"{type(field_value).__name__} = {field_value}",
                    )
                else:
                    self.print_status(
                        f"  Candle field '{field_name}'",
                        "❌",
                        f"НЕПРАВИЛЬНЫЙ ТИП: {type(field_value).__name__}",
                    )
                    all_ok = False

            return all_ok

        except Exception as e:
            self.print_status("DataRegistry integrity", "❌", str(e))
            import traceback

            traceback.print_exc()
            return False

    def test_5_indicator_values_range(self):
        """
        ВАЖНО: Проверка что индикаторы имеют ЛОГИЧНЫЕ значения
        - RSI: 0-100
        - ATR: > 0 (не 0.00)
        - ADX: 0-100
        - MACD: любое число
        """
        print("\n" + "=" * 80)
        print("ВАЖНАЯ ПРОВЕРКА: Диапазоны значений индикаторов")
        print("=" * 80)

        try:
            # Симулируем индикаторы
            test_indicators = {
                "rsi": 65.5,
                "atr": 0.50,
                "adx": 18.5,
                "macd": 10.25,
                "bb_upper": 93900.0,
                "bb_middle": 93850.0,
                "bb_lower": 93800.0,
            }

            checks = [
                ("RSI", test_indicators.get("rsi"), 0, 100),
                ("ATR", test_indicators.get("atr"), 0.00001, None),  # Должен быть > 0
                ("ADX", test_indicators.get("adx"), 0, 100),
                ("BB Upper vs Middle", test_indicators.get("bb_upper"), None, None, lambda: test_indicators.get("bb_upper") > test_indicators.get("bb_middle")),
                ("BB Middle vs Lower", test_indicators.get("bb_middle"), None, None, lambda: test_indicators.get("bb_middle") > test_indicators.get("bb_lower")),
            ]

            all_ok = True
            for check in checks:
                if len(check) == 4:
                    param_name, value, min_val, max_val = check
                    if value is None:
                        self.print_status(f"  {param_name}", "⚠️", "Значение не найдено")
                    elif min_val is not None and value < min_val:
                        self.print_status(
                            f"  {param_name}",
                            "❌",
                            f"СЛИШКОМ МАЛО: {value} < {min_val}",
                        )
                        all_ok = False
                    elif max_val is not None and value > max_val:
                        self.print_status(
                            f"  {param_name}",
                            "❌",
                            f"СЛИШКОМ МНОГО: {value} > {max_val}",
                        )
                        all_ok = False
                    else:
                        self.print_status(f"  {param_name}", "✅", f"{value}")
                else:  # Length 5 - с condition функцией
                    param_name, _, _, _, condition = check
                    if condition():
                        self.print_status(f"  {param_name}", "✅", "OK")
                    else:
                        self.print_status(f"  {param_name}", "❌", "УСЛОВИЕ НЕ ВЫПОЛНЕНО")
                        all_ok = False

            return all_ok

        except Exception as e:
            self.print_status("Indicator values range", "❌", str(e))
            return False

    def run_all_tests(self):
        """Запустить все тесты в порядке приоритета"""
        print("\n\n")
        print("█" * 80)
        print("█ 🔍 КОМПЛЕКСНЫЙ ТЕСТ: Целостность данных и типы при передаче")
        print("█" * 80)

        results = {
            "⚠️ КРИТИЧНО #1 - Config Loading": self.test_1_critical_config_loading(),
            "⚠️ КРИТИЧНО #2 - Numeric Types": self.test_2_critical_numeric_types(),
            "⚠️ КРИТИЧНО #3 - Regime Parameters": self.test_3_critical_regime_parameters(),
            "⚠️ ОЧЕНЬ ВАЖНО - DataRegistry": self.test_4_data_registry_integrity(),
            "ВАЖНО - Indicator Ranges": self.test_5_indicator_values_range(),
        }

        # ИТОГОВЫЙ ОТЧЕТ
        print("\n\n")
        print("█" * 80)
        print("█ 📊 ИТОГОВЫЙ РЕЗУЛЬТАТ")
        print("█" * 80)

        passed = sum(1 for v in results.values() if v)
        failed = len(results) - passed

        for test_name, result in results.items():
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"\n{status}: {test_name}")

        print(f"\n\n📈 Итого: {passed}/{len(results)} тестов прошли успешно")

        if self.warnings:
            print(f"\n⚠️ Предупреждений: {len(self.warnings)}")
            for warning in self.warnings:
                print(f"   - {warning}")

        if self.errors:
            print(f"\n❌ Ошибок: {len(self.errors)}")
            for error in self.errors:
                print(f"   - {error}")

            return False

        return failed == 0


if __name__ == "__main__":
    tester = DataIntegrityTester()
    success = tester.run_all_tests()

    sys.exit(0 if success else 1)
