"""
Тесты для Margin Calculator модуля.
Проверяет корректность расчетов маржи и ликвидации.
"""

import math

import pytest

from src.strategies.modules.margin_calculator import MarginCalculator


class TestMarginCalculator:
    """Тесты для MarginCalculator"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.calculator = MarginCalculator(
            default_leverage=3, maintenance_margin_ratio=0.01, initial_margin_ratio=0.1
        )

    def test_initialization(self):
        """Тест инициализации калькулятора"""
        assert self.calculator.default_leverage == 3
        assert self.calculator.maintenance_margin_ratio == 0.01
        assert self.calculator.initial_margin_ratio == 0.1

    def test_calculate_max_position_size(self):
        """Тест расчета максимального размера позиции"""
        equity = 1000.0
        current_price = 50000.0
        leverage = 3

        max_size = self.calculator.calculate_max_position_size(
            equity, current_price, leverage
        )

        expected_size = (equity * leverage) / current_price
        assert abs(max_size - expected_size) < 0.000001
        assert max_size == 0.06  # 1000 * 3 / 50000

    def test_calculate_liquidation_price_long(self):
        """Тест расчета цены ликвидации для лонга"""
        side = "buy"
        entry_price = 50000.0
        position_size = 0.06
        equity = 1000.0
        leverage = 3

        liq_price = self.calculator.calculate_liquidation_price(
            side, entry_price, position_size, equity, leverage
        )

        # Для лонга: LiqPrice = EntryPrice * (1 - (1/Leverage) + MaintenanceMarginRatio)
        expected_liq_price = entry_price * (1 - (1 / leverage) + 0.01)
        assert abs(liq_price - expected_liq_price) < 0.01
        assert liq_price < entry_price  # Ликвидация ниже цены входа для лонга

    def test_calculate_liquidation_price_short(self):
        """Тест расчета цены ликвидации для шорта"""
        side = "sell"
        entry_price = 50000.0
        position_size = 0.06
        equity = 1000.0
        leverage = 3

        liq_price = self.calculator.calculate_liquidation_price(
            side, entry_price, position_size, equity, leverage
        )

        # Для шорта: LiqPrice = EntryPrice * (1 + (1/Leverage) - MaintenanceMarginRatio)
        expected_liq_price = entry_price * (1 + (1 / leverage) - 0.01)
        assert abs(liq_price - expected_liq_price) < 0.01
        assert liq_price > entry_price  # Ликвидация выше цены входа для шорта

    def test_calculate_margin_ratio(self):
        """Тест расчета коэффициента маржи"""
        position_value = 3000.0
        equity = 1000.0
        leverage = 3

        margin_ratio = self.calculator.calculate_margin_ratio(
            position_value, equity, leverage
        )

        margin_used = position_value / leverage
        expected_ratio = equity / margin_used
        assert abs(margin_ratio - expected_ratio) < 0.01
        assert margin_ratio == 1.0  # 1000 / (3000/3) = 1.0

    def test_is_position_safe_safe(self):
        """Тест проверки безопасности позиции - безопасная"""
        position_value = 1000.0
        equity = 1000.0
        current_price = 50000.0
        entry_price = 49500.0
        side = "buy"
        leverage = 3
        safety_threshold = 1.5

        is_safe, details = self.calculator.is_position_safe(
            position_value,
            equity,
            current_price,
            entry_price,
            side,
            leverage,
            safety_threshold,
        )

        assert is_safe is True
        assert "margin_ratio" in details
        assert "pnl" in details
        assert "liquidation_price" in details
        assert details["pnl"] > 0  # Прибыль для лонга при росте цены

    def test_is_position_safe_unsafe(self):
        """Тест проверки безопасности позиции - небезопасная"""
        position_value = 3000.0
        equity = 1000.0
        current_price = 50000.0
        entry_price = 51000.0
        side = "buy"
        leverage = 3
        safety_threshold = 1.5

        is_safe, details = self.calculator.is_position_safe(
            position_value,
            equity,
            current_price,
            entry_price,
            side,
            leverage,
            safety_threshold,
        )

        assert is_safe is False
        assert details["pnl"] < 0  # Убыток для лонга при падении цены
        assert details["margin_ratio"] < safety_threshold

    def test_calculate_optimal_position_size(self):
        """Тест расчета оптимального размера позиции"""
        equity = 1000.0
        current_price = 50000.0
        risk_percentage = 0.02
        leverage = 3

        optimal_size = self.calculator.calculate_optimal_position_size(
            equity, current_price, risk_percentage, leverage
        )

        max_risk_usdt = equity * risk_percentage
        max_position_value = max_risk_usdt * leverage
        expected_size = max_position_value / current_price

        assert abs(optimal_size - expected_size) < 0.000001
        assert optimal_size == 0.0012  # (1000 * 0.02 * 3) / 50000

    def test_get_margin_health_status_excellent(self):
        """Тест статуса здоровья маржи - отличное состояние"""
        equity = 1000.0
        total_margin_used = 200.0

        status = self.calculator.get_margin_health_status(equity, total_margin_used)

        assert status["status"] == "excellent"
        assert status["level"] == 5.0  # 1000 / 200
        assert "Отличное состояние маржи" in status["message"]

    def test_get_margin_health_status_critical(self):
        """Тест статуса здоровья маржи - критическое состояние"""
        equity = 1000.0
        total_margin_used = 1200.0

        status = self.calculator.get_margin_health_status(equity, total_margin_used)

        assert status["status"] == "critical"
        assert status["level"] < 1.0
        assert "КРИТИЧНО" in status["message"]

    def test_get_margin_health_status_no_positions(self):
        """Тест статуса здоровья маржи - нет позиций"""
        equity = 1000.0
        total_margin_used = 0.0

        status = self.calculator.get_margin_health_status(equity, total_margin_used)

        assert status["status"] == "excellent"
        assert status["level"] == 100.0
        assert "Нет открытых позиций" in status["message"]

    def test_edge_cases(self):
        """Тест граничных случаев"""
        # Нулевой баланс
        max_size = self.calculator.calculate_max_position_size(0, 50000)
        assert max_size == 0

        # Нулевая цена
        with pytest.raises(ZeroDivisionError):
            self.calculator.calculate_max_position_size(1000, 0)

        # Отрицательный размер позиции
        liq_price = self.calculator.calculate_liquidation_price(
            "buy", 50000, -0.06, 1000, 3
        )
        assert liq_price > 0  # Должен обработать отрицательный размер

    def test_different_leverages(self):
        """Тест с разными уровнями левериджа"""
        equity = 1000.0
        current_price = 50000.0

        # Тест с плечом 1x
        max_size_1x = self.calculator.calculate_max_position_size(
            equity, current_price, 1
        )

        # Тест с плечом 5x
        max_size_5x = self.calculator.calculate_max_position_size(
            equity, current_price, 5
        )

        assert max_size_5x > max_size_1x
        assert max_size_1x == 0.02  # 1000 * 1 / 50000
        assert max_size_5x == 0.1  # 1000 * 5 / 50000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
