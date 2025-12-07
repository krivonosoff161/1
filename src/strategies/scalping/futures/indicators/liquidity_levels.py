"""
Liquidity Levels Detector

Определяет ближайшие уровни ликвидности (высокий объем) выше и ниже текущей цены.
Используется для умного закрытия позиций в exit_analyzer.
"""

import asyncio
import time
from typing import Dict, Optional

from loguru import logger

from src.clients.futures_client import OKXFuturesClient


class LiquidityLevelsDetector:
    """
    Детектор уровней ликвидности.

    Определяет ближайшие зоны высокого объема (ликвидности) выше и ниже текущей цены
    на основе данных стакана и истории объемов.
    """

    ORDERBOOK_ENDPOINT = "/api/v5/market/books"
    TICKER_ENDPOINT = "/api/v5/market/ticker"

    def __init__(self, client: Optional[OKXFuturesClient] = None):
        """
        Инициализация детектора уровней ликвидности.

        Args:
            client: Клиент OKX для получения данных стакана (опционально)
        """
        self.client = client
        self._cache: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()
        self._cache_ttl = 30  # Кеш на 30 секунд

        logger.debug("LiquidityLevelsDetector initialized")

    async def get_nearest_liquidity(
        self, symbol: str, current_price: Optional[float] = None
    ) -> Optional[Dict[str, Dict]]:
        """
        Получить ближайшие уровни ликвидности выше и ниже текущей цены.

        Args:
            symbol: Торговый символ
            current_price: Текущая цена (если не указана, получаем из тикера)

        Returns:
            Словарь с ключами "below" и "above", каждый содержит:
            {
                "volume": float,          # Объем ликвидности в USDT
                "distance_pct": float,   # Расстояние от цены в процентах
                "price_level": float,     # Ценовой уровень ликвидности
                "depth_usd": float       # Глубина стакана в USDT
            }
            Или None если не удалось получить данные
        """
        if not self.client:
            logger.debug("LiquidityLevelsDetector: клиент не указан, возвращаем None")
            return None

        # Проверяем кеш
        now = time.time()
        cached = self._cache.get(symbol)
        if cached and (now - cached.get("timestamp", 0)) < self._cache_ttl:
            return cached.get("data")

        try:
            async with self._lock:
                # Повторная проверка кеша после получения lock
                cached = self._cache.get(symbol)
                if cached and (now - cached.get("timestamp", 0)) < self._cache_ttl:
                    return cached.get("data")

                # Получаем текущую цену если не указана
                if current_price is None:
                    current_price = await self._get_current_price(symbol)
                    if current_price is None:
                        return None

                # Получаем данные стакана
                orderbook = await self._fetch_orderbook(symbol)
                if not orderbook:
                    return None

                # Анализируем уровни ликвидности
                liquidity_data = self._analyze_liquidity_levels(
                    orderbook, current_price
                )

                # Сохраняем в кеш
                self._cache[symbol] = {
                    "data": liquidity_data,
                    "timestamp": now,
                }

                return liquidity_data

        except Exception as e:
            logger.warning(
                f"⚠️ LiquidityLevelsDetector: ошибка получения уровней ликвидности для {symbol}: {e}"
            )
            return None

    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """Получить текущую цену из тикера"""
        try:
            response = await self.client.public_request(
                self.TICKER_ENDPOINT, params={"instId": symbol}
            )
            if response and "data" in response and len(response["data"]) > 0:
                ticker = response["data"][0]
                last_price = ticker.get("last")
                if last_price:
                    return float(last_price)
        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить цену для {symbol}: {e}")
        return None

    async def _fetch_orderbook(self, symbol: str, depth: int = 20) -> Optional[Dict]:
        """
        Получить данные стакана.

        Args:
            symbol: Торговый символ
            depth: Глубина стакана (количество уровней)

        Returns:
            Словарь с данными стакана или None
        """
        try:
            response = await self.client.public_request(
                self.ORDERBOOK_ENDPOINT,
                params={"instId": symbol, "sz": str(depth)},
            )
            if response and "data" in response and len(response["data"]) > 0:
                return response["data"][0]
        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить стакан для {symbol}: {e}")
        return None

    def _analyze_liquidity_levels(
        self, orderbook: Dict, current_price: float
    ) -> Dict[str, Dict]:
        """
        Анализирует уровни ликвидности из стакана.

        Args:
            orderbook: Данные стакана от OKX
            current_price: Текущая цена

        Returns:
            Словарь с уровнями ликвидности выше и ниже цены
        """
        below_liquidity = {
            "volume": 0.0,
            "distance_pct": 0.0,
            "price_level": 0.0,
            "depth_usd": 0.0,
        }
        above_liquidity = {
            "volume": 0.0,
            "distance_pct": 0.0,
            "price_level": 0.0,
            "depth_usd": 0.0,
        }

        try:
            # Получаем биды (покупки) и аски (продажи)
            bids = orderbook.get("bids", [])  # Список [цена, объем, ...]
            asks = orderbook.get("asks", [])  # Список [цена, объем, ...]

            if not bids or not asks:
                return {"below": below_liquidity, "above": above_liquidity}

            # Анализируем биды (ликвидность ниже цены)
            # Ищем уровень с максимальным объемом ниже текущей цены
            max_bid_volume = 0.0
            max_bid_price = 0.0
            total_bid_depth = 0.0

            for bid in bids[:10]:  # Берем первые 10 уровней
                if len(bid) >= 2:
                    bid_price = float(bid[0])
                    bid_volume = float(bid[1])
                    bid_value_usd = bid_price * bid_volume

                    if bid_price < current_price:
                        total_bid_depth += bid_value_usd
                        if bid_value_usd > max_bid_volume:
                            max_bid_volume = bid_value_usd
                            max_bid_price = bid_price

            if max_bid_price > 0:
                distance_pct = ((current_price - max_bid_price) / current_price) * 100
                below_liquidity = {
                    "volume": max_bid_volume,
                    "distance_pct": distance_pct,
                    "price_level": max_bid_price,
                    "depth_usd": total_bid_depth,
                }

            # Анализируем аски (ликвидность выше цены)
            # Ищем уровень с максимальным объемом выше текущей цены
            max_ask_volume = 0.0
            max_ask_price = 0.0
            total_ask_depth = 0.0

            for ask in asks[:10]:  # Берем первые 10 уровней
                if len(ask) >= 2:
                    ask_price = float(ask[0])
                    ask_volume = float(ask[1])
                    ask_value_usd = ask_price * ask_volume

                    if ask_price > current_price:
                        total_ask_depth += ask_value_usd
                        if ask_value_usd > max_ask_volume:
                            max_ask_volume = ask_value_usd
                            max_ask_price = ask_price

            if max_ask_price > 0:
                distance_pct = ((max_ask_price - current_price) / current_price) * 100
                above_liquidity = {
                    "volume": max_ask_volume,
                    "distance_pct": distance_pct,
                    "price_level": max_ask_price,
                    "depth_usd": total_ask_depth,
                }

            logger.debug(
                f"LiquidityLevels: {symbol} @ {current_price:.2f} - "
                f"below: {max_bid_volume:,.0f} USD @ {max_bid_price:.2f} ({below_liquidity['distance_pct']:.2f}%), "
                f"above: {max_ask_volume:,.0f} USD @ {max_ask_price:.2f} ({above_liquidity['distance_pct']:.2f}%)"
            )

        except Exception as e:
            logger.warning(f"⚠️ Ошибка анализа уровней ликвидности: {e}", exc_info=True)

        return {"below": below_liquidity, "above": above_liquidity}
