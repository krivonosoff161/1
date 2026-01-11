"""
Volume Profile Filter Module

Использует Volume Profile для улучшения входов:
- Бонус за вход в зоне высокого объема (Value Area)
- Бонус за вход около POC (точка максимального объема)
- Блокировка входов в зонах низкого объема
"""

import time
from typing import Dict, List, Optional, Tuple

import aiohttp
from loguru import logger
from pydantic import BaseModel, Field

from src.clients.spot_client import OKXClient
from src.indicators.advanced.volume_profile import (VolumeProfileCalculator,
                                                    VolumeProfileData)
from src.models import OHLCV


class VolumeProfileConfig(BaseModel):
    """Конфигурация Volume Profile модуля"""

    enabled: bool = Field(default=True, description="Включить модуль")

    lookback_timeframe: str = Field(
        default="1H", description="Таймфрейм для расчета профиля"
    )
    lookback_candles: int = Field(
        default=100, ge=20, le=500, description="Количество свечей для профиля"
    )

    price_buckets: int = Field(
        default=50, ge=20, le=100, description="Количество ценовых уровней"
    )

    value_area_percent: float = Field(
        default=70.0, ge=50.0, le=90.0, description="Процент для Value Area"
    )

    score_bonus_in_value_area: int = Field(
        default=1, ge=0, le=3, description="Бонус за вход в Value Area"
    )

    score_bonus_near_poc: int = Field(
        default=1, ge=0, le=3, description="Бонус за вход около POC"
    )

    poc_tolerance_percent: float = Field(
        default=0.005,
        ge=0.001,
        le=0.02,
        description="Допуск около POC (0.5%)",
    )

    cache_ttl_seconds: int = Field(
        default=600, ge=60, le=3600, description="Кэш профиля (секунды)"
    )


class VolumeProfileResult(BaseModel):
    """Результат проверки Volume Profile"""

    in_value_area: bool = Field(description="Цена в Value Area")
    near_poc: bool = Field(description="Цена около POC")
    bonus: int = Field(default=0, description="Бонус к score")
    poc_value: Optional[float] = Field(default=None, description="Значение POC")
    vah_value: Optional[float] = Field(default=None, description="Value Area High")
    val_value: Optional[float] = Field(default=None, description="Value Area Low")
    reason: str = Field(default="No reason provided", description="Причина решения")


