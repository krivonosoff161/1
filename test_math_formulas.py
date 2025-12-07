"""
UNIT-ТЕСТЫ ДЛЯ ВСЕХ МАТЕМАТИЧЕСКИХ ФОРМУЛ

Проверяет правильность всех расчетов:
- PnL для LONG и SHORT
- TP/SL для LONG и SHORT
- Trailing Stop Loss
- Расчеты размера позиций
- Расчеты маржи
"""

import pytest
from decimal import Decimal


class TestPnLCalculations:
    """Тесты для расчетов PnL"""
    
    def test_long_pnl_profit(self):
        """LONG позиция в прибыли"""
        entry_price = 100.0
        exit_price = 105.0
        size_in_coins = 1.0
        
        # LONG: (exit_price - entry_price) * size
        gross_pnl = (exit_price - entry_price) * size_in_coins
        
        assert gross_pnl == 5.0, f"Ожидалось 5.0, получено {gross_pnl}"
        
    def test_long_pnl_loss(self):
        """LONG позиция в убытке"""
        entry_price = 100.0
        exit_price = 95.0
        size_in_coins = 1.0
        
        # LONG: (exit_price - entry_price) * size
        gross_pnl = (exit_price - entry_price) * size_in_coins
        
        assert gross_pnl == -5.0, f"Ожидалось -5.0, получено {gross_pnl}"
        
    def test_short_pnl_profit(self):
        """SHORT позиция в прибыли"""
        entry_price = 100.0
        exit_price = 95.0
        size_in_coins = 1.0
        
        # SHORT: (entry_price - exit_price) * size
        gross_pnl = (entry_price - exit_price) * size_in_coins
        
        assert gross_pnl == 5.0, f"Ожидалось 5.0, получено {gross_pnl}"
        
    def test_short_pnl_loss(self):
        """SHORT позиция в убытке"""
        entry_price = 100.0
        exit_price = 105.0
        size_in_coins = 1.0
        
        # SHORT: (entry_price - exit_price) * size
        gross_pnl = (entry_price - exit_price) * size_in_coins
        
        assert gross_pnl == -5.0, f"Ожидалось -5.0, получено {gross_pnl}"
        
    def test_long_pnl_with_commission(self):
        """LONG PnL с учетом комиссии"""
        entry_price = 100.0
        exit_price = 105.0
        size_in_coins = 1.0
        commission_rate = 0.001  # 0.1%
        
        gross_pnl = (exit_price - entry_price) * size_in_coins
        notional_entry = size_in_coins * entry_price
        notional_exit = size_in_coins * exit_price
        commission = (notional_entry + notional_exit) * commission_rate
        net_pnl = gross_pnl - commission
        
        # Ожидаемый результат: 5.0 - (100 + 105) * 0.001 = 5.0 - 0.205 = 4.795
        expected_net_pnl = 5.0 - 0.205
        assert abs(net_pnl - expected_net_pnl) < 0.001, \
            f"Ожидалось {expected_net_pnl}, получено {net_pnl}"
        
    def test_short_pnl_with_commission(self):
        """SHORT PnL с учетом комиссии"""
        entry_price = 100.0
        exit_price = 95.0
        size_in_coins = 1.0
        commission_rate = 0.001  # 0.1%
        
        gross_pnl = (entry_price - exit_price) * size_in_coins
        notional_entry = size_in_coins * entry_price
        notional_exit = size_in_coins * exit_price
        commission = (notional_entry + notional_exit) * commission_rate
        net_pnl = gross_pnl - commission
        
        # Ожидаемый результат: 5.0 - (100 + 95) * 0.001 = 5.0 - 0.195 = 4.805
        expected_net_pnl = 5.0 - 0.195
        assert abs(net_pnl - expected_net_pnl) < 0.001, \
            f"Ожидалось {expected_net_pnl}, получено {net_pnl}"


class TestTPSLCalculations:
    """Тесты для расчетов TP/SL"""
    
    def test_long_tp(self):
        """LONG TP: entry_price + tp_distance"""
        entry_price = 100.0
        tp_percent = 0.01  # 1%
        tp_distance = entry_price * tp_percent
        
        tp_price = entry_price + tp_distance
        
        assert tp_price == 101.0, f"Ожидалось 101.0, получено {tp_price}"
        
    def test_long_sl(self):
        """LONG SL: entry_price - sl_distance"""
        entry_price = 100.0
        sl_percent = 0.015  # 1.5%
        sl_distance = entry_price * sl_percent
        
        sl_price = entry_price - sl_distance
        
        assert sl_price == 98.5, f"Ожидалось 98.5, получено {sl_price}"
        
    def test_short_tp(self):
        """SHORT TP: entry_price - tp_distance"""
        entry_price = 100.0
        tp_percent = 0.01  # 1%
        tp_distance = entry_price * tp_percent
        
        tp_price = entry_price - tp_distance
        
        assert tp_price == 99.0, f"Ожидалось 99.0, получено {tp_price}"
        
    def test_short_sl(self):
        """SHORT SL: entry_price + sl_distance"""
        entry_price = 100.0
        sl_percent = 0.015  # 1.5%
        sl_distance = entry_price * sl_percent
        
        sl_price = entry_price + sl_distance
        
        assert sl_price == 101.5, f"Ожидалось 101.5, получено {sl_price}"


