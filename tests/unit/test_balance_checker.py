"""
Unit tests
"""

import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

"""
Unit tests for Balance Checker module
"""

from unittest.mock import Mock

import pytest

from src.models import Balance, OrderSide
from src.strategies.modules.balance_checker import (BalanceCheckConfig,
                                                    BalanceChecker,
                                                    BalanceCheckResult)


class TestBalanceCheckConfig:
    """Тесты конфигурации Balance Checker"""

    def test_default_config(self):
        """Тест конфигурации по умолчанию"""
        config = BalanceCheckConfig()
        assert config.enabled is True
        assert config.usdt_reserve_percent == 10.0
        assert config.min_asset_balance_usd == 30.0
        assert config.min_usdt_balance == 30.0
        assert config.log_all_checks is False

    def test_custom_config(self):
        """Тест кастомной конфигурации"""
        config = BalanceCheckConfig(
            enabled=False,
            usdt_reserve_percent=15.0,
            min_asset_balance_usd=50.0,
            min_usdt_balance=50.0,
            log_all_checks=True,
        )
        assert config.enabled is False
        assert config.usdt_reserve_percent == 15.0
        assert config.min_asset_balance_usd == 50.0
        assert config.min_usdt_balance == 50.0
        assert config.log_all_checks is True


class TestBalanceCheckResult:
    """Тесты результата проверки баланса"""

    def test_allowed_result(self):
        """Тест разрешенной сделки"""
        result = BalanceCheckResult(
            allowed=True,
            reason="Sufficient balance",
            available_balance=1000.0,
            required_balance=500.0,
            currency="USDT",
        )
        assert result.allowed is True
        assert result.reason == "Sufficient balance"
        assert result.available_balance == 1000.0
        assert result.required_balance == 500.0
        assert result.currency == "USDT"

    def test_blocked_result(self):
        """Тест заблокированной сделки"""
        result = BalanceCheckResult(
            allowed=False,
            reason="Insufficient balance",
            available_balance=200.0,
            required_balance=500.0,
            currency="USDT",
        )
        assert result.allowed is False
        assert result.reason == "Insufficient balance"


