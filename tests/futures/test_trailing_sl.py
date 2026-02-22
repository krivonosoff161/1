"""
Тесты для TrailingStopLoss модуля.
"""

import pytest

from src.strategies.scalping.futures.indicators.trailing_stop_loss import (
    TrailingStopLoss,
)


class TestTrailingStopLoss:
    """Тесты для TrailingStopLoss"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.trailing_sl = TrailingStopLoss(
            initial_trail=0.05, max_trail=0.2, min_trail=0.02  # 0.05%  # 0.2%  # 0.02%
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

        assert self.trailing_sl.entry_price == 50000.0
        assert self.trailing_sl.side == "long"
        assert self.trailing_sl.highest_price == 50000.0

    def test_initialize_short(self):
        """Тест инициализации для шорта"""
        self.trailing_sl.initialize(entry_price=50000.0, side="short")

        assert self.trailing_sl.entry_price == 50000.0
        assert self.trailing_sl.side == "short"
        assert self.trailing_sl.lowest_price == 50000.0

    def test_update_long_profitable(self):
        """Тест обновления для прибыльного лонга"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")

        # Цена выросла
        new_stop = self.trailing_sl.update(current_price=51000.0)

        assert self.trailing_sl.highest_price == 51000.0
        assert new_stop is not None
        assert new_stop > 0

    def test_update_short_profitable(self):
        """Тест обновления для прибыльного шорта"""
        self.trailing_sl.initialize(entry_price=50000.0, side="short")

        # Цена упала
        new_stop = self.trailing_sl.update(current_price=49000.0)

        assert self.trailing_sl.lowest_price == 49000.0
        assert new_stop is not None
        assert new_stop > 0

    def test_get_stop_loss_long(self):
        """Тест получения стоп-лосса для лонга"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")

        stop_loss = self.trailing_sl.get_stop_loss()

        # Для лонга стоп ниже цены входа
        assert stop_loss < 50000.0
        expected = 50000.0 * (1 - 0.05)  # initial_trail
        assert abs(stop_loss - expected) < 1.0

    def test_get_stop_loss_short(self):
        """Тест получения стоп-лосса для шорта"""
        self.trailing_sl.initialize(entry_price=50000.0, side="short")

        stop_loss = self.trailing_sl.get_stop_loss()

        # Для шорта стоп выше цены входа
        assert stop_loss > 50000.0
        expected = 50000.0 * (1 + 0.05)  # initial_trail
        assert abs(stop_loss - expected) < 1.0

    def test_get_profit_pct_long(self):
        """Тест расчета прибыли для лонга"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")

        profit = self.trailing_sl.get_profit_pct(current_price=51000.0)

        expected = (51000.0 - 50000.0) / 50000.0
        assert abs(profit - expected) < 0.0001
        assert profit == 0.02  # 2%

    def test_get_profit_pct_short(self):
        """Тест расчета прибыли для шорта"""
        self.trailing_sl.initialize(entry_price=50000.0, side="short")

        profit = self.trailing_sl.get_profit_pct(current_price=49000.0)

        expected = (50000.0 - 49000.0) / 50000.0
        assert abs(profit - expected) < 0.0001
        assert profit == 0.02  # 2%

    def test_should_close_position_long(self):
        """Тест проверки закрытия позиции для лонга"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")

        # Цена упала ниже стоп-лосса
        should_close, reason = self.trailing_sl.should_close_position(
            current_price=47400.0
        )

        assert should_close is True
        assert reason == "trail_hit_loss"

    def test_should_close_position_short(self):
        """Тест проверки закрытия позиции для шорта"""
        self.trailing_sl.initialize(entry_price=50000.0, side="short")

        # Цена поднялась выше стоп-лосса
        should_close, reason = self.trailing_sl.should_close_position(
            current_price=52600.0
        )

        assert should_close is True
        assert reason == "trail_hit_loss"

    def test_distance_to_stop_pct(self):
        """Тест расчета расстояния до стоп-лосса"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")

        distance = self.trailing_sl.get_distance_to_stop_pct(current_price=50000.0)

        assert distance > 0
        assert distance < 1.0  # В процентах

    def test_reset(self):
        """Тест сброса трейлинг стопа"""
        self.trailing_sl.initialize(entry_price=50000.0, side="long")

        self.trailing_sl.reset()

        assert self.trailing_sl.highest_price == 0.0
        assert self.trailing_sl.lowest_price == float("inf")
        assert self.trailing_sl.entry_price == 0.0
        assert self.trailing_sl.side is None


