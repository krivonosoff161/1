"""
Indicator Calculator - Единый калькулятор индикаторов со стандартными периодами.

Обеспечивает консистентность расчетов индикаторов во всех модулях:
- Стандартные периоды для всех индикаторов
- Кэширование результатов
- Единый интерфейс для доступа к индикаторам
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from src.models import OHLCV


class IndicatorCalculator:
    """
    Единый калькулятор индикаторов со стандартными периодами.
    
    Обеспечивает консистентность расчетов во всех модулях системы.
    """

    # ✅ СТАНДАРТНЫЕ ПЕРИОДЫ ДЛЯ ВСЕХ ИНДИКАТОРОВ
    # Эти значения используются по умолчанию во всех модулях
    STANDARD_PERIODS = {
        "rsi": 14,
        "atr": 14,
        "sma_fast": 20,
        "sma_slow": 50,
        "ema_fast": 12,
        "ema_slow": 26,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "bb_period": 20,
        "bb_std_multiplier": 2.0,
        "adx": 9,  # FastADX period
    }

    # ✅ СТАНДАРТНЫЕ ПОРОГИ
    STANDARD_THRESHOLDS = {
        "rsi_overbought": 70.0,
        "rsi_oversold": 30.0,
        "adx_trending": 30.0,  # Обновлено согласно задаче 2.1
        "adx_ranging": 25.0,  # Обновлено согласно задаче 2.1
    }

    def __init__(self, custom_periods: Optional[Dict[str, int]] = None):
        """
        Инициализация Indicator Calculator.
        
        Args:
            custom_periods: Кастомные периоды для переопределения стандартных (опционально)
        """
        # Объединяем стандартные периоды с кастомными
        self.periods = self.STANDARD_PERIODS.copy()
        if custom_periods:
            self.periods.update(custom_periods)
        
        # Кэш для результатов расчетов
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_ttl_seconds = 30.0  # TTL кэша: 30 секунд
        
        logger.info(
            f"✅ IndicatorCalculator инициализирован со стандартными периодами: {self.periods}"
        )

    def get_period(self, indicator_name: str) -> int:
        """
        Получить период для индикатора.
        
        Args:
            indicator_name: Имя индикатора (rsi, atr, sma_fast, etc.)
            
        Returns:
            Период индикатора
        """
        return self.periods.get(indicator_name, 14)  # Default: 14

    def get_threshold(self, threshold_name: str) -> float:
        """
        Получить порог для индикатора.
        
        Args:
            threshold_name: Имя порога (rsi_overbought, adx_trending, etc.)
            
        Returns:
            Значение порога
        """
        return self.STANDARD_THRESHOLDS.get(threshold_name, 0.0)

    def get_all_periods(self) -> Dict[str, int]:
        """
        Получить все периоды индикаторов.
        
        Returns:
            Словарь {индикатор: период}
        """
        return self.periods.copy()

    def get_all_thresholds(self) -> Dict[str, float]:
        """
        Получить все пороги.
        
        Returns:
            Словарь {порог: значение}
        """
        return self.STANDARD_THRESHOLDS.copy()

    def calculate_sma(
        self, candles: List[OHLCV], period: Optional[int] = None
    ) -> Optional[float]:
        """
        Рассчитать SMA (Simple Moving Average).
        
        Args:
            candles: Список свечей
            period: Период (если None, используется стандартный)
            
        Returns:
            Значение SMA или None
        """
        if not candles:
            return None
        
        period = period or self.get_period("sma_fast")
        if len(candles) < period:
            return None
        
        closes = [c.close for c in candles[-period:]]
        return sum(closes) / len(closes)

    def calculate_ema(
        self, candles: List[OHLCV], period: Optional[int] = None
    ) -> Optional[float]:
        """
        Рассчитать EMA (Exponential Moving Average).
        
        Args:
            candles: Список свечей
            period: Период (если None, используется стандартный)
            
        Returns:
            Значение EMA или None
        """
        if not candles:
            return None
        
        period = period or self.get_period("ema_fast")
        if len(candles) < period:
            return None
        
        # Простой расчет EMA
        multiplier = 2.0 / (period + 1)
        closes = [c.close for c in candles]
        
        # Начальное значение - SMA
        ema = sum(closes[:period]) / period
        
        # Применяем формулу EMA
        for i in range(period, len(closes)):
            ema = (closes[i] * multiplier) + (ema * (1 - multiplier))
        
        return ema

    def calculate_atr(
        self, candles: List[OHLCV], period: Optional[int] = None
    ) -> Optional[float]:
        """
        Рассчитать ATR (Average True Range).
        
        Args:
            candles: Список свечей
            period: Период (если None, используется стандартный)
            
        Returns:
            Значение ATR или None
        """
        if not candles or len(candles) < 2:
            return None
        
        period = period or self.get_period("atr")
        if len(candles) < period + 1:
            return None
        
        import numpy as np
        
        true_ranges = []
        for i in range(1, len(candles)):
            high = candles[i].high
            low = candles[i].low
            prev_close = candles[i - 1].close
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return None
        
        return np.mean(true_ranges[-period:])

    def calculate_rsi(
        self, candles: List[OHLCV], period: Optional[int] = None
    ) -> Optional[float]:
        """
        Рассчитать RSI (Relative Strength Index).
        
        Args:
            candles: Список свечей
            period: Период (если None, используется стандартный)
            
        Returns:
            Значение RSI (0-100) или None
        """
        if not candles or len(candles) < 2:
            return None
        
        period = period or self.get_period("rsi")
        if len(candles) < period + 1:
            return None
        
        closes = [c.close for c in candles]
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return None
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        
        return rsi

    def get_cached_value(
        self, cache_key: str, indicator_name: str
    ) -> Optional[Any]:
        """
        Получить значение из кэша.
        
        Args:
            cache_key: Ключ кэша (обычно symbol)
            indicator_name: Имя индикатора
            
        Returns:
            Значение из кэша или None
        """
        import time
        
        if cache_key not in self._cache:
            return None
        
        cache_time = self._cache_timestamps.get(cache_key, 0)
        current_time = time.time()
        
        if current_time - cache_time > self._cache_ttl_seconds:
            # Кэш устарел
            return None
        
        return self._cache[cache_key].get(indicator_name)

    def set_cached_value(
        self, cache_key: str, indicator_name: str, value: Any
    ) -> None:
        """
        Сохранить значение в кэш.
        
        Args:
            cache_key: Ключ кэша (обычно symbol)
            indicator_name: Имя индикатора
            value: Значение для кэширования
        """
        import time
        
        if cache_key not in self._cache:
            self._cache[cache_key] = {}
        
        self._cache[cache_key][indicator_name] = value
        self._cache_timestamps[cache_key] = time.time()

    def clear_cache(self, cache_key: Optional[str] = None) -> None:
        """
        Очистить кэш.
        
        Args:
            cache_key: Ключ кэша для очистки (если None - очистить весь кэш)
        """
        if cache_key:
            self._cache.pop(cache_key, None)
            self._cache_timestamps.pop(cache_key, None)
            logger.debug(f"✅ IndicatorCalculator: Кэш очищен для {cache_key}")
        else:
            self._cache.clear()
            self._cache_timestamps.clear()
            logger.debug("✅ IndicatorCalculator: Весь кэш очищен")

    def validate_periods(self) -> Dict[str, bool]:
        """
        Валидация периодов индикаторов.
        
        Проверяет, что все периоды находятся в разумных пределах.
        
        Returns:
            Словарь {индикатор: валиден}
        """
        validation_results = {}
        
        for indicator, period in self.periods.items():
            is_valid = True
            
            # Проверяем разумные пределы
            if period < 1 or period > 200:
                is_valid = False
                logger.warning(
                    f"⚠️ IndicatorCalculator: Период {indicator}={period} вне разумных пределов [1, 200]"
                )
            
            validation_results[indicator] = is_valid
        
        return validation_results





