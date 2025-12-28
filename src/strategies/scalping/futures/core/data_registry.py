"""
DataRegistry - Единый реестр всех данных.

Это единый источник истины для всех данных в системе:
- Market data (цены, объемы, свечи)
- Indicators (ADX, MA, RSI, etc.)
- Regimes (trending, ranging, choppy) с параметрами
- Balance и balance profile
- Margin данные
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from src.models import OHLCV

from .candle_buffer import CandleBuffer


class DataRegistry:
    """
    Единый реестр всех данных.

    Хранит:
    - market_data: рыночные данные (цены, объемы, свечи)
    - indicators: индикаторы (ADX, MA, RSI, etc.)
    - regimes: режимы рынка с параметрами
    - balance: баланс и профиль баланса
    - margin: данные маржи

    Thread-safe операции через asyncio.Lock
    """

    def __init__(self):
        """Инициализация реестра"""
        # Market data: symbol -> {price, volume, candles, etc.}
        self._market_data: Dict[str, Dict[str, Any]] = {}

        # Indicators: symbol -> {indicator_name -> value}
        self._indicators: Dict[str, Dict[str, Any]] = {}

        # Regimes: symbol -> {regime: str, params: dict, updated_at: datetime}
        self._regimes: Dict[str, Dict[str, Any]] = {}

        # Balance: {balance: float, profile: str, updated_at: datetime}
        self._balance: Optional[Dict[str, Any]] = None

        # Margin: {used: float, available: float, total: float, updated_at: datetime}
        self._margin: Optional[Dict[str, Any]] = None

        # ✅ НОВОЕ: CandleBuffer для каждого символа и таймфрейма
        # Структура: symbol -> timeframe -> CandleBuffer
        # Например: "BTC-USDT" -> "1m" -> CandleBuffer(max_size=200)
        self._candle_buffers: Dict[str, Dict[str, CandleBuffer]] = {}

        self._lock = asyncio.Lock()

    # ==================== MARKET DATA ====================

    async def update_market_data(self, symbol: str, data: Dict[str, Any]) -> None:
        """
        Обновить рыночные данные для символа.

        Args:
            symbol: Торговый символ
            data: Рыночные данные (price, volume, candles, etc.)
        """
        async with self._lock:
            if symbol not in self._market_data:
                self._market_data[symbol] = {}

            self._market_data[symbol].update(data)
            self._market_data[symbol]["updated_at"] = datetime.now()

            logger.debug(f"✅ DataRegistry: Обновлены market data для {symbol}")

    async def get_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получить рыночные данные для символа.

        Args:
            symbol: Торговый символ

        Returns:
            Рыночные данные или None
        """
        async with self._lock:
            return (
                self._market_data.get(symbol, {}).copy()
                if symbol in self._market_data
                else None
            )

    async def get_price(self, symbol: str) -> Optional[float]:
        """
        Получить текущую цену символа.

        Args:
            symbol: Торговый символ

        Returns:
            Цена или None
        """
        async with self._lock:
            market_data = self._market_data.get(symbol, {})
            return market_data.get("price") or market_data.get("last_price")

    # ==================== INDICATORS ====================

    async def update_indicator(
        self, symbol: str, indicator_name: str, value: Any
    ) -> None:
        """
        Обновить значение индикатора.

        Args:
            symbol: Торговый символ
            indicator_name: Название индикатора (adx, ma_fast, ma_slow, etc.)
            value: Значение индикатора
        """
        async with self._lock:
            if symbol not in self._indicators:
                self._indicators[symbol] = {}

            self._indicators[symbol][indicator_name] = value
            self._indicators[symbol]["updated_at"] = datetime.now()

            logger.debug(
                f"✅ DataRegistry: Обновлен индикатор {indicator_name} для {symbol}"
            )

    async def update_indicators(self, symbol: str, indicators: Dict[str, Any]) -> None:
        """
        Обновить несколько индикаторов сразу.

        Args:
            symbol: Торговый символ
            indicators: Словарь индикаторов {indicator_name -> value}
        """
        async with self._lock:
            if symbol not in self._indicators:
                self._indicators[symbol] = {}

            self._indicators[symbol].update(indicators)
            self._indicators[symbol]["updated_at"] = datetime.now()

            logger.debug(f"✅ DataRegistry: Обновлены индикаторы для {symbol}")

    async def get_indicator(self, symbol: str, indicator_name: str) -> Optional[Any]:
        """
        Получить значение индикатора.

        Args:
            symbol: Торговый символ
            indicator_name: Название индикатора

        Returns:
            Значение индикатора или None
        """
        async with self._lock:
            return (
                self._indicators.get(symbol, {}).get(indicator_name)
                if symbol in self._indicators
                else None
            )

    async def get_indicators(self, symbol: str, check_freshness: bool = True) -> Optional[Dict[str, Any]]:
        """
        Получить все индикаторы для символа.

        Args:
            symbol: Торговый символ
            check_freshness: Проверять актуальность индикаторов (по умолчанию True)
                           Если ADX старше 1 секунды → вернуть None для пересчета

        Returns:
            Словарь всех индикаторов или None (если данные устарели или отсутствуют)
        """
        async with self._lock:
            if symbol not in self._indicators:
                return None
            
            indicators = self._indicators.get(symbol, {}).copy()
            
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Проверка актуальности ADX (TTL 1 секунда)
            if check_freshness and "updated_at" in indicators:
                updated_at = indicators.get("updated_at")
                if updated_at and isinstance(updated_at, datetime):
                    time_diff = (datetime.now() - updated_at).total_seconds()
                    if time_diff > 1.0:  # ADX старше 1 секунды - считается устаревшим
                        logger.debug(
                            f"⚠️ DataRegistry: Индикаторы для {symbol} устарели "
                            f"(прошло {time_diff:.2f}с > 1.0с), требуется пересчет"
                        )
                        return None  # Возвращаем None для пересчета
            
            return indicators

    # ==================== REGIMES ====================

    async def update_regime(
        self,
        symbol: str,
        regime: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Обновить режим рынка для символа.

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending, ranging, choppy)
            params: Параметры режима (tp_percent, sl_percent, etc.)
        """
        async with self._lock:
            if symbol not in self._regimes:
                self._regimes[symbol] = {}

            self._regimes[symbol]["regime"] = regime
            if params:
                self._regimes[symbol]["params"] = params.copy()
            self._regimes[symbol]["updated_at"] = datetime.now()

            logger.debug(f"✅ DataRegistry: Обновлен режим для {symbol}: {regime}")

    async def get_regime(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получить режим рынка для символа.

        Args:
            symbol: Торговый символ

        Returns:
            {regime: str, params: dict, updated_at: datetime} или None
        """
        async with self._lock:
            return (
                self._regimes.get(symbol, {}).copy()
                if symbol in self._regimes
                else None
            )

    async def get_regime_name(self, symbol: str) -> Optional[str]:
        """
        Получить название режима для символа.

        Args:
            symbol: Торговый символ

        Returns:
            Название режима (trending, ranging, choppy) или None
        """
        async with self._lock:
            regime_data = self._regimes.get(symbol, {})
            return regime_data.get("regime") if regime_data else None

    # ==================== BALANCE ====================

    async def update_balance(
        self, balance: float, profile: Optional[str] = None
    ) -> None:
        """
        Обновить баланс и профиль баланса.

        Args:
            balance: Текущий баланс
            profile: Профиль баланса (small, medium, large)
        """
        async with self._lock:
            self._balance = {
                "balance": balance,
                "profile": profile,
                "updated_at": datetime.now(),
            }

            logger.debug(
                f"✅ DataRegistry: Обновлен баланс: {balance:.2f} USDT (profile={profile})"
            )

    async def get_balance(self) -> Optional[Dict[str, Any]]:
        """
        Получить баланс и профиль.

        Returns:
            {balance: float, profile: str, updated_at: datetime} или None
        """
        async with self._lock:
            return self._balance.copy() if self._balance else None

    async def get_balance_value(self) -> Optional[float]:
        """
        Получить значение баланса.

        Returns:
            Баланс или None
        """
        async with self._lock:
            return self._balance.get("balance") if self._balance else None

    async def get_balance_profile(self) -> Optional[str]:
        """
        Получить профиль баланса.

        Returns:
            Профиль баланса (small, medium, large) или None
        """
        async with self._lock:
            return self._balance.get("profile") if self._balance else None

    # ==================== MARGIN ====================

    async def update_margin(
        self,
        used: float,
        available: Optional[float] = None,
        total: Optional[float] = None,
    ) -> None:
        """
        Обновить данные маржи.

        Args:
            used: Использованная маржа
            available: Доступная маржа
            total: Общая маржа
        """
        async with self._lock:
            self._margin = {
                "used": used,
                "available": available,
                "total": total,
                "updated_at": datetime.now(),
            }

            available_str = f"{available:.2f}" if available is not None else "N/A"
            logger.debug(
                f"✅ DataRegistry: Обновлена маржа: used={used:.2f}, available={available_str}"
            )

    async def get_margin(self) -> Optional[Dict[str, Any]]:
        """
        Получить данные маржи.

        Returns:
            {used: float, available: float, total: float, updated_at: datetime} или None
        """
        async with self._lock:
            return self._margin.copy() if self._margin else None

    async def get_margin_used(self) -> Optional[float]:
        """
        Получить использованную маржу.

        Returns:
            Использованная маржа или None
        """
        async with self._lock:
            return self._margin.get("used") if self._margin else None

    # ==================== SYNC METHODS (для совместимости) ====================

    def get_price_sync(self, symbol: str) -> Optional[float]:
        """
        Синхронная версия get_price (для совместимости).

        ⚠️ ВНИМАНИЕ: Используйте только если нет доступа к async контексту!

        Args:
            symbol: Торговый символ

        Returns:
            Цена или None
        """
        market_data = self._market_data.get(symbol, {})
        return market_data.get("price") or market_data.get("last_price")

    def get_regime_name_sync(self, symbol: str) -> Optional[str]:
        """
        Синхронная версия get_regime_name (для совместимости).

        ⚠️ ВНИМАНИЕ: Используйте только если нет доступа к async контексту!

        Args:
            symbol: Торговый символ

        Returns:
            Название режима или None
        """
        regime_data = self._regimes.get(symbol, {})
        return regime_data.get("regime") if regime_data else None

    def get_balance_profile_sync(self) -> Optional[str]:
        """
        Синхронная версия get_balance_profile (для совместимости).

        ⚠️ ВНИМАНИЕ: Используйте только если нет доступа к async контексту!

        Returns:
            Профиль баланса или None
        """
        return self._balance.get("profile") if self._balance else None

    # ==================== CANDLES ====================

    async def add_candle(self, symbol: str, timeframe: str, candle: OHLCV) -> None:
        """
        Добавить новую свечу в буфер для символа и таймфрейма.

        Если свеча для новой минуты (или нового таймфрейма) - закрывает последнюю и добавляет новую.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, etc.)
            candle: Свеча OHLCV
        """
        async with self._lock:
            if symbol not in self._candle_buffers:
                self._candle_buffers[symbol] = {}

            if timeframe not in self._candle_buffers[symbol]:
                # Создаем новый буфер для таймфрейма
                max_size = (
                    200 if timeframe == "1m" else 100
                )  # 200 для 1m, 100 для остальных
                self._candle_buffers[symbol][timeframe] = CandleBuffer(
                    max_size=max_size
                )
                logger.debug(
                    f"📊 DataRegistry: Создан CandleBuffer для {symbol} {timeframe} (max_size={max_size})"
                )

            # Добавляем свечу в буфер
            await self._candle_buffers[symbol][timeframe].add_candle(candle)
            logger.debug(
                f"📊 DataRegistry: Добавлена свеча {symbol} {timeframe} "
                f"(timestamp={candle.timestamp}, price={candle.close:.2f})"
            )

    async def update_last_candle(
        self,
        symbol: str,
        timeframe: str,
        high: Optional[float] = None,
        low: Optional[float] = None,
        close: Optional[float] = None,
        volume: Optional[float] = None,
    ) -> bool:
        """
        Обновить последнюю (формирующуюся) свечу для символа и таймфрейма.

        Используется когда свеча еще формируется (не завершилась).

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, etc.)
            high: Новая максимальная цена
            low: Новая минимальная цена
            close: Новая цена закрытия
            volume: Новый объем

        Returns:
            True если свеча обновлена, False если буфер не существует или пуст
        """
        async with self._lock:
            if symbol not in self._candle_buffers:
                return False

            if timeframe not in self._candle_buffers[symbol]:
                return False

            buffer = self._candle_buffers[symbol][timeframe]
            return await buffer.update_last_candle(high, low, close, volume)

    async def get_candles(self, symbol: str, timeframe: str) -> List[OHLCV]:
        """
        Получить все свечи для символа и таймфрейма.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, etc.)

        Returns:
            Список свечей (от старых к новым) или пустой список
        """
        async with self._lock:
            if symbol not in self._candle_buffers:
                return []

            if timeframe not in self._candle_buffers[symbol]:
                return []

            buffer = self._candle_buffers[symbol][timeframe]
            return await buffer.get_candles()

    async def get_last_candle(self, symbol: str, timeframe: str) -> Optional[OHLCV]:
        """
        Получить последнюю свечу для символа и таймфрейма.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, etc.)

        Returns:
            Последняя свеча или None
        """
        async with self._lock:
            if symbol not in self._candle_buffers:
                return None

            if timeframe not in self._candle_buffers[symbol]:
                return None

            buffer = self._candle_buffers[symbol][timeframe]
            return await buffer.get_last_candle()

    async def initialize_candles(
        self,
        symbol: str,
        timeframe: str,
        candles: List[OHLCV],
        max_size: Optional[int] = None,
    ) -> None:
        """
        Инициализировать буфер свечей для символа и таймфрейма.

        Используется при старте бота для загрузки исторических свечей.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, etc.)
            candles: Список свечей для инициализации
            max_size: Максимальный размер буфера (по умолчанию: 200 для 1m, 100 для остальных)
        """
        async with self._lock:
            if symbol not in self._candle_buffers:
                self._candle_buffers[symbol] = {}

            # Определяем max_size если не передан
            if max_size is None:
                max_size = 200 if timeframe == "1m" else 100

            # Создаем новый буфер
            buffer = CandleBuffer(max_size=max_size)
            self._candle_buffers[symbol][timeframe] = buffer

            # Добавляем все свечи
            for candle in candles:
                await buffer.add_candle(candle)

            logger.info(
                f"📊 DataRegistry: Инициализирован буфер свечей для {symbol} {timeframe} "
                f"({len(candles)} свечей, max_size={max_size})"
            )
