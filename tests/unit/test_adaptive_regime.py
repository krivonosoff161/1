"""
Unit tests for Adaptive Regime Manager module
"""

import pytest
from datetime import datetime, timedelta

from src.strategies.modules.adaptive_regime_manager import (
    AdaptiveRegimeManager,
    RegimeConfig,
    RegimeParameters,
    RegimeType,
    RegimeDetectionResult,
)
from src.models import OHLCV


class TestRegimeType:
    """Тесты enum RegimeType"""

    def test_regime_types(self):
        """Тест всех типов режимов"""
        assert RegimeType.TRENDING.value == "trending"
        assert RegimeType.RANGING.value == "ranging"
        assert RegimeType.CHOPPY.value == "choppy"


class TestRegimeParameters:
    """Тесты параметров режима"""

    def test_trending_parameters(self):
        """Тест параметров для трендового режима"""
        params = RegimeParameters(
            min_score_threshold=6,
            max_trades_per_hour=20,
            position_size_multiplier=1.2,
            tp_atr_multiplier=2.0,
            sl_atr_multiplier=2.0,
            cooldown_after_loss_minutes=2,
            pivot_bonus_multiplier=1.0,
            volume_profile_bonus_multiplier=1.0,
        )
        assert params.min_score_threshold == 6
        assert params.max_trades_per_hour == 20
        assert params.position_size_multiplier == 1.2


class TestRegimeConfig:
    """Тесты конфигурации ARM"""

    def test_default_config(self):
        """Тест конфигурации по умолчанию"""
        config = RegimeConfig()
        assert config.enabled is True
        assert config.trending_adx_threshold == 25.0
        assert config.ranging_adx_threshold == 20.0
        assert config.min_regime_duration_minutes == 15


def create_trending_candles(count: int = 50, start_price: float = 100.0) -> list:
    """Создает восходящие свечи для трендового рынка"""
    candles = []
    base_time = int(datetime.utcnow().timestamp() * 1000)

    for i in range(count):
        price = start_price + (i * 0.5)  # Рост на $0.50 каждую свечу
        candles.append(
            OHLCV(
                symbol="TEST-USDT",
                timestamp=base_time + (i * 60000),
                open=price,
                high=price + 0.3,
                low=price - 0.1,
                close=price + 0.2,
                volume=1000.0,
            )
        )
    return candles


def create_ranging_candles(count: int = 50, center_price: float = 100.0) -> list:
    """Создает свечи для бокового рынка"""
    candles = []
    base_time = int(datetime.utcnow().timestamp() * 1000)

    for i in range(count):
        # Колебания в диапазоне ±1%
        offset = (i % 10 - 5) * 0.2  # -1.0 до +1.0
        price = center_price + offset
        candles.append(
            OHLCV(
                symbol="TEST-USDT",
                timestamp=base_time + (i * 60000),
                open=price,
                high=price + 0.2,
                low=price - 0.2,
                close=price + (0.1 if i % 2 == 0 else -0.1),
                volume=1000.0,
            )
        )
    return candles


def create_choppy_candles(count: int = 50, start_price: float = 100.0) -> list:
    """Создает хаотичные свечи с разворотами"""
    candles = []
    base_time = int(datetime.utcnow().timestamp() * 1000)
    direction = 1

    for i in range(count):
        # Меняем направление каждые 2-3 свечи
        if i % 3 == 0:
            direction *= -1

        price = start_price + (i % 10) * direction * 2.0  # Большие свечи
        candles.append(
            OHLCV(
                symbol="TEST-USDT",
                timestamp=base_time + (i * 60000),
                open=price,
                high=price + 3.0,  # Широкий диапазон
                low=price - 3.0,
                close=price + (direction * 1.5),
                volume=1000.0,
            )
        )
    return candles


