"""Фильтр потока ордеров для OKX Futures."""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional, Tuple

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import OrderFlowFilterConfig


class OrderFlowFilter:
    """Простая оценка дисбаланса bid/ask для подтверждения направления сделки."""

    ORDERBOOK_ENDPOINT = "/api/v5/market/books"

    def __init__(
        self,
        client: Optional[OKXFuturesClient],
        config: OrderFlowFilterConfig,
    ) -> None:
        self.client = client
        self.config = config
        self._cache: Dict[Tuple[str, int], Dict[str, float]] = {}
        self._lock = asyncio.Lock()
        self._relax_state: Dict[str, Dict[str, float]] = {}

    async def is_signal_valid(
        self,
        symbol: str,
        side: str,
        snapshot: Optional[Dict[str, float]] = None,
        regime: Optional[str] = None,
        relax_multiplier: float = 1.0,
    ) -> bool:
        if not self.config.enabled:
            return True

        params = self._resolve_parameters(regime)
        relax_factor = self._get_relax_factor(symbol)
        external_relax = 1.0
        if relax_multiplier is not None and relax_multiplier > 0:
            external_relax = min(max(relax_multiplier, 0.1), 1.0)

        combined_relax = relax_factor * external_relax
        if combined_relax < 1.0:
            params = params.copy()
            params["long_threshold"] *= combined_relax
            params["short_threshold"] *= combined_relax
            params["min_total_depth_usd"] *= combined_relax
            reason = []
            if relax_factor < 1.0:
                reason.append(f"fail-open x{relax_factor:.2f}")
            if external_relax < 1.0:
                reason.append(f"impulse x{external_relax:.2f}")
            reason_str = ", ".join(reason) if reason else "combined"
            logger.debug(
                f"🔓 OrderFlowFilter: {symbol} пороги ослаблены x{combined_relax:.2f} ({reason_str})"
            )
        window = params["window"]
        data = snapshot or await self._get_depth(symbol, window)
        if not data:
            logger.debug(
                f"⚠️ OrderFlowFilter: нет данных по {symbol}, допускаем сигнал"
            )
            self._reset_block_state(symbol)
            return True

        depth_bid = (
            data.get("depth_bid_usd")
            if isinstance(data, dict)
            else getattr(data, "depth_bid_usd", 0.0)
        )
        depth_ask = (
            data.get("depth_ask_usd")
            if isinstance(data, dict)
            else getattr(data, "depth_ask_usd", 0.0)
        )

        total_depth = depth_bid + depth_ask
        if total_depth < params["min_total_depth_usd"]:
            logger.info(
                f"⛔ OrderFlowFilter: {symbol} отклонён — суммарная глубина {total_depth:,.0f} < {params['min_total_depth_usd']:,.0f} (regime={regime or 'n/a'})"
            )
            self._register_block(symbol)
            return False

        delta = self._calculate_delta(depth_bid, depth_ask)

        long_threshold = params["long_threshold"]
        short_threshold = params["short_threshold"]

        if side.lower() == "buy" and delta < long_threshold:
            logger.debug(
                f"⛔ OrderFlowFilter: delta={delta:.3f} < long_threshold {long_threshold:.3f} (regime={regime or 'n/a'})"
            )
            self._register_block(symbol)
            return False
        if side.lower() == "sell" and delta > short_threshold:
            logger.debug(
                f"⛔ OrderFlowFilter: delta={delta:.3f} > short_threshold {short_threshold:.3f} (regime={regime or 'n/a'})"
            )
            self._register_block(symbol)
            return False

        self._reset_block_state(symbol)
        logger.debug(
            f"✅ OrderFlowFilter: {symbol} {side} подтверждён (delta={delta:.3f}, regime={regime or 'n/a'})"
        )
        return True

    def _resolve_parameters(self, regime: Optional[str]) -> Dict[str, float]:
        window = self.config.window
        long_threshold = self.config.long_threshold
        short_threshold = self.config.short_threshold
        min_total_depth = self.config.min_total_depth_usd

        profiles = getattr(self.config, "regime_profiles", {}) or {}
        if regime:
            profile = profiles.get(regime.lower())
            if profile:
                if profile.window is not None:
                    window = max(5, profile.window)
                if profile.long_threshold is not None:
                    long_threshold = profile.long_threshold
                if profile.short_threshold is not None:
                    short_threshold = profile.short_threshold
                if profile.min_total_depth_usd is not None:
                    min_total_depth = max(0.0, profile.min_total_depth_usd)

        return {
            "window": window,
            "long_threshold": long_threshold,
            "short_threshold": short_threshold,
            "min_total_depth_usd": min_total_depth,
        }

    def _calculate_delta(self, bid_value: float, ask_value: float) -> float:
        total = bid_value + ask_value
        if total == 0:
            return 0.0
        return (bid_value - ask_value) / total

    async def _get_depth(self, symbol: str, window: int) -> Optional[Dict[str, float]]:
        now = time.time()
        cache_key = (symbol, window)
        cached = self._cache.get(cache_key)
        if (
            cached
            and (now - cached["timestamp"]) < self.config.refresh_interval_seconds
        ):
            return cached

        async with self._lock:
            cached = self._cache.get(cache_key)
            if (
                cached
                and (now - cached["timestamp"]) < self.config.refresh_interval_seconds
            ):
                return cached

            try:
                book = await self._fetch_orderbook(symbol, window)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    f"⚠️ OrderFlowFilter: не удалось получить orderbook для {symbol}: {exc}"
                )
                return cached

            depth_bid = sum(
                float(price) * float(size) for price, size, *_ in book["bids"]
            )
            depth_ask = sum(
                float(price) * float(size) for price, size, *_ in book["asks"]
            )

            snapshot = {
                "depth_bid_usd": depth_bid,
                "depth_ask_usd": depth_ask,
                "timestamp": time.time(),
            }
            self._cache[cache_key] = snapshot
            return snapshot

    async def _fetch_orderbook(self, symbol: str, window: int) -> Dict[str, list]:
        params = {"instId": f"{symbol}-SWAP", "sz": str(window)}
        if self.client:
            response = await self.client._make_request(  # type: ignore[attr-defined]
                "GET", self.ORDERBOOK_ENDPOINT, params=params
            )
        else:
            import aiohttp

            url = "https://www.okx.com" + self.ORDERBOOK_ENDPOINT
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    response = await resp.json()

        if not response or response.get("code") != "0":
            raise RuntimeError(f"Invalid orderbook response: {response}")

        data = response.get("data") or []
        if not data:
            raise RuntimeError("Orderbook data missing")

        book = data[0]
        return {
            "bids": book.get("bids", [])[:window],
            "asks": book.get("asks", [])[:window],
        }

    def _get_relax_factor(self, symbol: str) -> float:
        if not getattr(self.config, "fail_open_enabled", False):
            return 1.0
        state = self._relax_state.get(symbol)
        if not state:
            return 1.0
        now = time.time()
        relax_until = state.get("relax_until", 0.0)
        if relax_until > now:
            state["notified"] = True
            return max(0.05, getattr(self.config, "relax_multiplier", 0.5))
        if relax_until and relax_until <= now:
            state["relax_until"] = 0.0
            state["notified"] = False
        return 1.0

    def _register_block(self, symbol: str) -> None:
        if not getattr(self.config, "fail_open_enabled", False):
            return
        now = time.time()
        state = self._relax_state.setdefault(
            symbol,
            {"consecutive": 0, "relax_until": 0.0, "notified": False},
        )
        state["consecutive"] = state.get("consecutive", 0) + 1
        state["notified"] = False

        max_blocks = max(1, getattr(self.config, "max_consecutive_blocks", 4))
        if state["consecutive"] >= max_blocks:
            duration = max(1, getattr(self.config, "relax_duration_seconds", 30))
            state["relax_until"] = now + duration
            state["consecutive"] = 0
            state["notified"] = False
            logger.info(
                f"🔓 OrderFlowFilter fail-open активирован для {symbol}: пороги ослаблены на {duration}s"
            )

    def _reset_block_state(self, symbol: str) -> None:
        state = self._relax_state.get(symbol)
        if not state:
            return
        state["consecutive"] = 0
