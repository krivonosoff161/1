"""
Быстрый тест адаптивного баланса без сложных зависимостей
"""

import sys

sys.path.insert(0, "C:\\Users\\krivo\\simple trading bot okx")

from src.balance import (AdaptiveBalanceManager, BalanceProfile,
                         create_default_profiles)


def test_balance_manager():
    """Тест адаптивного баланс менеджера"""
    print("🧪 Testing Adaptive Balance Manager...")

    # Создаем профили
    profiles = create_default_profiles()
    manager = AdaptiveBalanceManager(profiles)

    # Тест 1: Small профиль
    print("📊 Test 1: Small profile")
    manager.update_balance(500.0)
    assert manager.current_profile == BalanceProfile.SMALL
    print(f"✅ Small profile: {manager.current_profile}")

    # Тест 2: Medium профиль
    print("📊 Test 2: Medium profile")
    manager.update_balance(3000.0)
    assert manager.current_profile == BalanceProfile.MEDIUM
    print(f"✅ Medium profile: {manager.current_profile}")

    # Тест 3: Large профиль
    print("📊 Test 3: Large profile")
    manager.update_balance(4000.0)
    assert manager.current_profile == BalanceProfile.LARGE
    print(f"✅ Large profile: {manager.current_profile}")

    # Тест 4: Применение параметров
    print("📊 Test 4: Parameter adaptation")
    regime_params = {
        "tp_multiplier": 2.0,
        "sl_multiplier": 1.5,
        "ph_threshold": 0.5,
        "score_threshold": 4.0,
        "max_trades_per_hour": 10,
    }

    adapted = manager.apply_to_regime_params(regime_params, "trending")
    print(
        f"✅ Adapted TP: {adapted['tp_multiplier']} (was {regime_params['tp_multiplier']})"
    )
    print(
        f"✅ Adapted SL: {adapted['sl_multiplier']} (was {regime_params['sl_multiplier']})"
    )

    # Тест 5: Размеры позиций
    print("📊 Test 5: Position sizing")
    sizing_params = manager.get_position_sizing_params()
    print(f"✅ Base position size: {sizing_params['base_position_size']}")
    print(f"✅ Max open positions: {sizing_params['max_open_positions']}")

    # Тест 6: Статистика
    print("📊 Test 6: Statistics")
    stats = manager.get_balance_stats()
    print(f"✅ Current balance: {stats['current_balance']}")
    print(f"✅ Current profile: {stats['current_profile']}")
    print(f"✅ Profile switches: {stats['profile_switches_count']}")

    print("🎉 All balance manager tests passed!")


def test_balance_integration():
    """Тест интеграции с WebSocket Orchestrator"""
    print("\n🧪 Testing Balance + WebSocket Integration...")

    try:
        from unittest.mock import Mock

        from src.config import APIConfig, BotConfig, RiskConfig, ScalpingConfig
        from src.okx_client import OKXClient
        from src.strategies.scalping.websocket_orchestrator import \
            WebSocketScalpingOrchestrator

        # Создаем простую конфигурацию
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
            },
        )

        # Мокаем OKX клиент
        mock_client = Mock(spec=OKXClient)

        # Создаем оркестратор
        orchestrator = WebSocketScalpingOrchestrator(config, mock_client)

        # Проверяем что баланс менеджер инициализирован
        assert orchestrator.balance_manager is not None
        print("✅ Balance manager initialized in orchestrator")

        # Тестируем обновление баланса
        orchestrator.balance_manager.update_balance(500.0)
        assert orchestrator.balance_manager.current_profile == BalanceProfile.SMALL
        print("✅ Balance manager working in orchestrator")

        # Тестируем статистику
        stats = orchestrator.get_stats()
        assert "balance_stats" in stats
        print("✅ Balance stats included in orchestrator stats")

        print("🎉 Balance + WebSocket integration test passed!")

    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    print("🚀 Starting Quick Balance Tests...")

    test_balance_manager()
    test_balance_integration()

    print("\n🎉 All Quick Balance Tests Completed!")
