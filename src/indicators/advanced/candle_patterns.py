"""
Candle Patterns Detector

Определяет разворотные паттерны свечей (Hammer, Engulfing) с адаптивной фильтрацией на основе ATR.
Используется для умного закрытия позиций в exit_analyzer.
"""

from typing import List, Optional

import numpy as np
from loguru import logger

from src.models import OHLCV


class CandlePatternDetector:
    """
    Детектор паттернов свечей с адаптивной фильтрацией.

    Использует ATR для фильтрации ложных сигналов и адаптивные пороги
    на основе волатильности рынка.
    """

    def __init__(self):
        """Инициализация детектора паттернов"""
        logger.debug("CandlePatternDetector initialized")

    async def is_hammer(
        self,
        candle: OHLCV,
        prev_candle: Optional[OHLCV] = None,
        atr: Optional[float] = None,
        atr_factor: float = 0.3,
    ) -> bool:
        """
        Определяет паттерн Hammer (молот).

        Hammer - это разворотный паттерн, где:
        - Маленькое тело (open/close близки)
        - Длинная нижняя тень (нижний фитиль)
        - Маленькая или отсутствующая верхняя тень

        Args:
            candle: Текущая свеча
            prev_candle: Предыдущая свеча (опционально, для контекста)
            atr: Average True Range для адаптивной фильтрации
            atr_factor: Множитель ATR для минимальной длины тени (по умолчанию 0.3)

        Returns:
            True если обнаружен Hammer паттерн
        """
        if not candle:
            return False

        try:
            open_price = float(candle.open)
            high_price = float(candle.high)
            low_price = float(candle.low)
            close_price = float(candle.close)

            # Вычисляем размеры тела и теней
            body_size = abs(close_price - open_price)
            upper_shadow = high_price - max(open_price, close_price)
            lower_shadow = min(open_price, close_price) - low_price
            total_range = high_price - low_price

            if total_range == 0:
                return False

            # Базовые условия для Hammer:
            # 1. Тело маленькое (< 30% от общего диапазона)
            body_ratio = body_size / total_range
            if body_ratio > 0.3:
                return False

            # 2. Нижняя тень длинная (> 2x размера тела)
            if body_size > 0 and lower_shadow < body_size * 2:
                return False

            # 3. Верхняя тень маленькая (< 50% от нижней тени)
            if lower_shadow > 0 and upper_shadow > lower_shadow * 0.5:
                return False

            # ✅ АДАПТИВНАЯ ФИЛЬТРАЦИЯ: Используем ATR для фильтрации ложных сигналов
            if atr is not None and atr > 0:
                min_shadow_size = atr * atr_factor
                if lower_shadow < min_shadow_size:
                    logger.debug(
                        f"Hammer отклонён: нижняя тень {lower_shadow:.4f} < ATR*{atr_factor} = {min_shadow_size:.4f}"
                    )
                    return False

            # Дополнительная проверка: нижняя тень должна быть значимой (> 40% от диапазона)
            lower_shadow_ratio = lower_shadow / total_range
            if lower_shadow_ratio < 0.4:
                return False

            logger.debug(
                f"✅ Hammer обнаружен: body={body_size:.4f}, lower_shadow={lower_shadow:.4f}, "
                f"upper_shadow={upper_shadow:.4f}, atr={atr:.4f if atr else 0}"
            )
            return True

        except Exception as e:
            logger.debug(f"⚠️ Ошибка определения Hammer: {e}")
            return False

    async def is_engulfing_bearish(
        self,
        current_candle: OHLCV,
        prev_candle: OHLCV,
        atr: Optional[float] = None,
        atr_factor: float = 0.5,
    ) -> bool:
        """
        Определяет медвежий Engulfing паттерн (поглощение).

        Bearish Engulfing - это разворотный паттерн, где:
        - Предыдущая свеча бычья (зеленая)
        - Текущая свеча медвежья (красная)
        - Текущая свеча полностью поглощает предыдущую (тело + тени)

        Args:
            current_candle: Текущая свеча (медвежья)
            prev_candle: Предыдущая свеча (бычья)
            atr: Average True Range для адаптивной фильтрации
            atr_factor: Множитель ATR для минимального размера поглощения (по умолчанию 0.5)

        Returns:
            True если обнаружен Bearish Engulfing паттерн
        """
        if not current_candle or not prev_candle:
            return False

        try:
            # Предыдущая свеча
            prev_open = float(prev_candle.open)
            prev_close = float(prev_candle.close)
            prev_high = float(prev_candle.high)
            prev_low = float(prev_candle.low)

            # Текущая свеча
            curr_open = float(current_candle.open)
            curr_close = float(current_candle.close)
            curr_high = float(current_candle.high)
            curr_low = float(current_candle.low)

            # Проверка 1: Предыдущая свеча должна быть бычьей (зеленой)
            prev_is_bullish = prev_close > prev_open
            if not prev_is_bullish:
                return False

            # Проверка 2: Текущая свеча должна быть медвежьей (красной)
            curr_is_bearish = curr_close < curr_open
            if not curr_is_bearish:
                return False

            # Проверка 3: Текущая свеча должна полностью поглощать предыдущую
            # Тело текущей свечи должно быть больше тела предыдущей
            prev_body = abs(prev_close - prev_open)
            curr_body = abs(curr_close - curr_open)

            if curr_body <= prev_body:
                return False

            # Проверка 4: Текущая свеча должна поглощать весь диапазон предыдущей
            # (high и low текущей свечи должны быть выше/ниже high и low предыдущей)
            if curr_high < prev_high or curr_low > prev_low:
                return False

            # ✅ АДАПТИВНАЯ ФИЛЬТРАЦИЯ: Используем ATR для фильтрации слабых сигналов
            if atr is not None and atr > 0:
                min_engulfing_size = atr * atr_factor
                if curr_body < min_engulfing_size:
                    logger.debug(
                        f"Bearish Engulfing отклонён: размер тела {curr_body:.4f} < ATR*{atr_factor} = {min_engulfing_size:.4f}"
                    )
                    return False

            # Дополнительная проверка: размер поглощения должен быть значимым
            # (тело текущей свечи должно быть минимум в 1.5 раза больше тела предыдущей)
            if curr_body < prev_body * 1.5:
                return False

            logger.debug(
                f"✅ Bearish Engulfing обнаружен: prev_body={prev_body:.4f}, "
                f"curr_body={curr_body:.4f}, atr={atr:.4f if atr else 0}"
            )
            return True

        except Exception as e:
            logger.debug(f"⚠️ Ошибка определения Bearish Engulfing: {e}")
            return False

    async def is_engulfing_bullish(
        self,
        current_candle: OHLCV,
        prev_candle: OHLCV,
        atr: Optional[float] = None,
        atr_factor: float = 0.5,
    ) -> bool:
        """
        Определяет бычий Engulfing паттерн (поглощение).

        Bullish Engulfing - это разворотный паттерн, где:
        - Предыдущая свеча медвежья (красная)
        - Текущая свеча бычья (зеленая)
        - Текущая свеча полностью поглощает предыдущую

        Args:
            current_candle: Текущая свеча (бычья)
            prev_candle: Предыдущая свеча (медвежья)
            atr: Average True Range для адаптивной фильтрации
            atr_factor: Множитель ATR для минимального размера поглощения

        Returns:
            True если обнаружен Bullish Engulfing паттерн
        """
        if not current_candle or not prev_candle:
            return False

        try:
            # Предыдущая свеча
            prev_open = float(prev_candle.open)
            prev_close = float(prev_candle.close)
            prev_high = float(prev_candle.high)
            prev_low = float(prev_candle.low)

            # Текущая свеча
            curr_open = float(current_candle.open)
            curr_close = float(current_candle.close)
            curr_high = float(current_candle.high)
            curr_low = float(current_candle.low)

            # Проверка 1: Предыдущая свеча должна быть медвежьей (красной)
            prev_is_bearish = prev_close < prev_open
            if not prev_is_bearish:
                return False

            # Проверка 2: Текущая свеча должна быть бычьей (зеленой)
            curr_is_bullish = curr_close > curr_open
            if not curr_is_bullish:
                return False

            # Проверка 3: Текущая свеча должна полностью поглощать предыдущую
            prev_body = abs(prev_close - prev_open)
            curr_body = abs(curr_close - curr_open)

            if curr_body <= prev_body:
                return False

            # Проверка 4: Текущая свеча должна поглощать весь диапазон предыдущей
            if curr_high < prev_high or curr_low > prev_low:
                return False

            # ✅ АДАПТИВНАЯ ФИЛЬТРАЦИЯ
            if atr is not None and atr > 0:
                min_engulfing_size = atr * atr_factor
                if curr_body < min_engulfing_size:
                    return False

            # Дополнительная проверка
            if curr_body < prev_body * 1.5:
                return False

            logger.debug(
                f"✅ Bullish Engulfing обнаружен: prev_body={prev_body:.4f}, "
                f"curr_body={curr_body:.4f}, atr={atr:.4f if atr else 0}"
            )
            return True

        except Exception as e:
            logger.debug(f"⚠️ Ошибка определения Bullish Engulfing: {e}")
            return False
