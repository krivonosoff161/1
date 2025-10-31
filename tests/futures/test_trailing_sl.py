"""
Тесты для TrailingStopLoss модуля.
"""

import pytest

<<<<<<< HEAD
from src.strategies.scalping.futures.indicators.trailing_stop_loss import \
    TrailingStopLoss

=======
from src.strategies.scalping.futures.indicators.trailing_stop_loss import \
    TrailingStopLoss

>>>>>>> 815de750043a85ff7eea3870ec2571987b582866


class TestTrailingStopLoss:
    """Тесты для TrailingStopLoss"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.trailing_sl = TrailingStopLoss(
<<<<<<< HEAD
            initial_trail=0.05, max_trail=0.2, min_trail=0.02  # 0.05%  # 0.2%  # 0.02%
=======
            initial_trail=0.05,  # 0.05%
            max_trail=0.2,  # 0.2%
            min_trail=0.02  # 0.02%
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        )

    def test_initialization(self):
        """Тест инициализации"""
        assert self.trailing_sl.initial_trail == 0.05
        assert self.trailing_sl.max_trail == 0.2
        assert self.trailing_sl.min_trail == 0.02
        assert self.trailing_sl.current_trail == 0.05

    def test_initialize_long(self):
        """Тест инициализации для лонга"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert self.trailing_sl.entry_price == 50000.0
        assert self.trailing_sl.side == "long"
        assert self.trailing_sl.highest_price == 50000.0

    def test_initialize_short(self):
        """Тест инициализации для шорта"""
        self.trailing_sl.initialize(entry_price=50000.0, side="short")
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert self.trailing_sl.entry_price == 50000.0
        assert self.trailing_sl.side == "short"
        assert self.trailing_sl.lowest_price == 50000.0

    def test_update_long_profitable(self):
        """Тест обновления для прибыльного лонга"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")
<<<<<<< HEAD

        # Цена выросла
        new_stop = self.trailing_sl.update(current_price=51000.0)

=======
        
        # Цена выросла
        new_stop = self.trailing_sl.update(current_price=51000.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert self.trailing_sl.highest_price == 51000.0
        assert new_stop is not None
        assert new_stop > 0

    def test_update_short_profitable(self):
        """Тест обновления для прибыльного шорта"""
        self.trailing_sl.initialize(entry_price=50000.0, side="short")
<<<<<<< HEAD

        # Цена упала
        new_stop = self.trailing_sl.update(current_price=49000.0)

=======
        
        # Цена упала
        new_stop = self.trailing_sl.update(current_price=49000.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert self.trailing_sl.lowest_price == 49000.0
        assert new_stop is not None
        assert new_stop > 0

    def test_get_stop_loss_long(self):
        """Тест получения стоп-лосса для лонга"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")
<<<<<<< HEAD

        stop_loss = self.trailing_sl.get_stop_loss()

=======
        
        stop_loss = self.trailing_sl.get_stop_loss()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # Для лонга стоп ниже цены входа
        assert stop_loss < 50000.0
        expected = 50000.0 * (1 - 0.05)  # initial_trail
        assert abs(stop_loss - expected) < 1.0

    def test_get_stop_loss_short(self):
        """Тест получения стоп-лосса для шорта"""
        self.trailing_sl.initialize(entry_price=50000.0, side="short")
<<<<<<< HEAD

        stop_loss = self.trailing_sl.get_stop_loss()

=======
        
        stop_loss = self.trailing_sl.get_stop_loss()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # Для шорта стоп выше цены входа
        assert stop_loss > 50000.0
        expected = 50000.0 * (1 + 0.05)  # initial_trail
        assert abs(stop_loss - expected) < 1.0

    def test_get_profit_pct_long(self):
        """Тест расчета прибыли для лонга"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")
<<<<<<< HEAD

        profit = self.trailing_sl.get_profit_pct(current_price=51000.0)

=======
        
        profit = self.trailing_sl.get_profit_pct(current_price=51000.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        expected = (51000.0 - 50000.0) / 50000.0
        assert abs(profit - expected) < 0.0001
        assert profit == 0.02  # 2%

    def test_get_profit_pct_short(self):
        """Тест расчета прибыли для шорта"""
        self.trailing_sl.initialize(entry_price=50000.0, side="short")
<<<<<<< HEAD

        profit = self.trailing_sl.get_profit_pct(current_price=49000.0)

=======
        
        profit = self.trailing_sl.get_profit_pct(current_price=49000.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        expected = (50000.0 - 49000.0) / 50000.0
        assert abs(profit - expected) < 0.0001
        assert profit == 0.02  # 2%

    def test_should_close_position_long(self):
        """Тест проверки закрытия позиции для лонга"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")
<<<<<<< HEAD

        # Цена упала ниже стоп-лосса
        should_close = self.trailing_sl.should_close_position(current_price=47400.0)

=======
        
        # Цена упала ниже стоп-лосса
        should_close = self.trailing_sl.should_close_position(current_price=47400.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert should_close is True

    def test_should_close_position_short(self):
        """Тест проверки закрытия позиции для шорта"""
        self.trailing_sl.initialize(entry_price=50000.0, side="short")
<<<<<<< HEAD

        # Цена поднялась выше стоп-лосса
        should_close = self.trailing_sl.should_close_position(current_price=52600.0)

=======
        
        # Цена поднялась выше стоп-лосса
        should_close = self.trailing_sl.should_close_position(current_price=52600.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert should_close is True

    def test_distance_to_stop_pct(self):
        """Тест расчета расстояния до стоп-лосса"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")
<<<<<<< HEAD

        distance = self.trailing_sl.get_distance_to_stop_pct(current_price=50000.0)

=======
        
        distance = self.trailing_sl.get_distance_to_stop_pct(current_price=50000.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert distance > 0
        assert distance < 1.0  # В процентах

    def test_reset(self):
        """Тест сброса трейлинг стопа"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")
<<<<<<< HEAD

        self.trailing_sl.reset()

=======
        
        self.trailing_sl.reset()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert self.trailing_sl.highest_price == 0.0
        assert self.trailing_sl.lowest_price == float("inf")
        assert self.trailing_sl.entry_price == 0.0
        assert self.trailing_sl.side is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


