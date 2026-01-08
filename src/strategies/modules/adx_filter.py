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

            # ✅ ИСПРАВЛЕНО: Проверка на nan значения
            if np.isnan(adx) or np.isnan(plus_di) or np.isnan(minus_di):
                logger.debug(
                    f"⚠️ ADX {symbol}: обнаружены nan значения (ADX={adx}, +DI={plus_di}, -DI={minus_di}), "
                    f"используем fallback: ADX=0.0, +DI={plus_di if not np.isnan(plus_di) else 0.0:.1f}, "
                    f"-DI={minus_di if not np.isnan(minus_di) else 0.0:.1f}"
                )
                # Используем fallback значения
                adx = 0.0 if np.isnan(adx) else adx
                plus_di = 0.0 if np.isnan(plus_di) else plus_di
                minus_di = 0.0 if np.isnan(minus_di) else minus_di

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
                        f"Weak trend: ADX={adx:.1f} < " f"{self.config.adx_threshold}"
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

    def _get_value(self, candle, key: str) -> float:
        """Безопасное извлечение значения из свечи (объект или словарь)."""
        if isinstance(candle, dict):
            return float(candle.get(key, 0))
        else:
            return float(getattr(candle, key, 0))

    def _calculate_adx(self, candles: List[Dict]) -> float:
        """
        Расчет ADX (Average Directional Index).

        ADX = SMA(DX, period)
        где DX = 100 * |+DI - -DI| / |+DI + -DI|
        """
        if len(candles) < self.config.adx_period + 1:
            return 0.0

        # Извлекаем данные (candles = List[OHLCV] или List[Dict])
        highs = np.array([self._get_value(c, "high") for c in candles])
        lows = np.array([self._get_value(c, "low") for c in candles])
        closes = np.array([self._get_value(c, "close") for c in candles])

        # True Range
        tr = self._calculate_tr(highs, lows, closes)

        # +DM и -DM
        plus_dm = self._calculate_plus_dm(highs)
        minus_dm = self._calculate_minus_dm(lows)

        # Сглаживание (Wilder's smoothing)
        atr = self._wilder_smooth(tr, self.config.adx_period)
        plus_di_smooth = self._wilder_smooth(plus_dm, self.config.adx_period)
        minus_di_smooth = self._wilder_smooth(minus_dm, self.config.adx_period)

        # ✅ ИСПРАВЛЕНО: Защита от деления на ноль и nan
        # Проверяем только последнее значение (первые period-1 значений всегда nan в Wilder's smoothing)
        if len(atr) == 0 or np.isnan(atr[-1]) or atr[-1] == 0:
            logger.debug(
                f"⚠️ ADX: последнее значение atr nan или ноль для {len(candles)} свечей "
                f"(atr[-1]={atr[-1] if len(atr) > 0 else 'N/A'}), "
                f"используем fallback значение 0.0"
            )
            return 0.0

        # ✅ ИСПРАВЛЕНО: Заменяем nan в atr на последнее валидное значение для безопасного деления
        # Это нужно, чтобы при делении plus_di_smooth и minus_di_smooth на atr не получить nan
        atr_safe = atr.copy()
        last_valid_atr = atr[-1]  # Последнее значение уже проверено на nan и 0
        atr_safe = np.where(np.isnan(atr_safe), last_valid_atr, atr_safe)

        # +DI и -DI (в процентах)
        plus_di_vals = (
            100 * plus_di_smooth / (atr_safe + 1e-10)
        )  # Защита от деления на ноль
        minus_di_vals = (
            100 * minus_di_smooth / (atr_safe + 1e-10)
        )  # Защита от деления на ноль

        # ✅ ИСПРАВЛЕНО: Проверяем только последние значения (первые period-1 значений всегда nan)
        if (
            len(plus_di_vals) == 0
            or np.isnan(plus_di_vals[-1])
            or len(minus_di_vals) == 0
            or np.isnan(minus_di_vals[-1])
        ):
            logger.debug(
                f"⚠️ ADX: последние значения +DI или -DI содержат nan после расчета "
                f"(+DI[-1]={plus_di_vals[-1] if len(plus_di_vals) > 0 else 'N/A'}, "
                f"-DI[-1]={minus_di_vals[-1] if len(minus_di_vals) > 0 else 'N/A'}), "
                f"используем fallback значение 0.0"
            )
            return 0.0

        # DX
        di_sum = plus_di_vals + minus_di_vals
        # Защита от деления на ноль и nan
        di_sum = np.where(
            di_sum == 0, 1e-10, di_sum
        )  # Заменяем нули на маленькое значение
        dx = 100 * np.abs(plus_di_vals - minus_di_vals) / di_sum

        # ✅ ИСПРАВЛЕНО: Проверяем только последнее значение DX
        if len(dx) == 0 or np.isnan(dx[-1]):
            logger.debug(
                f"⚠️ ADX: последнее значение DX содержит nan (DX[-1]={dx[-1] if len(dx) > 0 else 'N/A'}), "
                f"используем fallback значение 0.0"
            )
            return 0.0

        # ✅ ИСПРАВЛЕНО: Заменяем nan в DX на последнее валидное значение перед сглаживанием
        # Это нужно, чтобы Wilder's smoothing не дал nan в результате
        dx_safe = dx.copy()
        last_valid_dx = dx[-1]  # Последнее значение уже проверено на nan
        dx_safe = np.where(np.isnan(dx_safe), last_valid_dx, dx_safe)

        # ADX = сглаженный DX
        adx_vals = self._wilder_smooth(dx_safe, self.config.adx_period)

        # Проверяем финальное значение ADX
        if len(adx_vals) == 0 or np.isnan(adx_vals[-1]):
            logger.debug(
                f"⚠️ ADX: финальное значение nan или пустое, используем fallback значение 0.0"
            )
            return 0.0

        return float(adx_vals[-1])

    def _calculate_plus_di(self, candles: List) -> float:
        """Расчет +DI (Plus Directional Indicator)."""
        if len(candles) < self.config.adx_period + 1:
            return 0.0

        highs = np.array([self._get_value(c, "high") for c in candles])
        lows = np.array([self._get_value(c, "low") for c in candles])
        closes = np.array([self._get_value(c, "close") for c in candles])

        tr = self._calculate_tr(highs, lows, closes)
        plus_dm = self._calculate_plus_dm(highs)

        atr = self._wilder_smooth(tr, self.config.adx_period)
        plus_di_smooth = self._wilder_smooth(plus_dm, self.config.adx_period)

        # ✅ ИСПРАВЛЕНО: Защита от деления на ноль и nan
        # Проверяем только последнее значение (первые period-1 значений всегда nan в Wilder's smoothing)
        if len(atr) == 0 or np.isnan(atr[-1]) or atr[-1] == 0:
            return 0.0

        # ✅ ИСПРАВЛЕНО: Заменяем nan в atr на последнее валидное значение
        atr_safe = atr.copy()
        last_valid_atr = atr[-1]
        atr_safe = np.where(np.isnan(atr_safe), last_valid_atr, atr_safe)

        plus_di = 100 * plus_di_smooth / (atr_safe + 1e-10)  # Защита от деления на ноль

        if len(plus_di) == 0 or np.isnan(plus_di[-1]):
            return 0.0

        return float(plus_di[-1])

    def _calculate_minus_di(self, candles: List) -> float:
        """Расчет -DI (Minus Directional Indicator)."""
        if len(candles) < self.config.adx_period + 1:
            return 0.0

        highs = np.array([self._get_value(c, "high") for c in candles])
        lows = np.array([self._get_value(c, "low") for c in candles])
        closes = np.array([self._get_value(c, "close") for c in candles])

        tr = self._calculate_tr(highs, lows, closes)
        minus_dm = self._calculate_minus_dm(lows)

        atr = self._wilder_smooth(tr, self.config.adx_period)
        minus_di_smooth = self._wilder_smooth(minus_dm, self.config.adx_period)

        # ✅ ИСПРАВЛЕНО: Защита от деления на ноль и nan
        # Проверяем только последнее значение (первые period-1 значений всегда nan в Wilder's smoothing)
        if len(atr) == 0 or np.isnan(atr[-1]) or atr[-1] == 0:
            return 0.0

        # ✅ ИСПРАВЛЕНО: Заменяем nan в atr на последнее валидное значение
        atr_safe = atr.copy()
        last_valid_atr = atr[-1]
        atr_safe = np.where(np.isnan(atr_safe), last_valid_atr, atr_safe)

        minus_di = (
            100 * minus_di_smooth / (atr_safe + 1e-10)
        )  # Защита от деления на ноль

        if len(minus_di) == 0 or np.isnan(minus_di[-1]):
            return 0.0

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

        +DM = high - prev_high (если > 0 и > prev_low - low, иначе 0)
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 8.1.2026: Сравниваем up_move vs down_move
        """
        up_move = highs[1:] - highs[:-1]
        down_move = highs[0:-1] - highs[1:]  # prev_high - current_high (для сравнения)
        
        # Начинаем с нулей
        plus_dm = np.zeros(len(highs))
        
        # ✅ ИСПРАВЛЕНО: up_move > 0 И up_move > down_move
        # (оригинальная формула требует сравнения движений)
        plus_dm[1:] = np.where((up_move > 0) & (up_move > down_move), up_move, 0)

        return plus_dm

    def _calculate_minus_dm(self, lows: np.ndarray) -> np.ndarray:
        """
        -DM (Minus Directional Movement).

        -DM = prev_low - low (если > 0 и > high - prev_high, иначе 0)
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 8.1.2026: Сравниваем down_move vs up_move
        """
        down_move = lows[:-1] - lows[1:]
        up_move = lows[1:] - lows[:-1]  # current_low - prev_low (для сравнения)
        
        # Начинаем с нулей
        minus_dm = np.zeros(len(lows))
        
        # ✅ ИСПРАВЛЕНО: down_move > 0 И down_move > up_move
        # (оригинальная формула требует сравнения движений)
        minus_dm[1:] = np.where((down_move > 0) & (down_move > up_move), down_move, 0)

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
