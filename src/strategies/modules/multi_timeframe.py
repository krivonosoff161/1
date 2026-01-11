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
from typing import Dict, List, Optional, Union

import aiohttp
import numpy as np
from loguru import logger
from pydantic import BaseModel, Field

from src.models import OHLCV


class MTFConfig(BaseModel):
    """Конфигурация Multi-Timeframe модуля"""

    confirmation_timeframe: str = Field(
        default="5m", description="Таймфрейм для подтверждения (5m, 15m, 1H)"
    )
    score_bonus: Union[int, float] = Field(
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
        default=15,
        ge=5,
        le=300,
        description="Cache TTL in seconds. Reduced from 30 to 15 on 11.01.2026",
    )
    fail_open_enabled: bool = Field(
        default=False,
        description="Разрешать периодически пропускать сигналы без подтверждения",
    )
    fail_open_blocks: int = Field(
        default=3,
        ge=1,
        description="Количество подряд блокировок перед fail-open",
    )
    fail_open_cooldown_seconds: int = Field(
        default=60,
        ge=1,
        description="Кулдаун после срабатывания fail-open",
    )
    block_neutral: bool = Field(
        default=False,
        description="Блокировать сигналы при NEUTRAL тренде на старшем ТФ (более строгая фильтрация)",
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

    def __init__(
        self,
        client=None,
        config: MTFConfig = None,
        data_registry=None,
        structured_logger=None,
    ):
        """
        Инициализация MTF фильтра.

        Args:
            client: OKX API клиент (опционально, можно получать свечи напрямую)
            config: Конфигурация MTF модуля (если None - использует дефолтные значения)
            data_registry: DataRegistry для получения свечей (опционально, приоритет над API)
            structured_logger: StructuredLogger для логирования использования свечей (опционально)
        """
        self.client = client  # Может быть None - тогда получаем свечи напрямую
        self.config = config or MTFConfig()  # Дефолтная конфигурация если не передана
        self.data_registry = (
            data_registry  # ✅ КРИТИЧЕСКОЕ: DataRegistry для получения свечей
        )
        self.structured_logger = (
            structured_logger  # ✅ НОВОЕ: StructuredLogger для логирования
        )

        # Кэш для свечей старшего таймфрейма
        self._candles_cache: Dict[str, tuple[List[OHLCV], float]] = {}
        self._fail_open_state: Dict[str, Dict[str, float]] = {}

        logger.info(
            f"MTF Filter initialized: {self.config.confirmation_timeframe}, "
            f"bonus={self.config.score_bonus}, block_opposite={self.config.block_opposite}"
        )

    def update_parameters(self, new_config: MTFConfig):
        """
        Обновить параметры MTF (при переключении режима ARM).

        Args:
            new_config: Новая конфигурация MTF
        """
        old_block = self.config.block_opposite
        old_bonus = self.config.score_bonus

        self.config = new_config

        logger.info(
            f"🔄 MTF параметры обновлены:\n"
            f"   block_opposite: {old_block} → {new_config.block_opposite}\n"
            f"   score_bonus: {old_bonus} → {new_config.score_bonus}\n"
            f"   timeframe: {new_config.confirmation_timeframe}"
        )
        # Сбросить fail-open состояние при изменении конфигурации
        self._fail_open_state.clear()

    async def check_confirmation(self, symbol: str, signal_side: str) -> MTFResult:
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
                    # Нейтральный тренд: не блокируем, не подтверждаем (рекомендация избежать, но допускаем)
                    # ✅ СМЯГЧЕНО (11.01.2026): NEUTRAL теперь только совет, а не блок (даже если block_neutral=True)
                    logger.debug(
                        f"MTF ⚠️ {symbol}: LONG не подтвержден ({self.config.confirmation_timeframe} NEUTRAL, no penalty)"
                    )
                    return MTFResult(
                        confirmed=False,
                        blocked=False,
                        bonus=0,
                        reason=f"{self.config.confirmation_timeframe} в нейтральном тренде (не блокируем, но бонуса нет)",
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
                    # Нейтральный тренд: не блокируем, не подтверждаем (рекомендация избежать, но допускаем)
                    # ✅ СМЯГЧЕНО (11.01.2026): NEUTRAL теперь только совет, а не блок (даже если block_neutral=True)
                    logger.debug(
                        f"MTF ⚠️ {symbol}: SHORT не подтвержден ({self.config.confirmation_timeframe} NEUTRAL, no penalty)"
                    )
                    return MTFResult(
                        confirmed=False,
                        blocked=False,
                        bonus=0,
                        reason=f"{self.config.confirmation_timeframe} в нейтральном тренде (не блокируем, но бонуса нет)",
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

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Сначала пытаемся получить свечи из DataRegistry
            if self.data_registry:
                try:
                    candles = await self.data_registry.get_candles(
                        symbol, self.config.confirmation_timeframe
                    )
                    if candles and len(candles) >= self.config.ema_slow_period:
                        logger.debug(
                            f"MTF: Получено {len(candles)} свечей {self.config.confirmation_timeframe} "
                            f"для {symbol} из DataRegistry"
                        )
                        # ✅ НОВОЕ: Логируем использование DataRegistry
                        if (
                            hasattr(self, "structured_logger")
                            and self.structured_logger
                        ):
                            try:
                                self.structured_logger.log_candle_usage(
                                    filter_name="MTF",
                                    symbol=symbol,
                                    timeframe=self.config.confirmation_timeframe,
                                    source="dataregistry",
                                    candles_count=len(candles),
                                    fallback_to_api=False,
                                )
                            except Exception as e:
                                logger.debug(
                                    f"⚠️ Ошибка логирования использования свечей MTF: {e}"
                                )
                        # Кэшируем результат из DataRegistry
                        if candles:
                            self._candles_cache[symbol] = (candles, current_time)
                        return candles
                    else:
                        logger.info(  # ✅ ИЗМЕНЕНО: INFO вместо DEBUG для важного события
                            f"⚠️ MTF: DataRegistry содержит недостаточно свечей для {symbol} "
                            f"({len(candles) if candles else 0} свечей, нужно минимум {self.config.ema_slow_period}), "
                            f"используем fallback к API"
                        )
                        # ✅ НОВОЕ: Логируем fallback к API
                        if (
                            hasattr(self, "structured_logger")
                            and self.structured_logger
                        ):
                            try:
                                self.structured_logger.log_candle_usage(
                                    filter_name="MTF",
                                    symbol=symbol,
                                    timeframe=self.config.confirmation_timeframe,
                                    source="api",
                                    candles_count=len(candles) if candles else 0,
                                    fallback_to_api=True,
                                )
                            except Exception as e:
                                logger.debug(f"⚠️ Ошибка логирования fallback MTF: {e}")
                except Exception as e:
                    logger.debug(
                        f"MTF: Ошибка получения свечей из DataRegistry для {symbol}: {e}, "
                        f"используем fallback к API"
                    )

            # Fallback: запрашиваем через API
            # ✅ АДАПТАЦИЯ: Получаем свечи напрямую через публичный API (работает для futures и spot)
            if self.client and hasattr(self.client, "get_candles"):
                # Если клиент поддерживает get_candles - используем его
                candles = await self.client.get_candles(
                    symbol=symbol,
                    timeframe=self.config.confirmation_timeframe,
                    limit=limit,
                )
            else:
                # ✅ Получаем напрямую через публичный API (как в signal_generator)
                candles = await self._fetch_candles_directly(
                    symbol, self.config.confirmation_timeframe, limit
                )

            # Кэшируем результат
            if candles:
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

    async def _fetch_candles_directly(
        self, symbol: str, timeframe: str, limit: int
    ) -> List[OHLCV]:
        """
        Получить свечи напрямую через публичный API OKX.

        Args:
            symbol: Торговая пара (например "BTC-USDT")
            timeframe: Таймфрейм ("5m", "15m", "1H" и т.д.)
            limit: Количество свечей

        Returns:
            List[OHLCV]: Список свечей
        """
        try:
            # Формируем instId для futures (SWAP)
            inst_id = f"{symbol}-SWAP"

            # Формируем URL для публичного API
            url = f"https://www.okx.com/api/v5/market/candles"
            params = {"instId": inst_id, "bar": timeframe, "limit": limit}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == "0" and data.get("data"):
                            candles_data = data["data"]

                            # Конвертируем в OHLCV формат
                            ohlcv_list = []
                            for candle in candles_data:
                                if len(candle) >= 6:
                                    ohlcv_item = OHLCV(
                                        timestamp=int(candle[0])
                                        // 1000,  # OKX возвращает в миллисекундах
                                        symbol=symbol,
                                        open=float(candle[1]),
                                        high=float(candle[2]),
                                        low=float(candle[3]),
                                        close=float(candle[4]),
                                        volume=float(candle[5]),
                                    )
                                    ohlcv_list.append(ohlcv_item)

                            # Сортируем по timestamp (старые -> новые)
                            ohlcv_list.sort(key=lambda x: x.timestamp)

                            return ohlcv_list
                        else:
                            logger.warning(
                                f"MTF: API вернул ошибку для {symbol}: {data.get('msg', 'Unknown')}"
                            )
                    else:
                        logger.warning(
                            f"MTF: HTTP {resp.status} при получении свечей для {symbol}"
                        )

            return []

        except Exception as e:
            logger.error(f"MTF: Ошибка при прямом получении свечей для {symbol}: {e}")
            return []

    async def is_signal_valid(self, signal: Dict, market_data=None) -> bool:
        """
        Проверка валидности сигнала через MTF фильтр.

        Args:
            signal: Торговый сигнал (должен содержать "symbol" и "side")
            market_data: Рыночные данные (не используются в MTF)

        Returns:
            bool: True если сигнал валиден, False если заблокирован
        """
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")  # "buy" или "sell"

            if not symbol or not side:
                logger.warning(f"MTF: Неполный сигнал для проверки: {signal}")
                return True  # Fail-open: если нет данных - разрешаем

            # Конвертируем side в формат MTF ("buy" -> "LONG", "sell" -> "SHORT")
            signal_side = "LONG" if side == "buy" else "SHORT"

            # Проверяем подтверждение
            result = await self.check_confirmation(symbol, signal_side)

            # Если сигнал заблокирован - возвращаем False
            if result.blocked:
                if self._should_fail_open(symbol):
                    signal["mtf_fail_open"] = True
                    logger.info(
                        f"🔓 MTF fail-open: {symbol} {signal_side} допущен после серии блокировок"
                    )
                    return True
                logger.debug(
                    f"🔍 MTF заблокировал сигнал {symbol} {signal_side}: {result.reason}"
                )
                return False

            self._reset_fail_open(symbol)

            # Если сигнал подтвержден или нейтрален - разрешаем (может быть улучшен score)
            return True

        except Exception as e:
            logger.warning(
                f"⚠️ Ошибка проверки MTF для сигнала: {e}, разрешаем сигнал (fail-open)"
            )
            return True  # Fail-open: при ошибке разрешаем сигнал

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

    def _should_fail_open(self, symbol: str) -> bool:
        if not getattr(self.config, "fail_open_enabled", False):
            return False
        now = time.time()
        state = self._fail_open_state.setdefault(
            symbol,
            {"consecutive": 0, "cooldown_until": 0.0},
        )
        if state["cooldown_until"] > now:
            return False

        state["consecutive"] = state.get("consecutive", 0) + 1
        threshold = max(1, getattr(self.config, "fail_open_blocks", 3))
        if state["consecutive"] >= threshold:
            cooldown = max(1, getattr(self.config, "fail_open_cooldown_seconds", 60))
            state["consecutive"] = 0
            state["cooldown_until"] = now + cooldown
            return True
        return False

    def _reset_fail_open(self, symbol: str) -> None:
        state = self._fail_open_state.get(symbol)
        if not state:
            return
        state["consecutive"] = 0
