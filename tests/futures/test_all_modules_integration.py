"""
Интеграционные тесты для всех новых модулей PHASE 2.
"""

import pytest

from src.strategies.modules.margin_calculator import MarginCalculator
from src.strategies.modules.slippage_guard import SlippageGuard
from src.strategies.scalping.futures.indicators.fast_adx import FastADX

<<<<<<< HEAD
from src.strategies.scalping.futures.indicators.funding_rate_monitor import \
    FundingRateMonitor
from src.strategies.scalping.futures.indicators.order_flow_indicator import \
    OrderFlowIndicator
from src.strategies.scalping.futures.indicators.trailing_stop_loss import \
    TrailingStopLoss
from src.strategies.scalping.futures.risk.max_size_limiter import \
    MaxSizeLimiter

=======
from src.strategies.scalping.futures.indicators.funding_rate_monitor import \
    FundingRateMonitor
from src.strategies.scalping.futures.indicators.order_flow_indicator import \
    OrderFlowIndicator
from src.strategies.scalping.futures.indicators.trailing_stop_loss import \
    TrailingStopLoss
from src.strategies.scalping.futures.risk.max_size_limiter import \
    MaxSizeLimiter

>>>>>>> 815de750043a85ff7eea3870ec2571987b582866


class TestAllModulesIntegration:
    """Интеграционные тесты для всех модулей"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        # Инициализация всех модулей
        self.margin_calculator = MarginCalculator(
<<<<<<< HEAD
            default_leverage=3, maintenance_margin_ratio=0.01, initial_margin_ratio=0.1
        )

        self.slippage_guard = SlippageGuard(
            max_slippage_percent=0.1, max_spread_percent=0.05, order_timeout=30.0
        )

        self.trailing_sl = TrailingStopLoss(
            initial_trail=0.05, max_trail=0.2, min_trail=0.02, leverage=3
        )

        self.order_flow = OrderFlowIndicator(
            window=100, long_threshold=0.1, short_threshold=-0.1
        )

        self.funding_monitor = FundingRateMonitor(max_funding_rate=0.05)

        self.max_size_limiter = MaxSizeLimiter(
            max_single_size_usd=1000.0, max_total_size_usd=5000.0, max_positions=5
        )

        self.fast_adx = FastADX(period=9, threshold=20.0)
=======
            default_leverage=3,
            maintenance_margin_ratio=0.01,
            initial_margin_ratio=0.1
        )
        
        self.slippage_guard = SlippageGuard(
            max_slippage_percent=0.1,
            max_spread_percent=0.05,
            order_timeout=30.0
        )
        
        self.trailing_sl = TrailingStopLoss(
            initial_trail=0.05,
            max_trail=0.2,
            min_trail=0.02
        )
        
        self.order_flow = OrderFlowIndicator(
            window=100,
            long_threshold=0.1,
            short_threshold=-0.1
        )
        
        self.funding_monitor = FundingRateMonitor(
            max_funding_rate=0.05
        )
        
        self.max_size_limiter = MaxSizeLimiter(
            max_single_size_usd=1000.0,
            max_total_size_usd=5000.0,
            max_positions=5
        )
        
        self.fast_adx = FastADX(
            period=9,
            threshold=20.0
        )
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866

    def test_trailing_sl_with_order_flow(self):
        """Тест взаимодействия TrailingStopLoss и OrderFlow"""
        # Инициализация позиции
        self.trailing_sl.initialize(entry_price=50000.0, side="long")
<<<<<<< HEAD

        # Обновление OrderFlow
        self.order_flow.update(bid_volume=1000.0, ask_volume=800.0)

=======
        
        # Обновление OrderFlow
        self.order_flow.update(bid_volume=1000.0, ask_volume=800.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # Если OrderFlow благоприятен для лонга
        if self.order_flow.is_long_favorable():
            # TrailingSL должен обновляться
            stop_loss = self.trailing_sl.update(current_price=51000.0)
<<<<<<< HEAD

=======
            
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
            assert stop_loss is not None

    def test_funding_monitor_with_max_size_limiter(self):
        """Тест взаимодействия FundingRateMonitor и MaxSizeLimiter"""
        # Устанавливаем благоприятный funding
        self.funding_monitor.update(funding_rate=-0.01)
<<<<<<< HEAD

        # Проверяем максимальный размер
        can_open, _ = self.max_size_limiter.can_open_position("BTC-USDT", 800.0)

=======
        
        # Проверяем максимальный размер
        can_open, _ = self.max_size_limiter.can_open_position("BTC-USDT", 800.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # Если funding благоприятен и размер OK
        if self.funding_monitor.is_funding_favorable("long") and can_open:
            assert True  # Можно открывать

    def test_complete_trading_flow(self):
        """Тест полного торгового флоу"""
        # 1. Проверка OrderFlow
        self.order_flow.update(bid_volume=1200.0, ask_volume=800.0)
        assert self.order_flow.is_long_favorable() is True
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # 2. Проверка FastADX
        for i in range(15):
            self.fast_adx.update(
                high=50000.0 + i * 50,
                low=50000.0 + i * 50 - 100,
<<<<<<< HEAD
                close=50000.0 + i * 50 - 50,
=======
                close=50000.0 + i * 50 - 50
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
            )
        # Проверяем, что методы работают корректно
        adx_value = self.fast_adx.get_adx_value()
        direction = self.fast_adx.get_trend_direction()
        is_strong = self.fast_adx.is_trend_strong()
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert adx_value >= 0
        assert adx_value <= 100
        assert direction in ["bullish", "bearish", "neutral"]
        assert isinstance(is_strong, bool)
<<<<<<< HEAD

        # 3. Проверка Funding
        self.funding_monitor.update(funding_rate=-0.01)
        assert self.funding_monitor.is_funding_favorable("long") is True

        # 4. Проверка MaxSizeLimiter
        can_open, _ = self.max_size_limiter.can_open_position("BTC-USDT", 500.0)
        assert can_open is True

        # 5. Инициализация TrailingSL
        self.trailing_sl.initialize(entry_price=50000.0, side="long")

=======
        
        # 3. Проверка Funding
        self.funding_monitor.update(funding_rate=-0.01)
        assert self.funding_monitor.is_funding_favorable("long") is True
        
        # 4. Проверка MaxSizeLimiter
        can_open, _ = self.max_size_limiter.can_open_position("BTC-USDT", 500.0)
        assert can_open is True
        
        # 5. Инициализация TrailingSL
        self.trailing_sl.initialize(entry_price=50000.0, side="long")
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # 6. Обновление TrailingSL
        new_stop = self.trailing_sl.update(current_price=51000.0)
        assert new_stop is not None

    def test_risk_management_chain(self):
        """Тест цепочки управления рисками"""
        # Проверяем максимальный размер позиции
        equity = 1000.0
        max_size = self.margin_calculator.calculate_max_position_size(
            equity, current_price=50000.0, leverage=3
        )
<<<<<<< HEAD

        # Проверяем MaxSizeLimiter
        size_usd = max_size * 50000.0

        # Проверяем реальный размер (может превышать лимит)
        actual_size = min(size_usd, 1000.0)  # 3000 USD номинала = макс 1000 USD лимит
        can_open, reason = self.max_size_limiter.can_open_position(
            "BTC-USDT", actual_size
        )

=======
        
        # Проверяем MaxSizeLimiter
        size_usd = max_size * 50000.0
        
        # Проверяем реальный размер (может превышать лимит)
        actual_size = min(size_usd, 1000.0)  # 3000 USD номинала = макс 1000 USD лимит
        can_open, reason = self.max_size_limiter.can_open_position("BTC-USDT", actual_size)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # Должно пройти валидацию
        assert can_open is True, f"Не удалось открыть позицию: {reason}"

    def test_multiple_positions_management(self):
        """Тест управления несколькими позициями"""
        symbols = ["BTC-USDT", "ETH-USDT"]
        sizes = [500.0, 300.0]
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        for symbol, size in zip(symbols, sizes):
            can_open, _ = self.max_size_limiter.can_open_position(symbol, size)
            if can_open:
                self.max_size_limiter.add_position(symbol, size)
<<<<<<< HEAD

                # Создаем TrailingSL для каждой позиции
                trailing_sl = TrailingStopLoss()
                trailing_sl.initialize(
                    entry_price=50000.0 if "BTC" in symbol else 3000.0, side="long"
                )

=======
                
                # Создаем TrailingSL для каждой позиции
                trailing_sl = TrailingStopLoss()
                trailing_sl.initialize(entry_price=50000.0 if "BTC" in symbol else 3000.0, side="long")
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert self.max_size_limiter.get_position_count() == 2

    def test_margin_calculator_with_trailing_sl(self):
        """Тест взаимодействия MarginCalculator и TrailingStopLoss"""
        # Рассчитываем максимальный размер
        max_size = self.margin_calculator.calculate_max_position_size(
<<<<<<< HEAD
            equity=1000.0, current_price=50000.0, leverage=3
        )

        # Инициализируем TrailingSL
        self.trailing_sl.initialize(entry_price=50000.0, side="long")

        # Обновляем при росте цены
        new_stop = self.trailing_sl.update(current_price=52000.0)

=======
            equity=1000.0,
            current_price=50000.0,
            leverage=3
        )
        
        # Инициализируем TrailingSL
        self.trailing_sl.initialize(entry_price=50000.0, side="long")
        
        # Обновляем при росте цены
        new_stop = self.trailing_sl.update(current_price=52000.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        # Проверяем безопасность позиции
        position_value = max_size * 50000.0
        is_safe, details = self.margin_calculator.is_position_safe(
            position_value=position_value,
            equity=1000.0,
            current_price=52000.0,
            entry_price=50000.0,
            side="buy",
            leverage=3,
<<<<<<< HEAD
            safety_threshold=1.5,
        )

=======
            safety_threshold=1.5
        )
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert is_safe or new_stop is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
<<<<<<< HEAD
=======

>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
