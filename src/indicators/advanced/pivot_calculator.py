"""
Pivot Points Calculator

Рассчитывает классические Pivot Points и уровни поддержки/сопротивления
на основе данных предыдущего дня (High, Low, Close).

Pivot Points - это технические индикаторы, используемые трейдерами для
определения потенциальных уровней поддержки и сопротивления.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
from loguru import logger
from pydantic import BaseModel, Field

from src.models import OHLCV


class PivotLevels(BaseModel):
    """Уровни Pivot Points"""

    pivot_point: float = Field(description="Центральный Pivot Point (PP)")
    resistance_1: float = Field(description="Сопротивление 1 (R1)")
    resistance_2: float = Field(description="Сопротивление 2 (R2)")
    resistance_3: float = Field(description="Сопротивление 3 (R3)")
    support_1: float = Field(description="Поддержка 1 (S1)")
    support_2: float = Field(description="Поддержка 2 (S2)")
    support_3: float = Field(description="Поддержка 3 (S3)")
    calculated_at: float = Field(description="Timestamp расчета")
    source_date: str = Field(description="Дата данных (YYYY-MM-DD)")

    def get_all_levels(self) -> List[float]:
        """Получить все уровни как список"""
        return [
            self.support_3,
            self.support_2,
            self.support_1,
            self.pivot_point,
            self.resistance_1,
            self.resistance_2,
            self.resistance_3,
        ]

    def get_nearest_level(self, price: float) -> tuple[str, float, float]:
        """
        Найти ближайший уровень к цене.

        Args:
            price: Текущая цена

        Returns:
            (level_name, level_value, distance)
        """
        levels = {
            "S3": self.support_3,
            "S2": self.support_2,
            "S1": self.support_1,
            "PP": self.pivot_point,
            "R1": self.resistance_1,
            "R2": self.resistance_2,
            "R3": self.resistance_3,
        }

        nearest_name = None
        nearest_value = None
        min_distance = float("inf")

        for name, value in levels.items():
            distance = abs(price - value)
            if distance < min_distance:
                min_distance = distance
                nearest_name = name
                nearest_value = value

        return (nearest_name, nearest_value, min_distance)


class PivotCalculator:
    """
    Калькулятор классических Pivot Points.

    Рассчитывает уровни на основе формул:
    - PP = (High + Low + Close) / 3
    - R1 = 2*PP - Low
    - R2 = PP + (High - Low)
    - R3 = High + 2*(PP - Low)
    - S1 = 2*PP - High
    - S2 = PP - (High - Low)
    - S3 = Low - 2*(High - PP)

    Example:
        >>> calculator = PivotCalculator()
        >>> candles = await get_daily_candles("BTC-USDT")
        >>> levels = calculator.calculate_pivots(candles)
        >>> logger.info(f"PP: {levels.pivot_point}, R1: {levels.resistance_1}")
    """

    def __init__(self):
        """Инициализация калькулятора Pivot Points"""
        logger.info("Pivot Calculator initialized")

    def calculate_pivots(
        self, daily_candles: List[OHLCV], use_last_n_days: int = 1
    ) -> Optional[PivotLevels]:
        """
        Рассчитать Pivot Points на основе дневных свечей.

        Args:
            daily_candles: Список дневных свечей (1D timeframe)
            use_last_n_days: Использовать последние N дней для расчета

        Returns:
            PivotLevels или None если недостаточно данных

        Example:
            >>> daily_candles = await client.get_candles("BTC-USDT", "1D", 5)
            >>> pivots = calculator.calculate_pivots(daily_candles)
        """
        if not daily_candles or len(daily_candles) < use_last_n_days:
            logger.warning(
                f"Insufficient daily candles for pivot calculation "
                f"(have {len(daily_candles) if daily_candles else 0}, need {use_last_n_days})"
            )
            return None

        # Берем последние N дней
        recent_candles = daily_candles[-use_last_n_days:]

        # Находим High, Low, Close
        high = max(float(c.high) for c in recent_candles)
        low = min(float(c.low) for c in recent_candles)
        close = float(recent_candles[-1].close)

        # Рассчитываем Pivot Point (центральный уровень)
        pp = (high + low + close) / 3

        # Рассчитываем уровни сопротивления
        r1 = 2 * pp - low
        r2 = pp + (high - low)
        r3 = high + 2 * (pp - low)

        # Рассчитываем уровни поддержки
        s1 = 2 * pp - high
        s2 = pp - (high - low)
        s3 = low - 2 * (high - pp)

        # Создаем объект уровней
        levels = PivotLevels(
            pivot_point=pp,
            resistance_1=r1,
            resistance_2=r2,
            resistance_3=r3,
            support_1=s1,
            support_2=s2,
            support_3=s3,
            calculated_at=datetime.utcnow().timestamp(),
            source_date=datetime.fromtimestamp(recent_candles[-1].timestamp).strftime(
                "%Y-%m-%d"
            ),
        )

        logger.info(
            f"Pivots calculated (H={high:.2f}, L={low:.2f}, C={close:.2f}):\n"
            f"  R3={r3:.2f} | R2={r2:.2f} | R1={r1:.2f}\n"
            f"  PP={pp:.2f}\n"
            f"  S1={s1:.2f} | S2={s2:.2f} | S3={s3:.2f}"
        )

        return levels

    def is_near_level(
        self, price: float, level: float, tolerance_percent: float = 0.002
    ) -> bool:
        """
        Проверить находится ли цена около уровня.

        Args:
            price: Текущая цена
            level: Уровень Pivot
            tolerance_percent: Допуск в % (0.2% по умолчанию)

        Returns:
            bool: True если цена около уровня

        Example:
            >>> # Цена 50100, уровень 50000, допуск 0.2%
            >>> is_near = calculator.is_near_level(50100, 50000, 0.002)
            >>> # True (отклонение 0.2%)
        """
        tolerance = level * tolerance_percent
        return abs(price - level) <= tolerance

    def get_level_type(self, price: float, levels: PivotLevels) -> str:
        """
        Определить тип уровня относительно цены.

        Args:
            price: Текущая цена
            levels: Рассчитанные уровни

        Returns:
            str: "ABOVE_R3", "AT_PP", "BELOW_S3", etc.

        Example:
            >>> level_type = calculator.get_level_type(50100, pivot_levels)
            >>> # "BETWEEN_PP_R1" если цена между PP и R1
        """
        if price > levels.resistance_3:
            return "ABOVE_R3"
        elif price > levels.resistance_2:
            return "BETWEEN_R2_R3"
        elif price > levels.resistance_1:
            return "BETWEEN_R1_R2"
        elif price > levels.pivot_point:
            return "BETWEEN_PP_R1"
        elif price > levels.support_1:
            return "BETWEEN_S1_PP"
        elif price > levels.support_2:
            return "BETWEEN_S2_S1"
        elif price > levels.support_3:
            return "BETWEEN_S3_S2"
        else:
            return "BELOW_S3"

