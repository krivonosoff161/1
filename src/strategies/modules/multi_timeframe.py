"""
Multi-Timeframe Confirmation Module

Проверяет подтверждение торгового сигнала на старшем таймфрейме (5m).
Если 1m показывает LONG сигнал, проверяем что 5m тоже в бычьем тренде.

Logic:
1. Получаем свечи старшего таймфрейма (5m)
2. Рассчитываем EMA8 и EMA21
3. Определяем направление тренда:
   - Бычий: EMA8 > EMA21 и цена выше обеих
   - Медвежий: EMA8 < EMA21 и цена ниже обеих
4. Подтверждаем или блокируем сигнал
"""

import time
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
from loguru import logger
from pydantic import BaseModel, Field

from src.models import OHLCV
from src.okx_client import OKXClient


class MTFConfig(BaseModel):
    """Конфигурация Multi-Timeframe модуля"""

    confirmation_timeframe: str = Field(
        default="5m", description="Таймфрейм для подтверждения (5m, 15m, 1H)"
    )
    score_bonus: int = Field(
        default=2, ge=0, le=5, description="Бонус к score при подтверждении"
    )
    block_opposite: bool = Field(
        default=True, description="Блокировать противоположные сигналы"
    )
    ema_fast_period: int = Field(
        default=8, ge=3, le=20, description="Период быстрой EMA"
    )
    ema_slow_period: int = Field(
        default=21, ge=10, le=50, description="Период медленной EMA"
    )
    cache_ttl_seconds: int = Field(
        default=30, ge=10, le=300, description="Время жизни кэша свечей (секунды)"
    )


class MTFResult(BaseModel):
    """Результат Multi-Timeframe проверки"""

    confirmed: bool = Field(description="Сигнал подтвержден")
    blocked: bool = Field(description="Сигнал заблокирован")
    bonus: int = Field(default=0, description="Бонус к score")
    reason: str = Field(description="Причина решения")
    htf_trend: Optional[str] = Field(
        default=None, description="Тренд на старшем ТФ (BULLISH/BEARISH/NEUTRAL)"
    )


