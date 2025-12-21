"""
Indicators module - Technical indicators for trading strategies
"""

from src.indicators.base import (ATR, MACD, RSI, BollingerBands,
                                 ExponentialMovingAverage, IndicatorManager,
                                 SimpleMovingAverage, VolumeIndicator)

# ✅ ГРОК ОПТИМИЗАЦИЯ: TA-Lib обертки для ускорения на 70-85%
try:
    from src.indicators.talib_wrapper import (TALibATR, TALibBollingerBands,
                                              TALibEMA, TALibMACD, TALibRSI,
                                              TALibSMA)

    TALIB_AVAILABLE = True
    # ✅ ЛОГИРОВАНИЕ: Логируем успешную загрузку TA-Lib
    from loguru import logger

    logger.info(
        "✅ TA-Lib обертки загружены успешно - используется оптимизированная версия индикаторов"
    )
except ImportError as e:
    TALIB_AVAILABLE = False
    # Fallback на обычные индикаторы
    from loguru import logger

    logger.warning(
        f"⚠️ TA-Lib недоступен (ImportError: {e}), используется fallback на обычные индикаторы. "
        f"Производительность может быть ниже на 70-85%"
    )
    TALibRSI = RSI
    TALibEMA = ExponentialMovingAverage
    TALibATR = ATR
    TALibMACD = MACD
    TALibSMA = SimpleMovingAverage
    TALibBollingerBands = BollingerBands
except Exception as e:
    TALIB_AVAILABLE = False
    # Fallback на обычные индикаторы при любой другой ошибке
    from loguru import logger

    logger.error(
        f"❌ Ошибка при загрузке TA-Lib оберток ({type(e).__name__}: {e}), "
        f"используется fallback на обычные индикаторы"
    )
    TALibRSI = RSI
    TALibEMA = ExponentialMovingAverage
    TALibATR = ATR
    TALibMACD = MACD
    TALibSMA = SimpleMovingAverage
    TALibBollingerBands = BollingerBands

# Создаем алиас для совместимости
TechnicalIndicators = IndicatorManager

__all__ = [
    "ATR",
    "MACD",
    "RSI",
    "BollingerBands",
    "ExponentialMovingAverage",
    "IndicatorManager",
    "SimpleMovingAverage",
    "VolumeIndicator",
    "TechnicalIndicators",
    # TA-Lib обертки
    "TALibRSI",
    "TALibEMA",
    "TALibATR",
    "TALibMACD",
    "TALibSMA",
    "TALibBollingerBands",
    "TALIB_AVAILABLE",
]
