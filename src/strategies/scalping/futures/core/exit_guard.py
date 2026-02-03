from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from loguru import logger


class ExitGuard:
    """
    Single exit gate for all close decisions.

    Checks:
    1) Stale data (with REST refresh)
    2) Position integrity (with resync)
    3) Min holding (single block point)
    """

    DEFAULT_STALE_THRESHOLDS = {
        "entry": 3.0,
        "exit_normal": 5.0,
        "exit_critical": 10.0,
        "monitoring": 15.0,
    }

    DEFAULT_CRITICAL_EXCEPTIONS = {
        "critical_loss_cut",
        "critical_loss_cut_2x",
        "liquidation_risk",
        "exchange_force_close",
        "exchange_liquidation",
        "margin_call",
        "emergency_loss_protection",
    }

    def __init__(
        self,
        config: Optional[Any] = None,
        data_registry: Optional[Any] = None,
        position_registry: Optional[Any] = None,
        client: Optional[Any] = None,
        parameter_provider: Optional[Any] = None,
    ) -> None:
        self.data_registry = data_registry
        self.position_registry = position_registry
        self.client = client
        self.parameter_provider = parameter_provider

        self.stale_thresholds = dict(self.DEFAULT_STALE_THRESHOLDS)
        self.critical_exceptions = set(self.DEFAULT_CRITICAL_EXCEPTIONS)
        self.min_hold_bypass_mult = 1.2

        self._load_config(config)

    def _load_config(self, config: Optional[Any]) -> None:
        if config is None:
            return

        def _get(obj: Any, key: str, default: Any = None) -> Any:
            if obj is None:
                return default
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        guard_cfg = _get(config, "exit_guard")
        thresholds = _get(guard_cfg, "stale_thresholds") or _get(
            guard_cfg, "stale_thresholds_seconds"
        )
        if isinstance(thresholds, dict):
            for k, v in thresholds.items():
                try:
                    self.stale_thresholds[k] = float(v)
                except (TypeError, ValueError):
                    continue

        critical = _get(guard_cfg, "critical_exceptions")
        if isinstance(critical, (set, list, tuple)):
            self.critical_exceptions = set(str(x) for x in critical)

        bypass_mult = _get(guard_cfg, "min_hold_bypass_mult")
        try:
            if bypass_mult is not None:
                self.min_hold_bypass_mult = float(bypass_mult)
        except (TypeError, ValueError):
            self.min_hold_bypass_mult = 1.2

    async def check(
        self, symbol: str, reason: str, payload: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str]]:
        try:
            if not symbol:
                return False, "invalid_symbol"

            payload = payload or {}

            allowed, block = await self._check_stale(symbol, reason, payload)
            if not allowed:
                return False, block

            allowed, block = await self._check_integrity(symbol, payload)
            if not allowed:
                return False, block

            allowed, block = self._check_min_holding(symbol, reason, payload)
            if not allowed:
                return False, block

            return True, None
        except Exception as exc:
            logger.error(f"ExitGuard: error for {symbol}: {exc}")
            # Fail-open to avoid blocking closes when guard fails.
            return True, None

    def _is_critical_reason(self, reason: str) -> bool:
        if not reason:
            return False
        if reason in self.critical_exceptions:
            return True
        reason_l = reason.lower()
        if "liquidation" in reason_l or "margin_call" in reason_l:
            return True
        if "emergency" in reason_l:
            return True
        return False

    async def _check_stale(
        self, symbol: str, reason: str, payload: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        threshold = (
            self.stale_thresholds.get("exit_critical")
            if self._is_critical_reason(reason)
            else self.stale_thresholds.get("exit_normal")
        )
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            threshold = 5.0

        price_age = payload.get("price_age")

        if price_age is None and self.data_registry:
            try:
                snapshot = await self.data_registry.get_price_snapshot(symbol)
                if snapshot:
                    if payload.get("price") in (None, 0):
                        payload["price"] = snapshot.get("price")
                    if payload.get("price_source") is None:
                        payload["price_source"] = snapshot.get("source")
                    if price_age is None:
                        price_age = snapshot.get("age")
                        if price_age is not None:
                            payload["price_age"] = price_age
            except Exception:
                pass

        if price_age is None:
            return True, None

        try:
            price_age = float(price_age)
        except (TypeError, ValueError):
            return True, None

        if price_age <= threshold:
            return True, None

        fresh_price = await self._refresh_via_rest(symbol)
        if fresh_price:
            payload["price"] = fresh_price
            payload["price_source"] = "REST"
            payload["price_age"] = 0.0
            payload["price_refresh"] = "rest_fallback"
            return True, None

        if self._is_critical_reason(reason):
            logger.critical(
                "ExitGuard: allow critical exit on stale data "
                f"{symbol} age={price_age:.1f}s reason={reason}"
            )
            return True, None

        return False, f"stale_data_{price_age:.1f}s"

    async def _refresh_via_rest(self, symbol: str) -> Optional[float]:
        if not self.client:
            return None
        try:
            ticker = await self.client.get_ticker(symbol)
            if not ticker or not isinstance(ticker, dict):
                return None
            price = ticker.get("markPx") or ticker.get("last") or ticker.get("lastPx")
            if price is None:
                return None
            fresh_price = float(price)
            if fresh_price <= 0:
                return None
            if self.data_registry:
                try:
                    await self.data_registry.update_market_data(
                        symbol, {"price": fresh_price, "source": "REST"}
                    )
                except Exception:
                    pass
            return fresh_price
        except Exception as exc:
            logger.debug(f"ExitGuard: REST refresh failed for {symbol}: {exc}")
            return None

    async def _check_integrity(
        self, symbol: str, payload: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        position_data = payload.get("position_data")

        if position_data is None and self.position_registry:
            try:
                position_data = await self.position_registry.get_position(symbol)
                payload["position_data"] = position_data
            except Exception:
                position_data = None

        side, size = self._extract_side_size(position_data)
        if not position_data or side == "unknown" or size <= 0:
            exchange_position = await self._sync_position_from_exchange(symbol)
            if not exchange_position:
                if self.position_registry:
                    try:
                        await self.position_registry.unregister_position(symbol)
                    except Exception:
                        pass
                return False, "invalid_position_data"

            await self._update_registry_from_exchange(symbol, exchange_position)
            payload["position_data"] = exchange_position
            side, size = self._extract_side_size(exchange_position)
            if side == "unknown" or size <= 0:
                return False, "invalid_position_data"

        return True, None

    async def _sync_position_from_exchange(
        self, symbol: str
    ) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None
        try:
            positions = await self.client.get_positions(symbol)
            if not positions:
                return None
            for pos in positions:
                inst_id = str(pos.get("instId", "")).replace("-SWAP", "")
                if inst_id != symbol:
                    continue
                try:
                    size = float(pos.get("pos", "0"))
                except (TypeError, ValueError):
                    size = 0.0
                if size != 0:
                    return pos
            return None
        except Exception as exc:
            logger.debug(f"ExitGuard: sync failed for {symbol}: {exc}")
            return None

    async def _update_registry_from_exchange(
        self, symbol: str, exchange_position: Dict[str, Any]
    ) -> None:
        if not self.position_registry:
            return
        try:
            if await self.position_registry.has_position(symbol):
                await self.position_registry.update_position(
                    symbol, position_updates=exchange_position
                )
            else:
                metadata = await self.position_registry.get_metadata(symbol)
                await self.position_registry.register_position(
                    symbol, exchange_position, metadata=metadata
                )
        except Exception as exc:
            logger.debug(f"ExitGuard: registry update failed for {symbol}: {exc}")

    def _extract_side_size(
        self, position_data: Optional[Dict[str, Any]]
    ) -> Tuple[str, float]:
        if not position_data:
            return "unknown", 0.0
        side = (
            position_data.get("position_side")
            or position_data.get("posSide")
            or position_data.get("side")
            or "unknown"
        )
        side = str(side).lower() if side else "unknown"
        try:
            size = float(
                position_data.get("size", position_data.get("pos", 0)) or 0
            )
        except (TypeError, ValueError):
            size = 0.0
        return side, size

    def _check_min_holding(
        self, symbol: str, reason: str, payload: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        if self._should_bypass_min_holding(reason, payload):
            return True, None

        time_in_pos = (
            payload.get("time_in_pos")
            or payload.get("time_in_position")
            or payload.get("time_in_position_sec")
        )
        try:
            time_in_pos = float(time_in_pos) if time_in_pos is not None else None
        except (TypeError, ValueError):
            time_in_pos = None

        min_holding_minutes = payload.get("min_holding_minutes")
        if min_holding_minutes is None and self.parameter_provider:
            try:
                regime = payload.get("regime")
                exit_params = self.parameter_provider.get_exit_params(
                    symbol=symbol, regime=regime
                )
                if isinstance(exit_params, dict):
                    min_holding_minutes = exit_params.get("min_holding_minutes")
            except Exception:
                min_holding_minutes = None

        try:
            min_holding_minutes = (
                float(min_holding_minutes) if min_holding_minutes is not None else None
            )
        except (TypeError, ValueError):
            min_holding_minutes = None

        if min_holding_minutes is None or time_in_pos is None:
            return True, None

        min_holding_sec = min_holding_minutes * 60.0
        if time_in_pos < min_holding_sec:
            return False, f"min_holding_{time_in_pos:.1f}s<{min_holding_sec:.1f}s"
        return True, None

    def _should_bypass_min_holding(
        self, reason: str, payload: Dict[str, Any]
    ) -> bool:
        if self._is_critical_reason(reason):
            return True

        if payload.get("min_holding_bypass"):
            return True

        decision = payload.get("decision") or {}
        pnl_pct = decision.get("pnl_pct")
        sl_percent = decision.get("sl_percent")
        try:
            if pnl_pct is None or sl_percent is None:
                return False
            pnl_pct = float(pnl_pct)
            sl_percent = float(sl_percent)
            sl_threshold = -abs(sl_percent)
            return pnl_pct <= (sl_threshold * self.min_hold_bypass_mult)
        except (TypeError, ValueError):
            return False