class TestBalanceChecker:
    """Тесты Balance Checker"""

    @pytest.fixture
    def config(self):
        """Конфигурация для тестов"""
        return BalanceCheckConfig(
            usdt_reserve_percent=10.0,
            min_asset_balance_usd=30.0,
            min_usdt_balance=30.0,
        )

    @pytest.fixture
    def checker(self, config):
        """Balance Checker для тестов"""
        return BalanceChecker(config)

    def test_initialization(self, checker):
        """Тест инициализации"""
        assert checker.config is not None
        assert checker.total_checks == 0
        assert checker.total_blocked == 0
        assert len(checker.blocked_signals) == 0

    def test_check_usdt_sufficient_balance(self, checker):
        """Тест LONG: достаточно USDT"""
        balances = [
            Balance(currency="USDT", free=1000.0, used=0.0, total=1000.0),
        ]

        result = checker.check_balance(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            required_amount=0.001,  # 0.001 BTC
            current_price=50000.0,  # $50,000 per BTC
            balances=balances,
        )

        assert result.allowed is True
        assert result.currency == "USDT"
        assert result.available_balance == 900.0  # 1000 - 10% reserve
        assert result.required_balance == 50.0  # 0.001 * 50000
        assert checker.total_checks == 1
        assert checker.total_blocked == 0

    def test_check_usdt_insufficient_balance(self, checker):
        """Тест LONG: недостаточно USDT"""
        balances = [
            Balance(currency="USDT", free=40.0, used=0.0, total=40.0),
        ]

        result = checker.check_balance(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            required_amount=0.001,
            current_price=50000.0,
            balances=balances,
        )

        assert result.allowed is False
        assert result.currency == "USDT"
        assert "Insufficient USDT balance" in result.reason
        assert checker.total_checks == 1
        assert checker.total_blocked == 1
        assert checker.blocked_signals["BTC-USDT_LONG"] == 1

    def test_check_asset_sufficient_balance(self, checker):
        """Тест SHORT: достаточно актива"""
        balances = [
            Balance(currency="BTC", free=0.01, used=0.0, total=0.01),
        ]

        result = checker.check_balance(
            symbol="BTC-USDT",
            side=OrderSide.SELL,
            required_amount=0.001,
            current_price=50000.0,
            balances=balances,
        )

        assert result.allowed is True
        assert result.currency == "BTC"
        assert result.available_balance == 0.01
        assert result.required_balance == 0.001
        assert checker.total_checks == 1
        assert checker.total_blocked == 0

    def test_check_asset_insufficient_balance(self, checker):
        """Тест SHORT: недостаточно актива"""
        balances = [
            Balance(currency="BTC", free=0.0, used=0.0, total=0.0),
        ]

        result = checker.check_balance(
            symbol="BTC-USDT",
            side=OrderSide.SELL,
            required_amount=0.001,
            current_price=50000.0,
            balances=balances,
        )

        assert result.allowed is False
        assert result.currency == "BTC"
        assert "Insufficient BTC balance" in result.reason
        assert checker.total_checks == 1
        assert checker.total_blocked == 1
        assert checker.blocked_signals["BTC-USDT_SHORT"] == 1

    def test_check_asset_balance_too_small_usd(self, checker):
        """Тест SHORT: актива слишком мало в USD эквиваленте"""
        balances = [
            Balance(currency="SOL", free=0.1, used=0.0, total=0.1),
        ]

        result = checker.check_balance(
            symbol="SOL-USDT",
            side=OrderSide.SELL,
            required_amount=0.05,
            current_price=100.0,  # 0.05 SOL * $100 = $5 < $30 минимум
            balances=balances,
        )

        assert result.allowed is False
        assert result.currency == "SOL"
        assert "balance too small" in result.reason
        assert checker.total_checks == 1
        assert checker.total_blocked == 1

    def test_usdt_reserve_calculation(self, checker):
        """Тест расчета резерва USDT"""
        balances = [
            Balance(currency="USDT", free=1000.0, used=0.0, total=1000.0),
        ]

        # Требуем $950 (должно быть заблокировано, т.к. доступно только $900 после резерва)
        result = checker.check_balance(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            required_amount=0.019,  # 0.019 BTC
            current_price=50000.0,  # $950 required
            balances=balances,
        )

        assert result.allowed is False
        assert result.available_balance == 900.0  # 10% резерв вычтен

    def test_multiple_checks_statistics(self, checker):
        """Тест статистики множественных проверок"""
        balances_ok = [
            Balance(currency="USDT", free=1000.0, used=0.0, total=1000.0),
            Balance(currency="BTC", free=0.1, used=0.0, total=0.1),
        ]

        balances_empty = [
            Balance(currency="USDT", free=10.0, used=0.0, total=10.0),
            Balance(currency="BTC", free=0.0, used=0.0, total=0.0),
        ]

        # 4 успешные проверки
        for _ in range(4):
            checker.check_balance(
                "BTC-USDT", OrderSide.BUY, 0.001, 50000.0, balances_ok
            )

        # 6 неудачных проверок
        for _ in range(6):
            checker.check_balance(
                "ETH-USDT", OrderSide.SELL, 0.1, 2000.0, balances_empty
            )

        stats = checker.get_statistics()
        assert stats["total_checks"] == 10
        assert stats["total_blocked"] == 6
        assert stats["block_rate"] == 60.0
        assert stats["blocked_by_pair"]["ETH-USDT_SHORT"] == 6

    def test_no_balance_found(self, checker):
        """Тест: баланс валюты не найден"""
        balances = []  # Пустой список балансов

        result = checker.check_balance(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            required_amount=0.001,
            current_price=50000.0,
            balances=balances,
        )

        assert result.allowed is False
        assert result.currency == "USDT"

    def test_eth_short_sufficient(self, checker):
        """Тест SHORT ETH: достаточно ETH"""
        balances = [
            Balance(currency="ETH", free=1.0, used=0.0, total=1.0),
        ]

        result = checker.check_balance(
            symbol="ETH-USDT",
            side=OrderSide.SELL,
            required_amount=0.02,
            current_price=2000.0,  # 0.02 ETH * $2000 = $40 > $30 минимум
            balances=balances,
        )

        assert result.allowed is True
        assert result.currency == "ETH"

    def test_sol_long_edge_case(self, checker):
        """Тест LONG SOL: граничный случай (чуть больше минимума)"""
        balances = [
            Balance(currency="USDT", free=34.0, used=0.0, total=34.0),
        ]

        # Доступно: 34.0 - 10% = 30.6 USDT (чуть больше минимума $30)
        result = checker.check_balance(
            symbol="SOL-USDT",
            side=OrderSide.BUY,
            required_amount=0.15,
            current_price=200.0,  # $30 required
            balances=balances,
        )

        assert result.allowed is True
