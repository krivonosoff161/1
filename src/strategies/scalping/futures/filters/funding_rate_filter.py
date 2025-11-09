"""Фильтр по ставке funding для OKX Futures."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import FundingFilterConfig


@dataclass
class FundingSnapshot:
    symbol: str
    funding_rate: float
    next_funding_rate: float
    funding_time: Optional[str]
    next_funding_time: Optional[str]
    timestamp: float


class FundingRateFilter:
    """Проверка актуального и будущего funding перед размещением сделки."""

    PUBLIC_ENDPOINT = "/api/v5/public/funding-rate"

    def __init__(
        self,
        client: Optional[OKXFuturesClient],
        config: FundingFilterConfig,
    ) -> None:
        self.client = client
        self.config = config
        self._cache: Dict[str, FundingSnapshot] = {}
        self._lock = asyncio.Lock()

    async def is_signal_valid(self, symbol: str, side: str) -> bool:
        """Возвращает True, если funding допускает вход по направлению side."""
        if not self.config.enabled:
            return True

        snapshot = await self._get_snapshot(symbol)
        if not snapshot:
            # Не удалось получить данные – не блокируем, но логируем.
            logger.debug(
                f"⚠️ FundingRateFilter: нет данных по {symbol}, допускаем сигнал"
            )
            return True

        rate = snapshot.funding_rate
        next_rate = snapshot.next_funding_rate

        if self._violates_threshold(rate, side):
            logger.info(
                f"⛔ FundingRateFilter: {symbol} {side} отклонён. Текущий funding={rate:.4%}"
            )
            return False

        if self.config.include_next_funding and self._violates_threshold(
            next_rate, side
        ):
            logger.info(
                f"⛔ FundingRateFilter: {symbol} {side} отклонён. Следующий funding={next_rate:.4%}"
            )
            return False

        logger.debug(
            f"✅ FundingRateFilter: {symbol} {side} разрешён. rate={rate:.4%}, next={next_rate:.4%}"
        )
        return True

    async def _get_snapshot(self, symbol: str) -> Optional[FundingSnapshot]:
        now = time.time()
        cached = self._cache.get(symbol)
        if cached and (now - cached.timestamp) < self.config.refresh_interval_seconds:
            return cached

        async with self._lock:
            cached = self._cache.get(symbol)
            if (
                cached
                and (now - cached.timestamp) < self.config.refresh_interval_seconds
            ):
                return cached

            try:
                data = await self._fetch_funding(symbol)
            except Exception as exc:  # pragma: no cover - сетевые ошибки
                logger.warning(
                    f"⚠️ FundingRateFilter: не удалось обновить funding для {symbol}: {exc}"
                )
                return cached

            if not data:
                return cached

            snapshot = FundingSnapshot(
                symbol=symbol,
                funding_rate=self._normalize_rate(data.get("fundingRate")),
                next_funding_rate=self._normalize_rate(data.get("nextFundingRate")),
                funding_time=data.get("fundingTime"),
                next_funding_time=data.get("nextFundingTime"),
                timestamp=time.time(),
            )
            self._cache[symbol] = snapshot
            return snapshot

    async def _fetch_funding(self, symbol: str) -> Optional[Dict[str, str]]:
        inst_id = f"{symbol}-SWAP"
        params = {"instId": inst_id}

        # Предпочитаем использовать клиент, если он доступен
        if self.client:
            response = await self.client._make_request(  # type: ignore[attr-defined]
                "GET", self.PUBLIC_ENDPOINT, params=params
            )
        else:  # fallback на aiohttp при отсутствии клиента
            import aiohttp

            url = "https://www.okx.com" + self.PUBLIC_ENDPOINT
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    response = await resp.json()

        if not response or response.get("code") != "0":
            raise RuntimeError(f"Invalid funding response: {response}")

        data = response.get("data") or []
        return data[0] if data else None

    def _violates_threshold(self, rate: float, side: str) -> bool:
        if rate is None:
            return False
        abs_rate = abs(rate)
        if abs_rate > self.config.max_abs_rate:
            return True
        if side.lower() == "buy" and rate > self.config.max_positive_rate:
            return True
        if side.lower() == "sell" and rate < -self.config.max_negative_rate:
            return True
        return False

    @staticmethod
    def _normalize_rate(rate_value: Optional[str]) -> float:
        if rate_value is None:
            return 0.0
        try:
            rate = float(rate_value)
        except (TypeError, ValueError):
            return 0.0
        # OKX иногда возвращает значение в процентах, если > 1 – нормализуем
        if rate > 1 or rate < -1:
            rate /= 100.0
        return rate
