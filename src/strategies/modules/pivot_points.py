"""
Pivot Points Filter Module

Использует классические Pivot Points для улучшения входов:
- Бонус к score при входе около уровней поддержки/сопротивления
- Фильтрация входов далеко от уровней

Logic:
- LONG около Support уровней (S1, S2, S3) = бонус
- SHORT около Resistance уровней (R1, R2, R3) = бонус
- Вход далеко от уровней = штраф или блокировка
"""

import time
from typing import Dict, List, Optional

import aiohttp
from loguru import logger
from pydantic import BaseModel, Field

from src.clients.spot_client import OKXClient
from src.indicators.advanced.pivot_calculator import (PivotCalculator,
                                                      PivotLevels)
from src.models import OHLCV


class PivotPointsConfig(BaseModel):
    """Конфигурация Pivot Points модуля"""

    enabled: bool = Field(default=True, description="Включить модуль")

    daily_timeframe: str = Field(default="1D", description="Таймфрейм для расчета (1D)")

    use_last_n_days: int = Field(
        default=1, ge=1, le=5, description="Использовать последние N дней"
    )

    level_tolerance_percent: float = Field(
        default=0.003,
        ge=0.001,
        le=0.01,
        description="Допуск около уровня (0.3%)",
    )

    score_bonus_near_level: int = Field(
        default=1, ge=0, le=3, description="Бонус за вход около уровня"
    )

    cache_ttl_seconds: int = Field(
        default=3600, ge=300, le=86400, description="Кэш уровней (секунды)"
    )


class PivotPointsResult(BaseModel):
    """Результат проверки Pivot Points"""

    near_level: bool = Field(description="Цена около уровня")
    level_name: Optional[str] = Field(default=None, description="Название уровня")
    level_value: Optional[float] = Field(default=None, description="Значение уровня")
    distance_percent: Optional[float] = Field(
        default=None, description="Расстояние до уровня (%)"
    )
    bonus: int = Field(default=0, description="Бонус к score")
    reason: str = Field(description="Причина решения")


