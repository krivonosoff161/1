from __future__ import annotations

from dataclasses import asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple  # noqa: F401

from loguru import logger

from ..indicators.atr_provider import ATRProvider
from .parameter_schema import (
    ExitParams,
    OrderParams,
    ParameterBundle,
    ParameterStatus,
    PatternParams,
    RiskParams,
    SignalParams,
)
from .parameter_validators import (  # noqa: F401
    optional_float,
    optional_str,
    require_bool,
    require_dict,
    require_float,
    require_int,
    require_str,
)


class ParameterOrchestrator:
    """
    Single source of truth for all trading parameters.
    No fallbacks: if required config or market data is missing -> invalid.
    """

    def __init__(self, config_manager=None, data_registry=None, regime_manager=None):
        self.config_manager = config_manager
        self.data_registry = data_registry
        self.regime_manager = regime_manager
        self.atr_provider = ATRProvider(data_registry=data_registry)

        raw = getattr(config_manager, "_raw_config_dict", None) or {}
        self._raw = raw
        self._scalping = raw.get("scalping") or {}
        self._exit_params = raw.get("exit_params") or {}
        self._adaptive_regime = self._scalping.get("adaptive_regime") or {}
        self._signal_generator = self._scalping.get("signal_generator") or {}
        self._order_executor = self._scalping.get("order_executor") or {}
        self._balance_profiles = self._scalping.get("balance_profiles") or {}
        self._patterns = self._scalping.get("patterns") or {}
        self._by_symbol = self._scalping.get("by_symbol") or {}

        logger.info(
            f"ParameterOrchestrator init: raw scalping keys: {list(self._scalping.keys())}"
        )
        logger.info(
            f"ParameterOrchestrator init: adaptive_regime keys: {list(self._adaptive_regime.keys())}"
        )
        logger.info(
            f"ParameterOrchestrator init: patterns keys: {list(self._patterns.keys())}"
        )

    def resolve_bundle(
        self,
        symbol: str,
        regime: Optional[str] = None,
        market_data: Optional[Any] = None,
        balance: Optional[float] = None,
        position: Optional[Any] = None,
        include_signal: bool = True,
        include_exit: bool = True,
        include_order: bool = True,
        include_risk: bool = True,
        include_patterns: bool = True,
    ) -> ParameterBundle:
        status = ParameterStatus(valid=True)
        # Extract candles and current_price from market_data if available
        candles = None
        current_price = None
        if market_data:
            if hasattr(market_data, "ohlcv_data"):
                candles = market_data.ohlcv_data
            if hasattr(market_data, "current_tick") and market_data.current_tick:
                try:
                    current_price = float(market_data.current_tick.price)
                except Exception:
                    current_price = None
            if current_price is None and candles:
                try:
                    current_price = float(candles[-1].close)
                except Exception:
                    current_price = None

        regime_value = self._resolve_regime(
            symbol, regime, status, candles, current_price
        )

        signal_params = None
        exit_params = None
        order_params = None
        risk_params = None
        pattern_params = None

        if include_signal:
            signal_params = self._resolve_signal_params(symbol, regime_value, status)
            logger.debug(
                f"PARAM_ORCH: signal_params resolved: {signal_params is not None}, errors: {status.errors}"
            )
        if include_exit:
            exit_params = self._resolve_exit_params(
                symbol, regime_value, market_data, status
            )
        if include_order:
            order_params = self._resolve_order_params(symbol, regime_value, status)
        if include_risk:
            risk_params = self._resolve_risk_params(
                symbol, regime_value, balance, status
            )
        if include_patterns:
            pattern_params = self._resolve_pattern_params(symbol, regime_value, status)

        status.valid = status.valid and not status.errors

        return ParameterBundle(
            status=status,
            signal=signal_params,
            exit=exit_params,
            order=order_params,
            risk=risk_params,
            patterns=pattern_params,
        )

    def _resolve_regime(
        self,
        symbol: str,
        regime: Optional[str],
        status: ParameterStatus,
        candles: Optional[List] = None,
        current_price: Optional[float] = None,
    ) -> Optional[str]:
        if regime:
            logger.debug(
                f"PARAM_ORCH: _resolve_regime: using provided regime '{regime}'"
            )
            return self._normalize_regime(regime)
        if self.regime_manager is None:
            status.errors.append("regime_manager is not set")
            logger.debug("PARAM_ORCH: _resolve_regime: regime_manager is None")
            return None
        try:
            # Try detect_regime first (per-symbol), fallback to get_current_regime (global)
            if hasattr(self.regime_manager, "detect_regime"):
                if candles is None or current_price is None:
                    status.errors.append(
                        f"failed to get market data for regime detection: candles={candles is not None}, price={current_price is not None}"
                    )
                    return None
                resolved = self.regime_manager.detect_regime(candles, current_price)
                resolved = resolved.regime if hasattr(resolved, "regime") else resolved
                logger.debug(
                    f"PARAM_ORCH: _resolve_regime: detect_regime('{symbol}') returned '{resolved}'"
                )
            else:
                resolved = self.regime_manager.get_current_regime()
                logger.debug(
                    f"PARAM_ORCH: _resolve_regime: get_current_regime() returned '{resolved}'"
                )
        except Exception as exc:
            status.errors.append(f"failed to get regime: {exc}")
            logger.debug(
                f"PARAM_ORCH: _resolve_regime: exception getting regime: {exc}"
            )
            return None
        if not resolved:
            status.errors.append("regime is empty")
            logger.debug("PARAM_ORCH: _resolve_regime: regime is empty")
            return None
        resolved_str = self._normalize_regime(resolved)
        logger.debug(f"PARAM_ORCH: _resolve_regime: resolved to '{resolved_str}'")
        return resolved_str

    def _normalize_regime(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, Enum):
            return str(value.value).lower()
        if hasattr(value, "value") and isinstance(getattr(value, "value"), str):
            return str(getattr(value, "value")).lower()
        if hasattr(value, "name") and isinstance(getattr(value, "name"), str):
            return str(getattr(value, "name")).lower()
        raw = str(value).lower()
        if raw.startswith("regimetype."):
            return raw.split(".", 1)[1]
        return raw

    def _resolve_signal_params(
        self, symbol: str, regime: Optional[str], status: ParameterStatus
    ) -> Optional[SignalParams]:
        if regime is None:
            status.errors.append("signal params: regime missing")
            return None
        errors: list[str] = []

        sources = {
            "min_signal_strength": f"signal_generator.thresholds.by_regime.{regime}",
            "min_score_threshold": f"adaptive_regime.{regime}",
            "max_trades_per_hour": f"adaptive_regime.{regime}",
            "position_size_multiplier": f"adaptive_regime.{regime}",
            "indicators": f"adaptive_regime.{regime}.indicators",
        }

        thresholds = require_dict(
            self._signal_generator, "thresholds", errors, "scalping.signal_generator"
        )
        by_regime = require_dict(
            thresholds, "by_regime", errors, "scalping.signal_generator.thresholds"
        )
        regime_cfg = require_dict(
            by_regime, regime, errors, "scalping.signal_generator.thresholds.by_regime"
        )
        min_signal_strength = require_float(
            regime_cfg,
            "min_signal_strength",
            errors,
            f"signal_generator.thresholds.by_regime.{regime}",
        )

        # Override with symbol-specific value if available
        by_symbol = self._scalping.get("by_symbol")
        if isinstance(by_symbol, dict) and symbol in by_symbol:
            symbol_cfg = by_symbol.get(symbol)
            if isinstance(symbol_cfg, dict) and "min_signal_strength" in symbol_cfg:
                min_signal_strength = symbol_cfg["min_signal_strength"]
                sources["min_signal_strength"] = f"scalping.by_symbol.{symbol}"

        adaptive_regime_cfg = require_dict(
            self._adaptive_regime, regime, errors, "scalping.adaptive_regime"
        )
        min_score_threshold = require_float(
            adaptive_regime_cfg,
            "min_score_threshold",
            errors,
            f"adaptive_regime.{regime}",
        )
        max_trades_per_hour = require_int(
            adaptive_regime_cfg,
            "max_trades_per_hour",
            errors,
            f"adaptive_regime.{regime}",
        )
        position_size_multiplier = require_float(
            adaptive_regime_cfg,
            "position_size_multiplier",
            errors,
            f"adaptive_regime.{regime}",
        )

        indicators_cfg = require_dict(
            adaptive_regime_cfg, "indicators", errors, f"adaptive_regime.{regime}"
        )

        modules_cfg = (
            adaptive_regime_cfg.get("modules")
            if isinstance(adaptive_regime_cfg, dict)
            else None
        )
        adx_threshold = None
        if isinstance(modules_cfg, dict):
            adx_filter = modules_cfg.get("adx_filter")
            if isinstance(adx_filter, dict):
                adx_threshold = optional_float(adx_filter, "adx_threshold")

        # FIX 2026-02-22 P1.4: Override min_adx с per-symbol значения если есть.
        # Config давно содержит by_symbol.DOGE-USDT.min_adx: 8.0 и т.д., но код игнорировал их.
        if isinstance(by_symbol, dict) and symbol in by_symbol:
            symbol_cfg = by_symbol.get(symbol)
            if isinstance(symbol_cfg, dict) and "min_adx" in symbol_cfg:
                adx_threshold = float(symbol_cfg["min_adx"])
                sources["min_adx"] = f"scalping.by_symbol.{symbol}"

        if adx_threshold is None:
            errors.append(
                f"adaptive_regime.{regime}.modules.adx_filter.adx_threshold missing"
            )

        if errors:
            status.errors.extend(errors)
            return None

        return SignalParams(
            regime=regime,
            min_signal_strength=float(min_signal_strength),
            min_signal_strength_ranging=float(min_signal_strength),
            min_adx=float(adx_threshold),
            min_score_threshold=float(min_score_threshold),
            max_trades_per_hour=int(max_trades_per_hour),
            position_size_multiplier=float(position_size_multiplier),
            indicators=dict(indicators_cfg),
            sources=sources,
        )

    def _resolve_exit_params(
        self,
        symbol: str,
        regime: Optional[str],
        market_data: Optional[Any],
        status: ParameterStatus,
    ) -> Optional[ExitParams]:
        if regime is None:
            status.errors.append("exit params: regime missing")
            return None
        errors: list[str] = []
        exit_cfg = require_dict(self._exit_params, regime, errors, "exit_params")

        tp_atr_multiplier = require_float(
            exit_cfg, "tp_atr_multiplier", errors, f"exit_params.{regime}"
        )
        sl_atr_multiplier = require_float(
            exit_cfg, "sl_atr_multiplier", errors, f"exit_params.{regime}"
        )
        tp_min_percent = require_float(
            exit_cfg, "tp_min_percent", errors, f"exit_params.{regime}"
        )
        sl_min_percent = require_float(
            exit_cfg, "sl_min_percent", errors, f"exit_params.{regime}"
        )
        max_holding = require_float(
            exit_cfg, "max_holding_minutes", errors, f"exit_params.{regime}"
        )
        min_holding = require_float(
            exit_cfg, "min_holding_minutes", errors, f"exit_params.{regime}"
        )
        min_profit_for_extension = require_float(
            exit_cfg, "min_profit_for_extension", errors, f"exit_params.{regime}"
        )
        extension_percent = require_float(
            exit_cfg, "extension_percent", errors, f"exit_params.{regime}"
        )

        tp_max_percent = optional_float(exit_cfg, "tp_max_percent")
        sl_max_percent = optional_float(exit_cfg, "sl_max_percent")

        current_price = self._get_current_price(symbol, market_data, errors)
        atr_value = self.atr_provider.get_atr(symbol)
        if atr_value is None:
            errors.append(f"ATR missing for {symbol}")
        if current_price is None or current_price <= 0:
            errors.append("current_price missing or <= 0")

        if errors:
            status.errors.extend(errors)
            return None

        atr_pct = (atr_value / current_price) * 100.0
        tp_percent = max(tp_min_percent, atr_pct * tp_atr_multiplier)
        if tp_max_percent is not None:
            tp_percent = min(tp_percent, tp_max_percent)

        sl_percent = max(sl_min_percent, atr_pct * sl_atr_multiplier)
        if sl_max_percent is not None:
            sl_percent = min(sl_percent, sl_max_percent)

        ph_threshold_type = optional_str(exit_cfg, "ph_threshold_type")
        ph_threshold_percent = optional_float(exit_cfg, "ph_threshold_percent")
        ph_min_absolute_usd = optional_float(exit_cfg, "ph_min_absolute_usd")

        sources = {
            "exit_params": f"exit_params.{regime}",
            "atr": "data_registry.indicators.atr",
            "current_price": "market_data",
        }

        return ExitParams(
            regime=regime,
            tp_percent=float(tp_percent),
            sl_percent=float(sl_percent),
            tp_atr_multiplier=float(tp_atr_multiplier),
            sl_atr_multiplier=float(sl_atr_multiplier),
            tp_min_percent=float(tp_min_percent),
            tp_max_percent=float(tp_max_percent)
            if tp_max_percent is not None
            else None,
            sl_min_percent=float(sl_min_percent),
            sl_max_percent=float(sl_max_percent)
            if sl_max_percent is not None
            else None,
            max_holding_minutes=float(max_holding),
            min_holding_minutes=float(min_holding),
            min_profit_for_extension=float(min_profit_for_extension),
            extension_percent=float(extension_percent),
            ph_threshold_type=ph_threshold_type,
            ph_threshold_percent=ph_threshold_percent,
            ph_min_absolute_usd=ph_min_absolute_usd,
            sources=sources,
        )

    def _resolve_order_params(
        self, symbol: str, regime: Optional[str], status: ParameterStatus
    ) -> Optional[OrderParams]:
        if regime is None:
            status.errors.append("order params: regime missing")
            return None
        errors: list[str] = []
        limit_cfg = require_dict(
            self._order_executor, "limit_order", errors, "scalping.order_executor"
        )

        by_symbol = limit_cfg.get("by_symbol") if isinstance(limit_cfg, dict) else None
        by_regime = limit_cfg.get("by_regime") if isinstance(limit_cfg, dict) else None

        resolved_cfg: Dict[str, Any] = {}
        sources = {}

        if isinstance(by_symbol, dict) and symbol in by_symbol:
            symbol_cfg = by_symbol.get(symbol)
            if isinstance(symbol_cfg, dict):
                resolved_cfg.update(symbol_cfg)
                sources["by_symbol"] = f"order_executor.limit_order.by_symbol.{symbol}"
                if "by_regime" in symbol_cfg and isinstance(
                    symbol_cfg["by_regime"], dict
                ):
                    regime_cfg = symbol_cfg["by_regime"].get(regime)
                    if isinstance(regime_cfg, dict):
                        resolved_cfg.update(regime_cfg)
                        sources[
                            "by_symbol_by_regime"
                        ] = f"order_executor.limit_order.by_symbol.{symbol}.by_regime.{regime}"

        if isinstance(by_regime, dict) and regime in by_regime:
            regime_cfg = by_regime.get(regime)
            if isinstance(regime_cfg, dict):
                resolved_cfg.update(regime_cfg)
                sources["by_regime"] = f"order_executor.limit_order.by_regime.{regime}"

        # Apply base config last only if not overwritten
        if isinstance(limit_cfg, dict):
            for key, value in limit_cfg.items():
                if key not in resolved_cfg and key not in ("by_symbol", "by_regime"):
                    resolved_cfg[key] = value
                    sources.setdefault("base", "order_executor.limit_order")

        limit_offset = require_float(
            resolved_cfg, "limit_offset_percent", errors, "order_executor.limit_order"
        )
        max_wait = require_float(
            resolved_cfg, "max_wait_seconds", errors, "order_executor.limit_order"
        )
        auto_cancel = require_bool(
            resolved_cfg, "auto_cancel_enabled", errors, "order_executor.limit_order"
        )
        auto_replace = require_bool(
            resolved_cfg, "auto_replace_enabled", errors, "order_executor.limit_order"
        )
        replace_with_market = require_bool(
            resolved_cfg, "replace_with_market", errors, "order_executor.limit_order"
        )
        post_only = require_bool(
            resolved_cfg, "post_only", errors, "order_executor.limit_order"
        )
        adaptive_spread_offset = require_bool(
            resolved_cfg, "adaptive_spread_offset", errors, "order_executor.limit_order"
        )

        if errors:
            status.errors.extend(errors)
            return None

        return OrderParams(
            regime=regime,
            limit_offset_percent=float(limit_offset),
            max_wait_seconds=float(max_wait),
            auto_cancel_enabled=bool(auto_cancel),
            auto_replace_enabled=bool(auto_replace),
            replace_with_market=bool(replace_with_market),
            post_only=bool(post_only),
            adaptive_spread_offset=bool(adaptive_spread_offset),
            sources=sources,
        )

    def _resolve_risk_params(
        self,
        symbol: str,
        regime: Optional[str],
        balance: Optional[float],
        status: ParameterStatus,
    ) -> Optional[RiskParams]:
        if regime is None:
            status.errors.append("risk params: regime missing")
            return None
        errors: list[str] = []
        if balance is None or balance <= 0:
            errors.append("balance missing or <= 0")
            status.errors.extend(errors)
            return None

        leverage = require_float(self._scalping, "leverage", errors, "scalping")
        if leverage is None:
            status.errors.extend(errors)
            return None

        profile = self._select_balance_profile(balance, errors)
        if profile is None:
            status.errors.extend(errors)
            return None

        position_size_multiplier = None
        if isinstance(self._adaptive_regime, dict) and regime in self._adaptive_regime:
            cfg = self._adaptive_regime.get(regime)
            if isinstance(cfg, dict):
                position_size_multiplier = optional_float(
                    cfg, "position_size_multiplier"
                )
        if position_size_multiplier is None:
            errors.append(f"adaptive_regime.{regime}.position_size_multiplier missing")
            status.errors.extend(errors)
            return None

        min_position_usd = profile.get("min_position_usd")
        max_position_usd = profile.get("max_position_usd")
        max_open_positions = profile.get("max_open_positions")
        max_position_percent = profile.get("max_position_percent")

        # ✅ ИСПРАВЛЕНИЕ (11.02.2026): base_position_usd теперь вычисляется динамически
        # из max_position_percent × balance, если не задан явно в конфиге
        base_position_usd = profile.get("base_position_usd")
        if base_position_usd is None and max_position_percent is not None and balance:
            base_position_usd = float(balance) * float(max_position_percent) / 100.0

        if any(
            v is None
            for v in (
                base_position_usd,
                min_position_usd,
                max_position_usd,
                max_open_positions,
                max_position_percent,
            )
        ):
            errors.append("balance_profile missing required fields")

        if errors:
            status.errors.extend(errors)
            return None

        position_size_usd = float(base_position_usd) * float(position_size_multiplier)

        sources = {
            "balance_profile": f"scalping.balance_profiles.{profile.get('name')}",
            "position_size_multiplier": f"adaptive_regime.{regime}",
            "leverage": "scalping.leverage",
        }

        return RiskParams(
            regime=regime,
            leverage=float(leverage),
            position_size_usd=float(position_size_usd),
            min_position_usd=float(min_position_usd),
            max_position_usd=float(max_position_usd),
            max_open_positions=int(max_open_positions),
            max_position_percent=float(max_position_percent),
            sources=sources,
        )

    def _resolve_pattern_params(
        self, symbol: str, regime: Optional[str], status: ParameterStatus
    ) -> Optional[PatternParams]:
        if regime is None:
            status.errors.append("pattern params: regime missing")
            return None
        errors: list[str] = []
        enabled = (
            self._patterns.get("enabled") if isinstance(self._patterns, dict) else None
        )
        if enabled is None:
            errors.append("patterns.enabled missing")
        timeframe = None
        if isinstance(self._patterns, dict):
            timeframe = self._patterns.get("timeframe")
        if not timeframe:
            errors.append("patterns.timeframe missing")

        thresholds = {}
        if isinstance(self._patterns, dict):
            by_regime = self._patterns.get("by_regime")
            if isinstance(by_regime, dict) and regime in by_regime:
                thresholds = dict(by_regime.get(regime) or {})
        if enabled:
            required_keys = (
                "min_confidence",
                "min_strength",
                "boost_multiplier",
                "penalty_multiplier",
                "breakout_pct",
                "pinbar_wick_ratio",
                "min_bars",
            )
            for key in required_keys:
                if key not in thresholds:
                    errors.append(f"patterns.by_regime.{regime}.{key} missing")

        if errors:
            status.errors.extend(errors)
            return None

        sources = {"patterns": "scalping.patterns"}

        return PatternParams(
            regime=regime,
            enabled=bool(enabled),
            timeframe=str(timeframe),
            thresholds=thresholds,
            sources=sources,
        )

    def _get_current_price(
        self, symbol: str, market_data: Optional[Any], errors: list[str]
    ) -> Optional[float]:
        try:
            if market_data is not None:
                tick = getattr(market_data, "current_tick", None)
                if tick is not None and getattr(tick, "price", None) is not None:
                    price = float(tick.price)
                    if price > 0:
                        return price
                candles = getattr(market_data, "ohlcv_data", None) or []
                if candles:
                    last = candles[-1]
                    price = float(getattr(last, "close", 0.0))
                    if price > 0:
                        return price
        except Exception as exc:
            errors.append(f"failed to read current price from market_data: {exc}")
            return None

        price = self._get_price_from_registry(symbol, errors)
        if price is not None:
            return price

        errors.append("current_price not available from market_data or data_registry")
        return None

    def _get_price_from_registry(
        self, symbol: str, errors: list[str]
    ) -> Optional[float]:
        if not self.data_registry:
            return None
        try:
            raw = getattr(self.data_registry, "_market_data", None)
            if not isinstance(raw, dict):
                return None
            entry = raw.get(symbol) or {}
            price = entry.get("price") or entry.get("last_price")
            if price is not None:
                price_val = float(price)
                if price_val > 0:
                    return price_val
        except Exception as exc:
            errors.append(f"failed to read price from data_registry: {exc}")
            return None
        return None

    def _select_balance_profile(
        self, balance: float, errors: list[str]
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(self._balance_profiles, dict) or not self._balance_profiles:
            errors.append("scalping.balance_profiles missing")
            return None

        profiles = []
        for name, cfg in self._balance_profiles.items():
            if not isinstance(cfg, dict):
                continue
            threshold = cfg.get("threshold")
            if threshold is None:
                continue
            profiles.append((name, float(threshold), cfg))

        if not profiles:
            errors.append("no valid balance profiles found")
            return None

        profiles.sort(key=lambda item: item[1])
        chosen = None
        for name, threshold, cfg in profiles:
            if balance <= threshold:
                chosen = (name, cfg)
                break
        if chosen is None:
            chosen = (profiles[-1][0], profiles[-1][2])

        name, cfg = chosen
        cfg = dict(cfg)
        cfg["name"] = name

        if cfg.get("progressive"):
            min_balance = cfg.get("min_balance")
            size_at_min = cfg.get("size_at_min")
            size_at_max = cfg.get("size_at_max")
            threshold = cfg.get("threshold")
            if None in (min_balance, size_at_min, size_at_max, threshold):
                errors.append(f"balance_profile {name} missing progressive fields")
                return cfg
            max_balance = cfg.get("max_balance", threshold)
            if balance <= min_balance:
                base = size_at_min
            elif balance >= max_balance:
                base = size_at_max
            else:
                progress = (balance - min_balance) / (max_balance - min_balance)
                base = size_at_min + (size_at_max - size_at_min) * progress
            cfg["base_position_usd"] = base

        return cfg

    def log_bundle(self, bundle: ParameterBundle, symbol: str) -> None:
        if not bundle:
            return
        try:
            payload = {
                "symbol": symbol,
                "valid": bundle.status.valid,
                "errors": bundle.status.errors,
                "warnings": bundle.status.warnings,
                "signal": asdict(bundle.signal) if bundle.signal else None,
                "exit": asdict(bundle.exit) if bundle.exit else None,
                "order": asdict(bundle.order) if bundle.order else None,
                "risk": asdict(bundle.risk) if bundle.risk else None,
                "patterns": asdict(bundle.patterns) if bundle.patterns else None,
            }
            logger.debug(f"PARAM_ORCH: {payload}")
        except Exception as exc:
            logger.debug(f"PARAM_ORCH: failed to log bundle: {exc}")
