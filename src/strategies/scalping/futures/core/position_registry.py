"""
PositionRegistry - Единый реестр всех позиций.

Это единый источник истины для всех позиций в системе.
Хранит position данные + metadata (entry_time, regime, balance_profile, etc.)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger


@dataclass
class PositionMetadata:
    """Метаданные позиции"""

    entry_time: datetime
    regime: Optional[str] = None  # trending, ranging, choppy
    balance_profile: Optional[str] = None  # small, medium, large
    entry_price: Optional[float] = None
    position_side: Optional[str] = None  # long, short
    order_id: Optional[str] = None
    tp_percent: Optional[float] = None
    sl_percent: Optional[float] = None
    leverage: Optional[int] = None
    size_in_coins: Optional[float] = None
    margin_used: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для сериализации"""
        return {
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "regime": self.regime,
            "balance_profile": self.balance_profile,
            "entry_price": self.entry_price,
            "position_side": self.position_side,
            "order_id": self.order_id,
            "tp_percent": self.tp_percent,
            "sl_percent": self.sl_percent,
            "leverage": self.leverage,
            "size_in_coins": self.size_in_coins,
            "margin_used": self.margin_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PositionMetadata":
        """Создание из словаря"""
        # Парсим entry_time
        entry_time = None
        if data.get("entry_time"):
            if isinstance(data["entry_time"], str):
                try:
                    entry_time = datetime.fromisoformat(
                        data["entry_time"].replace("Z", "+00:00")
                    )
                except:
                    entry_time = None
            elif isinstance(data["entry_time"], datetime):
                entry_time = data["entry_time"]

        # Парсим created_at
        created_at = datetime.now()
        if data.get("created_at"):
            if isinstance(data["created_at"], str):
                try:
                    created_at = datetime.fromisoformat(
                        data["created_at"].replace("Z", "+00:00")
                    )
                except:
                    created_at = datetime.now()
            elif isinstance(data["created_at"], datetime):
                created_at = data["created_at"]

        return cls(
            entry_time=entry_time or datetime.now(),
            regime=data.get("regime"),
            balance_profile=data.get("balance_profile"),
            entry_price=data.get("entry_price"),
            position_side=data.get("position_side"),
            order_id=data.get("order_id"),
            tp_percent=data.get("tp_percent"),
            sl_percent=data.get("sl_percent"),
            leverage=data.get("leverage"),
            size_in_coins=data.get("size_in_coins"),
            margin_used=data.get("margin_used"),
            created_at=created_at,
        )


class PositionRegistry:
    """
    Единый реестр всех позиций.

    Хранит:
    - position: данные позиции с биржи (dict)
    - metadata: метаданные позиции (PositionMetadata)

    Thread-safe операции через asyncio.Lock
    """

    def __init__(self):
        """Инициализация реестра"""
        self._positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position dict
        self._metadata: Dict[str, PositionMetadata] = {}  # symbol -> metadata
        self._lock = asyncio.Lock()

    async def register_position(
        self,
        symbol: str,
        position: Dict[str, Any],
        metadata: Optional[PositionMetadata] = None,
    ) -> None:
        """
        Регистрация позиции в реестре.

        Args:
            symbol: Торговый символ
            position: Данные позиции с биржи (dict)
            metadata: Метаданные позиции (если None, создается с entry_time=now)
        """
        async with self._lock:
            self._positions[symbol] = position.copy()

            if metadata is None:
                metadata = PositionMetadata(entry_time=datetime.now())

            self._metadata[symbol] = metadata

            logger.debug(
                f"✅ PositionRegistry: Зарегистрирована позиция {symbol} "
                f"(entry_time={metadata.entry_time}, regime={metadata.regime})"
            )

    async def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получить данные позиции.

        Args:
            symbol: Торговый символ

        Returns:
            Данные позиции или None
        """
        async with self._lock:
            return (
                self._positions.get(symbol, {}).copy()
                if symbol in self._positions
                else None
            )

    async def get_metadata(self, symbol: str) -> Optional[PositionMetadata]:
        """
        Получить метаданные позиции.

        Args:
            symbol: Торговый символ

        Returns:
            Метаданные позиции или None
        """
        async with self._lock:
            return self._metadata.get(symbol)

    async def update_position(
        self,
        symbol: str,
        position_updates: Optional[Dict[str, Any]] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Обновить позицию и/или метаданные.

        Args:
            symbol: Торговый символ
            position_updates: Обновления для position (dict)
            metadata_updates: Обновления для metadata (dict)
        """
        async with self._lock:
            if symbol not in self._positions:
                logger.warning(
                    f"⚠️ PositionRegistry: Попытка обновить несуществующую позицию {symbol}"
                )
                return

            # Обновляем position
            if position_updates:
                self._positions[symbol].update(position_updates)

            # Обновляем metadata
            if metadata_updates:
                if symbol in self._metadata:
                    # Обновляем существующие метаданные
                    for key, value in metadata_updates.items():
                        if hasattr(self._metadata[symbol], key):
                            setattr(self._metadata[symbol], key, value)
                else:
                    # Создаем новые метаданные
                    self._metadata[symbol] = PositionMetadata.from_dict(
                        metadata_updates
                    )

            logger.debug(f"✅ PositionRegistry: Обновлена позиция {symbol}")

    async def unregister_position(self, symbol: str) -> None:
        """
        Удалить позицию из реестра.

        Args:
            symbol: Торговый символ
        """
        async with self._lock:
            if symbol in self._positions:
                del self._positions[symbol]
            if symbol in self._metadata:
                del self._metadata[symbol]

            logger.debug(f"✅ PositionRegistry: Удалена позиция {symbol}")

    async def has_position(self, symbol: str) -> bool:
        """
        Проверить наличие позиции.

        Args:
            symbol: Торговый символ

        Returns:
            True если позиция зарегистрирована
        """
        async with self._lock:
            return symbol in self._positions

    async def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """
        Получить все позиции.

        Returns:
            Копия словаря всех позиций
        """
        async with self._lock:
            return {k: v.copy() for k, v in self._positions.items()}

    async def get_all_metadata(self) -> Dict[str, PositionMetadata]:
        """
        Получить все метаданные.

        Returns:
            Копия словаря всех метаданных
        """
        async with self._lock:
            return self._metadata.copy()

    async def get_position_count(self) -> int:
        """
        Получить количество позиций.

        Returns:
            Количество зарегистрированных позиций
        """
        async with self._lock:
            return len(self._positions)

    def get_position_sync(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Синхронная версия get_position (для совместимости).

        ⚠️ ВНИМАНИЕ: Используйте только если нет доступа к async контексту!

        Args:
            symbol: Торговый символ

        Returns:
            Данные позиции или None
        """
        return (
            self._positions.get(symbol, {}).copy()
            if symbol in self._positions
            else None
        )

    def get_metadata_sync(self, symbol: str) -> Optional[PositionMetadata]:
        """
        Синхронная версия get_metadata (для совместимости).

        ⚠️ ВНИМАНИЕ: Используйте только если нет доступа к async контексту!

        Args:
            symbol: Торговый символ

        Returns:
            Метаданные позиции или None
        """
        return self._metadata.get(symbol)

    def has_position_sync(self, symbol: str) -> bool:
        """
        Синхронная версия has_position (для совместимости).

        ⚠️ ВНИМАНИЕ: Используйте только если нет доступа к async контексту!

        Args:
            symbol: Торговый символ

        Returns:
            True если позиция зарегистрирована
        """
        return symbol in self._positions
