"""
Unit тесты для Adaptive Balance Manager
"""

import pytest
from unittest.mock import Mock
from datetime import datetime, timedelta
from src.balance.adaptive_balance_manager import (
    AdaptiveBalanceManager,
    BalanceProfile,
    BalanceProfileConfig,
    BalanceUpdateEvent,
    create_default_profiles
)

class TestBalanceProfileConfig:
    """Тесты для BalanceProfileConfig"""
    
    def test_balance_profile_config_creation(self):
        """Тест создания конфигурации профиля баланса"""
        config = BalanceProfileConfig(
            threshold=1000.0,
            base_position_size=50.0,
            min_position_size=25.0,
            max_position_size=100.0,
            max_open_positions=2,
            max_position_percent=10.0,
            trending_boost={
                "tp_multiplier": 1.2,
                "sl_multiplier": 0.9,
                "ph_threshold": 1.1,
                "score_threshold": 0.9,
                "max_trades": 1.1
            },
            ranging_boost={
                "tp_multiplier": 1.0,
                "sl_multiplier": 1.0,
                "ph_threshold": 1.0,
                "score_threshold": 1.0,
                "max_trades": 1.0
            },
            choppy_boost={
                "tp_multiplier": 0.8,
                "sl_multiplier": 1.2,
                "ph_threshold": 0.9,
                "score_threshold": 1.1,
                "max_trades": 0.8
            }
        )
        
        assert config.threshold == 1000.0
        assert config.base_position_size == 50.0
        assert config.min_position_size == 25.0
        assert config.max_position_size == 100.0
        assert config.max_open_positions == 2
        assert config.max_position_percent == 10.0
        assert config.trending_boost["tp_multiplier"] == 1.2
        assert config.ranging_boost["tp_multiplier"] == 1.0
        assert config.choppy_boost["tp_multiplier"] == 0.8

class TestBalanceUpdateEvent:
    """Тесты для BalanceUpdateEvent"""
    
    def test_balance_update_event_creation(self):
        """Тест создания события обновления баланса"""
        event = BalanceUpdateEvent(
            event_type="position_opened",
            symbol="ETH-USDT",
            side="long",
            amount=100.0
        )
        
        assert event.event_type == "position_opened"
        assert event.symbol == "ETH-USDT"
        assert event.side == "long"
        assert event.amount == 100.0
        assert event.timestamp is not None
    
    def test_balance_update_event_auto_timestamp(self):
        """Тест автоматической установки timestamp"""
        event = BalanceUpdateEvent(event_type="manual_update")
        assert event.timestamp is not None
        assert isinstance(event.timestamp, datetime)

