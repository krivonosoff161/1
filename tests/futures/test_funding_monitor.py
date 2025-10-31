"""
Тесты для FundingRateMonitor модуля.
"""

import pytest

<<<<<<< HEAD
from src.strategies.scalping.futures.indicators.funding_rate_monitor import \
    FundingRateMonitor
=======
from src.strategies.scalping.futures.indicators.funding_rate_monitor import (
    FundingRateMonitor,
)
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866


class TestFundingRateMonitor:
    """Тесты для FundingRateMonitor"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.funding_monitor = FundingRateMonitor(max_funding_rate=0.05)

    def test_initialization(self):
        """Тест инициализации"""
        assert self.funding_monitor.max_funding_rate == 0.05
        assert self.funding_monitor.current_funding == 0.0
        assert len(self.funding_monitor.funding_history) == 0

    def test_update(self):
        """Тест обновления funding rate"""
        self.funding_monitor.update(funding_rate=0.01)
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert self.funding_monitor.current_funding == 0.01
        assert len(self.funding_monitor.funding_history) == 1

    def test_get_current_funding(self):
        """Тест получения текущего funding"""
        self.funding_monitor.update(funding_rate=0.02)
<<<<<<< HEAD

        current = self.funding_monitor.get_current_funding()

=======
        
        current = self.funding_monitor.get_current_funding()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert current == 0.02

    def test_get_avg_funding(self):
        """Тест получения среднего funding"""
        # Добавляем несколько значений
        for rate in [0.01, 0.02, 0.03, 0.02, 0.01]:
            self.funding_monitor.update(funding_rate=rate)
<<<<<<< HEAD

        avg = self.funding_monitor.get_avg_funding(periods=5)

=======
        
        avg = self.funding_monitor.get_avg_funding(periods=5)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        expected = sum([0.01, 0.02, 0.03, 0.02, 0.01]) / 5
        assert abs(avg - expected) < 0.0001

    def test_is_funding_favorable_long_positive(self):
        """Тест благоприятности funding для лонга при положительном funding"""
        self.funding_monitor.update(funding_rate=0.1)  # Высокий положительный
<<<<<<< HEAD

        is_favorable = self.funding_monitor.is_funding_favorable(side="long")

=======
        
        is_favorable = self.funding_monitor.is_funding_favorable(side="long")
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # Для лонга положительный funding неблагоприятен
        assert is_favorable is False

    def test_is_funding_favorable_long_negative(self):
        """Тест благоприятности funding для лонга при отрицательном funding"""
        self.funding_monitor.update(funding_rate=-0.02)  # Отрицательный
<<<<<<< HEAD

        is_favorable = self.funding_monitor.is_funding_favorable(side="long")

=======
        
        is_favorable = self.funding_monitor.is_funding_favorable(side="long")
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # Для лонга отрицательный funding благоприятен
        assert is_favorable is True

    def test_is_funding_favorable_short_positive(self):
        """Тест благоприятности funding для шорта при положительном funding"""
        self.funding_monitor.update(funding_rate=0.02)  # Положительный
<<<<<<< HEAD

        is_favorable = self.funding_monitor.is_funding_favorable(side="short")

=======
        
        is_favorable = self.funding_monitor.is_funding_favorable(side="short")
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # Для шорта положительный funding благоприятен
        assert is_favorable is True

    def test_is_funding_favorable_short_negative(self):
        """Тест благоприятности funding для шорта при отрицательном funding"""
        self.funding_monitor.update(funding_rate=-0.1)  # Высокий отрицательный
<<<<<<< HEAD

        is_favorable = self.funding_monitor.is_funding_favorable(side="short")

=======
        
        is_favorable = self.funding_monitor.is_funding_favorable(side="short")
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # Для шорта отрицательный funding неблагоприятен
        assert is_favorable is False

    def test_get_funding_trend(self):
        """Тест определения тренда funding"""
        # Симуляция растущего funding
        for rate in [0.01, 0.02, 0.03]:
            self.funding_monitor.update(funding_rate=rate)
<<<<<<< HEAD

        trend = self.funding_monitor.get_funding_trend()

=======
        
        trend = self.funding_monitor.get_funding_trend()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert trend == "increasing"

    def test_get_payment_amount_long_positive(self):
        """Тест расчета платежа для лонга при положительном funding"""
        self.funding_monitor.update(funding_rate=0.01)
<<<<<<< HEAD

        payment = self.funding_monitor.get_payment_amount(
            side="long", position_size=1.0, price=50000.0
        )

=======
        
        payment = self.funding_monitor.get_payment_amount(
            side="long", position_size=1.0, price=50000.0
        )
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        expected = 1.0 * 50000.0 * 0.01
        assert abs(payment - expected) < 0.01
        assert payment > 0  # Получение средств

    def test_get_payment_amount_short_positive(self):
        """Тест расчета платежа для шорта при положительном funding"""
        self.funding_monitor.update(funding_rate=0.01)
<<<<<<< HEAD

        payment = self.funding_monitor.get_payment_amount(
            side="short", position_size=1.0, price=50000.0
        )

=======
        
        payment = self.funding_monitor.get_payment_amount(
            side="short", position_size=1.0, price=50000.0
        )
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        expected = -1.0 * 50000.0 * 0.01  # Для шорта знак обратный
        assert abs(payment - expected) < 0.01
        assert payment < 0  # Выплата средств

    def test_get_funding_info(self):
        """Тест получения информации о funding"""
        self.funding_monitor.update(funding_rate=0.01)
<<<<<<< HEAD

        info = self.funding_monitor.get_funding_info(side="long")

=======
        
        info = self.funding_monitor.get_funding_info(side="long")
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert "current_funding" in info
        assert "avg_funding" in info
        assert "trend" in info
        assert "is_favorable" in info
        assert "payment_direction" in info
        assert "recommendation" in info

    def test_reset(self):
        """Тест сброса мониторинга"""
        self.funding_monitor.update(funding_rate=0.01)
<<<<<<< HEAD

        self.funding_monitor.reset()

=======
        
        self.funding_monitor.reset()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert len(self.funding_monitor.funding_history) == 0
        assert self.funding_monitor.current_funding == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