class TestTrailingStopLossBreakeven:
    """Тесты для BREAKEVEN функциональности"""

    def test_breakeven_initialization(self):
        """Тест инициализации с breakeven_trigger"""
        tsl = TrailingStopLoss(
            initial_trail=0.05,
            max_trail=0.2,
            min_trail=0.02,
            breakeven_trigger=0.008,  # 0.8%
        )
        assert tsl.breakeven_trigger == 0.008
        assert tsl.breakeven_activated is False
        assert tsl.breakeven_price is None

    def test_breakeven_not_activated_below_threshold_long(self):
        """Тест: breakeven НЕ активируется если прибыль ниже порога (LONG)"""
        tsl = TrailingStopLoss(
            initial_trail=0.05,
            max_trail=0.2,
            min_trail=0.02,
            breakeven_trigger=0.008,  # 0.8%
            trading_fee_rate=0.0005,
        )
        tsl.initialize(entry_price=50000.0, side="long")

        # Прибыль 0.5% (меньше 0.8%) - цена 50250
        tsl.update(current_price=50250.0)

        assert tsl.breakeven_activated is False
        assert tsl.breakeven_price is None

    def test_breakeven_activated_above_threshold_long(self):
        """Тест: breakeven активируется если прибыль выше порога (LONG)"""
        tsl = TrailingStopLoss(
            initial_trail=0.05,
            max_trail=0.2,
            min_trail=0.02,
            breakeven_trigger=0.008,  # 0.8%
            trading_fee_rate=0.0005,
        )
        tsl.initialize(entry_price=50000.0, side="long")

        # Прибыль 1.0% (больше 0.8%) - цена 50500
        tsl.update(current_price=50500.0)

        assert tsl.breakeven_activated is True
        # fee_buffer = trading_fee_rate * 2 = 0.0005 * 2 = 0.001, но после legacy конвертации
        # maker_fee_rate = 0.0005 / 2 = 0.00025, так что fee_buffer = 0.00025 * 2 = 0.0005
        # breakeven_price = entry * (1 + fee_buffer) = 50000 * (1 + 0.0005) = 50025
        expected_breakeven = 50000.0 * (1 + 0.0005)
        assert tsl.breakeven_price == pytest.approx(expected_breakeven, rel=1e-4)

    def test_breakeven_stop_loss_floor_long(self):
        """Тест: стоп-лосс не опускается ниже breakeven после активации (LONG)"""
        tsl = TrailingStopLoss(
            initial_trail=0.05,  # 5% trail
            max_trail=0.2,
            min_trail=0.02,
            breakeven_trigger=0.008,
            trading_fee_rate=0.0005,
        )
        tsl.initialize(entry_price=50000.0, side="long")

        # Прибыль 1.0% - активируем breakeven
        tsl.update(current_price=50500.0)
        assert tsl.breakeven_activated is True

        # Получаем стоп-лосс
        stop_loss = tsl.get_stop_loss()

        # Стоп должен быть НЕ НИЖЕ breakeven_price
        assert stop_loss >= tsl.breakeven_price

    def test_breakeven_activated_above_threshold_short(self):
        """Тест: breakeven активируется если прибыль выше порога (SHORT)"""
        tsl = TrailingStopLoss(
            initial_trail=0.05,
            max_trail=0.2,
            min_trail=0.02,
            breakeven_trigger=0.008,  # 0.8%
            trading_fee_rate=0.0005,
        )
        tsl.initialize(entry_price=50000.0, side="short")

        # Прибыль 1.0% (больше 0.8%) - цена упала до 49500
        tsl.update(current_price=49500.0)

        assert tsl.breakeven_activated is True
        # fee_buffer = trading_fee_rate * 2 = 0.0005 * 2 = 0.001, но после legacy конвертации
        # maker_fee_rate = 0.0005 / 2 = 0.00025, так что fee_buffer = 0.00025 * 2 = 0.0005
        # breakeven_price = entry * (1 - fee_buffer) = 50000 * (1 - 0.0005) = 49975
        expected_breakeven = 50000.0 * (1 - 0.0005)
        assert tsl.breakeven_price == pytest.approx(expected_breakeven, rel=1e-4)

    def test_breakeven_stop_loss_ceiling_short(self):
        """Тест: стоп-лосс не поднимается выше breakeven после активации (SHORT)"""
        tsl = TrailingStopLoss(
            initial_trail=0.05,  # 5% trail
            max_trail=0.2,
            min_trail=0.02,
            breakeven_trigger=0.008,
            trading_fee_rate=0.0005,
        )
        tsl.initialize(entry_price=50000.0, side="short")

        # Прибыль 1.0% - активируем breakeven
        tsl.update(current_price=49500.0)
        assert tsl.breakeven_activated is True

        # Получаем стоп-лосс
        stop_loss = tsl.get_stop_loss()

        # Стоп должен быть НЕ ВЫШЕ breakeven_price
        assert stop_loss <= tsl.breakeven_price

    def test_breakeven_reset_on_initialize(self):
        """Тест: breakeven сбрасывается при инициализации новой позиции"""
        tsl = TrailingStopLoss(
            initial_trail=0.05,
            max_trail=0.2,
            min_trail=0.02,
            breakeven_trigger=0.008,
            trading_fee_rate=0.0005,
        )
        tsl.initialize(entry_price=50000.0, side="long")
        tsl.update(current_price=50500.0)
        assert tsl.breakeven_activated is True

        # Новая позиция
        tsl.initialize(entry_price=60000.0, side="long")

        assert tsl.breakeven_activated is False
        assert tsl.breakeven_price is None

    def test_breakeven_reset_on_reset(self):
        """Тест: breakeven сбрасывается при вызове reset()"""
        tsl = TrailingStopLoss(
            initial_trail=0.05,
            max_trail=0.2,
            min_trail=0.02,
            breakeven_trigger=0.008,
            trading_fee_rate=0.0005,
        )
        tsl.initialize(entry_price=50000.0, side="long")
        tsl.update(current_price=50500.0)
        assert tsl.breakeven_activated is True

        # Сброс
        tsl.reset()

        assert tsl.breakeven_activated is False
        assert tsl.breakeven_price is None

    def test_breakeven_disabled_when_none(self):
        """Тест: breakeven отключен когда breakeven_trigger=None"""
        tsl = TrailingStopLoss(
            initial_trail=0.05,
            max_trail=0.2,
            min_trail=0.02,
            breakeven_trigger=None,  # Отключен
            trading_fee_rate=0.0005,
        )
        tsl.initialize(entry_price=50000.0, side="long")
        tsl.update(current_price=51000.0)  # 2% прибыли

        assert tsl.breakeven_activated is False
        assert tsl.breakeven_price is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
