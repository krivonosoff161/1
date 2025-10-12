"""
Unit tests for Time-Based Filter module
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.filters.time_session_manager import (
    TimeFilterConfig,
    TimeSessionManager,
    TradingSession,
    SessionOverlap,
)


class TestTimeFilterConfig:
    """Тесты конфигурации временного фильтра"""

    def test_default_config(self):
        """Тест конфигурации по умолчанию"""
        config = TimeFilterConfig()
        assert config.enabled is True
        assert config.trade_asian_session is True
        assert config.trade_european_session is True
        assert config.trade_american_session is True
        assert config.prefer_overlaps is True
        assert config.avoid_low_liquidity_hours is True
        assert config.avoid_weekends is True

    def test_custom_config(self):
        """Тест кастомной конфигурации"""
        config = TimeFilterConfig(
            enabled=False,
            trade_asian_session=False,
            prefer_overlaps=False,
        )
        assert config.enabled is False
        assert config.trade_asian_session is False
        assert config.prefer_overlaps is False


class TestTimeSessionManager:
    """Тесты менеджера торговых сессий"""

    @pytest.fixture
    def default_manager(self):
        """Менеджер с настройками по умолчанию"""
        config = TimeFilterConfig(
            prefer_overlaps=False,  # Торгуем весь день
            avoid_low_liquidity_hours=False,
            avoid_weekends=False,
        )
        return TimeSessionManager(config)

    @pytest.fixture
    def strict_manager(self):
        """Строгий менеджер (только пересечения)"""
        config = TimeFilterConfig(
            prefer_overlaps=True,  # Только пересечения
            avoid_low_liquidity_hours=True,
            avoid_weekends=True,
        )
        return TimeSessionManager(config)

    def test_asian_session_active(self, default_manager):
        """Тест: Азиатская сессия активна"""
        # 05:00 UTC = середина азиатской сессии
        test_time = datetime(2025, 10, 13, 5, 0, 0)  # Monday
        
        active_sessions = default_manager.get_active_sessions(test_time)
        
        assert len(active_sessions) == 1
        assert active_sessions[0].name == "Asian"
        assert default_manager.is_trading_allowed(test_time) is True

    def test_european_session_active(self, default_manager):
        """Тест: Европейская сессия активна"""
        # 12:00 UTC = середина европейской сессии
        test_time = datetime(2025, 10, 13, 12, 0, 0)  # Monday
        
        active_sessions = default_manager.get_active_sessions(test_time)
        
        assert len(active_sessions) == 1
        assert active_sessions[0].name == "European"
        assert default_manager.is_trading_allowed(test_time) is True

    def test_american_session_active(self, default_manager):
        """Тест: Американская сессия активна"""
        # 18:00 UTC = середина американской сессии
        test_time = datetime(2025, 10, 13, 18, 0, 0)  # Monday
        
        active_sessions = default_manager.get_active_sessions(test_time)
        
        assert len(active_sessions) == 1
        assert active_sessions[0].name == "American"
        assert default_manager.is_trading_allowed(test_time) is True

    def test_asian_european_overlap(self, default_manager):
        """Тест: Пересечение Азиатской и Европейской сессий"""
        # 08:00 UTC = Asian-European overlap
        test_time = datetime(2025, 10, 13, 8, 0, 0)  # Monday
        
        active_sessions = default_manager.get_active_sessions(test_time)
        overlap = default_manager.get_current_overlap(test_time)
        
        assert len(active_sessions) == 2  # Обе сессии активны
        assert overlap is not None
        assert overlap.name == "Asian-European"
        assert overlap.liquidity_multiplier == 1.3

    def test_european_american_overlap(self, default_manager):
        """Тест: Пересечение Европейской и Американской сессий"""
        # 14:00 UTC = European-American overlap (максимальная ликвидность)
        test_time = datetime(2025, 10, 13, 14, 0, 0)  # Monday
        
        active_sessions = default_manager.get_active_sessions(test_time)
        overlap = default_manager.get_current_overlap(test_time)
        
        assert len(active_sessions) == 2  # Обе сессии активны
        assert overlap is not None
        assert overlap.name == "European-American"
        assert overlap.liquidity_multiplier == 1.5  # Максимальная

    def test_prefer_overlaps_blocks_outside(self, strict_manager):
        """Тест: prefer_overlaps блокирует торговлю вне пересечений"""
        # 12:00 UTC = European session, но НЕ пересечение
        test_time = datetime(2025, 10, 13, 12, 0, 0)  # Monday
        
        overlap = strict_manager.get_current_overlap(test_time)
        trading_allowed = strict_manager.is_trading_allowed(test_time)
        
        assert overlap is None  # Нет пересечения
        assert trading_allowed is False  # Блокируем

    def test_prefer_overlaps_allows_overlap(self, strict_manager):
        """Тест: prefer_overlaps разрешает торговлю в пересечениях"""
        # 14:00 UTC = European-American overlap
        test_time = datetime(2025, 10, 13, 14, 0, 0)  # Monday
        
        overlap = strict_manager.get_current_overlap(test_time)
        trading_allowed = strict_manager.is_trading_allowed(test_time)
        
        assert overlap is not None
        assert trading_allowed is True

    def test_avoid_weekends_saturday_night(self, strict_manager):
        """Тест: Блокировка субботней ночи"""
        # Saturday 23:00 UTC
        test_time = datetime(2025, 10, 18, 23, 0, 0)  # Saturday
        
        trading_allowed = strict_manager.is_trading_allowed(test_time)
        
        assert trading_allowed is False

    def test_avoid_weekends_sunday(self, strict_manager):
        """Тест: Блокировка воскресенья"""
        # Sunday 12:00 UTC
        test_time = datetime(2025, 10, 19, 12, 0, 0)  # Sunday
        
        trading_allowed = strict_manager.is_trading_allowed(test_time)
        
        assert trading_allowed is False

    def test_low_liquidity_hours_blocked(self, strict_manager):
        """Тест: Блокировка часов низкой ликвидности"""
        # 02:00 UTC = низкая ликвидность
        test_time = datetime(2025, 10, 13, 2, 0, 0)  # Monday
        
        trading_allowed = strict_manager.is_trading_allowed(test_time)
        
        assert trading_allowed is False

    def test_liquidity_multiplier_in_overlap(self, default_manager):
        """Тест: Множитель ликвидности в пересечении"""
        # 14:00 UTC = European-American overlap
        test_time = datetime(2025, 10, 13, 14, 0, 0)
        
        multiplier = default_manager.get_liquidity_multiplier(test_time)
        
        assert multiplier == 1.5  # Максимальный множитель

    def test_liquidity_multiplier_in_session(self, default_manager):
        """Тест: Множитель ликвидности в обычной сессии"""
        # 12:00 UTC = European session (не пересечение)
        test_time = datetime(2025, 10, 13, 12, 0, 0)
        
        multiplier = default_manager.get_liquidity_multiplier(test_time)
        
        assert multiplier == 1.2  # European session multiplier

    def test_liquidity_multiplier_outside_sessions(self, default_manager):
        """Тест: Множитель ликвидности вне сессий"""
        # Создаем менеджер где все сессии выключены
        config = TimeFilterConfig(
            trade_asian_session=False,
            trade_european_session=False,
            trade_american_session=False,
        )
        manager = TimeSessionManager(config)
        
        test_time = datetime(2025, 10, 13, 12, 0, 0)
        multiplier = manager.get_liquidity_multiplier(test_time)
        
        assert multiplier == 0.5  # Минимальный

    def test_session_info(self, default_manager):
        """Тест: Получение полной информации о сессии"""
        # 14:00 UTC = European-American overlap
        test_time = datetime(2025, 10, 13, 14, 0, 0)  # Monday
        
        info = default_manager.get_session_info(test_time)
        
        assert info["trading_allowed"] is True
        assert "European" in info["active_sessions"]
        assert "American" in info["active_sessions"]
        assert info["current_overlap"] == "European-American"
        assert info["liquidity_multiplier"] == 1.5
        assert info["weekday"] == "Monday"

    def test_disabled_filter_always_allows(self):
        """Тест: Выключенный фильтр всегда разрешает"""
        config = TimeFilterConfig(enabled=False)
        manager = TimeSessionManager(config)
        
        # Любое время - разрешено
        test_time = datetime(2025, 10, 19, 3, 0, 0)  # Sunday 3 AM
        
        trading_allowed = manager.is_trading_allowed(test_time)
        
        assert trading_allowed is True

    def test_specific_session_disabled(self):
        """Тест: Выключение конкретной сессии"""
        config = TimeFilterConfig(
            trade_european_session=False,  # Европейская выключена
            prefer_overlaps=False,
        )
        manager = TimeSessionManager(config)
        
        # 12:00 UTC = European session time
        test_time = datetime(2025, 10, 13, 12, 0, 0)
        
        active_sessions = manager.get_active_sessions(test_time)
        
        assert len(active_sessions) == 0  # Нет активных
        assert manager.is_trading_allowed(test_time) is False

    def test_next_trading_time_in_session(self, default_manager):
        """Тест: Следующее время торговли (когда уже в сессии)"""
        # 12:00 UTC = European session
        test_time = datetime(2025, 10, 13, 12, 0, 0)
        
        next_time = default_manager.get_next_trading_time(test_time)
        
        assert "Trading is allowed now" in next_time

    def test_next_trading_time_outside_session(self, strict_manager):
        """Тест: Следующее время торговли (вне сессии)"""
        # 12:00 UTC = вне пересечений (при prefer_overlaps=True)
        test_time = datetime(2025, 10, 13, 12, 0, 0)
        
        next_time = strict_manager.get_next_trading_time(test_time)
        
        assert next_time is not None
        assert "Next trading" in next_time or "overlap" in next_time

    def test_is_hour_in_range_normal(self, default_manager):
        """Тест: Час в нормальном диапазоне"""
        # 10:00 в диапазоне 9:00-15:00
        result = default_manager._is_hour_in_range(10, 9, 15)
        assert result is True
        
        # 8:00 вне диапазона 9:00-15:00
        result = default_manager._is_hour_in_range(8, 9, 15)
        assert result is False

    def test_is_hour_in_range_midnight_crossing(self, default_manager):
        """Тест: Диапазон через полночь"""
        # 23:00 в диапазоне 22:00-02:00
        result = default_manager._is_hour_in_range(23, 22, 2)
        assert result is True
        
        # 01:00 в диапазоне 22:00-02:00
        result = default_manager._is_hour_in_range(1, 22, 2)
        assert result is True
        
        # 03:00 вне диапазона 22:00-02:00
        result = default_manager._is_hour_in_range(3, 22, 2)
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

