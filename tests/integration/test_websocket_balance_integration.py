"""
Integration тесты для WebSocket + Adaptive Balance интеграции
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.balance import BalanceProfile
from src.config import (APIConfig, BalanceProfileConfig, BotConfig, RiskConfig,
                        ScalpingConfig)
from src.okx_client import OKXClient
from src.strategies.scalping.websocket_orchestrator import \
    WebSocketScalpingOrchestrator


@pytest.fixture
def mock_config_with_balance():
    """Фикстура для конфигурации с баланс профилями"""
    api_config = APIConfig(
        api_key="test_key",
        api_secret="test_secret",
        passphrase="test_passphrase",
        sandbox=True,
    )

    scalping_config = ScalpingConfig()
    risk_config = RiskConfig()

    # Добавляем баланс профили
    balance_profiles = {
        "small": {
            "threshold": 1000.0,
            "base_position_size": 50.0,
            "min_position_size": 25.0,
            "max_position_size": 100.0,
            "max_open_positions": 2,
            "max_position_percent": 10.0,
            "trending_boost": {
                "tp_multiplier": 1.2,
                "sl_multiplier": 0.9,
                "ph_threshold": 1.1,
                "score_threshold": 0.9,
                "max_trades": 1.1,
            },
            "ranging_boost": {
                "tp_multiplier": 1.0,
                "sl_multiplier": 1.0,
                "ph_threshold": 1.0,
                "score_threshold": 1.0,
                "max_trades": 1.0,
            },
            "choppy_boost": {
                "tp_multiplier": 0.8,
                "sl_multiplier": 1.2,
                "ph_threshold": 0.9,
                "score_threshold": 1.1,
                "max_trades": 0.8,
            },
        },
        "medium": {
            "threshold": 2500.0,
            "base_position_size": 100.0,
            "min_position_size": 50.0,
            "max_position_size": 200.0,
            "max_open_positions": 3,
            "max_position_percent": 8.0,
            "trending_boost": {
                "tp_multiplier": 1.3,
                "sl_multiplier": 0.8,
                "ph_threshold": 1.2,
                "score_threshold": 0.8,
                "max_trades": 1.2,
            },
            "ranging_boost": {
                "tp_multiplier": 1.1,
                "sl_multiplier": 0.9,
                "ph_threshold": 1.1,
                "score_threshold": 0.9,
                "max_trades": 1.1,
            },
            "choppy_boost": {
                "tp_multiplier": 0.9,
                "sl_multiplier": 1.1,
                "ph_threshold": 1.0,
                "score_threshold": 1.0,
                "max_trades": 0.9,
            },
        },
        "large": {
            "threshold": 3500.0,
            "base_position_size": 200.0,
            "min_position_size": 100.0,
            "max_position_size": 500.0,
            "max_open_positions": 5,
            "max_position_percent": 6.0,
            "trending_boost": {
                "tp_multiplier": 1.5,
                "sl_multiplier": 0.7,
                "ph_threshold": 1.3,
                "score_threshold": 0.7,
                "max_trades": 1.5,
            },
            "ranging_boost": {
                "tp_multiplier": 1.2,
                "sl_multiplier": 0.8,
                "ph_threshold": 1.2,
                "score_threshold": 0.8,
                "max_trades": 1.2,
            },
            "choppy_boost": {
                "tp_multiplier": 1.0,
                "sl_multiplier": 1.0,
                "ph_threshold": 1.1,
                "score_threshold": 0.9,
                "max_trades": 1.0,
            },
        },
    }

    return BotConfig(
        api={"okx": api_config},
        scalping=scalping_config,
        risk=risk_config,
        trading={"symbols": ["ETH-USDT", "BTC-USDT"], "base_currency": "USDT"},
        balance_profiles=balance_profiles,
    )


@pytest.fixture
def mock_okx_client():
    """Фикстура для мок OKX клиента"""
    client = Mock(spec=OKXClient)
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.get_candles = AsyncMock(
        return_value=[
            ["1698000000000", "3850", "3860", "3840", "3851.16", "1000", "0", "0"],
            ["1698000060000", "3851", "3861", "3841", "3852.16", "1100", "0", "0"],
        ]
    )
    return client


class TestWebSocketBalanceIntegration:
    """Тесты интеграции WebSocket и Adaptive Balance"""

    def test_orchestrator_initialization_with_balance(
        self, mock_config_with_balance, mock_okx_client
    ):
        """Тест инициализации оркестратора с баланс менеджером"""
        orchestrator = WebSocketScalpingOrchestrator(
            mock_config_with_balance, mock_okx_client
        )

        # Проверяем что баланс менеджер инициализирован
        assert orchestrator.balance_manager is not None
        assert orchestrator.config.balance_profiles is not None
        assert len(orchestrator.config.balance_profiles) == 3

    def test_balance_manager_profile_determination(
        self, mock_config_with_balance, mock_okx_client
    ):
        """Тест определения профиля баланса"""
        orchestrator = WebSocketScalpingOrchestrator(
            mock_config_with_balance, mock_okx_client
        )

        # Тестируем small профиль
        orchestrator.balance_manager.update_balance(500.0)
        assert orchestrator.balance_manager.current_profile == BalanceProfile.SMALL

        # Тестируем medium профиль
        orchestrator.balance_manager.update_balance(2000.0)
        assert orchestrator.balance_manager.current_profile == BalanceProfile.MEDIUM

        # Тестируем large профиль
        orchestrator.balance_manager.update_balance(4000.0)
        assert orchestrator.balance_manager.current_profile == BalanceProfile.LARGE

    def test_balance_manager_parameter_adaptation(
        self, mock_config_with_balance, mock_okx_client
    ):
        """Тест адаптации параметров под профиль баланса"""
        orchestrator = WebSocketScalpingOrchestrator(
            mock_config_with_balance, mock_okx_client
        )

        # Устанавливаем large профиль
        orchestrator.balance_manager.update_balance(4000.0)

        # Тестируем адаптацию для trending режима
        regime_params = {
            "tp_multiplier": 2.0,
            "sl_multiplier": 1.5,
            "ph_threshold": 0.5,
            "score_threshold": 4.0,
            "max_trades_per_hour": 10,
        }

        adapted = orchestrator.balance_manager.apply_to_regime_params(
            regime_params, "trending"
        )

        # Проверяем применение boost множителей для large профиля в trending режиме
        assert adapted["tp_multiplier"] == 2.0 * 1.5  # 3.0
        assert adapted["sl_multiplier"] == 1.5 * 0.7  # 1.05
        assert adapted["ph_threshold"] == 0.5 * 1.3  # 0.65
        assert adapted["score_threshold"] == 4.0 * 0.7  # 2.8
        assert adapted["max_trades_per_hour"] == int(10 * 1.5)  # 15

    def test_balance_manager_position_sizing(
        self, mock_config_with_balance, mock_okx_client
    ):
        """Тест размеров позиций для разных профилей"""
        orchestrator = WebSocketScalpingOrchestrator(
            mock_config_with_balance, mock_okx_client
        )

        # Тестируем small профиль
        orchestrator.balance_manager.update_balance(500.0)
        small_params = orchestrator.balance_manager.get_position_sizing_params()
        assert small_params["base_position_size"] == 50.0
        assert small_params["max_open_positions"] == 2

        # Тестируем medium профиль
        orchestrator.balance_manager.update_balance(2000.0)
        medium_params = orchestrator.balance_manager.get_position_sizing_params()
        assert medium_params["base_position_size"] == 100.0
        assert medium_params["max_open_positions"] == 3

        # Тестируем large профиль
        orchestrator.balance_manager.update_balance(4000.0)
        large_params = orchestrator.balance_manager.get_position_sizing_params()
        assert large_params["base_position_size"] == 200.0
        assert large_params["max_open_positions"] == 5

    def test_balance_manager_profile_switching(
        self, mock_config_with_balance, mock_okx_client
    ):
        """Тест переключения профилей"""
        orchestrator = WebSocketScalpingOrchestrator(
            mock_config_with_balance, mock_okx_client
        )

        # Начинаем с small профиля
        orchestrator.balance_manager.update_balance(500.0)
        assert orchestrator.balance_manager.current_profile == BalanceProfile.SMALL
        assert len(orchestrator.balance_manager.profile_switches) == 1

        # Переключаемся на medium
        orchestrator.balance_manager.update_balance(2000.0)
        assert orchestrator.balance_manager.current_profile == BalanceProfile.MEDIUM
        assert len(orchestrator.balance_manager.profile_switches) == 2

        # Переключаемся на large
        orchestrator.balance_manager.update_balance(4000.0)
        assert orchestrator.balance_manager.current_profile == BalanceProfile.LARGE
        assert len(orchestrator.balance_manager.profile_switches) == 3

        # Проверяем информацию о переключениях
        switches = orchestrator.balance_manager.profile_switches
        assert switches[0]["old_profile"] is None
        assert switches[0]["new_profile"] == "small"
        assert switches[1]["old_profile"] == "small"
        assert switches[1]["new_profile"] == "medium"
        assert switches[2]["old_profile"] == "medium"
        assert switches[2]["new_profile"] == "large"

    def test_balance_manager_events_tracking(
        self, mock_config_with_balance, mock_okx_client
    ):
        """Тест отслеживания событий баланса"""
        orchestrator = WebSocketScalpingOrchestrator(
            mock_config_with_balance, mock_okx_client
        )

        # Создаем несколько событий
        orchestrator.balance_manager.check_and_update_balance(
            event="position_opened", symbol="ETH-USDT", side="long", amount=100.0
        )

        orchestrator.balance_manager.check_and_update_balance(
            event="position_closed", symbol="ETH-USDT", side="long", amount=105.0
        )

        orchestrator.balance_manager.check_and_update_balance(
            event="manual_update", symbol="BTC-USDT", side="short", amount=200.0
        )

        # Проверяем события
        events = orchestrator.balance_manager.balance_events
        assert len(events) == 3
        assert events[0].event_type == "position_opened"
        assert events[0].symbol == "ETH-USDT"
        assert events[1].event_type == "position_closed"
        assert events[1].symbol == "ETH-USDT"
        assert events[2].event_type == "manual_update"
        assert events[2].symbol == "BTC-USDT"

    def test_balance_manager_statistics(
        self, mock_config_with_balance, mock_okx_client
    ):
        """Тест статистики баланс менеджера"""
        orchestrator = WebSocketScalpingOrchestrator(
            mock_config_with_balance, mock_okx_client
        )

        # Устанавливаем профиль и создаем события
        orchestrator.balance_manager.update_balance(2000.0)
        orchestrator.balance_manager.check_and_update_balance(
            "position_opened", symbol="ETH-USDT"
        )

        # Получаем статистику
        stats = orchestrator.balance_manager.get_balance_stats()

        assert stats["current_balance"] == 2000.0
        assert stats["current_profile"] == "medium"
        assert "last_update" in stats
        assert stats["profile_switches_count"] == 1
        assert stats["balance_history_count"] == 1
        assert len(stats["recent_switches"]) == 1
        assert len(stats["recent_events"]) == 1

    def test_balance_manager_recommendations(
        self, mock_config_with_balance, mock_okx_client
    ):
        """Тест рекомендаций баланс менеджера"""
        orchestrator = WebSocketScalpingOrchestrator(
            mock_config_with_balance, mock_okx_client
        )

        # Тестируем рекомендации для small профиля с малым балансом
        orchestrator.balance_manager.update_balance(100.0)
        small_recommendations = (
            orchestrator.balance_manager.get_profile_recommendations()
        )

        assert small_recommendations["current_profile"] == "small"
        assert small_recommendations["balance"] == 100.0
        assert len(small_recommendations["recommendations"]) > 0

        # Тестируем рекомендации для large профиля с большим балансом
        orchestrator.balance_manager.update_balance(10000.0)
        large_recommendations = (
            orchestrator.balance_manager.get_profile_recommendations()
        )

        assert large_recommendations["current_profile"] == "large"
        assert large_recommendations["balance"] == 10000.0
        assert len(large_recommendations["recommendations"]) == 0

    def test_orchestrator_stats_with_balance(
        self, mock_config_with_balance, mock_okx_client
    ):
        """Тест статистики оркестратора с баланс менеджером"""
        orchestrator = WebSocketScalpingOrchestrator(
            mock_config_with_balance, mock_okx_client
        )

        # Устанавливаем профиль
        orchestrator.balance_manager.update_balance(2000.0)

        # Получаем статистику
        stats = orchestrator.get_stats()

        # Проверяем что статистика баланса включена
        assert "balance_stats" in stats
        balance_stats = stats["balance_stats"]
        assert balance_stats["current_balance"] == 2000.0
        assert balance_stats["current_profile"] == "medium"

    def test_balance_manager_fallback_profiles(self, mock_okx_client):
        """Тест fallback профилей при отсутствии конфигурации"""
        # Создаем конфигурацию без баланс профилей
        api_config = APIConfig(
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_passphrase",
            sandbox=True,
        )

        config = BotConfig(
            api=api_config,
            scalping=ScalpingConfig(),
            risk=RiskConfig(),
            trading={"symbols": ["ETH-USDT"], "base_currency": "USDT"},
            balance_profiles=None,  # Нет профилей
        )

        orchestrator = WebSocketScalpingOrchestrator(config, mock_okx_client)

        # Проверяем что баланс менеджер инициализирован с профилями по умолчанию
        assert orchestrator.balance_manager is not None

        # Тестируем работу с профилями по умолчанию
        orchestrator.balance_manager.update_balance(500.0)
        assert orchestrator.balance_manager.current_profile == BalanceProfile.SMALL

        orchestrator.balance_manager.update_balance(2000.0)
        assert orchestrator.balance_manager.current_profile == BalanceProfile.MEDIUM

        orchestrator.balance_manager.update_balance(4000.0)
        assert orchestrator.balance_manager.current_profile == BalanceProfile.LARGE


if __name__ == "__main__":
    print("🧪 Running WebSocket + Balance Integration tests...")

    # Создаем фикстуры
    from src.config import APIConfig, BotConfig, RiskConfig, ScalpingConfig

    api_config = APIConfig(
        api_key="test_key",
        api_secret="test_secret",
        passphrase="test_passphrase",
        sandbox=True,
    )

    config = BotConfig(
        api={"okx": api_config},
        scalping=ScalpingConfig(),
        risk=RiskConfig(),
        trading={"symbols": ["ETH-USDT"], "base_currency": "USDT"},
        balance_profiles={
            "small": {
                "threshold": 1000.0,
                "base_position_size": 50.0,
                "min_position_size": 25.0,
                "max_position_size": 100.0,
                "max_open_positions": 2,
                "max_position_percent": 10.0,
                "trending_boost": {
                    "tp_multiplier": 1.2,
                    "sl_multiplier": 0.9,
                    "ph_threshold": 1.1,
                    "score_threshold": 0.9,
                    "max_trades": 1.1,
                },
                "ranging_boost": {
                    "tp_multiplier": 1.0,
                    "sl_multiplier": 1.0,
                    "ph_threshold": 1.0,
                    "score_threshold": 1.0,
                    "max_trades": 1.0,
                },
                "choppy_boost": {
                    "tp_multiplier": 0.8,
                    "sl_multiplier": 1.2,
                    "ph_threshold": 0.9,
                    "score_threshold": 1.1,
                    "max_trades": 0.8,
                },
            }
        },
    )

    client = Mock(spec=OKXClient)

    # Запускаем тесты
    test_integration = TestWebSocketBalanceIntegration()

    test_integration.test_orchestrator_initialization_with_balance(config, client)
    print("✅ Orchestrator initialization test passed")

    test_integration.test_balance_manager_profile_determination(config, client)
    print("✅ Profile determination test passed")

    test_integration.test_balance_manager_parameter_adaptation(config, client)
    print("✅ Parameter adaptation test passed")

    test_integration.test_balance_manager_position_sizing(config, client)
    print("✅ Position sizing test passed")

    test_integration.test_balance_manager_profile_switching(config, client)
    print("✅ Profile switching test passed")

    test_integration.test_balance_manager_events_tracking(config, client)
    print("✅ Events tracking test passed")

    test_integration.test_balance_manager_statistics(config, client)
    print("✅ Statistics test passed")

    test_integration.test_balance_manager_recommendations(config, client)
    print("✅ Recommendations test passed")

    test_integration.test_orchestrator_stats_with_balance(config, client)
    print("✅ Orchestrator stats test passed")

    test_integration.test_balance_manager_fallback_profiles(client)
    print("✅ Fallback profiles test passed")

    print("🎉 All WebSocket + Balance Integration tests passed!")
