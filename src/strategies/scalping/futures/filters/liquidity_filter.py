"""Фильтр ликвидности для OKX Futures."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import LiquidityFilterConfig


@dataclass
class LiquiditySnapshot:
    symbol: str
    last_price: float
    daily_volume_usd: float
    best_bid_price: float
    best_ask_price: float
    best_bid_volume_usd: float
    best_ask_volume_usd: float
    depth_bid_usd: float
    depth_ask_usd: float
    timestamp: float

    @property
    def spread_percent(self) -> float:
        mid = (
            (self.best_bid_price + self.best_ask_price) / 2
            if self.best_bid_price and self.best_ask_price
            else 0
        )
        if mid == 0:
            return 0.0
        return (self.best_ask_price - self.best_bid_price) / mid * 100


class LiquidityFilter:
    """Проверка ликвидности по данным стакана и 24ч объёма."""

    TICKER_ENDPOINT = "/api/v5/market/ticker"
    ORDERBOOK_ENDPOINT = "/api/v5/market/books"

    def __init__(
        self,
        client: Optional[OKXFuturesClient],
        config: LiquidityFilterConfig,
    ) -> None:
        self.client = client
        self.config = config
        self._cache: Dict[str, LiquiditySnapshot] = {}
        self._lock = asyncio.Lock()
        self._relax_state: Dict[str, Dict[str, float]] = {}

    async def evaluate(
        self,
        symbol: str,
        regime: Optional[str] = None,
        relax_multiplier: float = 1.0,
        thresholds_override: Optional[Dict[str, float]] = None,
        signal_side: Optional[str] = None,  # ✅ НОВОЕ: Направление сигнала ("buy"/"sell" или "long"/"short")
    ) -> Tuple[bool, Optional[LiquiditySnapshot]]:
        if not self.config.enabled:
            return True, None

        snapshot = await self._get_snapshot(symbol)
        if not snapshot:
            logger.debug(
                f"⚠️ LiquidityFilter: не удалось получить данные по {symbol}, допускаем сигнал"
            )
            return True, None

        # ✅ ПРИОРИТЕТ: thresholds_override (из by_regime.{regime}.filters.liquidity) имеет ВЫСШИЙ приоритет
        # Сначала получаем пороги с учетом base -> symbol -> regime_multipliers
        thresholds, override_source = self._get_thresholds(symbol, regime)

        # Затем применяем thresholds_override (абсолютные значения из конфига, highest priority)
        if thresholds_override:
            for key, value in thresholds_override.items():
                if value is None:
                    continue
                if key in thresholds:
                    try:
                        thresholds[key] = float(value)
                    except (TypeError, ValueError):
                        continue
        relax_factor = self._get_relax_factor(symbol)
        external_relax = 1.0
        if relax_multiplier is not None and relax_multiplier > 0:
            external_relax = min(max(relax_multiplier, 0.1), 1.0)

        combined_relax = relax_factor * external_relax
        if combined_relax < 1.0:
            thresholds["min_daily_volume_usd"] *= combined_relax
            thresholds["min_best_bid_volume_usd"] *= combined_relax
            thresholds["min_best_ask_volume_usd"] *= combined_relax
            thresholds["min_orderbook_depth_usd"] *= combined_relax
            spread_relax = 1.0 + (1.0 - combined_relax)
            thresholds["max_spread_percent"] *= spread_relax
            reason = []
            if relax_factor < 1.0:
                reason.append(f"fail-open x{relax_factor:.2f}")
            if external_relax < 1.0:
                reason.append(f"impulse x{external_relax:.2f}")
            reason_str = ", ".join(reason) if reason else "combined"
            logger.debug(
                f"🔓 LiquidityFilter: {symbol} пороги ослаблены x{combined_relax:.2f} "
                f"(spread x{spread_relax:.2f}, {reason_str})"
            )
        regime_label = regime or "n/a"

        if snapshot.daily_volume_usd < thresholds["min_daily_volume_usd"]:
            logger.info(
                f"⛔ LiquidityFilter: {symbol} отклонён — 24ч объём {snapshot.daily_volume_usd:,.0f} < {thresholds['min_daily_volume_usd']:,.0f} (regime={regime_label})"
            )
            self._register_block(symbol)
            return False, snapshot

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем объемы в зависимости от направления сигнала
        # Для LONG (buy): нужен объем на bid (чтобы купить)
        # Для SHORT (sell): нужен объем на ask (чтобы продать)
        signal_side_normalized = None
        if signal_side:
            signal_side_normalized = signal_side.lower()
            if signal_side_normalized in ["buy", "long"]:
                signal_side_normalized = "buy"
            elif signal_side_normalized in ["sell", "short"]:
                signal_side_normalized = "sell"
        
        # Проверяем bid volume только для LONG сигналов
        if signal_side_normalized != "sell":  # Для LONG или если направление не указано (обратная совместимость)
            if snapshot.best_bid_volume_usd < thresholds["min_best_bid_volume_usd"]:
                logger.info(
                    f"⛔ LiquidityFilter: {symbol} отклонён — объём на лучшем bid {snapshot.best_bid_volume_usd:,.0f} < {thresholds['min_best_bid_volume_usd']:,.0f} "
                    f"(regime={regime_label}, side={'LONG' if signal_side_normalized == 'buy' else 'unknown'})"
                )
                self._register_block(symbol)
                return False, snapshot

        # Проверяем ask volume только для SHORT сигналов
        if signal_side_normalized != "buy":  # Для SHORT или если направление не указано (обратная совместимость)
            if snapshot.best_ask_volume_usd < thresholds["min_best_ask_volume_usd"]:
                logger.info(
                    f"⛔ LiquidityFilter: {symbol} отклонён — объём на лучшем ask {snapshot.best_ask_volume_usd:,.0f} < {thresholds['min_best_ask_volume_usd']:,.0f} "
                    f"(regime={regime_label}, side={'SHORT' if signal_side_normalized == 'sell' else 'unknown'})"
                )
                self._register_block(symbol)
                return False, snapshot

        if (
            snapshot.depth_bid_usd < thresholds["min_orderbook_depth_usd"]
            or snapshot.depth_ask_usd < thresholds["min_orderbook_depth_usd"]
        ):
            logger.info(
                f"⛔ LiquidityFilter: {symbol} отклонён — глубина стакана недостаточна (bid={snapshot.depth_bid_usd:,.0f}, ask={snapshot.depth_ask_usd:,.0f}, min={thresholds['min_orderbook_depth_usd']:,.0f}, regime={regime_label})"
            )
            self._register_block(symbol)
            return False, snapshot

        if snapshot.spread_percent > thresholds["max_spread_percent"]:
            logger.info(
                f"⛔ LiquidityFilter: {symbol} отклонён — спред {snapshot.spread_percent:.3f}% > {thresholds['max_spread_percent']:.3f}% (regime={regime_label})"
            )
            self._register_block(symbol)
            return False, snapshot

        self._reset_block_state(symbol)
        logger.debug(
            f"✅ LiquidityFilter: {symbol} проходит проверку (vol24h={snapshot.daily_volume_usd:,.0f} USD, spread={snapshot.spread_percent:.3f}%, source={override_source}, regime={regime_label})"
        )
        return True, snapshot

    async def _get_snapshot(self, symbol: str) -> Optional[LiquiditySnapshot]:
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
                ticker = await self._fetch_ticker(symbol)
                orderbook = await self._fetch_orderbook(symbol)
            except Exception as exc:  # pragma: no cover - сетевые ошибки
                logger.warning(
                    f"⚠️ LiquidityFilter: не удалось обновить данные для {symbol}: {exc}"
                )
                return cached

            if not ticker or not orderbook:
                return cached

            last_price = float(ticker.get("last", 0) or 0)
            vol24h_base = float(ticker.get("vol24h", 0) or 0)
            daily_volume_usd = vol24h_base * last_price

            best_bid_price = (
                float(orderbook["bids"][0][0]) if orderbook["bids"] else 0.0
            )
            best_bid_size = float(orderbook["bids"][0][1]) if orderbook["bids"] else 0.0
            best_ask_price = (
                float(orderbook["asks"][0][0]) if orderbook["asks"] else 0.0
            )
            best_ask_size = float(orderbook["asks"][0][1]) if orderbook["asks"] else 0.0

            depth_bid_usd = sum(
                float(price) * float(size) for price, size, *_ in orderbook["bids"]
            )
            depth_ask_usd = sum(
                float(price) * float(size) for price, size, *_ in orderbook["asks"]
            )
            
            # ✅ ЭТАП 1.3: Fallback на 24h volume для XRP-USDT если orderbook volume = 0
            best_bid_volume_usd = best_bid_price * best_bid_size
            best_ask_volume_usd = best_ask_price * best_ask_size
            
            # Получаем параметры fallback из конфига
            fallback_config = getattr(self.config, "volume_fallback", {})
            fallback_enabled = fallback_config.get("enabled", True)
            fallback_symbols = fallback_config.get("symbols", ["XRP-USDT"])
            fallback_percent = fallback_config.get("fallback_percent", 0.001)  # 0.1% от дневного объема
            
            if (
                fallback_enabled
                and symbol in fallback_symbols
                and (best_bid_volume_usd == 0 or best_ask_volume_usd == 0)
                and daily_volume_usd > 0
            ):
                # Используем 24h volume как fallback
                fallback_volume_usd = daily_volume_usd * fallback_percent
                if best_bid_volume_usd == 0:
                    best_bid_volume_usd = fallback_volume_usd
                    logger.debug(
                        f"📊 LiquidityFilter fallback для {symbol}: best_bid_volume_usd = 0, "
                        f"используем {fallback_percent:.3%} от 24h volume = {fallback_volume_usd:.2f} USD"
                    )
                if best_ask_volume_usd == 0:
                    best_ask_volume_usd = fallback_volume_usd
                    logger.debug(
                        f"📊 LiquidityFilter fallback для {symbol}: best_ask_volume_usd = 0, "
                        f"используем {fallback_percent:.3%} от 24h volume = {fallback_volume_usd:.2f} USD"
                    )

            snapshot = LiquiditySnapshot(
                symbol=symbol,
                last_price=last_price,
                daily_volume_usd=daily_volume_usd,
                best_bid_price=best_bid_price,
                best_ask_price=best_ask_price,
                best_bid_volume_usd=best_bid_volume_usd,
                best_ask_volume_usd=best_ask_volume_usd,
                depth_bid_usd=depth_bid_usd,
                depth_ask_usd=depth_ask_usd,
                timestamp=time.time(),
            )
            self._cache[symbol] = snapshot
            return snapshot

    async def _fetch_ticker(self, symbol: str) -> Dict[str, str]:
        params = {"instId": f"{symbol}-SWAP"}
        if self.client:
            response = await self.client._make_request(  # type: ignore[attr-defined]
                "GET", self.TICKER_ENDPOINT, params=params
            )
        else:
            import aiohttp

            url = "https://www.okx.com" + self.TICKER_ENDPOINT
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    response = await resp.json()

        if not response or response.get("code") != "0":
            raise RuntimeError(f"Invalid ticker response: {response}")

        data = response.get("data") or []
        if not data:
            raise RuntimeError("Ticker data missing")
        return data[0]

    async def _fetch_orderbook(self, symbol: str) -> Dict[str, list]:
        params = {"instId": f"{symbol}-SWAP", "sz": str(self.config.depth_levels)}
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
            "bids": book.get("bids", [])[: self.config.depth_levels],
            "asks": book.get("asks", [])[: self.config.depth_levels],
        }

    def _get_thresholds(
        self, symbol: str, regime: Optional[str] = None
    ) -> Tuple[Dict[str, float], str]:
        """
        Получение порогов ликвидности с учетом приоритетов.

        ПРИОРИТЕТ (от низкого к высокому):
        1. base (self.config - базовые значения из futures_modules.liquidity_filter)
        2. symbol_overrides (per-symbol переопределения)
        3. regime_multipliers (множители для режима)
        4. thresholds_override в evaluate() (абсолютные значения из by_regime.{regime}.filters.liquidity)
        """
        # 1. Базовые значения из конфига (lowest priority)
        base = {
            "min_daily_volume_usd": self.config.min_daily_volume_usd,
            "min_best_bid_volume_usd": self.config.min_best_bid_volume_usd,
            "min_best_ask_volume_usd": self.config.min_best_ask_volume_usd,
            "min_orderbook_depth_usd": self.config.min_orderbook_depth_usd,
            "max_spread_percent": self.config.max_spread_percent,
        }

        thresholds = base.copy()
        source = "base"

        # 2. Per-symbol overrides (выше приоритет чем base)
        overrides = getattr(self.config, "symbol_overrides", {}) or {}
        symbol_override = overrides.get(symbol)
        if symbol_override:
            if symbol_override.min_daily_volume_usd is not None:
                thresholds[
                    "min_daily_volume_usd"
                ] = symbol_override.min_daily_volume_usd
            if symbol_override.min_best_bid_volume_usd is not None:
                thresholds[
                    "min_best_bid_volume_usd"
                ] = symbol_override.min_best_bid_volume_usd
            if symbol_override.min_best_ask_volume_usd is not None:
                thresholds[
                    "min_best_ask_volume_usd"
                ] = symbol_override.min_best_ask_volume_usd
            if symbol_override.min_orderbook_depth_usd is not None:
                thresholds[
                    "min_orderbook_depth_usd"
                ] = symbol_override.min_orderbook_depth_usd
            if symbol_override.max_spread_percent is not None:
                thresholds["max_spread_percent"] = symbol_override.max_spread_percent
            source = "symbol"

        # 3. Regime multipliers (выше приоритет чем symbol, но ниже чем thresholds_override)
        multipliers = getattr(self.config, "regime_multipliers", {}) or {}
        if regime:
            regime_profile = multipliers.get(regime.lower())
            if regime_profile:
                thresholds = self._apply_regime_multipliers(thresholds, regime_profile)
                source = f"{source}+{regime.lower()}"

        # 4. thresholds_override применяется в evaluate() после этого (highest priority)

        return thresholds, source

    @staticmethod
    def _apply_regime_multipliers(
        thresholds: Dict[str, float], regime_profile
    ) -> Dict[str, float]:
        updated = thresholds.copy()

        def apply_multiplier(
            key: str, multiplier: Optional[float], min_value: float = 0.0
        ):
            if multiplier is not None:
                updated[key] = max(min_value, updated[key] * multiplier)

        apply_multiplier(
            "min_daily_volume_usd",
            getattr(regime_profile, "min_daily_volume_multiplier", None),
        )
        apply_multiplier(
            "min_best_bid_volume_usd",
            getattr(regime_profile, "min_best_bid_volume_multiplier", None),
        )
        apply_multiplier(
            "min_best_ask_volume_usd",
            getattr(regime_profile, "min_best_ask_volume_multiplier", None),
        )
        apply_multiplier(
            "min_orderbook_depth_usd",
            getattr(regime_profile, "min_orderbook_depth_multiplier", None),
        )

        spread_multiplier = getattr(regime_profile, "max_spread_multiplier", None)
        if spread_multiplier is not None:
            updated["max_spread_percent"] = max(
                0.01, updated["max_spread_percent"] * spread_multiplier
            )

        return updated

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

        max_blocks = max(1, getattr(self.config, "max_consecutive_blocks", 5))
        if state["consecutive"] >= max_blocks:
            duration = max(1, getattr(self.config, "relax_duration_seconds", 60))
            state["relax_until"] = now + duration
            state["consecutive"] = 0
            state["notified"] = False
            logger.info(
                f"🔓 LiquidityFilter fail-open активирован для {symbol}: пороги ослаблены на {duration}s"
            )

    def _reset_block_state(self, symbol: str) -> None:
        state = self._relax_state.get(symbol)
        if not state:
            return
        state["consecutive"] = 0
