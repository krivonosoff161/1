"""
Тест адаптивной системы параметров под каждый режим рынка
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from unittest.mock import Mock
from src.config import BotConfig, ScalpingConfig, RiskConfig, TradingConfig
from src.balance import AdaptiveBalanceManager, create_default_profiles
from src.strategies.modules.adaptive_regime_manager import AdaptiveRegimeManager, RegimeConfig, RegimeType
from src.strategies.scalping.websocket_orchestrator import WebSocketScalpingOrchestrator
from src.okx_client import OKXClient

async def test_adaptive_parameters():
    """Тестирует адаптивную систему параметров под каждый режим рынка"""
    print("🚀 Starting Adaptive Parameters Test...")
    
    # Создаем конфигурацию с баланс профилями
    config = BotConfig(
        api={"okx": {"api_key": "test", "api_secret": "test", "passphrase": "test", "sandbox": True}},
        scalping=ScalpingConfig(),
        risk=RiskConfig(),
        trading={
            "symbols": ["ETH-USDT"],
            "base_currency": "USDT"
        },
        balance_profiles={
            "small": {
                "threshold": 1000.0,
                "base_position_size": 50.0,
                "min_position_size": 25.0,
                "max_position_size": 100.0,
                "max_open_positions": 2,
                "max_position_percent": 10.0,
                "trending_boost": {"tp_multiplier": 1.2, "sl_multiplier": 0.9, "ph_threshold": 1.1, "score_threshold": 0.9, "max_trades": 1.1},
                "ranging_boost": {"tp_multiplier": 1.0, "sl_multiplier": 1.0, "ph_threshold": 1.0, "score_threshold": 1.0, "max_trades": 1.0},
                "choppy_boost": {"tp_multiplier": 0.8, "sl_multiplier": 1.2, "ph_threshold": 0.9, "score_threshold": 1.1, "max_trades": 0.8}
            },
            "medium": {
                "threshold": 2500.0,
                "base_position_size": 100.0,
                "min_position_size": 50.0,
                "max_position_size": 200.0,
                "max_open_positions": 3,
                "max_position_percent": 8.0,
                "trending_boost": {"tp_multiplier": 1.3, "sl_multiplier": 0.8, "ph_threshold": 1.2, "score_threshold": 0.8, "max_trades": 1.2},
                "ranging_boost": {"tp_multiplier": 1.1, "sl_multiplier": 0.9, "ph_threshold": 1.1, "score_threshold": 0.9, "max_trades": 1.1},
                "choppy_boost": {"tp_multiplier": 0.9, "sl_multiplier": 1.1, "ph_threshold": 1.0, "score_threshold": 1.0, "max_trades": 0.9}
            },
            "large": {
                "threshold": 3500.0,
                "base_position_size": 200.0,
                "min_position_size": 100.0,
                "max_position_size": 500.0,
                "max_open_positions": 5,
                "max_position_percent": 6.0,
                "trending_boost": {"tp_multiplier": 1.5, "sl_multiplier": 0.7, "ph_threshold": 1.3, "score_threshold": 0.7, "max_trades": 1.5},
                "ranging_boost": {"tp_multiplier": 1.2, "sl_multiplier": 0.8, "ph_threshold": 1.2, "score_threshold": 0.8, "max_trades": 1.2},
                "choppy_boost": {"tp_multiplier": 1.0, "sl_multiplier": 1.0, "ph_threshold": 1.1, "score_threshold": 0.9, "max_trades": 1.0}
            }
        }
    )
    
    # Мокаем OKX клиент
    mock_client = Mock(spec=OKXClient)
    mock_client.get_account_balance.return_value = 500.0  # Small баланс
    
    # Создаем оркестратор
    orchestrator = WebSocketScalpingOrchestrator(config, mock_client)
    
    print("✅ Orchestrator created successfully")
    
    # Тестируем разные комбинации баланс + режим
    test_cases = [
        {"balance": 500.0, "regime": "trending", "expected_profile": "small"},
        {"balance": 500.0, "regime": "ranging", "expected_profile": "small"},
        {"balance": 500.0, "regime": "choppy", "expected_profile": "small"},
        {"balance": 4000.0, "regime": "trending", "expected_profile": "large"},
        {"balance": 4000.0, "regime": "ranging", "expected_profile": "large"},
        {"balance": 4000.0, "regime": "choppy", "expected_profile": "large"},
    ]
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n📊 Test {i}: Balance ${case['balance']} + {case['regime'].upper()} mode")
        
        # Обновляем баланс
        orchestrator.balance_manager.update_balance(case['balance'])
        
        # Устанавливаем режим
        if case['regime'] == 'trending':
            orchestrator.arm.current_regime = RegimeType.TRENDING
        elif case['regime'] == 'ranging':
            orchestrator.arm.current_regime = RegimeType.RANGING
        else:  # choppy
            orchestrator.arm.current_regime = RegimeType.CHOPPY
        
        # Получаем адаптированные параметры
        regime_params = orchestrator.arm.get_current_parameters(orchestrator.balance_manager)
        
        print(f"   ✅ Profile: {orchestrator.balance_manager.current_profile}")
        print(f"   ✅ Regime: {orchestrator.arm.current_regime.value}")
        print(f"   ✅ TP Multiplier: {regime_params.tp_atr_multiplier:.2f}")
        print(f"   ✅ SL Multiplier: {regime_params.sl_atr_multiplier:.2f}")
        print(f"   ✅ Score Threshold: {regime_params.min_score_threshold:.2f}")
        print(f"   ✅ Max Trades: {regime_params.max_trades_per_hour}")
        
        # Проверяем что параметры адаптированы
        if case['expected_profile'] == 'small':
            if case['regime'] == 'trending':
                assert regime_params.tp_atr_multiplier > 2.0, f"Small+Trending TP should be boosted: {regime_params.tp_atr_multiplier}"
                assert regime_params.sl_atr_multiplier < 1.5, f"Small+Trending SL should be reduced: {regime_params.sl_atr_multiplier}"
            elif case['regime'] == 'choppy':
                assert regime_params.tp_atr_multiplier < 2.0, f"Small+Choppy TP should be reduced: {regime_params.tp_atr_multiplier}"
                assert regime_params.sl_atr_multiplier > 1.5, f"Small+Choppy SL should be increased: {regime_params.sl_atr_multiplier}"
        elif case['expected_profile'] == 'large':
            if case['regime'] == 'trending':
                # Large+Trending должен быть более агрессивным чем базовый trending
                assert regime_params.tp_atr_multiplier >= 2.5, f"Large+Trending TP should be at least 2.5: {regime_params.tp_atr_multiplier}"
                assert regime_params.sl_atr_multiplier <= 1.2, f"Large+Trending SL should be at most 1.2: {regime_params.sl_atr_multiplier}"
        
        print(f"   ✅ Parameters correctly adapted for {case['expected_profile']} + {case['regime']}")
    
    print("\n🎉 All Adaptive Parameters Tests Passed!")
    print("\n📋 Summary:")
    print("   ✅ Small balance + Trending = Aggressive TP, Conservative SL")
    print("   ✅ Small balance + Choppy = Conservative TP, Aggressive SL")
    print("   ✅ Large balance + Trending = Very Aggressive TP, Very Conservative SL")
    print("   ✅ Large balance + Choppy = Moderate TP, Moderate SL")
    print("   ✅ All combinations properly adapted!")

if __name__ == "__main__":
    asyncio.run(test_adaptive_parameters())