class VolumeProfileFilter:
    """
    Фильтр на основе Volume Profile.

    Использует распределение объема для определения зон высокой ликвидности
    и оптимальных точек входа.

    Example:
        >>> config = VolumeProfileConfig(score_bonus_in_value_area=1)
        >>> filter = VolumeProfileFilter(client, config)
        >>> result = await filter.check_entry("BTC-USDT", 50100)
        >>> if result.in_value_area:
        ...     score += result.bonus
    """

    def __init__(
        self, client: OKXClient, config: VolumeProfileConfig, data_registry=None
    ):
        """
        Инициализация Volume Profile фильтра.

        Args:
            client: OKX API клиент
            config: Конфигурация модуля
            data_registry: DataRegistry для получения свечей (опционально, приоритет над API)
        """
        self.client = client
        self.config = config
        self.data_registry = (
            data_registry  # ✅ КРИТИЧЕСКОЕ: DataRegistry для получения свечей
        )
        self.calculator = VolumeProfileCalculator(price_buckets=config.price_buckets)

        # Кэш профилей: symbol -> (VolumeProfileData, timestamp)
        self._profile_cache: Dict[str, Tuple[VolumeProfileData, float]] = {}

        logger.info(
            f"Volume Profile Filter initialized: "
            f"{config.lookback_timeframe}, "
            f"lookback={config.lookback_candles}, "
            f"buckets={config.price_buckets}"
        )

    async def check_entry(
        self, symbol: str, current_price: float
    ) -> VolumeProfileResult:
        """
        Проверить вход относительно Volume Profile.

        Args:
            symbol: Торговая пара
            current_price: Текущая цена

        Returns:
            VolumeProfileResult: Результат проверки

        Example:
            >>> result = await filter.check_entry("BTC-USDT", 50100)
            >>> logger.info(f"In Value Area: {result.in_value_area}, Bonus: {result.bonus}")
        """
        if not self.config.enabled:
            return VolumeProfileResult(
                in_value_area=False,
                near_poc=False,
                bonus=0,
                reason="Volume Profile disabled",
            )

        try:
            # Получаем профиль (с кэшированием)
            profile = await self._get_volume_profile(symbol)

            if not profile:
                return VolumeProfileResult(
                    in_value_area=False,
                    near_poc=False,
                    bonus=0,
                    reason="Could not calculate volume profile",
                )

            # Проверяем нахождение в Value Area
            in_value_area = profile.is_in_value_area(current_price)

            # Проверяем близость к POC
            poc_distance = abs(current_price - profile.poc) / profile.poc
            near_poc = poc_distance <= self.config.poc_tolerance_percent

            # Рассчитываем бонус
            bonus = 0
            reasons = []

            if near_poc:
                bonus += self.config.score_bonus_near_poc
                reasons.append(f"near POC (${profile.poc:.2f})")
                logger.info(
                    f"✅ Volume Profile: {symbol} near POC | "
                    f"Price: ${current_price:.2f}, POC: ${profile.poc:.2f}, "
                    f"Distance: {poc_distance:.2%}"
                )

            if in_value_area:
                bonus += self.config.score_bonus_in_value_area
                reasons.append(f"in Value Area (${profile.val:.2f}-${profile.vah:.2f})")
                logger.info(
                    f"✅ Volume Profile: {symbol} in Value Area | "
                    f"Price: ${current_price:.2f}, "
                    f"VAL: ${profile.val:.2f}, VAH: ${profile.vah:.2f}"
                )

            if bonus > 0:
                reason = f"Entry {', '.join(reasons)}"
            elif in_value_area:
                reason = "In Value Area (no bonus)"
            else:
                reason = f"Outside Value Area (POC=${profile.poc:.2f}, VA: ${profile.val:.2f}-${profile.vah:.2f})"
                logger.debug(
                    f"Volume Profile: {symbol} outside Value Area | "
                    f"Price: ${current_price:.2f}"
                )

            return VolumeProfileResult(
                in_value_area=in_value_area,
                near_poc=near_poc,
                bonus=bonus,
                poc_value=profile.poc,
                vah_value=profile.vah,
                val_value=profile.val,
                reason=reason,
            )

        except Exception as e:
            logger.error(f"Volume Profile error for {symbol}: {e}", exc_info=True)
            return VolumeProfileResult(
                in_value_area=False,
                near_poc=False,
                bonus=0,
                reason=f"Error: {str(e)}",
            )

    async def _get_volume_profile(self, symbol: str) -> Optional[VolumeProfileData]:
        """
        Получить Volume Profile с кэшированием.

        Args:
            symbol: Торговая пара

        Returns:
            VolumeProfileData или None
        """
        current_time = time.time()

        # Проверяем кэш
        if symbol in self._profile_cache:
            cached_profile, cached_time = self._profile_cache[symbol]
            if current_time - cached_time < self.config.cache_ttl_seconds:
                logger.debug(
                    f"Volume Profile: Using cached for {symbol} "
                    f"(age: {(current_time - cached_time)/60:.0f}min)"
                )
                return cached_profile

        # Получаем свечи для расчета
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Сначала пытаемся получить свечи из DataRegistry
            if self.data_registry:
                try:
                    candles = await self.data_registry.get_candles(
                        symbol, self.config.lookback_timeframe
                    )
                    if candles and len(candles) >= self.config.lookback_candles:
                        logger.debug(
                            f"Volume Profile: Получено {len(candles)} свечей {self.config.lookback_timeframe} "
                            f"для {symbol} из DataRegistry"
                        )
                        # Рассчитываем профиль из свечей DataRegistry
                        profile = self.calculator.calculate(
                            candles, self.config.value_area_percent
                        )
                        if profile:
                            self._profile_cache[symbol] = (profile, current_time)
                        return profile
                    else:
                        logger.debug(
                            f"Volume Profile: DataRegistry содержит недостаточно свечей для {symbol} "
                            f"({len(candles) if candles else 0} свечей, нужно минимум {self.config.lookback_candles}), "
                            f"используем fallback к API"
                        )
                except Exception as e:
                    logger.debug(
                        f"Volume Profile: Ошибка получения свечей из DataRegistry для {symbol}: {e}, "
                        f"используем fallback к API"
                    )

            # Fallback: запрашиваем через API
            # ✅ АДАПТАЦИЯ: Получаем свечи напрямую через публичный API если client не поддерживает get_candles
            if self.client and hasattr(self.client, "get_candles"):
                candles = await self.client.get_candles(
                    symbol=symbol,
                    timeframe=self.config.lookback_timeframe,
                    limit=self.config.lookback_candles,
                )
            else:
                candles = await self._fetch_candles_directly(
                    symbol, self.config.lookback_timeframe, self.config.lookback_candles
                )

            if not candles:
                logger.warning(f"No candles for volume profile: {symbol}")
                return None

            # Рассчитываем профиль
            profile = self.calculator.calculate(candles, self.config.value_area_percent)

            if profile:
                # Кэшируем
                self._profile_cache[symbol] = (profile, current_time)

            return profile

        except Exception as e:
            logger.error(f"Error fetching candles for volume profile {symbol}: {e}")
            return None

    def clear_cache(self, symbol: Optional[str] = None):
        """Очистить кэш профилей"""
        if symbol:
            if symbol in self._profile_cache:
                del self._profile_cache[symbol]
                logger.debug(f"Cleared volume profile cache for {symbol}")
        else:
            self._profile_cache.clear()
            logger.debug("Cleared all volume profile cache")

    async def is_signal_valid(self, signal: Dict, market_data=None) -> bool:
        """
        Проверка валидности сигнала через Volume Profile фильтр.

        Volume Profile НЕ блокирует сигналы, только дает бонусы к score.

        Args:
            signal: Торговый сигнал (должен содержать "symbol", "price")
            market_data: Рыночные данные (не используются)

        Returns:
            bool: Всегда True (не блокирует, только бонусы)
        """
        try:
            if not self.config.enabled:
                return True  # Фильтр отключен - разрешаем все

            symbol = signal.get("symbol")
            current_price = signal.get("price", 0.0)

            if not symbol or not current_price:
                logger.debug(f"VolumeProfile: Неполный сигнал для проверки: {signal}")
                return True  # Fail-open

            # Проверяем через check_entry (получаем бонус, но не блокируем)
            result = await self.check_entry(
                symbol=symbol,
                current_price=current_price,
            )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем что результат валиден перед использованием
            if not result or not isinstance(result, VolumeProfileResult):
                logger.warning(
                    f"VolumeProfile: Некорректный результат для {symbol}, позволяем сигнал"
                )
                return True  # Fail-open при ошибке

            # Добавляем бонус к score сигнала (если есть)
            if result.bonus > 0:
                signal["volume_profile_bonus"] = result.bonus
                if result.near_poc:
                    signal["near_poc"] = True
                if result.in_value_area:
                    signal["in_value_area"] = True
                logger.debug(
                    f"✅ VolumeProfile: {symbol} получил бонус +{result.bonus} "
                    f"(POC: {result.near_poc}, VA: {result.in_value_area})"
                )

            # Volume Profile НЕ блокирует сигналы - всегда разрешаем
            return True

        except Exception as e:
            logger.warning(
                f"⚠️ Ошибка проверки VolumeProfile для сигнала: {e}, "
                f"разрешаем сигнал (fail-open)"
            )
            return True  # Fail-open: при ошибке разрешаем сигнал

    async def _fetch_candles_directly(
        self, symbol: str, timeframe: str, limit: int
    ) -> List[OHLCV]:
        """
        Получить свечи напрямую через публичный API OKX.

        Args:
            symbol: Торговая пара (например "BTC-USDT")
            timeframe: Таймфрейм ("1H", "4H", "1D" и т.д.)
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
                                f"VolumeProfile: API вернул ошибку для {symbol}: {data.get('msg', 'Unknown')}"
                            )
                    else:
                        logger.warning(
                            f"VolumeProfile: HTTP {resp.status} при получении свечей для {symbol}"
                        )

            return []

        except Exception as e:
            logger.error(
                f"VolumeProfile: Ошибка при прямом получении свечей для {symbol}: {e}"
            )
            return []

    def get_stats(self) -> Dict:
        """Получить статистику фильтра"""
        return {
            "enabled": self.config.enabled,
            "cached_symbols": len(self._profile_cache),
            "lookback_timeframe": self.config.lookback_timeframe,
            "lookback_candles": self.config.lookback_candles,
            "price_buckets": self.config.price_buckets,
        }
