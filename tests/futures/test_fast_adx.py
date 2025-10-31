"""
Тесты для FastADX модуля.
"""

import pytest

from src.strategies.scalping.futures.indicators.fast_adx import FastADX


class TestFastADX:
    """Тесты для FastADX"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.fast_adx = FastADX(period=9, threshold=20.0)

    def test_initialization(self):
        """Тест инициализации"""
        assert self.fast_adx.period == 9
        assert self.fast_adx.threshold == 20.0
        assert len(self.fast_adx.di_plus_history) == 0
        assert len(self.fast_adx.di_minus_history) == 0

    def test_update(self):
        """Тест обновления индикатора"""
        self.fast_adx.update(high=51000.0, low=49000.0, close=50000.0)
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # После первого обновления должно быть в истории
        # (требуется несколько свечей для расчета)
        assert self.fast_adx.current_high == 51000.0
        assert self.fast_adx.current_low == 49000.0
        assert self.fast_adx.current_close == 50000.0

    def test_get_adx_value(self):
        """Тест получения значения ADX"""
        # Добавляем несколько свечей для расчета
        for i in range(15):
            self.fast_adx.update(
<<<<<<< HEAD
                high=50000.0 + i * 10, low=50000.0 - i * 10, close=50000.0 + i * 5
            )

        adx = self.fast_adx.get_adx_value()

=======
                high=50000.0 + i * 10,
                low=50000.0 - i * 10,
                close=50000.0 + i * 5
            )
        
        adx = self.fast_adx.get_adx_value()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert adx is not None
        assert 0 <= adx <= 100

    def test_is_trend_strong(self):
        """Тест проверки силы тренда"""
        # Добавляем сильный тренд
        for i in range(15):
            self.fast_adx.update(
                high=50000.0 + i * 100,  # Растущий тренд
                low=50000.0 + i * 100 - 100,
<<<<<<< HEAD
                close=50000.0 + i * 100 - 50,
            )

        adx = self.fast_adx.get_adx_value()
        is_strong = self.fast_adx.is_trend_strong()

=======
                close=50000.0 + i * 100 - 50
            )
        
        adx = self.fast_adx.get_adx_value()
        is_strong = self.fast_adx.is_trend_strong()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert isinstance(is_strong, bool)
        # Если ADX > threshold, тренд сильный
        assert is_strong == (adx > 20.0)

    def test_get_trend_direction(self):
        """Тест определения направления тренда"""
        # Добавляем свечи с растущим трендом
        for i in range(15):
            self.fast_adx.update(
                high=50000.0 + i * 50,
                low=50000.0 + i * 50 - 100,
<<<<<<< HEAD
                close=50000.0 + i * 50 - 50,
            )

        direction = self.fast_adx.get_trend_direction()

=======
                close=50000.0 + i * 50 - 50
            )
        
        direction = self.fast_adx.get_trend_direction()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert direction in ["bullish", "bearish", "neutral"]

    def test_get_di_plus(self):
        """Тест получения +DI"""
        # Добавляем свечи для расчета +DI
        for i in range(10):
            self.fast_adx.update(
                high=50000.0 + i * 10,
                low=50000.0 + i * 10 - 100,
<<<<<<< HEAD
                close=50000.0 + i * 10 - 50,
            )

        di_plus = self.fast_adx.get_di_plus()

=======
                close=50000.0 + i * 10 - 50
            )
        
        di_plus = self.fast_adx.get_di_plus()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert di_plus is not None
        assert di_plus >= 0

    def test_get_di_minus(self):
        """Тест получения -DI"""
        # Добавляем свечи для расчета -DI
        for i in range(10):
            self.fast_adx.update(
                high=50000.0 - i * 10 + 100,
                low=50000.0 - i * 10,
<<<<<<< HEAD
                close=50000.0 - i * 10 + 50,
            )

        di_minus = self.fast_adx.get_di_minus()

=======
                close=50000.0 - i * 10 + 50
            )
        
        di_minus = self.fast_adx.get_di_minus()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert di_minus is not None
        assert di_minus >= 0

    def test_edge_cases_flat_market(self):
        """Тест граничных случаев - боковой рынок"""
        # Добавляем свечи без четкого направления
        for i in range(15):
<<<<<<< HEAD
            self.fast_adx.update(high=50000.0 + 50, low=50000.0 - 50, close=50000.0)

        adx = self.fast_adx.get_adx_value()
        is_strong = self.fast_adx.is_trend_strong()

=======
            self.fast_adx.update(
                high=50000.0 + 50,
                low=50000.0 - 50,
                close=50000.0
            )
        
        adx = self.fast_adx.get_adx_value()
        is_strong = self.fast_adx.is_trend_strong()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # Боковой рынок должен давать низкий ADX
        assert is_strong is False or adx < 20.0

    def test_reset(self):
        """Тест сброса индикатора"""
        self.fast_adx.update(high=51000.0, low=49000.0, close=50000.0)
<<<<<<< HEAD

        self.fast_adx.reset()

=======
        
        self.fast_adx.reset()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert self.fast_adx.current_high == 0.0
        assert self.fast_adx.current_low == 0.0
        assert self.fast_adx.current_close == 0.0
        assert len(self.fast_adx.di_plus_history) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