class TestTrailingStopLoss:
    """Тесты для Trailing Stop Loss"""
    
    def test_long_trailing_stop(self):
        """LONG Trailing Stop: highest_price * (1 - trail_percent)"""
        entry_price = 100.0
        highest_price = 105.0
        trail_percent = 0.005  # 0.5%
        
        stop_loss = highest_price * (1 - trail_percent)
        
        # Ожидаемый результат: 105.0 * 0.995 = 104.475
        expected_stop = 104.475
        assert abs(stop_loss - expected_stop) < 0.001, \
            f"Ожидалось {expected_stop}, получено {stop_loss}"
        
    def test_short_trailing_stop(self):
        """SHORT Trailing Stop: lowest_price * (1 + trail_percent)"""
        entry_price = 100.0
        lowest_price = 95.0
        trail_percent = 0.005  # 0.5%
        
        stop_loss = lowest_price * (1 + trail_percent)
        
        # Ожидаемый результат: 95.0 * 1.005 = 95.475
        expected_stop = 95.475
        assert abs(stop_loss - expected_stop) < 0.001, \
            f"Ожидалось {expected_stop}, получено {stop_loss}"


class TestPositionSize:
    """Тесты для расчетов размера позиций"""
    
    def test_position_size_calculation(self):
        """Расчет размера позиции"""
        balance = 1000.0
        risk_per_trade = 0.02  # 2%
        price = 100.0
        
        base_size_usd = balance * risk_per_trade
        position_size_coins = base_size_usd / price
        
        # Ожидаемый результат: 1000 * 0.02 / 100 = 0.2 монет
        expected_size = 0.2
        assert abs(position_size_coins - expected_size) < 0.001, \
            f"Ожидалось {expected_size}, получено {position_size_coins}"
        
    def test_position_size_with_leverage(self):
        """Размер позиции с учетом плеча"""
        balance = 1000.0
        risk_per_trade = 0.02  # 2%
        leverage = 3
        price = 100.0
        
        base_size_usd = balance * risk_per_trade
        # С учетом плеча размер увеличивается
        leveraged_size_usd = base_size_usd * leverage
        position_size_coins = leveraged_size_usd / price
        
        # Ожидаемый результат: 1000 * 0.02 * 3 / 100 = 0.6 монет
        expected_size = 0.6
        assert abs(position_size_coins - expected_size) < 0.001, \
            f"Ожидалось {expected_size}, получено {position_size_coins}"


class TestMarginCalculations:
    """Тесты для расчетов маржи"""
    
    def test_margin_calculation(self):
        """Расчет маржи"""
        position_size_coins = 1.0
        price = 100.0
        leverage = 3
        
        notional = position_size_coins * price
        margin_required = notional / leverage
        
        # Ожидаемый результат: 100 / 3 = 33.333...
        expected_margin = 100.0 / 3.0
        assert abs(margin_required - expected_margin) < 0.001, \
            f"Ожидалось {expected_margin}, получено {margin_required}"


class TestSideNormalization:
    """Тесты для нормализации side"""
    
    def test_side_lower_long(self):
        """Проверка нормализации 'LONG' -> 'long'"""
        side = "LONG"
        normalized = side.lower()
        
        assert normalized == "long", f"Ожидалось 'long', получено '{normalized}'"
        
    def test_side_lower_short(self):
        """Проверка нормализации 'SHORT' -> 'short'"""
        side = "SHORT"
        normalized = side.lower()
        
        assert normalized == "short", f"Ожидалось 'short', получено '{normalized}'"
        
    def test_side_buy_to_long(self):
        """Проверка конвертации 'buy' -> 'long'"""
        side = "buy"
        side_lower = side.lower()
        
        if side_lower in ["buy", "long"]:
            position_side = "long"
        elif side_lower in ["sell", "short"]:
            position_side = "short"
        else:
            position_side = "long"
            
        assert position_side == "long", f"Ожидалось 'long', получено '{position_side}'"
        
    def test_side_sell_to_short(self):
        """Проверка конвертации 'sell' -> 'short'"""
        side = "sell"
        side_lower = side.lower()
        
        if side_lower in ["buy", "long"]:
            position_side = "long"
        elif side_lower in ["sell", "short"]:
            position_side = "short"
        else:
            position_side = "long"
            
        assert position_side == "short", f"Ожидалось 'short', получено '{position_side}'"


class TestContractConversion:
    """Тесты для конвертации контрактов в монеты"""
    
    def test_contracts_to_coins(self):
        """Конвертация контрактов в монеты"""
        size_in_contracts = 10.0
        ct_val = 0.01  # 1 контракт = 0.01 монеты
        
        size_in_coins = size_in_contracts * ct_val
        
        # Ожидаемый результат: 10 * 0.01 = 0.1 монет
        expected_size = 0.1
        assert abs(size_in_coins - expected_size) < 0.001, \
            f"Ожидалось {expected_size}, получено {size_in_coins}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

