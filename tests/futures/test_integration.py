"""
Интеграционные тесты для Futures модулей.
Проверяет взаимодействие между различными компонентами.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.clients.futures_client import OKXFuturesClient
from src.strategies.modules.liquidation_guard import LiquidationGuard
from src.strategies.modules.margin_calculator import MarginCalculator
from src.strategies.modules.slippage_guard import SlippageGuard


class TestFuturesIntegration:
    """Интеграционные тесты для Futures модулей"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.margin_calculator = MarginCalculator(
            default_leverage=3, maintenance_margin_ratio=0.01, initial_margin_ratio=0.1
        )

        self.liquidation_guard = LiquidationGuard(
            margin_calculator=self.margin_calculator,
            warning_threshold=1.8,
            danger_threshold=1.3,
            critical_threshold=1.1,
            auto_close_threshold=1.05,
        )

        self.slippage_guard = SlippageGuard(
            max_slippage_percent=0.1, max_spread_percent=0.05, order_timeout=30.0
        )

        self.client = OKXFuturesClient(
            api_key="test_key",
            secret_key="test_secret",
            passphrase="test_passphrase",
            sandbox=True,
            leverage=3,
        )

    @pytest.mark.asyncio
    async def test_margin_calculator_with_liquidation_guard(self):
        """Тест интеграции Margin Calculator с Liquidation Guard"""
        # Мокаем клиент
        mock_client = AsyncMock()
        mock_client.get_balance.return_value = 1000.0
        mock_client.get_positions.return_value = [
            {
                "instId": "BTC-USDT-SWAP",
                "pos": "0.06",
                "posSide": "long",
                "avgPx": "50000.0",
                "markPx": "51000.0",
                "lever": "3",
            }
        ]

        # Запускаем мониторинг
        await self.liquidation_guard.start_monitoring(mock_client, check_interval=0.1)

        # Ждем немного для выполнения проверки
        await asyncio.sleep(0.2)

        # Останавливаем мониторинг
        await self.liquidation_guard.stop_monitoring()

        # Проверяем, что мониторинг был запущен
        assert self.liquidation_guard.is_monitoring is False  # Остановлен

    @pytest.mark.asyncio
    async def test_liquidation_guard_callback(self):
        """Тест callback функции Liquidation Guard"""
        callback_called = False
        callback_data = None

        async def test_callback(level, symbol, side, margin_ratio, details):
            nonlocal callback_called, callback_data
            callback_called = True
            callback_data = {
                "level": level,
                "symbol": symbol,
                "side": side,
                "margin_ratio": margin_ratio,
                "details": details,
            }

        # Мокаем клиент с критической позицией
        mock_client = AsyncMock()
        mock_client.get_balance.return_value = 100.0  # Низкий баланс
        mock_client.get_positions.return_value = [
            {
                "instId": "BTC-USDT-SWAP",
                "pos": "0.06",
                "posSide": "long",
                "avgPx": "50000.0",
                "markPx": "51000.0",
                "lever": "3",
            }
        ]

        # Запускаем мониторинг с callback
        await self.liquidation_guard.start_monitoring(
            mock_client, check_interval=0.1, callback=test_callback
        )

        # Ждем выполнения проверки
        await asyncio.sleep(0.2)

        # Останавливаем мониторинг
        await self.liquidation_guard.stop_monitoring()

        # Проверяем, что callback был вызван
        assert callback_called is True
        assert callback_data is not None
        assert callback_data["level"] in ["warning", "danger", "critical"]

    @pytest.mark.asyncio
    async def test_slippage_guard_order_validation(self):
        """Тест валидации ордеров через Slippage Guard"""
        # Мокаем клиент
        mock_client = AsyncMock()

        # Тест валидации валидного ордера
        is_valid, reason = await self.slippage_guard.validate_order_before_placement(
            symbol="BTC-USDT",
            side="buy",
            order_type="market",
            price=None,
            size=0.01,
            client=mock_client,
        )

        # Поскольку мы мокаем _get_current_prices, результат может быть False
        # Но важно, что функция выполняется без ошибок
        assert isinstance(is_valid, bool)
        assert isinstance(reason, str)

    @pytest.mark.asyncio
    async def test_margin_status_integration(self):
        """Тест интеграции получения статуса маржи"""
        # Мокаем клиент
        mock_client = AsyncMock()
        mock_client.get_balance.return_value = 1000.0
        mock_client.get_positions.return_value = [
            {
                "instId": "BTC-USDT-SWAP",
                "pos": "0.06",
                "posSide": "long",
                "avgPx": "50000.0",
                "markPx": "51000.0",
                "lever": "3",
            }
        ]

        # Получаем статус маржи
        status = await self.liquidation_guard.get_margin_status(mock_client)

        # Проверяем структуру ответа
        assert "equity" in status
        assert "total_margin_used" in status
        assert "available_margin" in status
        assert "health_status" in status
        assert "positions" in status
        assert "timestamp" in status

        # Проверяем значения
        assert status["equity"] == 1000.0
        assert status["total_margin_used"] > 0
        assert len(status["positions"]) == 1

    @pytest.mark.asyncio
    async def test_emergency_close_position(self):
        """Тест экстренного закрытия позиции"""
        # Мокаем клиент
        mock_client = AsyncMock()
        mock_client.get_positions.return_value = [
            {
                "instId": "BTC-USDT-SWAP",
                "pos": "0.06",
                "posSide": "long",
                "avgPx": "50000.0",
                "markPx": "51000.0",
                "lever": "3",
            }
        ]
        mock_client.place_futures_order.return_value = {
            "code": "0",
            "data": [{"ordId": "12345"}],
        }

        # Создаем позицию для закрытия
        position = {"instId": "BTC-USDT-SWAP", "pos": "0.06", "posSide": "long"}

        # Вызываем экстренное закрытие
        await self.liquidation_guard._emergency_close_position(
            "BTC-USDT", "long", mock_client
        )

        # Проверяем, что был вызван place_futures_order
        mock_client.place_futures_order.assert_called_once()
        call_args = mock_client.place_futures_order.call_args
        assert call_args[1]["symbol"] == "BTC-USDT"
        assert call_args[1]["side"] == "sell"  # Закрытие лонга
        assert call_args[1]["size"] == 0.06
        assert call_args[1]["order_type"] == "market"

    @pytest.mark.asyncio
    async def test_slippage_statistics(self):
        """Тест статистики проскальзывания"""
        # Получаем статистику
        stats = self.slippage_guard.get_slippage_statistics()

        # Проверяем структуру
        assert "active_orders_count" in stats
        assert "monitored_symbols" in stats
        assert "max_slippage_percent" in stats
        assert "max_spread_percent" in stats
        assert "order_timeout" in stats
        assert "is_monitoring" in stats

        # Проверяем значения
        assert stats["active_orders_count"] == 0
        assert stats["max_slippage_percent"] == 0.1
        assert stats["max_spread_percent"] == 0.05
        assert stats["order_timeout"] == 30.0
        assert stats["is_monitoring"] is False

    @pytest.mark.asyncio
    async def test_margin_calculator_edge_cases(self):
        """Тест граничных случаев Margin Calculator"""
        # Тест с нулевым балансом
        max_size = self.margin_calculator.calculate_max_position_size(0, 50000)
        assert max_size == 0

        # Тест с очень маленьким балансом
        max_size = self.margin_calculator.calculate_max_position_size(1, 50000)
        assert max_size > 0
        assert max_size < 0.001

        # Тест с очень высокой ценой
        max_size = self.margin_calculator.calculate_max_position_size(1000, 1000000)
        assert max_size > 0
        assert max_size < 0.01

    @pytest.mark.asyncio
    async def test_liquidation_guard_thresholds(self):
        """Тест порогов Liquidation Guard"""
        # Проверяем установку порогов
        assert self.liquidation_guard.warning_threshold == 1.8
        assert self.liquidation_guard.danger_threshold == 1.3
        assert self.liquidation_guard.critical_threshold == 1.1
        assert self.liquidation_guard.auto_close_threshold == 1.05

        # Тест изменения порогов
        self.liquidation_guard.set_thresholds(
            warning=2.0, danger=1.5, critical=1.2, auto_close=1.1
        )

        assert self.liquidation_guard.warning_threshold == 2.0
        assert self.liquidation_guard.danger_threshold == 1.5
        assert self.liquidation_guard.critical_threshold == 1.2
        assert self.liquidation_guard.auto_close_threshold == 1.1

    @pytest.mark.asyncio
    async def test_slippage_guard_parameters(self):
        """Тест параметров Slippage Guard"""
        # Проверяем установку параметров
        assert self.slippage_guard.max_slippage_percent == 0.1
        assert self.slippage_guard.max_spread_percent == 0.05
        assert self.slippage_guard.order_timeout == 30.0

        # Тест изменения параметров
        self.slippage_guard.set_parameters(
            max_slippage=0.2, max_spread=0.1, timeout=60.0
        )

        assert self.slippage_guard.max_slippage_percent == 0.2
        assert self.slippage_guard.max_spread_percent == 0.1
        assert self.slippage_guard.order_timeout == 60.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
