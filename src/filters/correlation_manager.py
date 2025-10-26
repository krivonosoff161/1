"""
Correlation Manager

Управляет расчетом корреляции между торговыми парами для избежания
одновременных позиций в сильно коррелированных активах.

Использует Pearson correlation для определения степени зависимости
движения цен между парами.
"""

import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
from loguru import logger
from pydantic import BaseModel, Field

from src.models import OHLCV
from src.clients.spot_client import OKXClient


class CorrelationConfig(BaseModel):
    """Конфигурация расчета корреляции"""

    lookback_candles: int = Field(
        default=100, ge=20, le=500, description="Количество свечей для расчета"
    )
    timeframe: str = Field(
        default="5m", description="Таймфрейм для расчета корреляции"
    )
    cache_ttl_seconds: int = Field(
        default=300, ge=60, le=3600, description="Время жизни кэша (секунды)"
    )
    high_correlation_threshold: float = Field(
        default=0.7,
        ge=0.5,
        le=1.0,
        description="Порог высокой корреляции (>0.7 = сильная)",
    )


class CorrelationData(BaseModel):
    """Данные о корреляции между парами"""

    pair1: str
    pair2: str
    correlation: float = Field(description="Коэффициент корреляции Пирсона (-1 to 1)")
    calculated_at: float = Field(description="Timestamp расчета")
    candles_count: int = Field(description="Количество свечей использованных для расчета")

    @property
    def is_strong(self) -> bool:
        """Сильная корреляция (>0.7 или <-0.7)"""
        return abs(self.correlation) > 0.7

    @property
    def is_positive(self) -> bool:
        """Положительная корреляция (активы двигаются вместе)"""
        return self.correlation > 0


