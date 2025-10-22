"""
Indicators module - Technical indicators for trading strategies
"""

from src.indicators.base import (
    ATR,
    MACD,
    RSI,
    BollingerBands,
    ExponentialMovingAverage,
    IndicatorManager,
    SimpleMovingAverage,
    VolumeIndicator,
)

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
]

