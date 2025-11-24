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
from typing import Any, Dict, Optional

from loguru import logger


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

    async def get_indicators(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получить все индикаторы для символа.

        Args:
            symbol: Торговый символ

        Returns:
            Словарь всех индикаторов или None
        """
        async with self._lock:
            return (
                self._indicators.get(symbol, {}).copy()
                if symbol in self._indicators
                else None
            )

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

            logger.debug(
                f"✅ DataRegistry: Обновлена маржа: used={used:.2f}, available={available:.2f if available else 'N/A'}"
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
