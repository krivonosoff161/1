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

from loguru import logger
from pydantic import BaseModel, Field

from src.indicators.advanced.pivot_calculator import PivotCalculator, PivotLevels
from src.models import OHLCV
from src.okx_client import OKXClient


class PivotPointsConfig(BaseModel):
    """Конфигурация Pivot Points модуля"""

    enabled: bool = Field(default=True, description="Включить модуль")

    daily_timeframe: str = Field(
        default="1D", description="Таймфрейм для расчета (1D)"
    )

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

        # Получаем дневные свечи
        try:
            daily_candles = await self.client.get_candles(
                symbol=symbol, timeframe=self.config.daily_timeframe, limit=10
            )

            if not daily_candles:
                logger.warning(f"No daily candles for {symbol}")
                return None

            # Рассчитываем уровни
            levels = self.calculator.calculate_pivots(
                daily_candles, self.config.use_last_n_days
            )

            if levels:
                # Кэшируем
                self._levels_cache[symbol] = (levels, current_time)

            return levels

        except Exception as e:
            logger.error(f"Error fetching daily candles for {symbol}: {e}")
            return None

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

