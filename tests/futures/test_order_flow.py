"""
Тесты для OrderFlowIndicator модуля.
"""

import pytest

from src.strategies.scalping.futures.indicators.order_flow_indicator import (
    OrderFlowIndicator,
)


class TestOrderFlowIndicator:
    """Тесты для OrderFlowIndicator"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.order_flow = OrderFlowIndicator(
            window=100, long_threshold=0.1, short_threshold=-0.1
        )

    def test_initialization(self):
        """Тест инициализации"""
        assert self.order_flow.window == 100
        assert self.order_flow.long_threshold == 0.1
        assert self.order_flow.short_threshold == -0.1

    def test_update_normal(self):
        """Тест обновления с нормальными значениями"""
        self.order_flow.update(bid_volume=1000.0, ask_volume=800.0)
        
        assert len(self.order_flow.bid_volumes) == 1
        assert len(self.order_flow.ask_volumes) == 1
        assert len(self.order_flow.deltas) == 1

    def test_get_delta(self):
        """Тест получения delta"""
        self.order_flow.update(bid_volume=1000.0, ask_volume=800.0)
        
        delta = self.order_flow.get_delta()
        
        expected = (1000.0 - 800.0) / 1800.0  # (bid - ask) / total
        assert abs(delta - expected) < 0.0001

    def test_get_avg_delta(self):
        """Тест получения среднего delta"""
        # Добавляем несколько значений
        for i in range(10):
            self.order_flow.update(bid_volume=1000.0 + i, ask_volume=800.0 + i)
        
        avg_delta = self.order_flow.get_avg_delta(periods=10)
        
        assert avg_delta != 0
        assert -1.0 <= avg_delta <= 1.0

    def test_get_delta_trend_increasing(self):
        """Тест определения растущего тренда delta"""
        # Симуляция растущей delta
        deltas = [0.01, 0.02, 0.03, 0.04, 0.05]
        for delta in deltas:
            self.order_flow.deltas.append(delta)
        
        trend = self.order_flow.get_delta_trend()
        
        assert trend == "long"

    def test_get_delta_trend_decreasing(self):
        """Тест определения падающего тренда delta"""
        # Симуляция падающей delta
        deltas = [0.05, 0.04, 0.03, 0.02, 0.01]
        for delta in deltas:
            self.order_flow.deltas.append(delta)
        
        trend = self.order_flow.get_delta_trend()
        
        assert trend == "short"

    def test_is_long_favorable(self):
        """Тест проверки благоприятности лонга"""
        self.order_flow.update(bid_volume=1000.0, ask_volume=800.0)
        
        is_favorable = self.order_flow.is_long_favorable()
        
        # bid > ask → delta > 0 → должен быть благоприятным
        assert is_favorable is True

    def test_is_short_favorable(self):
        """Тест проверки благоприятности шорта"""
        self.order_flow.update(bid_volume=800.0, ask_volume=1000.0)
        
        is_favorable = self.order_flow.is_short_favorable()
        
        # bid < ask → delta < 0 → должен быть благоприятным
        assert is_favorable is True

    def test_get_market_pressure(self):
        """Тест получения рыночного давления"""
        self.order_flow.update(bid_volume=1000.0, ask_volume=800.0)
        
        pressure = self.order_flow.get_market_pressure()
        
        assert "current_delta" in pressure
        assert "avg_delta" in pressure
        assert "trend" in pressure
        assert "strength" in pressure
        assert "favor_long" in pressure
        assert "favor_short" in pressure
        assert 0 <= pressure["strength"] <= 100

    def test_calculate_delta_edge_cases(self):
        """Тест расчета delta для граничных случаев"""
        # Одинаковые объемы
        self.order_flow.update(bid_volume=1000.0, ask_volume=1000.0)
        delta = self.order_flow.get_delta()
        assert delta == 0.0
        
        # Очень большой bid
        self.order_flow.update(bid_volume=10000.0, ask_volume=100.0)
        delta = self.order_flow.get_delta()
        assert delta > 0.9  # Очень близко к 1.0
        
        # Очень большой ask
        self.order_flow.update(bid_volume=100.0, ask_volume=10000.0)
        delta = self.order_flow.get_delta()
        assert delta < -0.9  # Очень близко к -1.0

    def test_reset(self):
        """Тест сброса индикатора"""
        self.order_flow.update(bid_volume=1000.0, ask_volume=800.0)
        
        self.order_flow.reset()
        
        assert len(self.order_flow.bid_volumes) == 0
        assert len(self.order_flow.ask_volumes) == 0
        assert len(self.order_flow.deltas) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


