"""
PositionRegistry - Единый реестр всех позиций.

Это единый источник истины для всех позиций в системе.
Хранит position данные + metadata (entry_time, regime, balance_profile, etc.)
"""

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class PositionMetadata:
    """Метаданные позиции"""

    entry_time: datetime
    # ✅ Трассировка (для связывания entry/partial/final close в логах и CSV)
    position_id: Optional[str] = None
    regime: Optional[str] = None  # trending, ranging, choppy
    balance_profile: Optional[str] = None  # small, medium, large
    entry_price: Optional[float] = None
    position_side: Optional[str] = None  # long, short
    order_id: Optional[str] = None
    order_type: Optional[str] = None
    tp_percent: Optional[float] = None
    sl_percent: Optional[float] = None
    leverage: Optional[int] = None
    size_in_coins: Optional[float] = None
    margin_used: Optional[float] = None
    min_holding_seconds: Optional[
        float
    ] = None  # ✅ НОВОЕ: Минимальное время удержания (из конфига)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # ✅ НОВОЕ: Отслеживание максимальной прибыли
    peak_profit_usd: float = 0.0  # Максимальная прибыль в USD
    peak_profit_time: Optional[datetime] = None  # Время достижения максимума
    peak_profit_price: Optional[float] = None  # Цена при максимуме прибыли
    tp_extension_count: int = 0  # Количество продлений TP
    partial_tp_executed: bool = False  # ✅ ИСПРАВЛЕНО: Флаг выполнения partial_tp
    scaling_history: Optional[
        List[Dict[str, Any]]
    ] = None  # ✅ НОВОЕ: История добавлений к позиции

    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для сериализации"""
        return {
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "position_id": self.position_id,
            "regime": self.regime,
            "balance_profile": self.balance_profile,
            "entry_price": self.entry_price,
            "position_side": self.position_side,
            "order_id": self.order_id,
            "order_type": self.order_type,
            "tp_percent": self.tp_percent,
            "sl_percent": self.sl_percent,
            "leverage": self.leverage,
            "size_in_coins": self.size_in_coins,
            "margin_used": self.margin_used,
            "min_holding_seconds": self.min_holding_seconds,  # ✅ НОВОЕ
            "created_at": self.created_at.isoformat() if self.created_at else None,
            # ✅ НОВОЕ: Отслеживание максимальной прибыли
            "peak_profit_usd": self.peak_profit_usd,
            "peak_profit_time": self.peak_profit_time.isoformat()
            if self.peak_profit_time
            else None,
            "peak_profit_price": self.peak_profit_price,
            "tp_extension_count": self.tp_extension_count,
            "partial_tp_executed": self.partial_tp_executed,  # ✅ ИСПРАВЛЕНО
            "scaling_history": self.scaling_history,  # ✅ НОВОЕ: История добавлений
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
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Убеждаемся, что entry_time всегда offset-aware
                # Это предотвращает ошибку "can't compare offset-naive and offset-aware datetimes"
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)

        # Парсим created_at
        created_at = datetime.now(timezone.utc)
        if data.get("created_at"):
            if isinstance(data["created_at"], str):
                try:
                    created_at = datetime.fromisoformat(
                        data["created_at"].replace("Z", "+00:00")
                    )
                except:
                    created_at = datetime.now(timezone.utc)
            elif isinstance(data["created_at"], datetime):
                created_at = data["created_at"]
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Убеждаемся, что created_at всегда offset-aware
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)

        # Парсим peak_profit_time
        peak_profit_time = None
        if data.get("peak_profit_time"):
            if isinstance(data["peak_profit_time"], str):
                try:
                    peak_profit_time = datetime.fromisoformat(
                        data["peak_profit_time"].replace("Z", "+00:00")
                    )
                except:
                    peak_profit_time = None
            elif isinstance(data["peak_profit_time"], datetime):
                peak_profit_time = data["peak_profit_time"]
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Убеждаемся, что peak_profit_time всегда offset-aware
                if peak_profit_time and peak_profit_time.tzinfo is None:
                    peak_profit_time = peak_profit_time.replace(tzinfo=timezone.utc)

        return cls(
            entry_time=entry_time or datetime.now(timezone.utc),
            position_id=data.get("position_id"),
            regime=deepcopy(
                data.get("regime")
            ),  # ✅ deepcopy для защиты от вложенных структур
            balance_profile=deepcopy(data.get("balance_profile")),
            entry_price=data.get("entry_price"),  # float - не нужен deepcopy
            position_side=deepcopy(
                data.get("position_side")
            ),  # str - не критично, но для единообразия
            order_id=deepcopy(data.get("order_id")),
            order_type=deepcopy(data.get("order_type")),
            tp_percent=data.get("tp_percent"),  # float - не нужен deepcopy
            sl_percent=data.get("sl_percent"),  # float - не нужен deepcopy
            leverage=data.get("leverage"),  # int - не нужен deepcopy
            size_in_coins=data.get("size_in_coins"),  # float - не нужен deepcopy
            margin_used=data.get("margin_used"),  # float - не нужен deepcopy
            min_holding_seconds=data.get(
                "min_holding_seconds"
            ),  # ✅ НОВОЕ: float - не нужен deepcopy
            created_at=created_at,  # datetime - immutable
            # ✅ НОВОЕ: Отслеживание максимальной прибыли
            peak_profit_usd=data.get(
                "peak_profit_usd", 0.0
            ),  # float - не нужен deepcopy
            peak_profit_time=peak_profit_time,  # datetime - immutable
            peak_profit_price=data.get(
                "peak_profit_price"
            ),  # float - не нужен deepcopy
            tp_extension_count=data.get(
                "tp_extension_count", 0
            ),  # int - не нужен deepcopy
            partial_tp_executed=data.get(
                "partial_tp_executed", False
            ),  # ✅ ИСПРАВЛЕНО: bool - не нужен deepcopy
            scaling_history=deepcopy(
                data.get("scaling_history")
            ),  # ✅ НОВОЕ: История добавлений (список dict)
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
                from datetime import timezone

                metadata = PositionMetadata(entry_time=datetime.now(timezone.utc))

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
            Копия метаданных позиции или None (защита от мутаций)
        """
        async with self._lock:
            metadata = self._metadata.get(symbol)
            if metadata is None:
                return None
            # ✅ Возвращаем копию через replace() для защиты от мутаций
            return replace(metadata)

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

            # ✅ Доп. защита: если в position_updates пришел entry_time/cTime/openTime — обновляем metadata.entry_time
            def _parse_entry_time(value: Any) -> Optional[datetime]:
                if value is None:
                    return None
                if isinstance(value, datetime):
                    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                if isinstance(value, (int, float)):
                    ts = float(value)
                    if ts > 1e12:
                        ts /= 1000.0
                    return datetime.fromtimestamp(ts, tz=timezone.utc)
                if isinstance(value, str):
                    if value.isdigit():
                        ts = float(value) / 1000.0
                        return datetime.fromtimestamp(ts, tz=timezone.utc)
                    try:
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        return (
                            parsed
                            if parsed.tzinfo
                            else parsed.replace(tzinfo=timezone.utc)
                        )
                    except ValueError:
                        return None
                return None

            entry_time_candidate = None
            if position_updates:
                for key in ("entry_time", "cTime", "openTime", "c_time", "open_time"):
                    if key in position_updates and position_updates.get(key):
                        entry_time_candidate = _parse_entry_time(
                            position_updates.get(key)
                        )
                        if entry_time_candidate:
                            break

            if entry_time_candidate and symbol in self._metadata:
                existing_entry_time = self._metadata[symbol].entry_time
                if existing_entry_time and existing_entry_time.tzinfo is None:
                    existing_entry_time = existing_entry_time.replace(
                        tzinfo=timezone.utc
                    )
                should_update_entry = (
                    existing_entry_time is None
                    or entry_time_candidate
                    < (existing_entry_time - timedelta(seconds=5))
                )
                if should_update_entry:
                    if metadata_updates is None:
                        metadata_updates = {}
                    metadata_updates["entry_time"] = entry_time_candidate

            # Обновляем position
            if position_updates:
                self._positions[symbol].update(position_updates)

            # Обновляем metadata
            if metadata_updates:
                if symbol in self._metadata:
                    # ✅ Создаем новый объект через replace() вместо мутации через setattr()
                    existing = self._metadata[symbol]
                    # Готовим обновленные поля с deepcopy для защиты от вложенных структур
                    updated_fields = {}
                    for key, value in metadata_updates.items():
                        if hasattr(existing, key):
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Убеждаемся, что entry_time всегда offset-aware
                            # Это предотвращает ошибку "can't compare offset-naive and offset-aware datetimes"
                            if key == "entry_time" and isinstance(value, datetime):
                                if value.tzinfo is None:
                                    value = value.replace(tzinfo=timezone.utc)
                            updated_fields[key] = deepcopy(
                                value
                            )  # защита от вложенных структур (dict, list)
                    # Создаем новый объект с обновленными полями
                    self._metadata[symbol] = replace(existing, **updated_fields)
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

    def get_all_positions_sync(self) -> Dict[str, Dict[str, Any]]:
        """
        ✅ Синхронная версия get_all_positions (для прокси active_positions).

        ⚠️ ВНИМАНИЕ: Используйте только если нет доступа к async контексту!
        Возвращает копию словаря для безопасности.

        Returns:
            Копия словаря всех позиций
        """
        return {k: v.copy() for k, v in self._positions.items()}