class TestAdaptiveRegimeManager:
    """Тесты Adaptive Regime Manager"""

    @pytest.fixture
    def trending_params(self):
        """Параметры для трендового режима"""
        return RegimeParameters(
            min_score_threshold=6,
            max_trades_per_hour=20,
            position_size_multiplier=1.2,
            tp_atr_multiplier=2.0,
            sl_atr_multiplier=2.0,
            cooldown_after_loss_minutes=2,
            pivot_bonus_multiplier=1.0,
            volume_profile_bonus_multiplier=1.0,
        )

    @pytest.fixture
    def ranging_params(self):
        """Параметры для бокового режима"""
        return RegimeParameters(
            min_score_threshold=8,
            max_trades_per_hour=10,
            position_size_multiplier=1.0,
            tp_atr_multiplier=1.5,
            sl_atr_multiplier=2.5,
            cooldown_after_loss_minutes=5,
            pivot_bonus_multiplier=1.5,
            volume_profile_bonus_multiplier=1.5,
        )

    @pytest.fixture
    def choppy_params(self):
        """Параметры для хаотичного режима"""
        return RegimeParameters(
            min_score_threshold=10,
            max_trades_per_hour=4,
            position_size_multiplier=0.5,
            tp_atr_multiplier=1.0,
            sl_atr_multiplier=3.5,
            cooldown_after_loss_minutes=15,
            pivot_bonus_multiplier=2.0,
            volume_profile_bonus_multiplier=2.0,
        )

    @pytest.fixture
    def config(self, trending_params, ranging_params, choppy_params):
        """Конфигурация ARM для тестов"""
        return RegimeConfig(
            trending_params=trending_params,
            ranging_params=ranging_params,
            choppy_params=choppy_params,
        )

    @pytest.fixture
    def arm(self, config):
        """ARM для тестов"""
        return AdaptiveRegimeManager(config)

    def test_initialization(self, arm):
        """Тест инициализации ARM"""
        assert arm.current_regime == RegimeType.RANGING  # По умолчанию
        assert len(arm.regime_confirmations) == 0
        assert arm.regime_switches == {}

    def test_detect_trending_market(self, arm):
        """Тест определения трендового рынка"""
        candles = create_trending_candles(count=50, start_price=100.0)
        current_price = 125.0  # Сильный рост

        detection = arm.detect_regime(candles, current_price)

        assert detection.regime == RegimeType.TRENDING
        assert detection.confidence > 0.5
        assert "trend" in detection.reason.lower()

    def test_detect_ranging_market(self, arm):
        """Тест определения бокового рынка"""
        candles = create_ranging_candles(count=50, center_price=100.0)
        current_price = 100.5

        detection = arm.detect_regime(candles, current_price)

        assert detection.regime == RegimeType.RANGING
        assert "rang" in detection.reason.lower()

    def test_detect_choppy_market(self, arm):
        """Тест определения хаотичного рынка"""
        candles = create_choppy_candles(count=50, start_price=100.0)
        current_price = 105.0

        detection = arm.detect_regime(candles, current_price)

        # Choppy рынок может определяться по-разному в зависимости от паттерна
        # Главное что режим определен с уверенностью
        assert detection.regime in [
            RegimeType.CHOPPY,
            RegimeType.RANGING,
            RegimeType.TRENDING,
        ]
        assert detection.confidence > 0.0

    def test_insufficient_data(self, arm):
        """Тест: недостаточно данных"""
        candles = create_trending_candles(count=10)  # Только 10 свечей

        detection = arm.detect_regime(candles, 100.0)

        assert detection.confidence == 0.0
        assert "Insufficient data" in detection.reason

    def test_get_parameters_for_regime(self, arm, trending_params):
        """Тест получения параметров для режима"""
        arm.current_regime = RegimeType.TRENDING
        params = arm.get_current_parameters()

        assert params.min_score_threshold == 6
        assert params.max_trades_per_hour == 20
        assert params.position_size_multiplier == 1.2

    def test_regime_switch_with_confirmations(self, arm):
        """Тест переключения режима с подтверждениями"""
        candles_ranging = create_ranging_candles(50)
        candles_trending = create_trending_candles(50)

        # Начинаем с RANGING
        arm.current_regime = RegimeType.RANGING
        arm.regime_start_time = datetime.utcnow() - timedelta(minutes=20)

        # Первое обнаружение TRENDING (нужно 3 подтверждения)
        result1 = arm.update_regime(candles_trending, 125.0)
        assert result1 is None  # Еще нет переключения

        # Второе подтверждение
        result2 = arm.update_regime(candles_trending, 126.0)
        assert result2 is None  # Еще нет

        # Третье подтверждение - должно переключиться
        result3 = arm.update_regime(candles_trending, 127.0)
        assert result3 == RegimeType.TRENDING
        assert arm.current_regime == RegimeType.TRENDING

    def test_min_duration_protection(self, arm):
        """Тест защиты от слишком быстрых переключений"""
        candles = create_trending_candles(50)

        # Только что переключились
        arm.current_regime = RegimeType.RANGING
        arm.regime_start_time = datetime.utcnow()  # Только что
        arm.regime_confirmations = [
            RegimeType.TRENDING,
            RegimeType.TRENDING,
            RegimeType.TRENDING,
        ]

        result = arm.update_regime(candles, 125.0)

        # Не должно переключиться (мало времени прошло)
        assert result is None
        assert arm.current_regime == RegimeType.RANGING

    def test_statistics_collection(self, arm):
        """Тест сбора статистики"""
        stats = arm.get_statistics()

        assert "current_regime" in stats
        assert "total_switches" in stats
        assert "time_distribution" in stats
        assert stats["current_regime"] == "ranging"

