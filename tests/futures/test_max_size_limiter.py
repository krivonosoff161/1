"""
Тесты для MaxSizeLimiter модуля.
"""

import pytest

<<<<<<< HEAD
from src.strategies.scalping.futures.risk.max_size_limiter import \
    MaxSizeLimiter
=======
from src.strategies.scalping.futures.risk.max_size_limiter import MaxSizeLimiter
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866


class TestMaxSizeLimiter:
    """Тесты для MaxSizeLimiter"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.limiter = MaxSizeLimiter(
<<<<<<< HEAD
            max_single_size_usd=1000.0, max_total_size_usd=5000.0, max_positions=5
=======
            max_single_size_usd=1000.0,
            max_total_size_usd=5000.0,
            max_positions=5
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        )

    def test_initialization(self):
        """Тест инициализации"""
        assert self.limiter.max_single_size_usd == 1000.0
        assert self.limiter.max_total_size_usd == 5000.0
        assert self.limiter.max_positions == 5
        assert len(self.limiter.position_sizes) == 0

    def test_can_open_position_valid(self):
        """Тест проверки открытия валидной позиции"""
        can_open, reason = self.limiter.can_open_position("BTC-USDT", 500.0)
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert can_open is True
        assert "Можно открыть" in reason

    def test_can_open_position_too_large(self):
        """Тест проверки слишком большой позиции"""
        can_open, reason = self.limiter.can_open_position("BTC-USDT", 1500.0)
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert can_open is False
        assert "превышает лимит" in reason

    def test_can_open_position_max_positions(self):
        """Тест проверки превышения количества позиций"""
        # Открываем максимальное количество позиций
        for i in range(5):
            self.limiter.add_position(f"SYMBOL{i}", 100.0)
<<<<<<< HEAD

        can_open, reason = self.limiter.can_open_position("BTC-USDT", 500.0)

=======
        
        can_open, reason = self.limiter.can_open_position("BTC-USDT", 500.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert can_open is False
        assert "лимит" in reason

    def test_can_open_position_max_total_size(self):
        """Тест превышения общего размера позиций"""
        # Открываем позиции почти до лимита
        self.limiter.add_position("BTC-USDT", 4500.0)
<<<<<<< HEAD

        can_open, reason = self.limiter.can_open_position("ETH-USDT", 600.0)

=======
        
        can_open, reason = self.limiter.can_open_position("ETH-USDT", 600.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert can_open is False
        assert "превышает" in reason

    def test_can_open_position_duplicate_symbol(self):
        """Тест проверки дублирующей позиции"""
        self.limiter.add_position("BTC-USDT", 500.0)
<<<<<<< HEAD

        can_open, reason = self.limiter.can_open_position("BTC-USDT", 300.0)

=======
        
        can_open, reason = self.limiter.can_open_position("BTC-USDT", 300.0)
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert can_open is False
        assert "уже открыта" in reason

    def test_add_position(self):
        """Тест добавления позиции"""
        self.limiter.add_position("BTC-USDT", 500.0)
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert "BTC-USDT" in self.limiter.position_sizes
        assert self.limiter.position_sizes["BTC-USDT"] == 500.0

    def test_remove_position(self):
        """Тест удаления позиции"""
        self.limiter.add_position("BTC-USDT", 500.0)
<<<<<<< HEAD

        self.limiter.remove_position("BTC-USDT")

=======
        
        self.limiter.remove_position("BTC-USDT")
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert "BTC-USDT" not in self.limiter.position_sizes

    def test_get_total_size(self):
        """Тест получения общего размера"""
        self.limiter.add_position("BTC-USDT", 1000.0)
        self.limiter.add_position("ETH-USDT", 500.0)
<<<<<<< HEAD

        total = self.limiter.get_total_size()

=======
        
        total = self.limiter.get_total_size()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert total == 1500.0

    def test_get_available_size(self):
        """Тест получения доступного размера"""
        self.limiter.add_position("BTC-USDT", 2000.0)
<<<<<<< HEAD

        available = self.limiter.get_available_size()

=======
        
        available = self.limiter.get_available_size()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert available == 3000.0  # 5000.0 - 2000.0

    def test_get_position_count(self):
        """Тест получения количества позиций"""
        self.limiter.add_position("BTC-USDT", 500.0)
        self.limiter.add_position("ETH-USDT", 300.0)
<<<<<<< HEAD

        count = self.limiter.get_position_count()

=======
        
        count = self.limiter.get_position_count()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert count == 2

    def test_reset(self):
        """Тест сброса лимитера"""
        self.limiter.add_position("BTC-USDT", 500.0)
<<<<<<< HEAD

        self.limiter.reset()

=======
        
        self.limiter.reset()
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert len(self.limiter.position_sizes) == 0

    def test_multiple_positions(self):
        """Тест нескольких позиций"""
        symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
        sizes = [500.0, 300.0, 200.0]
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        for symbol, size in zip(symbols, sizes):
            can_open, _ = self.limiter.can_open_position(symbol, size)
            if can_open:
                self.limiter.add_position(symbol, size)
<<<<<<< HEAD

=======
        
>>>>>>> 815de750043a85ff7eea3870ec2571987b582866
        assert len(self.limiter.position_sizes) == 3
        assert self.limiter.get_total_size() == 1000.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


