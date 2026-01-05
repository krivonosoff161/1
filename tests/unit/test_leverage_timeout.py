"""
Unit тесты для Leverage Timeout (критическая проблема #9)
Проверяет обработку timeout ошибок (50004) при установке leverage
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.clients.futures_client import OKXFuturesClient


class TestLeverageTimeout:
    """Тесты для обработки timeout при установке leverage"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.client = OKXFuturesClient(
            api_key="test_key",
            secret_key="test_secret",
            passphrase="test_pass",
            sandbox=True,
        )

    @pytest.mark.asyncio
    async def test_set_leverage_handles_timeout_50004(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: set_leverage должен обрабатывать timeout (50004) с retry"""
        # Мокируем _make_request чтобы вернуть ошибку 50004
        with patch.object(
            self.client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            # Первые 2 попытки возвращают timeout, третья успешна
            mock_request.side_effect = [
                RuntimeError(
                    "OKX API error: status 400, data: {'code': '50004', 'msg': 'API endpoint request timeout. '}"
                ),
                RuntimeError(
                    "OKX API error: status 400, data: {'code': '50004', 'msg': 'API endpoint request timeout. '}"
                ),
                {"code": "0", "data": [{"lever": "5"}]},  # Успешный ответ
            ]

            # Вызываем set_leverage
            result = await self.client.set_leverage("BTC-USDT", 5, pos_side="long")

            # Проверяем что было 3 попытки (2 timeout + 1 успешная)
            assert (
                mock_request.call_count == 3
            ), f"Должно быть 3 попытки (получено: {mock_request.call_count})"
            assert result["code"] == "0", "Последняя попытка должна быть успешной"

    @pytest.mark.asyncio
    async def test_set_leverage_handles_rate_limit_429(self):
        """Тест обработки rate limit (429)"""
        with patch.object(
            self.client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            # Первая попытка возвращает 429, вторая успешна
            mock_request.side_effect = [
                RuntimeError("429 Too Many Requests"),
                {"code": "0", "data": [{"lever": "5"}]},
            ]

            result = await self.client.set_leverage("BTC-USDT", 5)

            assert mock_request.call_count == 2, "Должно быть 2 попытки"
            assert result["code"] == "0", "Вторая попытка должна быть успешной"

    @pytest.mark.asyncio
    async def test_set_leverage_max_retries_exceeded(self):
        """Тест превышения максимального количества попыток"""
        with patch.object(
            self.client, "_make_request", new_callable=AsyncMock
        ) as mock_request:
            # Все попытки возвращают timeout
            mock_request.side_effect = RuntimeError(
                "OKX API error: status 400, data: {'code': '50004', 'msg': 'API endpoint request timeout. '}"
            )

            # Ожидаем что после всех попыток будет выброшено исключение
            with pytest.raises(RuntimeError):
                await self.client.set_leverage("BTC-USDT", 5)

            # Проверяем что было максимум попыток (5)
            assert (
                mock_request.call_count == 5
            ), f"Должно быть 5 попыток (получено: {mock_request.call_count})"