class MultiTimeframeFilter:
    """
    Multi-Timeframe фильтр для подтверждения сигналов.

    Использует старший таймфрейм для подтверждения направления тренда
    и фильтрации ложных сигналов на младшем таймфрейме.

    Example:
        >>> config = MTFConfig(confirmation_timeframe="5m", score_bonus=2)
        >>> mtf = MultiTimeframeFilter(client, config)
        >>> result = await mtf.check_confirmation("BTC-USDT", "LONG")
        >>> if result.confirmed:
        ...     score += result.bonus
    """

    def __init__(self, client: OKXClient, config: MTFConfig):
        """
        Инициализация MTF фильтра.

        Args:
            client: OKX API клиент
            config: Конфигурация MTF модуля
        """
        self.client = client
        self.config = config

        # Кэш для свечей старшего таймфрейма
        self._candles_cache: Dict[str, tuple[List[OHLCV], float]] = {}

        logger.info(
            f"MTF Filter initialized: {config.confirmation_timeframe}, "
            f"bonus={config.score_bonus}, block_opposite={config.block_opposite}"
        )

    async def check_confirmation(
        self, symbol: str, signal_side: str
    ) -> MTFResult:
        """
        Проверить подтверждение сигнала на старшем таймфрейме.

        Args:
            symbol: Торговая пара (например, "BTC-USDT")
            signal_side: Направление сигнала ("LONG" или "SHORT")

        Returns:
            MTFResult: Результат проверки с подтверждением или блокировкой

        Example:
            >>> result = await mtf.check_confirmation("BTC-USDT", "LONG")
            >>> if result.confirmed:
            ...     logger.info(f"MTF confirmed: {result.reason}")
            >>> elif result.blocked:
            ...     logger.warning(f"MTF blocked: {result.reason}")
        """
        try:
            # Получаем свечи старшего таймфрейма (с кэшированием)
            candles = await self._get_htf_candles(symbol)

            if not candles or len(candles) < self.config.ema_slow_period:
                logger.warning(
                    f"MTF: Недостаточно данных для {symbol} "
                    f"({len(candles) if candles else 0} свечей)"
                )
                return MTFResult(
                    confirmed=False,
                    blocked=False,
                    bonus=0,
                    reason="Недостаточно исторических данных",
                    htf_trend=None,
                )

            # Рассчитываем тренд на старшем ТФ
            htf_trend = self._calculate_trend(candles)

            # Логика подтверждения/блокировки
            if signal_side == "LONG":
                if htf_trend == "BULLISH":
                    # Бычий тренд на 5m подтверждает LONG на 1m
                    logger.info(
                        f"MTF ✅ {symbol}: LONG confirmed by {self.config.confirmation_timeframe} BULLISH trend"
                    )
                    return MTFResult(
                        confirmed=True,
                        blocked=False,
                        bonus=self.config.score_bonus,
                        reason=f"{self.config.confirmation_timeframe} в бычьем тренде (EMA8>EMA21)",
                        htf_trend=htf_trend,
                    )
                elif htf_trend == "BEARISH" and self.config.block_opposite:
                    # Медвежий тренд на 5m блокирует LONG на 1m
                    logger.info(
                        f"MTF ❌ {symbol}: LONG blocked by {self.config.confirmation_timeframe} BEARISH trend"
                    )
                    return MTFResult(
                        confirmed=False,
                        blocked=True,
                        bonus=0,
                        reason=f"{self.config.confirmation_timeframe} в медвежьем тренде - блокируем LONG",
                        htf_trend=htf_trend,
                    )
                else:
                    # Нейтральный тренд - не подтверждаем, но и не блокируем
                    logger.debug(
                        f"MTF ⚠️ {symbol}: LONG не подтвержден ({self.config.confirmation_timeframe} NEUTRAL)"
                    )
                    return MTFResult(
                        confirmed=False,
                        blocked=False,
                        bonus=0,
                        reason=f"{self.config.confirmation_timeframe} в нейтральном тренде",
                        htf_trend=htf_trend,
                    )

            elif signal_side == "SHORT":
                if htf_trend == "BEARISH":
                    # Медвежий тренд на 5m подтверждает SHORT на 1m
                    logger.info(
                        f"MTF ✅ {symbol}: SHORT confirmed by {self.config.confirmation_timeframe} BEARISH trend"
                    )
                    return MTFResult(
                        confirmed=True,
                        blocked=False,
                        bonus=self.config.score_bonus,
                        reason=f"{self.config.confirmation_timeframe} в медвежьем тренде (EMA8<EMA21)",
                        htf_trend=htf_trend,
                    )
                elif htf_trend == "BULLISH" and self.config.block_opposite:
                    # Бычий тренд на 5m блокирует SHORT на 1m
                    logger.info(
                        f"MTF ❌ {symbol}: SHORT blocked by {self.config.confirmation_timeframe} BULLISH trend"
                    )
                    return MTFResult(
                        confirmed=False,
                        blocked=True,
                        bonus=0,
                        reason=f"{self.config.confirmation_timeframe} в бычьем тренде - блокируем SHORT",
                        htf_trend=htf_trend,
                    )
                else:
                    # Нейтральный тренд
                    logger.debug(
                        f"MTF ⚠️ {symbol}: SHORT не подтвержден ({self.config.confirmation_timeframe} NEUTRAL)"
                    )
                    return MTFResult(
                        confirmed=False,
                        blocked=False,
                        bonus=0,
                        reason=f"{self.config.confirmation_timeframe} в нейтральном тренде",
                        htf_trend=htf_trend,
                    )

            else:
                logger.error(f"MTF: Неизвестное направление сигнала: {signal_side}")
                return MTFResult(
                    confirmed=False,
                    blocked=False,
                    bonus=0,
                    reason=f"Неизвестное направление: {signal_side}",
                    htf_trend=None,
                )

        except Exception as e:
            logger.error(f"MTF: Ошибка при проверке {symbol}: {e}", exc_info=True)
            return MTFResult(
                confirmed=False,
                blocked=False,
                bonus=0,
                reason=f"Ошибка: {str(e)}",
                htf_trend=None,
            )

    async def _get_htf_candles(self, symbol: str) -> List[OHLCV]:
        """
        Получить свечи старшего таймфрейма с кэшированием.

        Args:
            symbol: Торговая пара

        Returns:
            List[OHLCV]: Список свечей
        """
        current_time = time.time()

        # Проверяем кэш
        if symbol in self._candles_cache:
            cached_candles, cached_time = self._candles_cache[symbol]
            if current_time - cached_time < self.config.cache_ttl_seconds:
                logger.debug(
                    f"MTF: Используем кэшированные свечи для {symbol} "
                    f"(возраст: {current_time - cached_time:.1f}с)"
                )
                return cached_candles

        # Получаем свежие свечи
        try:
            # Запрашиваем больше свечей для расчета EMA
            limit = max(50, self.config.ema_slow_period * 2)
            candles = await self.client.get_candles(
                symbol=symbol, timeframe=self.config.confirmation_timeframe, limit=limit
            )

            # Кэшируем результат
            self._candles_cache[symbol] = (candles, current_time)

            logger.debug(
                f"MTF: Получено {len(candles)} свечей {self.config.confirmation_timeframe} для {symbol}"
            )
            return candles

        except Exception as e:
            logger.error(
                f"MTF: Ошибка при получении свечей {self.config.confirmation_timeframe} для {symbol}: {e}"
            )
            return []

    def _calculate_trend(self, candles: List[OHLCV]) -> str:
        """
        Рассчитать тренд на основе EMA8 и EMA21.

        Args:
            candles: Список свечей OHLCV

        Returns:
            str: "BULLISH", "BEARISH" или "NEUTRAL"
        """
        if len(candles) < self.config.ema_slow_period:
            return "NEUTRAL"

        # Извлекаем цены закрытия
        closes = np.array([float(c.close) for c in candles])

        # Рассчитываем EMA
        ema_fast = self._calculate_ema(closes, self.config.ema_fast_period)
        ema_slow = self._calculate_ema(closes, self.config.ema_slow_period)

        # Текущие значения (последняя свеча)
        current_price = closes[-1]
        current_ema_fast = ema_fast[-1]
        current_ema_slow = ema_slow[-1]

        logger.debug(
            f"MTF Trend: Price={current_price:.2f}, "
            f"EMA{self.config.ema_fast_period}={current_ema_fast:.2f}, "
            f"EMA{self.config.ema_slow_period}={current_ema_slow:.2f}"
        )

        # Определяем тренд
        if current_ema_fast > current_ema_slow and current_price > current_ema_fast:
            # Бычий тренд: быстрая EMA > медленной EMA и цена выше быстрой EMA
            return "BULLISH"
        elif current_ema_fast < current_ema_slow and current_price < current_ema_fast:
            # Медвежий тренд: быстрая EMA < медленной EMA и цена ниже быстрой EMA
            return "BEARISH"
        else:
            # Нейтральный: нет четкого тренда
            return "NEUTRAL"

    def _calculate_ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """
        Рассчитать Exponential Moving Average.

        Args:
            prices: Массив цен
            period: Период EMA

        Returns:
            np.ndarray: Массив значений EMA
        """
        ema = np.zeros_like(prices)
        multiplier = 2 / (period + 1)

        # Первое значение EMA = SMA
        ema[0] = prices[0]

        # Рассчитываем EMA
        for i in range(1, len(prices)):
            ema[i] = (prices[i] - ema[i - 1]) * multiplier + ema[i - 1]

        return ema

    def clear_cache(self, symbol: Optional[str] = None):
        """
        Очистить кэш свечей.

        Args:
            symbol: Конкретная пара или None для очистки всего кэша
        """
        if symbol:
            if symbol in self._candles_cache:
                del self._candles_cache[symbol]
                logger.debug(f"MTF: Кэш для {symbol} очищен")
        else:
            self._candles_cache.clear()
            logger.debug("MTF: Весь кэш очищен")

