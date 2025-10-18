"""
ADX (Average Directional Index) Filter.

Фильтрует сигналы по СИЛЕ ТРЕНДА:
- ADX > порога = сильный тренд, торгуем
- ADX < порога = слабый тренд, НЕ торгуем

Также проверяет НАПРАВЛЕНИЕ тренда через +DI и -DI:
- LONG: +DI должен быть значительно > -DI
- SHORT: -DI должен быть значительно > +DI
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from loguru import logger

from src.models import OrderSide


@dataclass
class ADXFilterConfig:
    """Конфигурация ADX фильтра."""

    enabled: bool = True
    adx_threshold: float = 25.0  # Минимальная сила тренда
    di_difference: float = 5.0  # Разница между +DI и -DI
    adx_period: int = 14  # Период расчета ADX
    timeframe: str = "15m"  # На каком таймфрейме считать


@dataclass
class ADXResult:
    """Результат проверки ADX."""

    allowed: bool
    adx_value: float
    plus_di: float
    minus_di: float
    reason: str


class ADXFilter:
    """
    Фильтр силы тренда через ADX.

    ADX показывает СИЛУ тренда (не направление!):
    - ADX < 20: Нет тренда (флэт)
    - ADX 20-25: Слабый тренд
    - ADX 25-50: Сильный тренд
    - ADX > 50: Очень сильный тренд

    +DI и -DI показывают НАПРАВЛЕНИЕ:
    - +DI > -DI: Восходящий тренд (LONG)
    - -DI > +DI: Нисходящий тренд (SHORT)
    """

    def __init__(self, config: ADXFilterConfig):
        """
        Args:
            config: Конфигурация ADX фильтра
        """
        self.config = config

        logger.info(
            f"✅ ADX Filter initialized | "
            f"Threshold: {config.adx_threshold} | "
            f"DI diff: {config.di_difference} | "
            f"Period: {config.adx_period}"
        )

    def check_trend_strength(
        self, symbol: str, side: OrderSide, candles: List
    ) -> ADXResult:
        """
        Проверяет силу и направление тренда.

        Args:
            symbol: Торговый символ
            side: Направление сигнала (BUY=LONG, SELL=SHORT)
            candles: OHLCV свечи для расчета

        Returns:
            ADXResult с результатом проверки
        """
        if not self.config.enabled:
            return ADXResult(
                allowed=True,
                adx_value=0,
                plus_di=0,
                minus_di=0,
                reason="ADX filter disabled",
            )

        try:
            # Расчет ADX, +DI, -DI
            adx = self._calculate_adx(candles)
            plus_di = self._calculate_plus_di(candles)
            minus_di = self._calculate_minus_di(candles)

            logger.debug(
                f"📊 ADX {symbol}: ADX={adx:.1f}, "
                f"+DI={plus_di:.1f}, -DI={minus_di:.1f}"
            )

            # 1. Проверка силы тренда
            if adx < self.config.adx_threshold:
                return ADXResult(
                    allowed=False,
                    adx_value=adx,
                    plus_di=plus_di,
                    minus_di=minus_di,
                    reason=(
                        f"Weak trend: ADX={adx:.1f} < "
                        f"{self.config.adx_threshold}"
                    ),
                )

            # 2. Проверка направления тренда
            if side == OrderSide.BUY:  # LONG
                if plus_di < minus_di + self.config.di_difference:
                    return ADXResult(
                        allowed=False,
                        adx_value=adx,
                        plus_di=plus_di,
                        minus_di=minus_di,
                        reason=(
                            f"+DI not dominant: +DI={plus_di:.1f}, "
                            f"-DI={minus_di:.1f} "
                            f"(need +DI > -DI + {self.config.di_difference})"
                        ),
                    )
            else:  # SHORT
                if minus_di < plus_di + self.config.di_difference:
                    return ADXResult(
                        allowed=False,
                        adx_value=adx,
                        plus_di=plus_di,
                        minus_di=minus_di,
                        reason=(
                            f"-DI not dominant: -DI={minus_di:.1f}, "
                            f"+DI={plus_di:.1f} "
                            f"(need -DI > +DI + {self.config.di_difference})"
                        ),
                    )

            # ✅ Все проверки прошли
            return ADXResult(
                allowed=True,
                adx_value=adx,
                plus_di=plus_di,
                minus_di=minus_di,
                reason=f"Strong trend: ADX={adx:.1f}, DI diff={abs(plus_di - minus_di):.1f}",
            )

        except Exception as e:
            logger.error(f"❌ ADX calculation error for {symbol}: {e}")
            # В случае ошибки - пропускаем фильтр
            return ADXResult(
                allowed=True,
                adx_value=0,
                plus_di=0,
                minus_di=0,
                reason=f"ADX error (skipped): {e}",
            )

    def _calculate_adx(self, candles: List[Dict]) -> float:
        """
        Расчет ADX (Average Directional Index).

        ADX = SMA(DX, period)
        где DX = 100 * |+DI - -DI| / |+DI + -DI|
        """
        if len(candles) < self.config.adx_period + 1:
            return 0.0

        # Извлекаем данные (candles = List[OHLCV])
        highs = np.array([float(c.high) for c in candles])
        lows = np.array([float(c.low) for c in candles])
        closes = np.array([float(c.close) for c in candles])

        # True Range
        tr = self._calculate_tr(highs, lows, closes)

        # +DM и -DM
        plus_dm = self._calculate_plus_dm(highs)
        minus_dm = self._calculate_minus_dm(lows)

        # Сглаживание (Wilder's smoothing)
        atr = self._wilder_smooth(tr, self.config.adx_period)
        plus_di_smooth = self._wilder_smooth(plus_dm, self.config.adx_period)
        minus_di_smooth = self._wilder_smooth(minus_dm, self.config.adx_period)

        # +DI и -DI (в процентах)
        plus_di_vals = 100 * plus_di_smooth / atr
        minus_di_vals = 100 * minus_di_smooth / atr

        # DX
        dx = 100 * np.abs(plus_di_vals - minus_di_vals) / (
            plus_di_vals + minus_di_vals + 1e-10
        )

        # ADX = сглаженный DX
        adx_vals = self._wilder_smooth(dx, self.config.adx_period)

        return float(adx_vals[-1])

    def _calculate_plus_di(self, candles: List) -> float:
        """Расчет +DI (Plus Directional Indicator)."""
        if len(candles) < self.config.adx_period + 1:
            return 0.0

        highs = np.array([float(c.high) for c in candles])
        lows = np.array([float(c.low) for c in candles])
        closes = np.array([float(c.close) for c in candles])

        tr = self._calculate_tr(highs, lows, closes)
        plus_dm = self._calculate_plus_dm(highs)

        atr = self._wilder_smooth(tr, self.config.adx_period)
        plus_di_smooth = self._wilder_smooth(plus_dm, self.config.adx_period)

        plus_di = 100 * plus_di_smooth / atr

        return float(plus_di[-1])

    def _calculate_minus_di(self, candles: List) -> float:
        """Расчет -DI (Minus Directional Indicator)."""
        if len(candles) < self.config.adx_period + 1:
            return 0.0

        highs = np.array([float(c.high) for c in candles])
        lows = np.array([float(c.low) for c in candles])
        closes = np.array([float(c.close) for c in candles])

        tr = self._calculate_tr(highs, lows, closes)
        minus_dm = self._calculate_minus_dm(lows)

        atr = self._wilder_smooth(tr, self.config.adx_period)
        minus_di_smooth = self._wilder_smooth(minus_dm, self.config.adx_period)

        minus_di = 100 * minus_di_smooth / atr

        return float(minus_di[-1])

    def _calculate_tr(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
    ) -> np.ndarray:
        """
        True Range = max(high - low, |high - prev_close|, |low - prev_close|).
        """
        hl = highs - lows
        hc = np.abs(highs[1:] - closes[:-1])
        lc = np.abs(lows[1:] - closes[:-1])

        # Добавляем первый элемент (для него prev_close нет)
        tr = np.zeros(len(highs))
        tr[0] = hl[0]
        tr[1:] = np.maximum(hl[1:], np.maximum(hc, lc))

        return tr

    def _calculate_plus_dm(self, highs: np.ndarray) -> np.ndarray:
        """
        +DM (Plus Directional Movement).

        +DM = high - prev_high (если > 0 и > |low - prev_low|, иначе 0)
        """
        up_move = highs[1:] - highs[:-1]

        plus_dm = np.zeros(len(highs))
        plus_dm[1:] = np.where(up_move > 0, up_move, 0)

        return plus_dm

    def _calculate_minus_dm(self, lows: np.ndarray) -> np.ndarray:
        """
        -DM (Minus Directional Movement).

        -DM = prev_low - low (если > 0 и > high - prev_high, иначе 0)
        """
        down_move = lows[:-1] - lows[1:]

        minus_dm = np.zeros(len(lows))
        minus_dm[1:] = np.where(down_move > 0, down_move, 0)

        return minus_dm

    def _wilder_smooth(self, values: np.ndarray, period: int) -> np.ndarray:
        """
        Сглаживание Wilder's (как в оригинальном ADX).

        smoothed[i] = (smoothed[i-1] * (period - 1) + values[i]) / period
        """
        smoothed = np.zeros(len(values))
        smoothed[: period - 1] = np.nan

        # Первое значение = простое среднее
        smoothed[period - 1] = np.mean(values[:period])

        # Последующие значения = Wilder's smoothing
        for i in range(period, len(values)):
            smoothed[i] = (smoothed[i - 1] * (period - 1) + values[i]) / period

        return smoothed

    def update_parameters(self, new_config: ADXFilterConfig):
        """
        Обновление параметров ADX (для ARM).

        Args:
            new_config: Новая конфигурация
        """
        old_threshold = self.config.adx_threshold
        old_di = self.config.di_difference

        self.config = new_config

        logger.info(
            f"🔄 ADX параметры обновлены:\n"
            f"   adx_threshold: {old_threshold} → {new_config.adx_threshold}\n"
            f"   di_difference: {old_di} → {new_config.di_difference}"
        )

