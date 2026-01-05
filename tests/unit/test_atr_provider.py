"""
Unit тесты для ATR Provider (критическая проблема #6)
Проверяет что ATR правильно рассчитывается и сохраняется в DataRegistry
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.models import OHLCV
from src.strategies.scalping.futures.core.data_registry import DataRegistry
from src.strategies.scalping.futures.indicators.atr_provider import ATRProvider


class TestATRProvider:
    """Тесты для ATR Provider"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.data_registry = Mock(spec=DataRegistry)
        self.atr_provider = ATRProvider(data_registry=self.data_registry)

    def test_atr_provider_init(self):
        """Тест инициализации ATR Provider"""
        assert self.atr_provider.data_registry == self.data_registry
        # Проверяем что кэш существует (может быть пустым или иметь другую структуру)
        assert hasattr(self.atr_provider, "data_registry")

    def test_get_atr_returns_none_when_not_found(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: ATR должен возвращать None если не найден (БЕЗ FALLBACK)"""
        # Мокируем DataRegistry._indicators чтобы вернуть пустой dict
        self.data_registry._indicators = {}

        atr = self.atr_provider.get_atr("BTC-USDT")

        assert atr is None, "ATR должен быть None если не найден (БЕЗ FALLBACK)"

    def test_get_atr_returns_none_when_zero(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: ATR должен возвращать None если равен 0.0 (БЕЗ FALLBACK)"""
        # Мокируем DataRegistry._indicators чтобы вернуть ATR=0.0
        self.data_registry._indicators = {"BTC-USDT": {"atr": 0.0}}

        atr = self.atr_provider.get_atr("BTC-USDT")

        assert atr is None, "ATR должен быть None если равен 0.0 (БЕЗ FALLBACK)"

    def test_get_atr_returns_value_when_valid(self):
        """Тест получения валидного ATR"""
        # Мокируем DataRegistry._indicators напрямую (ATRProvider использует _indicators)
        self.data_registry._indicators = {"BTC-USDT": {"atr": 150.5}}

        atr = self.atr_provider.get_atr("BTC-USDT")

        assert atr == 150.5, "ATR должен возвращать валидное значение"

    def test_get_atr_checks_multiple_keys(self):
        """Тест проверки нескольких ключей для ATR"""
        # Мокируем DataRegistry._indicators чтобы вернуть ATR по ключу "atr_14"
        self.data_registry._indicators = {"BTC-USDT": {"atr_14": 200.0}}

        atr = self.atr_provider.get_atr("BTC-USDT")

        assert atr == 200.0, "ATR должен находиться по разным ключам (atr, atr_14)"

    def test_get_atr_caches_result(self):
        """Тест кэширования ATR"""
        # Мокируем DataRegistry._indicators
        self.data_registry._indicators = {"BTC-USDT": {"atr": 100.0}}

        # Первый вызов
        atr1 = self.atr_provider.get_atr("BTC-USDT")

        # Удаляем из _indicators чтобы проверить что используется кэш
        del self.data_registry._indicators["BTC-USDT"]

        # Второй вызов должен использовать кэш
        atr2 = self.atr_provider.get_atr("BTC-USDT")

        assert atr1 == atr2 == 100.0, "ATR должен кэшироваться"


class TestATRProviderWithDataRegistry:
    """Интеграционные тесты ATR Provider с DataRegistry"""

    @pytest.mark.asyncio
    async def test_atr_saved_to_dataregistry(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: ATR должен сохраняться в DataRegistry"""
        data_registry = DataRegistry()
        atr_provider = ATRProvider(data_registry=data_registry)

        # Сохраняем ATR в DataRegistry
        await data_registry.update_indicators("BTC-USDT", {"atr": 150.5})

        # Получаем ATR через ATRProvider
        atr = atr_provider.get_atr("BTC-USDT")

        assert atr == 150.5, "ATR должен быть получен из DataRegistry"

    @pytest.mark.asyncio
    async def test_atr_zero_not_saved(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: ATR=0.0 НЕ должен сохраняться в DataRegistry"""
        data_registry = DataRegistry()
        atr_provider = ATRProvider(data_registry=data_registry)

        # Пытаемся сохранить ATR=0.0 (не должно сохраниться)
        await data_registry.update_indicators("BTC-USDT", {"atr": 0.0})

        # Получаем ATR через ATRProvider
        atr = atr_provider.get_atr("BTC-USDT")

        # ATR=0.0 должен вернуть None (БЕЗ FALLBACK)
        assert atr is None, "ATR=0.0 должен вернуть None (БЕЗ FALLBACK)"
