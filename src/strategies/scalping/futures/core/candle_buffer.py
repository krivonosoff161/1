"""
CandleBuffer - Циклический буфер для хранения свечей.

Хранит N свечей в памяти и обновляет их инкрементально:
- При добавлении новой свечи - удаляется самая старая (FIFO)
- При обновлении последней свечи - обновляются high/low/close/volume
"""

import asyncio
from datetime import datetime
from typing import List, Optional

from loguru import logger

from src.models import OHLCV


class CandleBuffer:
    """
    Циклический буфер для хранения свечей.

    Хранит N свечей и автоматически удаляет самые старые при добавлении новых.
    Thread-safe через asyncio.Lock.
    """

    def __init__(self, max_size: int = 200):
        """
        Инициализация буфера.

        Args:
            max_size: Максимальное количество свечей (по умолчанию 200)
        """
        self.max_size = max_size
        self._candles: List[OHLCV] = []
        self._lock = asyncio.Lock()

    async def add_candle(self, candle: OHLCV) -> None:
        """
        Добавить новую свечу в буфер.

        Если буфер заполнен, удаляется самая старая свеча (FIFO).
        Не добавляет свечу, если timestamp совпадает с последней (фильтрация дубликатов).

        Args:
            candle: Свеча OHLCV
        """
        async with self._lock:
            last_ts = getattr(self._candles[-1], "timestamp", None) if self._candles else None
            new_ts = getattr(candle, "timestamp", None)

            # Фильтрация дубликатов и вставок "из прошлого"
            if last_ts is not None and new_ts is not None:
                if new_ts == last_ts:
                    # logger.debug(f"⏩ CandleBuffer: Дубликат свечи по timestamp {new_ts} — не добавлен")
                    return
                if new_ts < last_ts:
                    logger.debug(
                        f"⏩ CandleBuffer: out-of-order candle ignored (ts={new_ts}, last_ts={last_ts})"
                    )
                    return
            self._candles.append(candle)

            # Если превышен max_size, удаляем самую старую свечу
            if len(self._candles) > self.max_size:
                removed_candle = self._candles.pop(0)
                # DEBUG логирование отключено - слишком много вывода, убивает бота
                # Включить только если нужна отладка конкретного буфера
                # logger.debug(f"📊 CandleBuffer: Удалена старая свеча ...")

    async def update_last_candle(
        self,
        high: Optional[float] = None,
        low: Optional[float] = None,
        close: Optional[float] = None,
        volume: Optional[float] = None,
    ) -> bool:
        """
        Обновить последнюю свечу в буфере (формирующуюся свечу).

        Используется когда свеча еще формируется (не завершилась).

        Args:
            high: Новая максимальная цена
            low: Новая минимальная цена
            close: Новая цена закрытия
            volume: Новый объем

        Returns:
            True если свеча обновлена, False если буфер пуст
        """
        async with self._lock:
            if not self._candles:
                return False

            last_candle = self._candles[-1]

            # Обновляем только переданные значения
            if high is not None:
                last_candle.high = max(last_candle.high, high)
            if low is not None:
                last_candle.low = min(last_candle.low, low)
            if close is not None:
                last_candle.close = close
            if volume is not None:
                last_candle.volume = volume

            return True

    async def get_candles(self) -> List[OHLCV]:
        """
        Получить все свечи из буфера.

        Returns:
            Копия списка свечей
        """
        async with self._lock:
            return self._candles.copy()

    async def get_last_candle(self) -> Optional[OHLCV]:
        """
        Получить последнюю свечу из буфера.

        Returns:
            Последняя свеча или None если буфер пуст
        """
        async with self._lock:
            return self._candles[-1] if self._candles else None

    async def get_first_candle(self) -> Optional[OHLCV]:
        """
        Получить первую (самую старую) свечу из буфера.

        Returns:
            Первая свеча или None если буфер пуст
        """
        async with self._lock:
            return self._candles[0] if self._candles else None

    async def size(self) -> int:
        """
        Получить количество свечей в буфере.

        Returns:
            Количество свечей
        """
        async with self._lock:
            return len(self._candles)

    async def clear(self) -> None:
        """
        Очистить буфер.
        """
        async with self._lock:
            self._candles.clear()
            logger.debug("📊 CandleBuffer: Буфер очищен")

    async def is_empty(self) -> bool:
        """
        Проверить, пуст ли буфер.

        Returns:
            True если буфер пуст, False иначе
        """
        async with self._lock:
            return len(self._candles) == 0

    async def get_candles_count(self) -> int:
        """
        Получить количество свечей (синхронная версия для совместимости).

        Returns:
            Количество свечей
        """
        return await self.size()