class CorrelationManager:
    """
    Менеджер корреляций между торговыми парами.

    Рассчитывает и кэширует корреляции Пирсона между парами на основе
    исторических данных цен закрытия.

    Example:
        >>> config = CorrelationConfig(lookback_candles=100)
        >>> manager = CorrelationManager(client, config)
        >>> corr = await manager.get_correlation("BTC-USDT", "ETH-USDT")
        >>> if corr.is_strong:
        ...     logger.info(f"Strong correlation: {corr.correlation:.2f}")
    """

    def __init__(self, client: OKXClient, config: CorrelationConfig):
        """
        Инициализация менеджера корреляций.

        Args:
            client: OKX API клиент
            config: Конфигурация расчета корреляции
        """
        self.client = client
        self.config = config

        # Кэш корреляций: (pair1, pair2) -> CorrelationData
        self._correlation_cache: Dict[Tuple[str, str], CorrelationData] = {}

        # Кэш свечей: symbol -> (candles, timestamp)
        self._candles_cache: Dict[str, Tuple[List[OHLCV], float]] = {}

        logger.info(
            f"Correlation Manager initialized: {config.timeframe}, "
            f"lookback={config.lookback_candles}, threshold={config.high_correlation_threshold}"
        )

    async def get_correlation(
        self, pair1: str, pair2: str, force_refresh: bool = False
    ) -> Optional[CorrelationData]:
        """
        Получить корреляцию между двумя парами.

        Args:
            pair1: Первая торговая пара
            pair2: Вторая торговая пара
            force_refresh: Принудительно пересчитать (игнорировать кэш)

        Returns:
            CorrelationData или None если не удалось рассчитать

        Example:
            >>> corr = await manager.get_correlation("BTC-USDT", "ETH-USDT")
            >>> logger.info(f"BTC-ETH correlation: {corr.correlation:.2f}")
        """
        # Нормализуем порядок пар (всегда в алфавитном порядке)
        pair1, pair2 = sorted([pair1, pair2])

        # Проверяем кэш (если не принудительное обновление)
        if not force_refresh:
            cache_key = (pair1, pair2)
            if cache_key in self._correlation_cache:
                cached_corr = self._correlation_cache[cache_key]
                age = time.time() - cached_corr.calculated_at
                if age < self.config.cache_ttl_seconds:
                    logger.debug(
                        f"Correlation: Using cached {pair1}/{pair2}: "
                        f"{cached_corr.correlation:.3f} (age: {age:.0f}s)"
                    )
                    return cached_corr

        try:
            # Получаем свечи для обеих пар
            candles1 = await self._get_candles(pair1)
            candles2 = await self._get_candles(pair2)

            if not candles1 or not candles2:
                logger.warning(
                    f"Correlation: No candles for {pair1} or {pair2}"
                )
                return None

            # Проверяем достаточно ли данных
            min_candles = min(len(candles1), len(candles2))
            if min_candles < 20:
                logger.warning(
                    f"Correlation: Insufficient data for {pair1}/{pair2} "
                    f"({min_candles} candles, need 20+)"
                )
                return None

            # Синхронизируем по времени (берем последние N свечей)
            sync_count = min(min_candles, self.config.lookback_candles)
            prices1 = np.array([float(c.close) for c in candles1[-sync_count:]])
            prices2 = np.array([float(c.close) for c in candles2[-sync_count:]])

            # Рассчитываем корреляцию Пирсона
            correlation = self._calculate_pearson_correlation(prices1, prices2)

            # Создаем объект данных
            corr_data = CorrelationData(
                pair1=pair1,
                pair2=pair2,
                correlation=correlation,
                calculated_at=time.time(),
                candles_count=sync_count,
            )

            # Кэшируем результат
            cache_key = (pair1, pair2)
            self._correlation_cache[cache_key] = corr_data

            logger.info(
                f"Correlation calculated: {pair1}/{pair2} = {correlation:.3f} "
                f"({'STRONG' if corr_data.is_strong else 'weak'}, "
                f"{'positive' if corr_data.is_positive else 'negative'}, "
                f"n={sync_count})"
            )

            return corr_data

        except Exception as e:
            logger.error(f"Error calculating correlation {pair1}/{pair2}: {e}", exc_info=True)
            return None

    async def get_all_correlations(
        self, symbols: List[str]
    ) -> Dict[Tuple[str, str], CorrelationData]:
        """
        Получить корреляции для всех пар символов.

        Args:
            symbols: Список торговых пар

        Returns:
            Dict с корреляциями: (pair1, pair2) -> CorrelationData

        Example:
            >>> symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
            >>> all_corr = await manager.get_all_correlations(symbols)
            >>> for (p1, p2), corr in all_corr.items():
            ...     logger.info(f"{p1}/{p2}: {corr.correlation:.2f}")
        """
        correlations = {}

        # Генерируем все уникальные пары
        for i, pair1 in enumerate(symbols):
            for pair2 in symbols[i + 1 :]:
                corr = await self.get_correlation(pair1, pair2)
                if corr:
                    correlations[(pair1, pair2)] = corr

        logger.info(
            f"Calculated {len(correlations)} correlations for {len(symbols)} symbols"
        )
        return correlations

    def get_highly_correlated_pairs(
        self, symbol: str, all_symbols: List[str], threshold: Optional[float] = None
    ) -> List[Tuple[str, float]]:
        """
        Получить пары с высокой корреляцией к данному символу.

        Args:
            symbol: Целевой символ
            all_symbols: Все доступные символы
            threshold: Порог корреляции (по умолчанию из конфига)

        Returns:
            List[(symbol, correlation)] для сильно коррелированных пар

        Example:
            >>> # Найти пары сильно коррелированные с BTC
            >>> pairs = manager.get_highly_correlated_pairs(
            ...     "BTC-USDT",
            ...     ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
            ... )
            >>> # [("ETH-USDT", 0.85), ("SOL-USDT", 0.72)]
        """
        if threshold is None:
            threshold = self.config.high_correlation_threshold

        correlated = []

        for other_symbol in all_symbols:
            if other_symbol == symbol:
                continue

            # Проверяем кэш
            pair1, pair2 = sorted([symbol, other_symbol])
            cache_key = (pair1, pair2)

            if cache_key in self._correlation_cache:
                corr_data = self._correlation_cache[cache_key]
                if abs(corr_data.correlation) >= threshold:
                    correlated.append((other_symbol, corr_data.correlation))

        # Сортируем по силе корреляции (по убыванию абсолютного значения)
        correlated.sort(key=lambda x: abs(x[1]), reverse=True)

        return correlated

    async def _get_candles(self, symbol: str) -> List[OHLCV]:
        """
        Получить свечи с кэшированием.

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
                    f"Correlation: Using cached candles for {symbol} "
                    f"(age: {current_time - cached_time:.0f}s)"
                )
                return cached_candles

        # Получаем свежие свечи
        try:
            limit = self.config.lookback_candles + 10  # Запас
            candles = await self.client.get_candles(
                symbol=symbol, timeframe=self.config.timeframe, limit=limit
            )

            # Кэшируем
            self._candles_cache[symbol] = (candles, current_time)

            logger.debug(
                f"Correlation: Fetched {len(candles)} candles {self.config.timeframe} for {symbol}"
            )
            return candles

        except Exception as e:
            logger.error(f"Error fetching candles for {symbol}: {e}")
            return []

    def _calculate_pearson_correlation(
        self, prices1: np.ndarray, prices2: np.ndarray
    ) -> float:
        """
        Рассчитать корреляцию Пирсона между двумя массивами цен.

        Args:
            prices1: Массив цен первой пары
            prices2: Массив цен второй пары

        Returns:
            float: Коэффициент корреляции (-1 to 1)
        """
        # Проверка на одинаковую длину
        if len(prices1) != len(prices2):
            raise ValueError("Price arrays must have the same length")

        # Рассчитываем корреляцию
        correlation_matrix = np.corrcoef(prices1, prices2)
        correlation = correlation_matrix[0, 1]

        # Обрабатываем NaN (если данные константны)
        if np.isnan(correlation):
            logger.warning("NaN correlation detected (constant prices?), returning 0")
            return 0.0

        return float(correlation)

    def clear_cache(self, symbol: Optional[str] = None):
        """
        Очистить кэш корреляций и/или свечей.

        Args:
            symbol: Конкретный символ или None для очистки всего
        """
        if symbol:
            # Очистка для конкретного символа
            if symbol in self._candles_cache:
                del self._candles_cache[symbol]

            # Очистка корреляций связанных с этим символом
            keys_to_remove = [
                key
                for key in self._correlation_cache.keys()
                if symbol in key
            ]
            for key in keys_to_remove:
                del self._correlation_cache[key]

            logger.debug(f"Cleared correlation cache for {symbol}")
        else:
            # Полная очистка
            self._correlation_cache.clear()
            self._candles_cache.clear()
            logger.debug("Cleared all correlation cache")

    def get_cache_stats(self) -> Dict[str, int]:
        """
        Получить статистику кэша.

        Returns:
            Dict со статистикой
        """
        return {
            "correlations_cached": len(self._correlation_cache),
            "candles_cached": len(self._candles_cache),
            "cache_ttl_seconds": self.config.cache_ttl_seconds,
        }