class PivotPointsFilter:
    """
    Фильтр на основе Pivot Points для улучшения точности входов.

    Example:
        >>> config = PivotPointsConfig(score_bonus_near_level=1)
        >>> filter = PivotPointsFilter(client, config)
        >>> result = await filter.check_entry("BTC-USDT", 50100, "LONG")
        >>> if result.near_level:
        ...     score += result.bonus
    """

    def __init__(self, client: OKXClient, config: PivotPointsConfig):
        """
        Инициализация Pivot Points фильтра.

        Args:
            client: OKX API клиент
            config: Конфигурация модуля
        """
        self.client = client
        self.config = config
        self.calculator = PivotCalculator()

        # Кэш уровней: symbol -> (PivotLevels, timestamp)
        self._levels_cache: Dict[str, tuple[PivotLevels, float]] = {}

        logger.info(
            f"Pivot Points Filter initialized: "
            f"tolerance={config.level_tolerance_percent:.2%}, "
            f"bonus={config.score_bonus_near_level}"
        )

    async def check_entry(
        self, symbol: str, current_price: float, signal_side: str
    ) -> PivotPointsResult:
        """
        Проверить вход относительно Pivot уровней.

        Args:
            symbol: Торговая пара
            current_price: Текущая цена
            signal_side: Направление сигнала ("LONG" или "SHORT")

        Returns:
            PivotPointsResult: Результат проверки

        Example:
            >>> result = await filter.check_entry("BTC-USDT", 50100, "LONG")
            >>> if result.near_level and result.level_name == "S1":
            ...     logger.info("Entry near S1 support!")
        """
        if not self.config.enabled:
            return PivotPointsResult(
                near_level=False, bonus=0, reason="Pivot filter disabled"
            )

        try:
            # Получаем уровни Pivot (с кэшированием)
            levels = await self._get_pivot_levels(symbol)

            if not levels:
                return PivotPointsResult(
                    near_level=False,
                    bonus=0,
                    reason="Could not calculate pivot levels",
                )

            # Находим ближайший уровень
            nearest_name, nearest_value, distance = levels.get_nearest_level(
                current_price
            )
            distance_percent = distance / current_price

            # Проверяем находимся ли около уровня
            is_near = self.calculator.is_near_level(
                current_price, nearest_value, self.config.level_tolerance_percent
            )

            if not is_near:
                logger.debug(
                    f"Pivot: {symbol} ${current_price:.2f} NOT near any level "
                    f"(nearest: {nearest_name}=${nearest_value:.2f}, "
                    f"distance: {distance_percent:.2%})"
                )
                return PivotPointsResult(
                    near_level=False,
                    level_name=nearest_name,
                    level_value=nearest_value,
                    distance_percent=distance_percent,
                    bonus=0,
                    reason=f"Not near any level (nearest: {nearest_name})",
                )

            # Около уровня - проверяем логику входа
            bonus = 0

            if signal_side == "LONG":
                # LONG лучше входить от Support уровней (S1, S2, S3, PP)
                if nearest_name in ["S1", "S2", "S3", "PP"]:
                    bonus = self.config.score_bonus_near_level
                    logger.info(
                        f"✅ Pivot BONUS: {symbol} LONG near {nearest_name} support "
                        f"(${nearest_value:.2f}, distance: {distance_percent:.2%}) | +{bonus}"
                    )
                    return PivotPointsResult(
                        near_level=True,
                        level_name=nearest_name,
                        level_value=nearest_value,
                        distance_percent=distance_percent,
                        bonus=bonus,
                        reason=f"LONG near support {nearest_name}",
                    )
                else:
                    # LONG около Resistance - нейтрально
                    logger.debug(
                        f"⚠️ Pivot: {symbol} LONG near {nearest_name} resistance "
                        f"(not ideal, but allowed)"
                    )
                    return PivotPointsResult(
                        near_level=True,
                        level_name=nearest_name,
                        level_value=nearest_value,
                        distance_percent=distance_percent,
                        bonus=0,
                        reason=f"LONG near resistance {nearest_name} (neutral)",
                    )

            elif signal_side == "SHORT":
                # SHORT лучше входить от Resistance уровней (R1, R2, R3)
                if nearest_name in ["R1", "R2", "R3"]:
                    bonus = self.config.score_bonus_near_level
                    logger.info(
                        f"✅ Pivot BONUS: {symbol} SHORT near {nearest_name} resistance "
                        f"(${nearest_value:.2f}, distance: {distance_percent:.2%}) | +{bonus}"
                    )
                    return PivotPointsResult(
                        near_level=True,
                        level_name=nearest_name,
                        level_value=nearest_value,
                        distance_percent=distance_percent,
                        bonus=bonus,
                        reason=f"SHORT near resistance {nearest_name}",
                    )
                else:
                    # SHORT около Support/PP - нейтрально
                    logger.debug(
                        f"⚠️ Pivot: {symbol} SHORT near {nearest_name} support "
                        f"(not ideal, but allowed)"
                    )
                    return PivotPointsResult(
                        near_level=True,
                        level_name=nearest_name,
                        level_value=nearest_value,
                        distance_percent=distance_percent,
                        bonus=0,
                        reason=f"SHORT near support {nearest_name} (neutral)",
                    )

        except Exception as e:
            logger.error(f"Pivot filter error for {symbol}: {e}", exc_info=True)
            return PivotPointsResult(
                near_level=False, bonus=0, reason=f"Error: {str(e)}"
            )

    async def is_signal_valid(self, signal: Dict, market_data=None) -> bool:
        """
        Проверка валидности сигнала через Pivot Points фильтр.

        Pivot Points НЕ блокирует сигналы, только дает бонусы к score.

        Args:
            signal: Торговый сигнал (должен содержать "symbol", "side", "price")
            market_data: Рыночные данные (не используются)

        Returns:
            bool: Всегда True (не блокирует, только бонусы)
        """
        try:
            if not self.config.enabled:
                return True  # Фильтр отключен - разрешаем все

            symbol = signal.get("symbol")
            signal_side = signal.get("side")  # "buy" или "sell"
            current_price = signal.get("price", 0.0)

            if not symbol or not signal_side or not current_price:
                logger.debug(f"Pivot: Неполный сигнал для проверки: {signal}")
                return True  # Fail-open

            # Конвертируем side в формат PivotPoints ("buy" -> "LONG", "sell" -> "SHORT")
            signal_side_long = "LONG" if signal_side == "buy" else "SHORT"

            # Проверяем через check_entry (получаем бонус, но не блокируем)
            result = await self.check_entry(
                symbol=symbol,
                current_price=current_price,
                signal_side=signal_side_long,
            )

            # Добавляем бонус к score сигнала (если есть)
            if result.bonus > 0:
                signal["pivot_bonus"] = result.bonus
                signal["pivot_level"] = result.level_name
                logger.debug(
                    f"✅ PivotPoints: {symbol} {signal_side_long} получил бонус +{result.bonus} "
                    f"(уровень: {result.level_name})"
                )

            # Pivot Points НЕ блокирует сигналы - всегда разрешаем
            return True

        except Exception as e:
            logger.warning(
                f"⚠️ Ошибка проверки PivotPoints для сигнала: {e}, "
                f"разрешаем сигнал (fail-open)"
            )
            return True  # Fail-open: при ошибке разрешаем сигнал

    async def _get_pivot_levels(self, symbol: str) -> Optional[PivotLevels]:
        """
        Получить Pivot уровни с кэшированием.

        Args:
            symbol: Торговая пара

        Returns:
            PivotLevels или None
        """
        current_time = time.time()

        # Проверяем кэш
        if symbol in self._levels_cache:
            cached_levels, cached_time = self._levels_cache[symbol]
            if current_time - cached_time < self.config.cache_ttl_seconds:
                logger.debug(
                    f"Pivot: Using cached levels for {symbol} "
                    f"(age: {(current_time - cached_time)/60:.0f}min)"
                )
                return cached_levels

        # Получаем дневные свечи с fallback системой
        daily_candles = None

        # Попытка 1: Дневные свечи (1D) - предпочтительный вариант
        try:
            # ✅ АДАПТАЦИЯ: Получаем свечи напрямую через публичный API если client не поддерживает get_candles
            if self.client and hasattr(self.client, "get_candles"):
                daily_candles = await self.client.get_candles(
                    symbol=symbol, timeframe=self.config.daily_timeframe, limit=10
                )
            else:
                daily_candles = await self._fetch_candles_directly(
                    symbol, self.config.daily_timeframe, 10
                )

            if daily_candles:
                logger.debug(
                    f"Pivot: Got {len(daily_candles)} daily (1D) candles for {symbol}"
                )
        except Exception as e:
            logger.warning(f"Pivot: Failed to get 1D candles for {symbol}: {e}")

        # Попытка 2: Fallback на 4H свечи (группируем в дневные)
        if not daily_candles:
            try:
                logger.info(f"Pivot: Trying 4H candles fallback for {symbol}...")
                if self.client and hasattr(self.client, "get_candles"):
                    h4_candles = await self.client.get_candles(
                        symbol=symbol, timeframe="4H", limit=60  # 60 * 4H = 10 дней
                    )
                else:
                    h4_candles = await self._fetch_candles_directly(symbol, "4H", 60)

                if h4_candles:
                    # Группируем 4H свечи в дневные (6 свечей = 1 день)
                    daily_candles = self._group_to_daily(h4_candles, candles_per_day=6)
                    logger.info(
                        f"Pivot: Grouped {len(h4_candles)} 4H candles → {len(daily_candles)} daily for {symbol}"
                    )
            except Exception as e:
                logger.warning(f"Pivot: 4H fallback failed for {symbol}: {e}")

        # Попытка 3: Fallback на 1H свечи (группируем в дневные)
        if not daily_candles:
            try:
                logger.info(f"Pivot: Trying 1H candles fallback for {symbol}...")
                if self.client and hasattr(self.client, "get_candles"):
                    h1_candles = await self.client.get_candles(
                        symbol=symbol, timeframe="1H", limit=240  # 240 * 1H = 10 дней
                    )
                else:
                    h1_candles = await self._fetch_candles_directly(symbol, "1H", 240)

                if h1_candles:
                    # Группируем 1H свечи в дневные (24 свечи = 1 день)
                    daily_candles = self._group_to_daily(h1_candles, candles_per_day=24)
                    logger.info(
                        f"Pivot: Grouped {len(h1_candles)} 1H candles → {len(daily_candles)} daily for {symbol}"
                    )
            except Exception as e:
                logger.warning(f"Pivot: 1H fallback failed for {symbol}: {e}")

        # Если все попытки провалились
        if not daily_candles:
            logger.error(
                f"Pivot: All attempts failed for {symbol}, using cached levels if available"
            )
            # Возвращаем из кэша если есть (даже старый)
            if symbol in self._levels_cache:
                cached_levels, _ = self._levels_cache[symbol]
                logger.warning(f"Pivot: Using stale cache for {symbol}")
                return cached_levels
            return None

        # Рассчитываем уровни
        try:
            levels = self.calculator.calculate_pivots(
                daily_candles, self.config.use_last_n_days
            )

            if levels:
                # Кэшируем
                self._levels_cache[symbol] = (levels, current_time)
                logger.debug(f"Pivot: Cached levels for {symbol}")

            return levels

        except Exception as e:
            logger.error(f"Pivot: Error calculating levels for {symbol}: {e}")
            return None

    def _group_to_daily(
        self, candles: List[OHLCV], candles_per_day: int
    ) -> List[OHLCV]:
        """
        Группирует свечи меньшего таймфрейма в дневные.

        Args:
            candles: Список свечей (1H или 4H)
            candles_per_day: Сколько свечей в одном дне (24 для 1H, 6 для 4H)

        Returns:
            Список дневных свечей
        """
        if len(candles) < candles_per_day:
            return []

        daily_candles = []

        # Группируем свечи по дням
        for i in range(0, len(candles), candles_per_day):
            group = candles[i : i + candles_per_day]

            # Если неполный день - пропускаем
            if len(group) < candles_per_day:
                continue

            # Создаем дневную свечу
            daily_candle = OHLCV(
                symbol=group[0].symbol,
                timestamp=group[0].timestamp,  # Начало дня
                open=group[0].open,  # Open первой свечи
                high=max(c.high for c in group),  # Максимум за день
                low=min(c.low for c in group),  # Минимум за день
                close=group[-1].close,  # Close последней свечи
                volume=sum(c.volume for c in group),  # Сумма объемов
                timeframe="1D",
            )
            daily_candles.append(daily_candle)

        return daily_candles

    async def _fetch_candles_directly(
        self, symbol: str, timeframe: str, limit: int
    ) -> List[OHLCV]:
        """
        Получить свечи напрямую через публичный API OKX.

        Args:
            symbol: Торговая пара (например "BTC-USDT")
            timeframe: Таймфрейм ("1D", "4H", "1H" и т.д.)
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
                                f"Pivot: API вернул ошибку для {symbol}: {data.get('msg', 'Unknown')}"
                            )
                    else:
                        logger.warning(
                            f"Pivot: HTTP {resp.status} при получении свечей для {symbol}"
                        )

            return []

        except Exception as e:
            logger.error(f"Pivot: Ошибка при прямом получении свечей для {symbol}: {e}")
            return []

    def clear_cache(self, symbol: Optional[str] = None):
        """Очистить кэш уровней"""
        if symbol:
            if symbol in self._levels_cache:
                del self._levels_cache[symbol]
                logger.debug(f"Cleared pivot cache for {symbol}")
        else:
            self._levels_cache.clear()
            logger.debug("Cleared all pivot cache")

    def get_stats(self) -> Dict:
        """Получить статистику фильтра"""
        return {
            "enabled": self.config.enabled,
            "cached_symbols": len(self._levels_cache),
            "tolerance": self.config.level_tolerance_percent,
            "bonus": self.config.score_bonus_near_level,
        }
