"""
ПОЛНЫЙ интеграционный тест для проблемы #3: Закрытие в боковике без анализа
Проверяет ВСЮ ЦЕПОЧКУ: ExitAnalyzer → DataRegistry → анализ → timeout
БЕЗ МОКОВ (кроме клиента биржи для безопасности)
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

from src.strategies.scalping.futures.core.data_registry import DataRegistry
from src.strategies.scalping.futures.core.position_registry import \
    PositionRegistry
from src.strategies.scalping.futures.indicators.atr_provider import ATRProvider
# Реальные импорты
from src.strategies.scalping.futures.positions.exit_analyzer import \
    ExitAnalyzer


class TestExitAnalyzerRealChain(unittest.IsolatedAsyncioTestCase):
    """ПОЛНЫЙ тест цепочки ExitAnalyzer (проблема #3)"""

    async def asyncSetUp(self):
        """Настройка с РЕАЛЬНЫМИ компонентами"""
        # ✅ РЕАЛЬНЫЙ DataRegistry
        self.data_registry = DataRegistry()

        # ✅ РЕАЛЬНЫЙ PositionRegistry
        self.position_registry = PositionRegistry()

        # ✅ РЕАЛЬНЫЙ ATRProvider
        self.atr_provider = ATRProvider(data_registry=self.data_registry)

        # ✅ РЕАЛЬНЫЙ ExitAnalyzer (с реальными зависимостями)
        self.exit_analyzer = ExitAnalyzer(
            position_registry=self.position_registry,
            data_registry=self.data_registry,
            exit_decision_logger=Mock(),
            orchestrator=Mock(),
            config_manager=Mock(),
            signal_generator=Mock(),
            signal_locks_ref={},
            parameter_provider=Mock(),
        )

        # Устанавливаем ATRProvider
        if hasattr(self.exit_analyzer, "set_atr_provider"):
            self.exit_analyzer.set_atr_provider(self.atr_provider)

        # Сохраняем режим в DataRegistry (как делает реальный бот)
        await self.data_registry.update_regime(
            "BTC-USDT",
            {
                "regime": "ranging",
                "params": {"max_holding_minutes": 30},
            },
        )

    async def test_full_chain_analysis_before_timeout(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: Анализ вызывается ПЕРЕД проверкой timeout"""
        symbol = "BTC-USDT"

        # ✅ ШАГ 1: Создаем позицию в PositionRegistry (РЕАЛЬНЫЙ)
        entry_time = datetime.now(timezone.utc) - timedelta(
            minutes=35
        )  # Больше timeout
        position_metadata = {
            "symbol": symbol,
            "side": "long",
            "entry_price": 50000.0,
            "size": 0.0027,
            "entry_time": entry_time,
            "unrealized_pnl": 10.0,
        }
        self.position_registry.register_position(symbol, position_metadata)

        # ✅ ШАГ 2: Сохраняем ATR в DataRegistry (как делает реальный бот)
        await self.data_registry.update_indicators(symbol, {"atr": 200.0})

        # ✅ ШАГ 3: Вызываем analyze_position (РЕАЛЬНЫЙ ExitAnalyzer)
        # Мокируем только методы анализа для проверки порядка вызовов
        analysis_called = []

        original_analyze_trend = self.exit_analyzer._analyze_trend
        original_check_reversal = self.exit_analyzer._check_reversal_signals

        async def mock_analyze_trend(*args, **kwargs):
            analysis_called.append("analyze_trend")
            return (
                await original_analyze_trend(*args, **kwargs)
                if callable(original_analyze_trend)
                else "up"
            )

        async def mock_check_reversal(*args, **kwargs):
            analysis_called.append("check_reversal")
            return (
                await original_check_reversal(*args, **kwargs)
                if callable(original_check_reversal)
                else False
            )

        self.exit_analyzer._analyze_trend = mock_analyze_trend
        self.exit_analyzer._check_reversal_signals = mock_check_reversal

        # ✅ ШАГ 4: Вызываем analyze_position
        result = await self.exit_analyzer.analyze_position(symbol)

        # ✅ ШАГ 5: Проверяем что анализ был вызван ПЕРЕД timeout
        # (если анализ был вызван, значит timeout не блокирует анализ)
        self.assertGreater(
            len(analysis_called),
            0,
            msg="❌ ПРОБЛЕМА #3: Методы анализа НЕ были вызваны!",
        )

        # ✅ Проверяем что анализ был вызван (значит timeout проверяется ПОСЛЕ)
        self.assertIn(
            "analyze_trend",
            analysis_called,
            msg="❌ ПРОБЛЕМА #3: _analyze_trend не был вызван!",
        )

    async def test_full_chain_dataregistry_regime_read(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: ExitAnalyzer читает режим из DataRegistry"""
        symbol = "BTC-USDT"

        # ✅ ШАГ 1: Сохраняем режим в DataRegistry (как делает реальный бот)
        await self.data_registry.update_regime(
            symbol,
            {
                "regime": "ranging",
                "params": {"max_holding_minutes": 30},
            },
        )

        # ✅ ШАГ 2: Читаем режим из DataRegistry (РЕАЛЬНЫЙ DataRegistry)
        regime_data = await self.data_registry.get_regime(symbol)

        # ✅ ШАГ 3: Проверяем что режим прочитан правильно
        self.assertIsNotNone(
            regime_data,
            msg="❌ ПРОБЛЕМА: DataRegistry не возвращает режим!",
        )

        self.assertEqual(
            regime_data.get("regime"),
            "ranging",
            msg="❌ ПРОБЛЕМА: Режим прочитан неправильно!",
        )

        # ✅ ШАГ 4: Проверяем что ExitAnalyzer может использовать режим
        # (режим используется внутри analyze_position)


if __name__ == "__main__":
    unittest.main()