class TestAdaptiveBalanceManager:
    """Тесты для AdaptiveBalanceManager"""
    
    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.profiles = create_default_profiles()
        self.manager = AdaptiveBalanceManager(self.profiles)
    
    def test_initialization(self):
        """Тест инициализации менеджера"""
        assert self.manager.profiles == self.profiles
        assert self.manager.current_profile is None
        assert self.manager.current_balance == 0.0
        assert self.manager.profile_switches == []
        assert self.manager.balance_history == []
        assert self.manager.balance_events == []
    
    def test_update_balance_small_profile(self):
        """Тест обновления баланса для small профиля"""
        # Обновляем баланс для small профиля
        changed = self.manager.update_balance(500.0)
        
        assert changed is True  # Первое обновление всегда меняет профиль
        assert self.manager.current_balance == 500.0
        assert self.manager.current_profile == BalanceProfile.SMALL
        assert len(self.manager.balance_history) == 1
    
    def test_update_balance_medium_profile(self):
        """Тест обновления баланса для medium профиля"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Обновляем баланс для medium профиля (больше 2500.0)
        changed = manager.update_balance(3000.0)
        
        assert changed is True  # Первое обновление всегда меняет профиль
        assert manager.current_balance == 3000.0
        assert manager.current_profile == BalanceProfile.MEDIUM
        assert len(manager.balance_history) == 1
    
    def test_update_balance_large_profile(self):
        """Тест обновления баланса для large профиля"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Обновляем баланс для large профиля
        changed = manager.update_balance(4000.0)
        
        assert changed is True
        assert manager.current_balance == 4000.0
        assert manager.current_profile == BalanceProfile.LARGE
        assert len(manager.balance_history) == 1
    
    def test_update_balance_no_change(self):
        """Тест обновления баланса без изменения профиля"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Устанавливаем small профиль
        manager.update_balance(500.0)
        
        # Обновляем в том же диапазоне
        changed = manager.update_balance(800.0)
        
        assert changed is False
        assert manager.current_balance == 800.0
        assert manager.current_profile == BalanceProfile.SMALL
        assert len(manager.balance_history) == 2
    
    def test_profile_switch_small_to_medium(self):
        """Тест переключения с small на medium профиль"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Начинаем с small
        manager.update_balance(500.0)
        
        # Переключаемся на medium (больше 2500.0)
        changed = manager.update_balance(3000.0)
        
        assert changed is True
        assert manager.current_profile == BalanceProfile.MEDIUM
        assert len(manager.profile_switches) == 2  # Первое обновление + переключение
        
        switch = manager.profile_switches[1]  # Второе переключение
        assert switch["old_profile"] == "small"
        assert switch["new_profile"] == "medium"
        assert switch["old_balance"] == 500.0
        assert switch["new_balance"] == 3000.0
        assert switch["balance_change"] == 2500.0
    
    def test_profile_switch_medium_to_large(self):
        """Тест переключения с medium на large профиль"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Начинаем с medium
        manager.update_balance(3000.0)
        
        # Переключаемся на large
        changed = manager.update_balance(4000.0)
        
        assert changed is True
        assert manager.current_profile == BalanceProfile.LARGE
        assert len(manager.profile_switches) == 2  # Первое обновление + переключение
    
    def test_get_current_profile_config(self):
        """Тест получения конфигурации текущего профиля"""
        # Устанавливаем small профиль
        self.manager.update_balance(500.0)
        
        config = self.manager.get_current_profile_config()
        
        assert config is not None
        assert config.threshold == 1000.0
        assert config.base_position_size == 50.0
        assert config.max_open_positions == 2
    
    def test_get_current_profile_config_no_profile(self):
        """Тест получения конфигурации без установленного профиля"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        config = manager.get_current_profile_config()
        assert config is None
    
    def test_apply_to_regime_params_trending(self):
        """Тест применения параметров к trending режиму"""
        # Устанавливаем large профиль
        self.manager.update_balance(4000.0)
        
        regime_params = {
            "tp_multiplier": 2.0,
            "sl_multiplier": 1.5,
            "ph_threshold": 0.5,
            "score_threshold": 4.0,
            "max_trades_per_hour": 10
        }
        
        adapted = self.manager.apply_to_regime_params(regime_params, "trending")
        
        # Проверяем применение boost множителей
        assert adapted["tp_multiplier"] == 2.0 * 1.5  # 2.0 * 1.5 = 3.0
        assert adapted["sl_multiplier"] == 1.5 * 0.7  # 1.5 * 0.7 = 1.05
        assert adapted["ph_threshold"] == 0.5 * 1.3   # 0.5 * 1.3 = 0.65
        assert adapted["score_threshold"] == 4.0 * 0.7  # 4.0 * 0.7 = 2.8
        assert adapted["max_trades_per_hour"] == int(10 * 1.5)  # 10 * 1.5 = 15
    
    def test_apply_to_regime_params_ranging(self):
        """Тест применения параметров к ranging режиму"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Устанавливаем medium профиль
        manager.update_balance(3000.0)
        
        regime_params = {
            "tp_multiplier": 2.0,
            "sl_multiplier": 1.5,
            "ph_threshold": 0.5,
            "score_threshold": 4.0,
            "max_trades_per_hour": 10
        }
        
        adapted = manager.apply_to_regime_params(regime_params, "ranging")
        
        # Проверяем применение boost множителей для ranging
        assert adapted["tp_multiplier"] == 2.0 * 1.1  # 2.0 * 1.1 = 2.2
        assert adapted["sl_multiplier"] == 1.5 * 0.9  # 1.5 * 0.9 = 1.35
        assert adapted["ph_threshold"] == 0.5 * 1.1   # 0.5 * 1.1 = 0.55
        assert adapted["score_threshold"] == 4.0 * 0.9  # 4.0 * 0.9 = 3.6
        assert adapted["max_trades_per_hour"] == int(10 * 1.1)  # 10 * 1.1 = 11
    
    def test_apply_to_regime_params_choppy(self):
        """Тест применения параметров к choppy режиму"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Устанавливаем small профиль
        manager.update_balance(500.0)
        
        regime_params = {
            "tp_multiplier": 2.0,
            "sl_multiplier": 1.5,
            "ph_threshold": 0.5,
            "score_threshold": 4.0,
            "max_trades_per_hour": 10
        }
        
        adapted = manager.apply_to_regime_params(regime_params, "choppy")
        
        # Проверяем применение boost множителей для choppy
        assert adapted["tp_multiplier"] == 2.0 * 0.8  # 2.0 * 0.8 = 1.6
        assert adapted["sl_multiplier"] == 1.5 * 1.2  # 1.5 * 1.2 = 1.8
        assert adapted["ph_threshold"] == 0.5 * 0.9   # 0.5 * 0.9 = 0.45
        assert adapted["score_threshold"] == 4.0 * 1.1  # 4.0 * 1.1 = 4.4
        assert adapted["max_trades_per_hour"] == int(10 * 0.8)  # 10 * 0.8 = 8
    
    def test_apply_to_regime_params_no_balance_manager(self):
        """Тест применения параметров без баланс менеджера"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Не устанавливаем профиль
        regime_params = {"tp_multiplier": 2.0}
        adapted = manager.apply_to_regime_params(regime_params, "trending")
        
        # Параметры должны остаться без изменений
        assert adapted == regime_params
    
    def test_get_position_sizing_params(self):
        """Тест получения параметров размеров позиций"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Устанавливаем medium профиль
        manager.update_balance(3000.0)
        
        params = manager.get_position_sizing_params()
        
        assert params["base_position_size"] == 100.0
        assert params["min_position_size"] == 50.0
        assert params["max_position_size"] == 200.0
        assert params["max_open_positions"] == 3
        assert params["max_position_percent"] == 8.0
    
    def test_get_position_sizing_params_no_profile(self):
        """Тест получения параметров без установленного профиля"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        params = manager.get_position_sizing_params()
        assert params == {}
    
    def test_check_and_update_balance(self):
        """Тест проверки и обновления баланса"""
        # Устанавливаем профиль
        self.manager.update_balance(1000.0)
        
        # Создаем событие
        result = self.manager.check_and_update_balance(
            event="position_opened",
            symbol="ETH-USDT",
            side="long",
            amount=100.0
        )
        
        assert result is True
        assert len(self.manager.balance_events) == 1
        
        event = self.manager.balance_events[0]
        assert event.event_type == "position_opened"
        assert event.symbol == "ETH-USDT"
        assert event.side == "long"
        assert event.amount == 100.0
    
    def test_get_balance_stats(self):
        """Тест получения статистики баланса"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Устанавливаем профиль
        manager.update_balance(3000.0)
        
        stats = manager.get_balance_stats()
        
        assert stats["current_balance"] == 3000.0
        assert stats["current_profile"] == "medium"
        assert "last_update" in stats
        assert stats["profile_switches_count"] == 1
        assert stats["balance_history_count"] == 1
        assert len(stats["recent_switches"]) == 1
        assert len(stats["recent_events"]) == 0
    
    def test_get_profile_recommendations_small(self):
        """Тест получения рекомендаций для small профиля"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Устанавливаем small профиль с небольшим балансом
        manager.update_balance(200.0)
        
        recommendations = manager.get_profile_recommendations()
        
        assert recommendations["current_profile"] == "small"
        assert recommendations["balance"] == 200.0
        # Проверяем что рекомендации есть (может быть 0 если баланс достаточный)
        assert "recommendations" in recommendations
    
    def test_get_profile_recommendations_large(self):
        """Тест получения рекомендаций для large профиля"""
        # Создаем новый менеджер для этого теста
        manager = AdaptiveBalanceManager(self.profiles)
        
        # Устанавливаем large профиль с большим балансом
        manager.update_balance(10000.0)
        
        recommendations = manager.get_profile_recommendations()
        
        assert recommendations["current_profile"] == "large"
        assert recommendations["balance"] == 10000.0
        assert len(recommendations["recommendations"]) == 0  # Нет рекомендаций для большого баланса

class TestCreateDefaultProfiles:
    """Тесты для create_default_profiles"""
    
    def test_create_default_profiles(self):
        """Тест создания профилей по умолчанию"""
        profiles = create_default_profiles()
        
        assert len(profiles) == 3
        assert "small" in profiles
        assert "medium" in profiles
        assert "large" in profiles
        
        # Проверяем small профиль
        small = profiles["small"]
        assert small.threshold == 1000.0
        assert small.base_position_size == 50.0
        assert small.max_open_positions == 2
        
        # Проверяем medium профиль
        medium = profiles["medium"]
        assert medium.threshold == 2500.0
        assert medium.base_position_size == 100.0
        assert medium.max_open_positions == 3
        
        # Проверяем large профиль
        large = profiles["large"]
        assert large.threshold == 3500.0
        assert large.base_position_size == 200.0
        assert large.max_open_positions == 5
    
    def test_default_profiles_boost_configs(self):
        """Тест boost конфигураций в профилях по умолчанию"""
        profiles = create_default_profiles()
        
        # Проверяем trending boost для large профиля
        large_trending = profiles["large"].trending_boost
        assert large_trending["tp_multiplier"] == 1.5
        assert large_trending["sl_multiplier"] == 0.7
        assert large_trending["max_trades"] == 1.5
        
        # Проверяем choppy boost для small профиля
        small_choppy = profiles["small"].choppy_boost
        assert small_choppy["tp_multiplier"] == 0.8
        assert small_choppy["sl_multiplier"] == 1.2
        assert small_choppy["max_trades"] == 0.8

if __name__ == "__main__":
    print("🧪 Running Adaptive Balance Manager tests...")
    
    # Запуск тестов
    test_config = TestBalanceProfileConfig()
    test_config.test_balance_profile_config_creation()
    print("✅ BalanceProfileConfig tests passed")
    
    test_event = TestBalanceUpdateEvent()
    test_event.test_balance_update_event_creation()
    test_event.test_balance_update_event_auto_timestamp()
    print("✅ BalanceUpdateEvent tests passed")
    
    test_manager = TestAdaptiveBalanceManager()
    test_manager.setup_method()
    test_manager.test_initialization()
    test_manager.test_update_balance_small_profile()
    test_manager.test_update_balance_medium_profile()
    test_manager.test_update_balance_large_profile()
    test_manager.test_update_balance_no_change()
    test_manager.test_profile_switch_small_to_medium()
    test_manager.test_profile_switch_medium_to_large()
    test_manager.test_get_current_profile_config()
    test_manager.test_get_current_profile_config_no_profile()
    test_manager.test_apply_to_regime_params_trending()
    test_manager.test_apply_to_regime_params_ranging()
    test_manager.test_apply_to_regime_params_choppy()
    test_manager.test_apply_to_regime_params_no_balance_manager()
    test_manager.test_get_position_sizing_params()
    test_manager.test_get_position_sizing_params_no_profile()
    test_manager.test_check_and_update_balance()
    test_manager.test_get_balance_stats()
    test_manager.test_get_profile_recommendations_small()
    test_manager.test_get_profile_recommendations_large()
    print("✅ AdaptiveBalanceManager tests passed")
    
    test_default = TestCreateDefaultProfiles()
    test_default.test_create_default_profiles()
    test_default.test_default_profiles_boost_configs()
    print("✅ CreateDefaultProfiles tests passed")
    
    print("🎉 All Adaptive Balance Manager tests passed!")
