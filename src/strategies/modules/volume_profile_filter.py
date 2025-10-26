"""
Volume Profile Filter Module

Использует Volume Profile для улучшения входов:
- Бонус за вход в зоне высокого объема (Value Area)
- Бонус за вход около POC (точка максимального объема)
- Блокировка входов в зонах низкого объема
"""

import time
from typing import Dict, Optional

from loguru import logger
from pydantic import BaseModel, Field

from src.clients.spot_client import OKXClient
from src.indicators.advanced.volume_profile import (VolumeProfileCalculator,
                                                    VolumeProfileData)


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
    reason: str = Field(description="Причина решения")


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

    def __init__(self, client: OKXClient, config: VolumeProfileConfig):
        """
        Инициализация Volume Profile фильтра.

        Args:
            client: OKX API клиент
            config: Конфигурация модуля
        """
        self.client = client
        self.config = config
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
            candles = await self.client.get_candles(
                symbol=symbol,
                timeframe=self.config.lookback_timeframe,
                limit=self.config.lookback_candles,
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

    def get_stats(self) -> Dict:
        """Получить статистику фильтра"""
        return {
            "enabled": self.config.enabled,
            "cached_symbols": len(self._profile_cache),
            "lookback_timeframe": self.config.lookback_timeframe,
            "lookback_candles": self.config.lookback_candles,
            "price_buckets": self.config.price_buckets,
        }
