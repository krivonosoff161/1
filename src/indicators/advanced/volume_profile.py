"""
Volume Profile Indicator

Анализирует распределение торгового объема по ценовым уровням для определения
зон высокой ликвидности и важных уровней поддержки/сопротивления.

Key Levels:
- POC (Point of Control): Уровень с максимальным объемом
- VAH (Value Area High): Верхняя граница зоны 70% объема
- VAL (Value Area Low): Нижняя граница зоны 70% объема
"""

from typing import Dict, List, Optional, Tuple

import numpy as np
from loguru import logger
from pydantic import BaseModel, Field

from src.models import OHLCV


class VolumeProfileData(BaseModel):
    """Данные Volume Profile"""

    poc: float = Field(description="Point of Control (максимальный объем)")
    vah: float = Field(description="Value Area High (70% объема сверху)")
    val: float = Field(description="Value Area Low (70% объема снизу)")
    total_volume: float = Field(description="Общий объем")
    price_levels: int = Field(description="Количество ценовых уровней")
    value_area_volume_percent: float = Field(
        default=70.0, description="Процент объема в Value Area"
    )

    def is_in_value_area(self, price: float) -> bool:
        """Проверить находится ли цена в Value Area"""
        return self.val <= price <= self.vah

    def get_distance_from_poc(self, price: float) -> float:
        """Расстояние от POC в процентах"""
        return abs(price - self.poc) / self.poc


class VolumeProfileCalculator:
    """
    Калькулятор Volume Profile.

    Рассчитывает распределение объема по ценовым уровням и определяет
    ключевые зоны (POC, VAH, VAL).

    Example:
        >>> calculator = VolumeProfileCalculator(price_buckets=50)
        >>> profile = calculator.calculate(candles)
        >>> logger.info(f"POC: {profile.poc}, VAH: {profile.vah}, VAL: {profile.val}")
    """

    def __init__(self, price_buckets: int = 50):
        """
        Инициализация калькулятора Volume Profile.

        Args:
            price_buckets: Количество ценовых уровней для распределения объема
        """
        self.price_buckets = price_buckets
        logger.info(f"Volume Profile Calculator initialized: {price_buckets} price levels")

    def calculate(
        self,
        candles: List[OHLCV],
        value_area_percent: float = 70.0,
    ) -> Optional[VolumeProfileData]:
        """
        Рассчитать Volume Profile на основе свечей.

        Args:
            candles: Список свечей OHLCV
            value_area_percent: Процент объема для Value Area (обычно 70%)

        Returns:
            VolumeProfileData или None если недостаточно данных

        Example:
            >>> candles = await client.get_candles("BTC-USDT", "1H", 100)
            >>> profile = calculator.calculate(candles)
        """
        if not candles or len(candles) < 10:
            logger.warning(
                f"Insufficient candles for volume profile "
                f"(have {len(candles) if candles else 0}, need 10+)"
            )
            return None

        try:
            # Извлекаем данные
            highs = np.array([float(c.high) for c in candles])
            lows = np.array([float(c.low) for c in candles])
            closes = np.array([float(c.close) for c in candles])
            volumes = np.array([float(c.volume) for c in candles])

            # Определяем диапазон цен
            min_price = lows.min()
            max_price = highs.max()
            price_range = max_price - min_price

            if price_range == 0:
                logger.warning("Zero price range, cannot calculate volume profile")
                return None

            # Создаем ценовые уровни (buckets)
            price_levels = np.linspace(min_price, max_price, self.price_buckets)
            volume_at_price = np.zeros(self.price_buckets)

            # Распределяем объем по ценовым уровням
            for i, candle in enumerate(candles):
                # Для каждой свечи распределяем объем между low и high
                candle_low = lows[i]
                candle_high = highs[i]
                candle_volume = volumes[i]

                # Находим индексы уровней в диапазоне свечи
                for j, price_level in enumerate(price_levels):
                    if candle_low <= price_level <= candle_high:
                        # Объем распределяется равномерно внутри свечи
                        volume_at_price[j] += candle_volume / (candle_high - candle_low + 1e-10)

            # Находим POC (Point of Control) - уровень с максимальным объемом
            poc_index = np.argmax(volume_at_price)
            poc = price_levels[poc_index]

            # Рассчитываем Value Area (70% объема)
            total_volume = volume_at_price.sum()
            value_area_volume_target = total_volume * (value_area_percent / 100)

            # Находим VAH и VAL (расширяем от POC пока не достигнем 70% объема)
            val_index, vah_index = self._find_value_area(
                volume_at_price, poc_index, value_area_volume_target
            )

            val = price_levels[val_index]
            vah = price_levels[vah_index]

            profile = VolumeProfileData(
                poc=poc,
                vah=vah,
                val=val,
                total_volume=float(total_volume),
                price_levels=self.price_buckets,
                value_area_volume_percent=value_area_percent,
            )

            logger.info(
                f"Volume Profile calculated: "
                f"POC=${poc:.2f}, VAH=${vah:.2f}, VAL=${val:.2f}, "
                f"Total Vol={total_volume:.0f}"
            )

            return profile

        except Exception as e:
            logger.error(f"Error calculating volume profile: {e}", exc_info=True)
            return None

    def _find_value_area(
        self,
        volume_at_price: np.ndarray,
        poc_index: int,
        target_volume: float,
    ) -> Tuple[int, int]:
        """
        Найти границы Value Area (VAL и VAH).

        Args:
            volume_at_price: Массив объемов по ценовым уровням
            poc_index: Индекс POC
            target_volume: Целевой объем для Value Area (70% от общего)

        Returns:
            (val_index, vah_index): Индексы границ Value Area
        """
        val_index = poc_index
        vah_index = poc_index
        current_volume = volume_at_price[poc_index]

        # Расширяем в обе стороны от POC
        while current_volume < target_volume:
            # Определяем куда расширять (где больше объем)
            volume_below = (
                volume_at_price[val_index - 1] if val_index > 0 else 0
            )
            volume_above = (
                volume_at_price[vah_index + 1]
                if vah_index < len(volume_at_price) - 1
                else 0
            )

            if volume_below > volume_above and val_index > 0:
                # Расширяем вниз
                val_index -= 1
                current_volume += volume_at_price[val_index]
            elif vah_index < len(volume_at_price) - 1:
                # Расширяем вверх
                vah_index += 1
                current_volume += volume_at_price[vah_index]
            else:
                # Достигли границ массива
                break

        return val_index, vah_index

