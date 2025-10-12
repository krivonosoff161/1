"""
Unit tests for Volatility Adapter module
"""

import pytest
from src.strategies.modules.volatility_adapter import (
    VolatilityAdapter,
    VolatilityModeConfig,
    VolatilityParameters,
    VolatilityRegime,
)


class TestVolatilityModeConfig:
    """Тесты конфигурации режимов волатильности"""

    def test_default_config(self):
        """Тест конфигурации по умолчанию"""
        config = VolatilityModeConfig()
        assert config.enabled is True
        assert config.low_volatility_threshold == 0.01
        assert config.high_volatility_threshold == 0.02
        assert config.low_vol_score_threshold == 6
        assert config.normal_vol_score_threshold == 7
        assert config.high_vol_score_threshold == 8


class TestVolatilityAdapter:
    """Тесты адаптера волатильности"""

    @pytest.fixture
    def adapter(self):
        """Адаптер с настройками по умолчанию"""
        config = VolatilityModeConfig()
        return VolatilityAdapter(config)

    def test_low_volatility_detection(self, adapter):
        """Тест определения LOW волатильности"""
        # 0.5% волатильность = LOW
        params = adapter.get_parameters(current_volatility=0.005)
        
        assert params.regime == VolatilityRegime.LOW
        assert params.sl_multiplier == 1.5
        assert params.tp_multiplier == 1.0
        assert params.score_threshold == 6
        assert params.position_size_multiplier == 1.2

    def test_normal_volatility_detection(self, adapter):
        """Тест определения NORMAL волатильности"""
        # 1.5% волатильность = NORMAL
        params = adapter.get_parameters(current_volatility=0.015)
        
        assert params.regime == VolatilityRegime.NORMAL
        assert params.sl_multiplier == 2.5
        assert params.tp_multiplier == 1.5
        assert params.score_threshold == 7
        assert params.position_size_multiplier == 1.0

    def test_high_volatility_detection(self, adapter):
        """Тест определения HIGH волатильности"""
        # 3% волатильность = HIGH
        params = adapter.get_parameters(current_volatility=0.03)
        
        assert params.regime == VolatilityRegime.HIGH
        assert params.sl_multiplier == 3.5
        assert params.tp_multiplier == 2.5
        assert params.score_threshold == 8
        assert params.position_size_multiplier == 0.7

    def test_regime_change_logging(self, adapter):
        """Тест логирования смены режима"""
        # Первая проверка - LOW
        params1 = adapter.get_parameters(0.005)
        assert adapter.current_regime == VolatilityRegime.LOW
        assert adapter.regime_change_count == 1
        
        # Вторая проверка - тот же режим
        params2 = adapter.get_parameters(0.008)
        assert adapter.regime_change_count == 1  # Не изменился
        
        # Третья проверка - HIGH
        params3 = adapter.get_parameters(0.03)
        assert adapter.current_regime == VolatilityRegime.HIGH
        assert adapter.regime_change_count == 2  # Изменился!

    def test_calculate_volatility_normalized(self, adapter):
        """Тест расчета нормализованной волатильности"""
        # ATR=50, Price=2000 -> 2.5% волатильность
        vol = adapter.calculate_volatility(atr=50, price=2000, normalize=True)
        
        assert vol == 0.025  # 2.5%

    def test_calculate_volatility_raw(self, adapter):
        """Тест расчета сырой волатильности (ATR)"""
        vol = adapter.calculate_volatility(atr=50, price=2000, normalize=False)
        
        assert vol == 50  # Сырой ATR

    def test_should_adjust_parameters_true(self, adapter):
        """Тест: нужно ли пересчитывать параметры (большое изменение)"""
        # Изменение с 1% до 2% (разница 1% > порог 0.3%)
        should_adjust = adapter.should_adjust_parameters(
            volatility=0.02,
            last_check_volatility=0.01,
            threshold=0.003,
        )
        
        assert should_adjust is True

    def test_should_adjust_parameters_false(self, adapter):
        """Тест: не нужно пересчитывать (маленькое изменение)"""
        # Изменение с 1.0% до 1.1% (разница 0.1% < порог 0.3%)
        should_adjust = adapter.should_adjust_parameters(
            volatility=0.011,
            last_check_volatility=0.010,
            threshold=0.003,
        )
        
        assert should_adjust is False

    def test_get_adjusted_score_threshold_low(self, adapter):
        """Тест адаптированного порога в LOW режиме"""
        # LOW volatility -> порог 6
        threshold = adapter.get_adjusted_score_threshold(
            base_threshold=7, current_volatility=0.005
        )
        
        assert threshold == 6

    def test_get_adjusted_score_threshold_high(self, adapter):
        """Тест адаптированного порога в HIGH режиме"""
        # HIGH volatility -> порог 8
        threshold = adapter.get_adjusted_score_threshold(
            base_threshold=7, current_volatility=0.03
        )
        
        assert threshold == 8

    def test_disabled_adapter_returns_normal(self):
        """Тест: выключенный адаптер всегда возвращает NORMAL"""
        config = VolatilityModeConfig(enabled=False)
        adapter = VolatilityAdapter(config)
        
        # Даже при высокой волатильности
        params = adapter.get_parameters(current_volatility=0.05)
        
        assert params.regime == VolatilityRegime.NORMAL
        assert params.score_threshold == 7

    def test_get_regime_info(self, adapter):
        """Тест получения информации о режиме"""
        # Делаем несколько проверок
        adapter.get_parameters(0.005)  # LOW
        adapter.get_parameters(0.015)  # NORMAL
        adapter.get_parameters(0.03)   # HIGH
        
        info = adapter.get_regime_info()
        
        assert info["enabled"] is True
        assert info["current_regime"] == "HIGH_VOL"
        assert info["regime_changes"] == 3

    def test_boundary_conditions_low_normal(self, adapter):
        """Тест граничных условий LOW/NORMAL"""
        # Ровно на границе 1%
        params = adapter.get_parameters(0.01)
        
        # Должно быть NORMAL (>= порог)
        assert params.regime == VolatilityRegime.NORMAL

    def test_boundary_conditions_normal_high(self, adapter):
        """Тест граничных условий NORMAL/HIGH"""
        # Чуть выше границы 2%
        params = adapter.get_parameters(0.021)
        
        # Должно быть HIGH (> порог)
        assert params.regime == VolatilityRegime.HIGH

    def test_zero_volatility(self, adapter):
        """Тест нулевой волатильности"""
        params = adapter.get_parameters(0.0)
        
        # Нулевая волатильность = LOW
        assert params.regime == VolatilityRegime.LOW

    def test_extreme_volatility(self, adapter):
        """Тест экстремальной волатильности"""
        params = adapter.get_parameters(0.10)  # 10%!
        
        # Экстремальная волатильность = HIGH
        assert params.regime == VolatilityRegime.HIGH


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

