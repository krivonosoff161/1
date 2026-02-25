"""
Risk Manager РґР»СЏ Futures С‚РѕСЂРіРѕРІР»Рё.

РћС‚РІРµС‚СЃС‚РІРµРЅРЅРѕСЃС‚СЊ:
- Р Р°СЃС‡РµС‚ СЂР°Р·РјРµСЂР° РїРѕР·РёС†РёРё СЃ СѓС‡РµС‚РѕРј Р±Р°Р»Р°РЅСЃР° Рё СЂРµР¶РёРјР°
- РџСЂРѕРІРµСЂРєР° Р±РµР·РѕРїР°СЃРЅРѕСЃС‚Рё РјР°СЂР¶Рё
- РРЅС‚РµРіСЂР°С†РёСЏ СЃ ConfigManager
- РРЅС‚РµРіСЂР°С†РёСЏ СЃ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёРјРё risk РјРѕРґСѓР»СЏРјРё
- вњ… FIX: Circuit breaker РґР»СЏ СЃРµСЂРёРё СѓР±С‹С‚РєРѕРІ
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig

from .config.config_manager import ConfigManager
from .config.config_view import get_scalping_view
from .risk.liquidation_protector import LiquidationProtector
from .risk.margin_monitor import MarginMonitor
from .risk.max_size_limiter import MaxSizeLimiter
from .utils.units import pct_points_to_fraction


class FuturesRiskManager:
    """
    РњРµРЅРµРґР¶РµСЂ СЂРёСЃРєРѕРІ РґР»СЏ Futures С‚РѕСЂРіРѕРІР»Рё.

    Р¦РµРЅС‚СЂР°Р»РёР·СѓРµС‚ РІСЃСЋ Р»РѕРіРёРєСѓ СѓРїСЂР°РІР»РµРЅРёСЏ СЂРёСЃРєР°РјРё.
    """

    def __init__(
        self,
        config: BotConfig,
        client: OKXFuturesClient,
        config_manager: ConfigManager,
        liquidation_protector: Optional[LiquidationProtector] = None,
        margin_monitor: Optional[MarginMonitor] = None,
        max_size_limiter: Optional[MaxSizeLimiter] = None,
        orchestrator: Optional[Any] = None,
        data_registry=None,  # вњ… РќРћР’РћР•: DataRegistry РґР»СЏ С‡С‚РµРЅРёСЏ Р±Р°Р»Р°РЅСЃР°
    ):
        """
        Args:
            config: РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ Р±РѕС‚Р°
            client: Futures РєР»РёРµРЅС‚
            config_manager: Config Manager
            liquidation_protector: Р—Р°С‰РёС‚Р° РѕС‚ Р»РёРєРІРёРґР°С†РёРё (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ)
            margin_monitor: РњРѕРЅРёС‚РѕСЂРёРЅРі РјР°СЂР¶Рё (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ)
            max_size_limiter: РћРіСЂР°РЅРёС‡РёС‚РµР»СЊ СЂР°Р·РјРµСЂР° (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ)
            orchestrator: РЎСЃС‹Р»РєР° РЅР° orchestrator РґР»СЏ РґРѕСЃС‚СѓРїР° Рє РјРµС‚РѕРґР°Рј (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ)
            data_registry: DataRegistry РґР»СЏ С‡С‚РµРЅРёСЏ Р±Р°Р»Р°РЅСЃР° (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ)
        """
        self.config = config
        self.scalping_config = get_scalping_view(config)
        self.risk_config = config.risk
        self.client = client
        self.config_manager = config_manager
        self.liquidation_protector = liquidation_protector
        self.margin_monitor = margin_monitor
        self.max_size_limiter = max_size_limiter
        self.orchestrator = orchestrator  # вњ… Р Р•Р¤РђРљРўРћР РРќР“: Р”Р»СЏ РґРѕСЃС‚СѓРїР° Рє РјРµС‚РѕРґР°Рј orchestrator
        # вњ… РќРћР’РћР•: DataRegistry РґР»СЏ С‡С‚РµРЅРёСЏ Р±Р°Р»Р°РЅСЃР°
        self.data_registry = data_registry

        # РџРѕР»СѓС‡Р°РµРј symbol_profiles РёР· config_manager
        self.symbol_profiles = config_manager.get_symbol_profiles()

        # вњ… FIX: Circuit breaker РґР»СЏ СЃРµСЂРёРё СѓР±С‹С‚РєРѕРІ - РђР”РђРџРўРР’РќРћ РёР· РєРѕРЅС„РёРіР°
        self.pair_loss_streak: Dict[
            str, int
        ] = {}  # symbol в†’ РєРѕР»-РІРѕ СѓР±С‹С‚РєРѕРІ РїРѕРґСЂСЏРґ
        self.pair_block_until: Dict[
            str, float
        ] = {}  # symbol в†’ monotonic time РґРѕ РєРѕС‚РѕСЂРѕРіРѕ Р±Р»РѕРє

        # вњ… FIX: Р§РёС‚Р°РµРј РёР· РєРѕРЅС„РёРіР°, РЅРµ С…Р°СЂРґ-РєРѕРґ
        self._max_consecutive_losses = (
            getattr(self.risk_config, "consecutive_losses_limit", None) or 5
        )
        self._block_duration_minutes = (
            getattr(self.risk_config, "pair_block_duration_min", None) or 30
        )

        # вњ… РќРћР’РћР•: РћС‚СЃР»РµР¶РёРІР°РЅРёРµ РґРЅРµРІРЅРѕРіРѕ PnL РґР»СЏ max_daily_loss
        self.daily_pnl: float = 0.0  # РўРµРєСѓС‰РёР№ РґРЅРµРІРЅРѕР№ PnL
        self.daily_pnl_date: Optional[
            str
        ] = None  # Р”Р°С‚Р° С‚РµРєСѓС‰РµРіРѕ РґРЅСЏ (YYYY-MM-DD)
        raw_max_daily_loss_percent = getattr(
            self.risk_config, "max_daily_loss_percent", None
        )
        if raw_max_daily_loss_percent is None:
            risk_cfg_raw = {}
            if self.config_manager and hasattr(self.config_manager, "_raw_config_dict"):
                risk_cfg_raw = (self.config_manager._raw_config_dict or {}).get(
                    "risk", {}
                )
            if isinstance(risk_cfg_raw, dict):
                raw_max_daily_loss_percent = risk_cfg_raw.get("max_daily_loss_percent")
        if raw_max_daily_loss_percent is None:
            model_fields = getattr(type(self.risk_config), "model_fields", {})
            default_field = (
                model_fields.get("max_daily_loss_percent")
                if isinstance(model_fields, dict)
                else None
            )
            raw_max_daily_loss_percent = getattr(default_field, "default", 10.0)
        try:
            self.max_daily_loss_percent: float = float(raw_max_daily_loss_percent)
        except (TypeError, ValueError):
            self.max_daily_loss_percent = 10.0  # Model default fallback
        # Max daily loss percent of balance
        self.daily_trading_stopped: bool = (
            False  # Р¤Р»Р°Рі РѕСЃС‚Р°РЅРѕРІРєРё С‚РѕСЂРіРѕРІР»Рё
        )

        logger.info(
            f"ADAPT_LOAD consecutive_losses_limit={self._max_consecutive_losses}"
        )
        logger.info(
            f"ADAPT_LOAD pair_block_duration_min={self._block_duration_minutes}"
        )
        logger.info("вњ… FuturesRiskManager initialized")

    def _get_symbol_regime_profile(
        self, symbol: Optional[str], regime: Optional[str]
    ) -> Dict[str, Any]:
        """Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅС‹Р№ РјРµС‚РѕРґ РґР»СЏ РїРѕР»СѓС‡РµРЅРёСЏ regime_profile (Р°РЅР°Р»РѕРі orchestrator._get_symbol_regime_profile)"""
        if not symbol:
            return {}
        profile = self.symbol_profiles.get(symbol, {})
        if not profile:
            return {}
        if regime:
            symbol_dict = (
                self.config_manager.to_dict(profile)
                if not isinstance(profile, dict)
                else profile
            )
            return symbol_dict.get(regime.lower(), {})
        return {}

    def _resolve_sl_percent_for_risk(
        self, symbol: Optional[str], regime: Optional[str]
    ) -> float:
        """РќР°РґС‘Р¶РЅРѕ РїРѕР»СѓС‡РёС‚СЊ sl_percent РґР»СЏ СЂРёСЃРє-СЂР°СЃС‡С‘С‚РѕРІ (РІ РїСЂРѕС†РµРЅС‚Р°С…, РЅРµ РґРѕР»Рµ)."""
        # 1) РР· scalping_config (РµСЃР»Рё Р·Р°РґР°РЅ)
        sl_percent = getattr(self.scalping_config, "sl_percent", None)
        if sl_percent is not None:
            return float(sl_percent)

        # 2) РР· exit_params (С†РµРЅС‚СЂР°Р»РёР·РѕРІР°РЅРЅС‹Рµ РїР°СЂР°РјРµС‚СЂС‹ РІС‹С…РѕРґРѕРІ)
        try:
            raw = getattr(self.config_manager, "_raw_config_dict", {}) or {}
            exit_params = raw.get("exit_params") or {}
            regime_key = (regime or "ranging").lower()
            sl_percent = (exit_params.get(regime_key) or {}).get("sl_min_percent")
            if sl_percent is not None:
                return float(sl_percent)
        except Exception:
            pass

        # 3) РР· symbol_profiles РїРѕ СЂРµР¶РёРјСѓ (РµСЃР»Рё Р·Р°РґР°РЅ)
        if symbol:
            regime_profile = self._get_symbol_regime_profile(symbol, regime)
            sl_percent = regime_profile.get("sl_percent")
            if sl_percent is not None:
                return float(sl_percent)

        raise ValueError(
            "sl_percent РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚: РїСЂРѕРІРµСЂСЊ config_futures.yaml (scalping.sl_percent РёР»Рё exit_params.<regime>.sl_min_percent)"
        )

    async def _get_used_margin(self) -> float:
        """РџРѕР»СѓС‡Р°РµС‚ РёСЃРїРѕР»СЊР·РѕРІР°РЅРЅСѓСЋ РјР°СЂР¶Сѓ С‡РµСЂРµР· orchestrator РёР»Рё РЅР°РїСЂСЏРјСѓСЋ"""
        if self.orchestrator and hasattr(self.orchestrator, "_get_used_margin"):
            return await self.orchestrator._get_used_margin()
        # Fallback: РїРѕР»СѓС‡Р°РµРј РЅР°РїСЂСЏРјСѓСЋ
        try:
            exchange_positions = await self.client.get_positions()
            if not exchange_positions:
                return 0.0
            total_margin = 0.0
            for pos in exchange_positions:
                try:
                    pos_size = float(pos.get("pos", "0") or 0)
                except (TypeError, ValueError):
                    pos_size = 0.0
                if abs(pos_size) < 1e-8:
                    continue
                try:
                    margin = float(pos.get("margin", "0") or 0)
                    total_margin += margin
                except (TypeError, ValueError):
                    continue
            return total_margin
        except Exception as e:
            logger.warning(f"вљ пёЏ РћС€РёР±РєР° РїРѕР»СѓС‡РµРЅРёСЏ used_margin: {e}")
            return 0.0

    def _calculate_dynamic_margin_cap(
        self,
        balance: float,
        symbol: str,
        regime: str,
        volatility: Optional[float] = None,
        daily_pnl: float = 0.0,
        open_positions_margin: float = 0.0,
    ) -> float:
        """
        Р”РёРЅР°РјРёС‡РµСЃРєРёР№ СЂР°СЃС‡РµС‚ РјР°РєСЃРёРјР°Р»СЊРЅРѕР№ РјР°СЂР¶Рё РЅР° СЃРґРµР»РєСѓ.

        РЈС‡РёС‚С‹РІР°РµС‚:
        - max_margin_per_trade РёР· РєРѕРЅС„РёРіР°
        - Р’РѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ (ATR)
        - РџСЂРѕСЃР°РґРєСѓ РїРѕСЂС‚С„РµР»СЏ
        - Р РµР¶РёРј СЂС‹РЅРєР°

        Args:
            balance: РўРµРєСѓС‰РёР№ Р±Р°Р»Р°РЅСЃ
            symbol: РўРѕСЂРіРѕРІС‹Р№ СЃРёРјРІРѕР»
            regime: Р РµР¶РёРј СЂС‹РЅРєР° (trending, ranging, choppy)
            volatility: Р’РѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ (ATR % РѕС‚ С†РµРЅС‹, РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ)
            daily_pnl: Р”РЅРµРІРЅРѕР№ PnL (РґР»СЏ СЂР°СЃС‡РµС‚Р° РїСЂРѕСЃР°РґРєРё)
            open_positions_margin: РСЃРїРѕР»СЊР·РѕРІР°РЅРЅР°СЏ РјР°СЂР¶Р° РѕС‚РєСЂС‹С‚С‹С… РїРѕР·РёС†РёР№

        Returns:
            РњР°РєСЃРёРјР°Р»СЊРЅР°СЏ РјР°СЂР¶Р° РЅР° СЃРґРµР»РєСѓ РІ USD
        """
        try:
            # РџРѕР»СѓС‡Р°РµРј РїР°СЂР°РјРµС‚СЂС‹ РёР· РєРѕРЅС„РёРіР°
            risk_config = getattr(self.scalping_config, "risk_config", {})
            if isinstance(risk_config, dict):
                max_margin_per_trade_pct = (
                    risk_config.get("max_margin_per_trade", 15.0) / 100.0
                )
                volatility_factor_enabled = risk_config.get(
                    "volatility_factor_enabled", True
                )
                drawdown_factor_enabled = risk_config.get(
                    "drawdown_factor_enabled", True
                )
                min_margin_cap = risk_config.get("min_margin_cap", 8.0)
                max_margin_cap_multiplier = risk_config.get(
                    "max_margin_cap_multiplier", 2.0
                )
            else:
                max_margin_per_trade_pct = (
                    getattr(risk_config, "max_margin_per_trade", 15.0) / 100.0
                )
                volatility_factor_enabled = getattr(
                    risk_config, "volatility_factor_enabled", True
                )
                drawdown_factor_enabled = getattr(
                    risk_config, "drawdown_factor_enabled", True
                )
                min_margin_cap = getattr(risk_config, "min_margin_cap", 8.0)
                max_margin_cap_multiplier = getattr(
                    risk_config, "max_margin_cap_multiplier", 2.0
                )

            # Р‘Р°Р·РѕРІС‹Р№ РєР°Рї = Р±Р°Р»Р°РЅСЃ * РїСЂРѕС†РµРЅС‚
            base_cap = balance * max_margin_per_trade_pct

            # Р¤Р°РєС‚РѕСЂ РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚Рё (С‡РµРј РІС‹С€Рµ РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ, С‚РµРј РјРµРЅСЊС€Рµ РєР°Рї)
            volatility_factor = 1.0
            if volatility_factor_enabled and volatility is not None and volatility > 0:
                # РќРѕСЂРјР°Р»РёР·СѓРµРј РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ: 1% = 1.0, 2% = 0.5, 3% = 0.33
                # РСЃРїРѕР»СЊР·СѓРµРј РѕР±СЂР°С‚РЅСѓСЋ Р·Р°РІРёСЃРёРјРѕСЃС‚СЊ: factor = 1 / (1 + volatility)
                volatility_factor = 1.0 / (
                    1.0 + volatility * 10
                )  # РЈРјРЅРѕР¶Р°РµРј РЅР° 10 РґР»СЏ СѓСЃРёР»РµРЅРёСЏ СЌС„С„РµРєС‚Р°
                volatility_factor = max(
                    0.5, min(1.5, volatility_factor)
                )  # РћРіСЂР°РЅРёС‡РёРІР°РµРј 0.5-1.5

            # Р¤Р°РєС‚РѕСЂ РїСЂРѕСЃР°РґРєРё (С‡РµРј Р±РѕР»СЊС€Рµ РїСЂРѕСЃР°РґРєР°, С‚РµРј РјРµРЅСЊС€Рµ РєР°Рї)
            drawdown_factor = 1.0
            if drawdown_factor_enabled and daily_pnl < 0:
                # РџСЂРѕСЃР°РґРєР° СѓРјРµРЅСЊС€Р°РµС‚ РєР°Рї: -5% = 0.5, -10% = 0.0
                drawdown_pct = abs(daily_pnl) / balance if balance > 0 else 0.0
                drawdown_factor = max(
                    0.0, 1.0 - drawdown_pct * 2
                )  # РЈСЃРёР»РёРІР°РµРј СЌС„С„РµРєС‚ РїСЂРѕСЃР°РґРєРё
                drawdown_factor = max(
                    0.3, min(1.0, drawdown_factor)
                )  # РњРёРЅРёРјСѓРј 30% РѕС‚ Р±Р°Р·РѕРІРѕРіРѕ РєР°РїР°

            # Р РµР¶РёРјРЅС‹Р№ РјРЅРѕР¶РёС‚РµР»СЊ (trending = Р±РѕР»СЊС€Рµ, choppy = РјРµРЅСЊС€Рµ)
            regime_multiplier = 1.0
            if regime:
                regime_lower = regime.lower()
                if regime_lower == "trending":
                    regime_multiplier = 1.2  # +20% РІ С‚СЂРµРЅРґРµ
                elif regime_lower == "ranging":
                    regime_multiplier = 1.0  # РЎС‚Р°РЅРґР°СЂС‚
                elif regime_lower == "choppy":
                    regime_multiplier = 0.8  # -20% РІ С…Р°РѕСЃРµ

            # Р Р°СЃСЃС‡РёС‚С‹РІР°РµРј РґРёРЅР°РјРёС‡РµСЃРєРёР№ РєР°Рї
            dynamic_cap = (
                base_cap * volatility_factor * drawdown_factor * regime_multiplier
            )

            # РџСЂРёРјРµРЅСЏРµРј РѕРіСЂР°РЅРёС‡РµРЅРёСЏ
            min_cap = min_margin_cap
            max_cap = base_cap * max_margin_cap_multiplier

            final_cap = max(min_cap, min(dynamic_cap, max_cap))

            logger.debug(
                f"рџ“Љ Dynamic Margin Cap РґР»СЏ {symbol} ({regime}): "
                f"base=${base_cap:.2f}, vol_factor={volatility_factor:.2f}, "
                f"drawdown_factor={drawdown_factor:.2f}, regime_mult={regime_multiplier:.2f}, "
                f"final=${final_cap:.2f}"
            )

            return final_cap

        except Exception as e:
            logger.warning(
                f"вљ пёЏ РћС€РёР±РєР° СЂР°СЃС‡РµС‚Р° dynamic_margin_cap: {e}"
            )
            # Fallback: РІРѕР·РІСЂР°С‰Р°РµРј Р±Р°Р·РѕРІС‹Р№ РєР°Рї
            risk_config = getattr(self.scalping_config, "risk_config", {})
            if isinstance(risk_config, dict):
                max_margin_per_trade_pct = (
                    risk_config.get("max_margin_per_trade", 15.0) / 100.0
                )
            else:
                max_margin_per_trade_pct = (
                    getattr(risk_config, "max_margin_per_trade", 15.0) / 100.0
                )
            return balance * max_margin_per_trade_pct

    async def calculate_max_margin_per_position(
        self,
        balance: float,
        balance_profile: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> float:
        """
        Р Р°СЃСЃС‡РёС‚Р°С‚СЊ РјР°РєСЃРёРјР°Р»СЊРЅСѓСЋ РјР°СЂР¶Сѓ РЅР° РѕРґРЅСѓ РїРѕР·РёС†РёСЋ.

        РСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РґР»СЏ РїСЂРѕРІРµСЂРєРё Р»РёРјРёС‚РѕРІ РїСЂРё РґРѕР±Р°РІР»РµРЅРёРё Рє РїРѕР·РёС†РёРё.
        РЈС‡РёС‚С‹РІР°РµС‚ Р±Р°Р»Р°РЅСЃ, РїСЂРѕС„РёР»СЊ Р±Р°Р»Р°РЅСЃР° Рё СЂРµР¶РёРј СЂС‹РЅРєР°.

        Args:
            balance: РўРµРєСѓС‰РёР№ Р±Р°Р»Р°РЅСЃ
            balance_profile: РџСЂРѕС„РёР»СЊ Р±Р°Р»Р°РЅСЃР° (small, medium, large)
            regime: Р РµР¶РёРј СЂС‹РЅРєР° (trending, ranging, choppy)

        Returns:
            РњР°РєСЃРёРјР°Р»СЊРЅР°СЏ РјР°СЂР¶Р° РЅР° РїРѕР·РёС†РёСЋ РІ USD
        """
        try:
            # вњ… P0-1 FIX: РСЃРїРѕР»СЊР·СѓРµРј max_position_percent РёР· РєРѕРЅС„РёРіР° (РґРµР»РёРј РЅР° 100)
            resolved_profile_name = balance_profile
            profile_cfg: Dict[str, Any] = {}

            # 1) Get profile selected by current balance (source of truth).
            if self.config_manager:
                selected_profile = self.config_manager.get_balance_profile(balance)
                profile_cfg = self.config_manager.to_dict(selected_profile)
                resolved_profile_name = selected_profile.get(
                    "name", resolved_profile_name
                )

            # 2) Optional explicit override by profile name from config.
            if balance_profile:
                balance_profiles_raw = getattr(
                    self.scalping_config, "balance_profiles", {}
                )
                if isinstance(balance_profiles_raw, dict):
                    balance_profiles = balance_profiles_raw
                elif self.config_manager:
                    balance_profiles = self.config_manager.to_dict(balance_profiles_raw)
                else:
                    balance_profiles = {}
                requested_profile = (
                    balance_profiles.get(balance_profile, {})
                    if isinstance(balance_profiles, dict)
                    else {}
                )
                if not isinstance(requested_profile, dict) and self.config_manager:
                    requested_profile = self.config_manager.to_dict(requested_profile)
                if requested_profile:
                    profile_cfg = requested_profile
                    resolved_profile_name = balance_profile
                else:
                    logger.warning(
                        f"Invalid balance_profile={balance_profile}, use auto profile={resolved_profile_name}"
                    )

            raw_max_position_percent = profile_cfg.get("max_position_percent")
            if raw_max_position_percent is None:
                raise ValueError(
                    f"max_position_percent missing for balance_profile={resolved_profile_name}"
                )

            # max_position_percent in config is percent points (e.g. 15.0 = 15%).
            base_percent = float(raw_max_position_percent) / 100.0
            if base_percent <= 0 or base_percent > 1.0:
                raise ValueError(
                    f"Invalid max_position_percent={base_percent*100:.2f}% for profile={resolved_profile_name}"
                )

            # РљРѕСЂСЂРµРєС‚РёСЂРѕРІРєР° РїРѕ СЂРµР¶РёРјСѓ СЂС‹РЅРєР°
            regime_multiplier = 1.0
            if regime == "trending":
                regime_multiplier = (
                    1.05  # +5% РІ С‚СЂРµРЅРґРµ (РјРѕР¶РЅРѕ Р±РѕР»СЊС€Рµ)
                )
            elif regime == "choppy":
                regime_multiplier = 0.95  # -5% РІ С…Р°РѕСЃРµ (РјРµРЅСЊС€Рµ СЂРёСЃРєР°)
            # ranging: 1.0 (Р±РµР· РёР·РјРµРЅРµРЅРёР№)

            max_margin_per_position = balance * base_percent * regime_multiplier

            logger.debug(
                f"рџ“Љ [MAX_MARGIN_PER_POSITION] balance=${balance:.2f}, "
                f"profile={resolved_profile_name}, regime={regime}, "
                f"base_percent={base_percent*100:.1f}%, "
                f"regime_multiplier={regime_multiplier}, "
                f"max_margin=${max_margin_per_position:.2f}"
            )

            return max_margin_per_position

        except Exception as e:
            logger.error(
                f"Failed max_margin_per_position calculation: {e}", exc_info=True
            )
            # Fallback: recover percent from selected config profile first.
            try:
                if self.config_manager:
                    fallback_profile = self.config_manager.get_balance_profile(balance)
                    fallback_percent = (
                        float(fallback_profile.get("max_position_percent")) / 100.0
                    )
                    return balance * max(0.0, min(1.0, fallback_percent))
            except Exception:
                pass
            # Last-resort safeguard.
            return balance * 0.20

    def _calculate_risk_based_margin(
        self,
        balance: float,
        risk_per_trade: float,
        sl_distance_pct: float,
        leverage: int,
        price: float,
    ) -> float:
        """
        Р Р°СЃС‡РµС‚ РјР°СЂР¶Рё С‡РµСЂРµР· risk_usd / sl_distance (РЈСЂРѕРІРµРЅСЊ 3: Margin Budget).

        Р¤РѕСЂРјСѓР»Р°:
        risk_usd = balance * risk_per_trade
        size_coins = risk_usd / sl_distance_pct
        margin_usd = (size_coins * price) / leverage

        Args:
            balance: РўРµРєСѓС‰РёР№ Р±Р°Р»Р°РЅСЃ
            risk_per_trade: Р РёСЃРє РЅР° СЃРґРµР»РєСѓ РІ РїСЂРѕС†РµРЅС‚Р°С… (РЅР°РїСЂРёРјРµСЂ, 0.012 = 1.2%)
            sl_distance_pct: Р Р°СЃСЃС‚РѕСЏРЅРёРµ РґРѕ SL РІ РїСЂРѕС†РµРЅС‚Р°С… (РЅР°РїСЂРёРјРµСЂ, 0.02 = 2%)
            leverage: РџР»РµС‡Рѕ
            price: РўРµРєСѓС‰Р°СЏ С†РµРЅР°

        Returns:
            РњР°СЂР¶Р° РІ USD
        """
        try:
            if sl_distance_pct <= 0 or leverage <= 0 or price <= 0:
                logger.warning(
                    f"вљ пёЏ Risk-based margin: РЅРµРІР°Р»РёРґРЅС‹Рµ РїР°СЂР°РјРµС‚СЂС‹ "
                    f"(sl_distance={sl_distance_pct}, leverage={leverage}, price={price})"
                )
                return 0.0

            # Р Р°СЃСЃС‡РёС‚С‹РІР°РµРј СЂРёСЃРє РІ USD
            risk_usd = balance * risk_per_trade

            # Р Р°СЃСЃС‡РёС‚С‹РІР°РµРј СЂР°Р·РјРµСЂ РїРѕР·РёС†РёРё РІ РјРѕРЅРµС‚Р°С… С‡РµСЂРµР· СЂРёСЃРє
            # Р•СЃР»Рё SL = 2%, С‚Рѕ РїСЂРё СѓР±С‹С‚РєРµ 2% РјС‹ РїРѕС‚РµСЂСЏРµРј risk_usd
            # Р—РЅР°С‡РёС‚: size_coins * price * sl_distance_pct = risk_usd
            # size_coins = risk_usd / (price * sl_distance_pct)
            size_coins = risk_usd / (price * sl_distance_pct)

            # Р Р°СЃСЃС‡РёС‚С‹РІР°РµРј РЅРѕРјРёРЅР°Р»СЊРЅСѓСЋ СЃС‚РѕРёРјРѕСЃС‚СЊ
            notional_usd = size_coins * price

            # Р Р°СЃСЃС‡РёС‚С‹РІР°РµРј РјР°СЂР¶Сѓ
            margin_usd = notional_usd / leverage

            logger.debug(
                f"рџ“Љ Risk-based Margin: risk_usd=${risk_usd:.2f}, "
                f"sl_distance={sl_distance_pct*100:.2f}%, size_coins={size_coins:.6f}, "
                f"notional=${notional_usd:.2f}, margin=${margin_usd:.2f}"
            )

            return margin_usd

        except Exception as e:
            logger.warning(f"вљ пёЏ РћС€РёР±РєР° СЂР°СЃС‡РµС‚Р° risk_based_margin: {e}")
            return 0.0

    async def _check_drawdown_protection(self) -> bool:
        """РџСЂРѕРІРµСЂСЏРµС‚ drawdown protection С‡РµСЂРµР· orchestrator"""
        if self.orchestrator and hasattr(
            self.orchestrator, "_check_drawdown_protection"
        ):
            return await self.orchestrator._check_drawdown_protection()
        return True  # Р•СЃР»Рё orchestrator РЅРµ РґРѕСЃС‚СѓРїРµРЅ, СЂР°Р·СЂРµС€Р°РµРј С‚РѕСЂРіРѕРІР»СЋ

    async def _check_emergency_stop_unlock(self):
        """РџСЂРѕРІРµСЂСЏРµС‚ emergency stop unlock С‡РµСЂРµР· orchestrator"""
        if self.orchestrator and hasattr(
            self.orchestrator, "_check_emergency_stop_unlock"
        ):
            return await self.orchestrator._check_emergency_stop_unlock()

    # вњ… FIX: Circuit breaker РјРµС‚РѕРґС‹ РґР»СЏ СЃРµСЂРёРё СѓР±С‹С‚РєРѕРІ
    def record_trade_result(
        self,
        symbol: str,
        is_profit: bool,
        error_code: Optional[str] = None,
        error_msg: Optional[str] = None,
    ):
        """
        Р—Р°РїРёСЃС‹РІР°РµС‚ СЂРµР·СѓР»СЊС‚Р°С‚ СЃРґРµР»РєРё РґР»СЏ circuit breaker.
        Р’С‹Р·С‹РІР°С‚СЊ РїРѕСЃР»Рµ Р·Р°РєСЂС‹С‚РёСЏ РєР°Р¶РґРѕР№ СЃРґРµР»РєРё.

        Args:
            symbol: РўРѕСЂРіРѕРІС‹Р№ СЃРёРјРІРѕР»
            is_profit: True РµСЃР»Рё РїСЂРёР±С‹Р»СЊ, False РµСЃР»Рё СѓР±С‹С‚РѕРє
            error_code: РљРѕРґ РѕС€РёР±РєРё (РЅР°РїСЂРёРјРµСЂ, "51169") - РґР»СЏ С„РёР»СЊС‚СЂР°С†РёРё С‚РµС…РЅРёС‡РµСЃРєРёС… РѕС€РёР±РѕРє
            error_msg: РЎРѕРѕР±С‰РµРЅРёРµ РѕР± РѕС€РёР±РєРµ - РґР»СЏ РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅРѕР№ РїСЂРѕРІРµСЂРєРё
        """
        # вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР•: РќРµ СЃС‡РёС‚Р°РµРј С‚РµС…РЅРёС‡РµСЃРєРёРµ РѕС€РёР±РєРё (51169) РєР°Рє СѓР±С‹С‚РєРё
        # РћС€РёР±РєР° 51169 = "Order failed because you don't have any positions to reduce"
        # Р­С‚Рѕ С‚РµС…РЅРёС‡РµСЃРєР°СЏ РѕС€РёР±РєР°, Р° РЅРµ СѓР±С‹С‚РѕРє РѕС‚ СЂС‹РЅРєР°
        if not is_profit and (
            error_code == "51169"
            or (error_msg and "don't have any positions" in error_msg.lower())
        ):
            logger.debug(
                f"вљ пёЏ РўРµС…РЅРёС‡РµСЃРєР°СЏ РѕС€РёР±РєР° {error_code} РґР»СЏ {symbol} РЅРµ СЃС‡РёС‚Р°РµС‚СЃСЏ СѓР±С‹С‚РєРѕРј РґР»СЏ PAIR_BLOCK"
            )
            return  # РќРµ Р·Р°РїРёСЃС‹РІР°РµРј РєР°Рє СѓР±С‹С‚РѕРє

        if is_profit:
            # РЎР±СЂР°СЃС‹РІР°РµРј СЃРµСЂРёСЋ РїСЂРё РїСЂРёР±С‹Р»Рё
            if symbol in self.pair_loss_streak:
                old_streak = self.pair_loss_streak[symbol]
                if old_streak > 0:
                    logger.info(
                        f"PAIR_STREAK_RESET {symbol}: {old_streak} в†’ 0 (profit)"
                    )
            self.pair_loss_streak[symbol] = 0
        else:
            # РЈРІРµР»РёС‡РёРІР°РµРј СЃРµСЂРёСЋ РїСЂРё СѓР±С‹С‚РєРµ
            self.pair_loss_streak[symbol] = self.pair_loss_streak.get(symbol, 0) + 1
            streak = self.pair_loss_streak[symbol]

            if streak < self._max_consecutive_losses:
                logger.info(
                    f"PAIR_STREAK {symbol} {streak}/{self._max_consecutive_losses}"
                )
            else:
                # Р‘Р»РѕРєРёСЂСѓРµРј РїР°СЂСѓ
                block_until = time.monotonic() + (self._block_duration_minutes * 60)
                self.pair_block_until[symbol] = block_until
                logger.critical(
                    f"PAIR_BLOCK {symbol} {streak}/{self._max_consecutive_losses} "
                    f"в†’ blocked for {self._block_duration_minutes} min"
                )

    def get_consecutive_losses(self, symbol: str) -> int:
        """РџРѕР»СѓС‡РёС‚СЊ РєРѕР»РёС‡РµСЃС‚РІРѕ РїРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅС‹С… СѓР±С‹С‚РєРѕРІ РґР»СЏ СЃРёРјРІРѕР»Р°."""
        return self.pair_loss_streak.get(symbol, 0)

    def is_symbol_blocked(self, symbol: str) -> bool:
        """РџСЂРѕРІРµСЂСЏРµС‚, Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅ Р»Рё СЃРёРјРІРѕР» РёР·-Р·Р° СЃРµСЂРёРё СѓР±С‹С‚РєРѕРІ."""
        if symbol not in self.pair_block_until:
            return False

        block_until = self.pair_block_until[symbol]
        if time.monotonic() >= block_until:
            # Р‘Р»РѕРєРёСЂРѕРІРєР° РёСЃС‚РµРєР»Р° - СЃР±СЂР°СЃС‹РІР°РµРј
            del self.pair_block_until[symbol]
            self.pair_loss_streak[symbol] = 0
            logger.info(f"PAIR_UNBLOCK {symbol}: block expired, streak reset")
            return False

        # Р‘Р»РѕРєРёСЂРѕРІРєР° Р°РєС‚РёРІРЅР°
        remaining = (block_until - time.monotonic()) / 60
        logger.debug(f"PAIR_BLOCKED {symbol}: {remaining:.1f} min remaining")
        return True

    async def _check_max_daily_loss(self, balance: float) -> bool:
        """
        РџСЂРѕРІРµСЂРєР° РјР°РєСЃРёРјР°Р»СЊРЅРѕР№ РґРЅРµРІРЅРѕР№ РїРѕС‚РµСЂРё.

        Args:
            balance: РўРµРєСѓС‰РёР№ Р±Р°Р»Р°РЅСЃ

        Returns:
            True РµСЃР»Рё С‚РѕСЂРіРѕРІР»СЏ СЂР°Р·СЂРµС€РµРЅР°, False РµСЃР»Рё РїСЂРµРІС‹С€РµРЅ Р»РёРјРёС‚
        """
        try:
            # РџРѕР»СѓС‡Р°РµРј С‚РµРєСѓС‰СѓСЋ РґР°С‚Сѓ
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Р•СЃР»Рё РґР°С‚Р° РёР·РјРµРЅРёР»Р°СЃСЊ, СЃР±СЂР°СЃС‹РІР°РµРј РґРЅРµРІРЅРѕР№ PnL
            if self.daily_pnl_date != current_date:
                logger.info(
                    f"рџ“… РќРѕРІС‹Р№ С‚РѕСЂРіРѕРІС‹Р№ РґРµРЅСЊ: {current_date}. "
                    f"РЎР±СЂР°СЃС‹РІР°РµРј РґРЅРµРІРЅРѕР№ PnL (Р±С‹Р»Рѕ: ${self.daily_pnl:.2f})"
                )
                self.daily_pnl = 0.0
                self.daily_pnl_date = current_date
                self.daily_trading_stopped = False

            # Р•СЃР»Рё С‚РѕСЂРіРѕРІР»СЏ СѓР¶Рµ РѕСЃС‚Р°РЅРѕРІР»РµРЅР°, РїСЂРѕРІРµСЂСЏРµРј РЅРµ РЅСѓР¶РЅРѕ Р»Рё СЂР°Р·Р±Р»РѕРєРёСЂРѕРІР°С‚СЊ
            if self.daily_trading_stopped:
                # РџСЂРѕРІРµСЂСЏРµРј, РЅРµ РІРѕСЃСЃС‚Р°РЅРѕРІРёР»СЃСЏ Р»Рё Р±Р°Р»Р°РЅСЃ
                max_daily_loss_usd = balance * (self.max_daily_loss_percent / 100.0)
                if self.daily_pnl >= -max_daily_loss_usd:
                    logger.info(
                        f"вњ… Р”РЅРµРІРЅРѕР№ PnL РІРѕСЃСЃС‚Р°РЅРѕРІРёР»СЃСЏ: ${self.daily_pnl:.2f} >= "
                        f"-${max_daily_loss_usd:.2f}. Р’РѕР·РѕР±РЅРѕРІР»СЏРµРј С‚РѕСЂРіРѕРІР»СЋ"
                    )
                    self.daily_trading_stopped = False
                else:
                    logger.warning(
                        f"в›” РўРѕСЂРіРѕРІР»СЏ РѕСЃС‚Р°РЅРѕРІР»РµРЅР° РёР·-Р·Р° РїСЂРµРІС‹С€РµРЅРёСЏ max_daily_loss: "
                        f"PnL=${self.daily_pnl:.2f}, Р»РёРјРёС‚=-${max_daily_loss_usd:.2f} "
                        f"({self.max_daily_loss_percent}% РѕС‚ Р±Р°Р»Р°РЅСЃР° ${balance:.2f})"
                    )
                    return False

            # РџСЂРѕРІРµСЂСЏРµРј С‚РµРєСѓС‰РёР№ РґРЅРµРІРЅРѕР№ PnL
            max_daily_loss_usd = balance * (self.max_daily_loss_percent / 100.0)
            if self.daily_pnl <= -max_daily_loss_usd:
                logger.error(
                    f"вќЊ РџР Р•Р’Р«РЁР•Рќ MAX_DAILY_LOSS: PnL=${self.daily_pnl:.2f} <= "
                    f"-${max_daily_loss_usd:.2f} ({self.max_daily_loss_percent}% РѕС‚ Р±Р°Р»Р°РЅСЃР° ${balance:.2f})"
                )
                self.daily_trading_stopped = True
                return False

            return True

        except Exception as e:
            logger.error(
                f"вќЊ РћС€РёР±РєР° РїСЂРѕРІРµСЂРєРё max_daily_loss: {e}",
                exc_info=True,
            )
            # РџСЂРё РѕС€РёР±РєРµ СЂР°Р·СЂРµС€Р°РµРј С‚РѕСЂРіРѕРІР»СЋ (Р±РµР·РѕРїР°СЃРЅРµРµ)
            return True

    def record_daily_pnl(self, pnl: float):
        """
        Р—Р°РїРёСЃС‹РІР°РµС‚ PnL СЃРґРµР»РєРё РІ РґРЅРµРІРЅРѕР№ PnL.

        Args:
            pnl: PnL СЃРґРµР»РєРё (РјРѕР¶РµС‚ Р±С‹С‚СЊ РѕС‚СЂРёС†Р°С‚РµР»СЊРЅС‹Рј)
        """
        try:
            # РџРѕР»СѓС‡Р°РµРј С‚РµРєСѓС‰СѓСЋ РґР°С‚Сѓ
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Р•СЃР»Рё РґР°С‚Р° РёР·РјРµРЅРёР»Р°СЃСЊ, СЃР±СЂР°СЃС‹РІР°РµРј РґРЅРµРІРЅРѕР№ PnL
            if self.daily_pnl_date != current_date:
                logger.info(
                    f"рџ“… РќРѕРІС‹Р№ С‚РѕСЂРіРѕРІС‹Р№ РґРµРЅСЊ: {current_date}. "
                    f"РЎР±СЂР°СЃС‹РІР°РµРј РґРЅРµРІРЅРѕР№ PnL (Р±С‹Р»Рѕ: ${self.daily_pnl:.2f})"
                )
                self.daily_pnl = 0.0
                self.daily_pnl_date = current_date
                self.daily_trading_stopped = False

            # Р”РѕР±Р°РІР»СЏРµРј PnL СЃРґРµР»РєРё
            self.daily_pnl += pnl

            logger.debug(
                f"рџ“Љ Р”РЅРµРІРЅРѕР№ PnL РѕР±РЅРѕРІР»РµРЅ: ${self.daily_pnl:.2f} "
                f"(РґРѕР±Р°РІР»РµРЅРѕ: ${pnl:.2f})"
            )

        except Exception as e:
            logger.error(
                f"вќЊ РћС€РёР±РєР° Р·Р°РїРёСЃРё РґРЅРµРІРЅРѕРіРѕ PnL: {e}",
                exc_info=True,
            )

    async def calculate_position_size(
        self,
        balance: Optional[
            float
        ] = None,  # вњ… РќРћР’РћР•: РћРїС†РёРѕРЅР°Р»СЊРЅС‹Р№ Р±Р°Р»Р°РЅСЃ (С‡РёС‚Р°РµРј РёР· DataRegistry РµСЃР»Рё РЅРµ РїРµСЂРµРґР°РЅ)
        price: float = 0.0,
        signal: Optional[Dict[str, Any]] = None,
        signal_generator=None,
    ) -> float:
        """
        Р Р°СЃСЃС‡РёС‚С‹РІР°РµС‚ СЂР°Р·РјРµСЂ РїРѕР·РёС†РёРё СЃ СѓС‡РµС‚РѕРј Balance Profiles Рё СЂРµР¶РёРјР° СЂС‹РЅРєР°.
        вњ… Р Р•Р¤РђРљРўРћР РРќР“: Р’СЃСЏ Р»РѕРіРёРєР° РїРµСЂРµРЅРµСЃРµРЅР° РёР· orchestrator._calculate_position_size
        вњ… РќРћР’РћР•: Р‘Р°Р»Р°РЅСЃ С‡РёС‚Р°РµС‚СЃСЏ РёР· DataRegistry, РµСЃР»Рё РЅРµ РїРµСЂРµРґР°РЅ

        Args:
            balance: РўРµРєСѓС‰РёР№ Р±Р°Р»Р°РЅСЃ (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ, С‡РёС‚Р°РµС‚СЃСЏ РёР· DataRegistry РµСЃР»Рё РЅРµ РїРµСЂРµРґР°РЅ)
            price: РўРµРєСѓС‰Р°СЏ С†РµРЅР°
            signal: РўРѕСЂРіРѕРІС‹Р№ СЃРёРіРЅР°Р»
            signal_generator: Signal generator РґР»СЏ РѕРїСЂРµРґРµР»РµРЅРёСЏ СЂРµР¶РёРјР°

        Returns:
            float: Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё РІ РјРѕРЅРµС‚Р°С… (РЅРµ USD!)
        """
        try:
            # вњ… РљР РРўРР§Р•РЎРљРћР•: РџСЂРѕРІРµСЂРєР° max_daily_loss РїРµСЂРµРґ СЂР°СЃС‡РµС‚РѕРј СЂР°Р·РјРµСЂР°
            # РџРѕР»СѓС‡Р°РµРј Р±Р°Р»Р°РЅСЃ РґР»СЏ РїСЂРѕРІРµСЂРєРё (РµСЃР»Рё РЅРµ РїРµСЂРµРґР°РЅ, РїРѕР»СѓС‡РёРј РїРѕР·Р¶Рµ)
            check_balance = balance
            if check_balance is None and self.data_registry:
                try:
                    balance_data = await self.data_registry.get_balance()
                    if balance_data:
                        check_balance = balance_data.get("balance")
                except Exception:
                    pass

            if check_balance and check_balance > 0:
                if not await self._check_max_daily_loss(check_balance):
                    logger.warning(
                        f"в›” РўРѕСЂРіРѕРІР»СЏ РѕСЃС‚Р°РЅРѕРІР»РµРЅР° РёР·-Р·Р° РїСЂРµРІС‹С€РµРЅРёСЏ max_daily_loss. "
                        f"Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё РЅРµ СЂР°СЃСЃС‡РёС‚С‹РІР°РµС‚СЃСЏ."
                    )
                    return 0.0

            # вњ… РќРћР’РћР•: РџРѕР»СѓС‡Р°РµРј Р±Р°Р»Р°РЅСЃ РёР· DataRegistry, РµСЃР»Рё РЅРµ РїРµСЂРµРґР°РЅ
            if balance is None:
                if self.data_registry:
                    try:
                        balance_data = await self.data_registry.get_balance()
                        if balance_data:
                            balance = balance_data.get("balance")
                            logger.debug(
                                f"вњ… RiskManager: Р‘Р°Р»Р°РЅСЃ РїРѕР»СѓС‡РµРЅ РёР· DataRegistry: ${balance:.2f}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"вљ пёЏ РћС€РёР±РєР° РїРѕР»СѓС‡РµРЅРёСЏ Р±Р°Р»Р°РЅСЃР° РёР· DataRegistry: {e}"
                        )

                # Fallback: РµСЃР»Рё DataRegistry РЅРµ РґРѕСЃС‚СѓРїРµРЅ РёР»Рё РЅРµС‚ РґР°РЅРЅС‹С…
                if balance is None:
                    if self.client:
                        try:
                            balance = await self.client.get_balance()
                            logger.debug(
                                f"вњ… RiskManager: Р‘Р°Р»Р°РЅСЃ РїРѕР»СѓС‡РµРЅ РёР· API: ${balance:.2f}"
                            )
                        except Exception as e:
                            logger.error(
                                f"вќЊ РћС€РёР±РєР° РїРѕР»СѓС‡РµРЅРёСЏ Р±Р°Р»Р°РЅСЃР° РёР· API: {e}"
                            )
                            return 0.0
                    else:
                        logger.error(
                            "вќЊ RiskManager: РќРµС‚ РґРѕСЃС‚СѓРїР° Рє Р±Р°Р»Р°РЅСЃСѓ (РЅРµС‚ data_registry Рё client)"
                        )
                        return 0.0

            if signal is None:
                signal = {}

            symbol = signal.get("symbol")
            symbol_regime = signal.get("regime")
            if (
                symbol
                and not symbol_regime
                and signal_generator
                and hasattr(signal_generator, "regime_managers")
            ):
                manager = signal_generator.regime_managers.get(symbol)
                if manager:
                    symbol_regime = manager.get_current_regime()
            if (
                not symbol_regime
                and signal_generator
                and hasattr(signal_generator, "regime_manager")
                and signal_generator.regime_manager
            ):
                symbol_regime = signal_generator.regime_manager.get_current_regime()

            balance_profile = self.config_manager.get_balance_profile(balance)

            # рџ”Ґ РђР”РђРџРўРР’РќР«Р™ Р РђРЎР§РЃРў (11.02.2026): РјР°СЂР¶Р° = balance Г— max_position_percent%
            # РСЃС‚РёРЅРЅР°СЏ Р°РґР°РїС‚РёРІРЅРѕСЃС‚СЊ вЂ” СЂР°Р·РјРµСЂ РїРѕР·РёС†РёРё РІСЃРµРіРґР° РїСЂРѕРїРѕСЂС†РёРѕРЅР°Р»РµРЅ С‚РµРєСѓС‰РµРјСѓ Р±Р°Р»Р°РЅСЃСѓ.
            # РџСЂРѕС„РёР»СЊ (micro/small/medium/large) Р·Р°РґР°С‘С‚ С‚РѕР»СЊРєРѕ РїСЂРѕС†РµРЅС‚ Рё Р·Р°С‰РёС‚РЅС‹Рµ Р»РёРјРёС‚С‹.
            # РџСЂРё СЂРѕСЃС‚Рµ Р±Р°Р»Р°РЅСЃР° 350$ в†’ 1000$ в†’ РјР°СЂР¶Р° Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЂР°СЃС‚С‘С‚ (% Г— Р±Р°Р»Р°РЅСЃ).
            is_progressive = False  # РџСЂРѕРіСЂРµСЃСЃРёРІРЅР°СЏ РёРЅС‚РµСЂРїРѕР»СЏС†РёСЏ Р·Р°РјРµРЅРµРЅР° РїСЂРѕС†РµРЅС‚РЅС‹Рј СЂР°СЃС‡С‘С‚РѕРј

            # РџРѕР»СѓС‡Р°РµРј leverage Р·Р°СЂР°РЅРµРµ (РЅСѓР¶РµРЅ РґР»СЏ СЂР°СЃС‡С‘С‚Р° РЅРѕРјРёРЅР°Р»Р°)
            _leverage_for_size = None
            if signal:
                _leverage_for_size = signal.get("leverage")
            if not _leverage_for_size or _leverage_for_size <= 0:
                _leverage_for_size = getattr(self.scalping_config, "leverage", None)
            if not _leverage_for_size or _leverage_for_size <= 0:
                _leverage_for_size = 3  # fallback

            max_pct = balance_profile.get("max_position_percent", 15.0)
            margin_target_usd = (
                balance * max_pct / 100.0
            )  # С†РµР»РµРІР°СЏ РњРђР Р–Рђ РІ USD
            base_usd_size = (
                margin_target_usd * _leverage_for_size
            )  # РЅРѕРјРёРЅР°Р»СЊРЅР°СЏ СЃС‚РѕРёРјРѕСЃС‚СЊ

            logger.info(
                f"рџ“Љ РђРґР°РїС‚РёРІРЅС‹Р№ СЂР°Р·РјРµСЂ [{balance_profile.get('name', '?')}]: "
                f"${balance:.2f} Г— {max_pct}% = ${margin_target_usd:.2f} РјР°СЂР¶Р° "
                f"Г— {_leverage_for_size}x = ${base_usd_size:.2f} РЅРѕРјРёРЅР°Р»"
            )

            min_usd_size = balance_profile["min_position_usd"]
            max_usd_size = balance_profile["max_position_usd"]

            # вњ… Р’РђР РРђРќРў B: РџСЂРёРјРµРЅРёС‚СЊ per-symbol РјРЅРѕР¶РёС‚РµР»СЊ Рє Р±Р°Р·РѕРІРѕРјСѓ СЂР°Р·РјРµСЂСѓ
            if symbol:
                symbol_profile = self.symbol_profiles.get(symbol, {})
                if symbol_profile:
                    symbol_dict = (
                        self.config_manager.to_dict(symbol_profile)
                        if not isinstance(symbol_profile, dict)
                        else symbol_profile
                    )
                    position_multiplier = symbol_dict.get("position_multiplier")

                    if position_multiplier is not None:
                        original_size = base_usd_size
                        if position_multiplier != 1.0:
                            base_usd_size = base_usd_size * float(position_multiplier)
                            # рџ”‡ РР—РњР•РќР•РќРћ (2026-02-08): INFO в†’ DEBUG РґР»СЏ СЃРЅРёР¶РµРЅРёСЏ РѕР±СЉРµРјР° Р»РѕРіРѕРІ
                            logger.debug(
                                f"рџ“Љ Per-symbol multiplier РґР»СЏ {symbol}: {position_multiplier}x "
                                f"в†’ СЂР°Р·РјРµСЂ ${original_size:.2f} в†’ ${base_usd_size:.2f}"
                            )
                        # else:
                        #     logger.debug(
                        #         f"рџ“Љ Per-symbol multiplier РґР»СЏ {symbol}: {position_multiplier}x "
                        #         f"в†’ СЂР°Р·РјРµСЂ ${original_size:.2f} (Р±РµР· РёР·РјРµРЅРµРЅРёР№)"
                        #     )
                    # else:
                    #     logger.debug(
                    #         f"рџ“Љ Per-symbol multiplier РґР»СЏ {symbol}: РЅРµ РЅР°Р№РґРµРЅ "
                    #         f"(РёСЃРїРѕР»СЊР·СѓРµРј Р±Р°Р·РѕРІС‹Р№ СЂР°Р·РјРµСЂ ${base_usd_size:.2f})"
                    #     )
                # else:
                #     logger.debug(
                #         f"вљ пёЏ symbol_profile РЅРµ РЅР°Р№РґРµРЅ РґР»СЏ {symbol} РІ symbol_profiles"
                #     )

            # РџСЂРёРјРµРЅСЏРµРј position overrides (РµСЃР»Рё СѓРєР°Р·Р°РЅС‹, РѕРЅРё РёРјРµСЋС‚ РїСЂРёРѕСЂРёС‚РµС‚ РґР»СЏ С‚РѕС‡РЅРѕР№ РЅР°СЃС‚СЂРѕР№РєРё)
            position_overrides: Dict[str, Any] = {}
            if symbol:
                regime_profile = self._get_symbol_regime_profile(symbol, symbol_regime)
                position_overrides = self.config_manager.to_dict(
                    regime_profile.get("position", {})
                )

            # вљ пёЏ Р’РђР–РќРћ: position overrides РёР· symbol_profiles РјРѕРіСѓС‚ Р±С‹С‚СЊ СѓСЃС‚Р°СЂРµРІС€РёРјРё
            # РћРЅРё РїСЂРёРјРµРЅСЏСЋС‚СЃСЏ С‚РѕР»СЊРєРѕ РµСЃР»Рё СЏРІРЅРѕ СѓРєР°Р·Р°РЅС‹ Рё РёРјРµСЋС‚ РїСЂРёРѕСЂРёС‚РµС‚ РЅР°Рґ multiplier
            # Р”Р»СЏ РЅРѕРІРѕР№ СЃРёСЃС‚РµРјС‹ СЂРµРєРѕРјРµРЅРґСѓРµС‚СЃСЏ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ С‚РѕР»СЊРєРѕ position_multiplier
            if position_overrides.get("base_position_usd") is not None:
                # вњ… РРЎРџР РђР’Р›Р•РќРћ: РРіРЅРѕСЂРёСЂСѓРµРј override РµСЃР»Рё РѕРЅ РјРµРЅСЊС€Рµ Р±Р°Р·РѕРІРѕРіРѕ СЂР°Р·РјРµСЂР°
                override_size = float(position_overrides["base_position_usd"])
                if override_size < base_usd_size:
                    logger.debug(
                        f"вљ пёЏ РРіРЅРѕСЂРёСЂСѓРµРј position override РґР»СЏ {symbol}: "
                        f"${override_size:.2f} < Р±Р°Р·РѕРІС‹Р№ ${base_usd_size:.2f} (РёР· balance_profile)"
                    )
                elif abs(override_size - base_usd_size) / base_usd_size > 0.5:
                    logger.debug(
                        f"вљ пёЏ РРіРЅРѕСЂРёСЂСѓРµРј СѓСЃС‚Р°СЂРµРІС€РёР№ position override РґР»СЏ {symbol}: "
                        f"${override_size:.2f} (РёСЃРїРѕР»СЊР·СѓРµРј multiplier: ${base_usd_size:.2f})"
                    )
                else:
                    base_usd_size = override_size
                    logger.info(
                        f"рџ“Љ РСЃРїРѕР»СЊР·СѓРµРј position override РґР»СЏ {symbol}: ${base_usd_size:.2f} (СѓРІРµР»РёС‡РµРЅ СЃ Р±Р°Р·РѕРІРѕРіРѕ)"
                    )

            # вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР•: min/max РёР· symbol_profiles РЅРµ РґРѕР»Р¶РЅС‹ СѓРјРµРЅСЊС€Р°С‚СЊ Р·РЅР°С‡РµРЅРёСЏ РёР· balance_profile
            if position_overrides.get("min_position_usd") is not None:
                symbol_min = float(position_overrides["min_position_usd"])
                balance_min = min_usd_size
                if symbol_min > min_usd_size:
                    min_usd_size = symbol_min
                    logger.debug(
                        f"рџ“Љ Min position size РёР· symbol_profiles (${symbol_min:.2f}) Р±РѕР»СЊС€Рµ "
                        f"balance_profile (${balance_min:.2f}), РёСЃРїРѕР»СЊР·СѓРµРј ${symbol_min:.2f}"
                    )
                else:
                    logger.debug(
                        f"рџ“Љ Min position size РёР· symbol_profiles (${symbol_min:.2f}) РјРµРЅСЊС€Рµ РёР»Рё СЂР°РІРЅРѕ "
                        f"balance_profile (${balance_min:.2f}), РёРіРЅРѕСЂРёСЂСѓРµРј (РёСЃРїРѕР»СЊР·СѓРµРј ${balance_min:.2f})"
                    )

            if position_overrides.get("max_position_usd") is not None:
                symbol_max = float(position_overrides["max_position_usd"])
                balance_max = max_usd_size

                # рџ”ґ BUG #28 FIX: РёСЃРїРѕР»СЊР·СѓРµРј min(per_symbol, global) Рё Р»РѕРіРёСЂСѓРµРј РєРѕРЅС„Р»РёРєС‚
                if symbol_max < balance_max:
                    logger.info(
                        f"вљ пёЏ max_position_usd per-symbol (${symbol_max:.2f}) < global (${balance_max:.2f}), РёСЃРїРѕР»СЊР·СѓРµРј min=${symbol_max:.2f}"
                    )
                    max_usd_size = symbol_max
                else:
                    max_usd_size = balance_max
                    logger.debug(
                        f"рџ“Љ max_position_usd per-symbol (${symbol_max:.2f}) >= global (${balance_max:.2f}), РѕСЃС‚Р°РІР»СЏРµРј global ${balance_max:.2f}"
                    )

                if max_usd_size < min_usd_size:
                    logger.warning(
                        f"вљ пёЏ РљРѕРЅС„Р»РёРєС‚ Р»РёРјРёС‚РѕРІ: max_position_usd (${max_usd_size:.2f}) < "
                        f"min_position_usd (${min_usd_size:.2f}) РґР»СЏ {symbol}. "
                        f"РСЃРїРѕР»СЊР·СѓРµРј max_position_usd = min_position_usd (${min_usd_size:.2f})."
                    )
                    max_usd_size = min_usd_size

            if position_overrides.get("max_position_percent") is not None:
                max_pct = position_overrides["max_position_percent"]
                if max_pct is not None:
                    balance_profile["max_position_percent"] = float(max_pct)

            # вњ… РњРћР”Р•Р РќРР—РђР¦РРЇ: РЈР±РёСЂР°РµРј fallback Р·РЅР°С‡РµРЅРёСЏ, С‚СЂРµР±СѓРµРј РёР· РєРѕРЅС„РёРіР°
            if min_usd_size is None or min_usd_size <= 0:
                logger.error(
                    f"вќЊ min_position_usd РЅРµ СѓРєР°Р·Р°РЅ РІ РєРѕРЅС„РёРіРµ РґР»СЏ РїСЂРѕС„РёР»СЏ {balance_profile.get('name', 'unknown')}! "
                    f"РџСЂРѕРІРµСЂСЊС‚Рµ config_futures.yaml -> scalping -> balance_profiles -> {balance_profile.get('name', 'unknown')} -> min_position_usd"
                )
                raise ValueError(
                    f"min_position_usd РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ СѓРєР°Р·Р°РЅ РІ РєРѕРЅС„РёРіРµ РґР»СЏ РїСЂРѕС„РёР»СЏ {balance_profile.get('name', 'unknown')}"
                )
            if max_usd_size is None or max_usd_size <= 0:
                logger.error(
                    f"вќЊ max_position_usd РЅРµ СѓРєР°Р·Р°РЅ РІ РєРѕРЅС„РёРіРµ РґР»СЏ РїСЂРѕС„РёР»СЏ {balance_profile.get('name', 'unknown')}! "
                    f"РџСЂРѕРІРµСЂСЊС‚Рµ config_futures.yaml -> scalping -> balance_profiles -> {balance_profile.get('name', 'unknown')} -> max_position_usd"
                )
                raise ValueError(
                    f"max_position_usd РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ СѓРєР°Р·Р°РЅ РІ РєРѕРЅС„РёРіРµ РґР»СЏ РїСЂРѕС„РёР»СЏ {balance_profile.get('name', 'unknown')}"
                )

            # вњ… РњРћР”Р•Р РќРР—РђР¦РРЇ: РЈР±РёСЂР°РµРј fallback Р·РЅР°С‡РµРЅРёСЏ, С‚СЂРµР±СѓРµРј РёР· РєРѕРЅС„РёРіР°
            profile_max_positions = balance_profile.get("max_open_positions")
            if profile_max_positions is None or profile_max_positions <= 0:
                logger.error(
                    f"вќЊ max_open_positions РЅРµ СѓРєР°Р·Р°РЅ РІ РєРѕРЅС„РёРіРµ РґР»СЏ РїСЂРѕС„РёР»СЏ {balance_profile.get('name', 'unknown')}! "
                    f"РџСЂРѕРІРµСЂСЊС‚Рµ config_futures.yaml -> scalping -> balance_profiles -> {balance_profile.get('name', 'unknown')} -> max_open_positions"
                )
                raise ValueError(
                    f"max_open_positions РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ СѓРєР°Р·Р°РЅ РІ РєРѕРЅС„РёРіРµ РґР»СЏ РїСЂРѕС„РёР»СЏ {balance_profile.get('name', 'unknown')}"
                )

            if position_overrides.get("max_open_positions") is not None:
                profile_max_positions = int(position_overrides["max_open_positions"])
            global_max_positions = getattr(
                self.risk_config, "max_open_positions", profile_max_positions
            )
            if profile_max_positions:
                allowed_positions = max(
                    1, min(profile_max_positions, global_max_positions)
                )
                if (
                    self.max_size_limiter
                    and self.max_size_limiter.max_positions != allowed_positions
                ):
                    logger.debug(
                        f"рџ”§ MaxSizeLimiter: РѕР±РЅРѕРІР»СЏРµРј max_positions {self.max_size_limiter.max_positions} в†’ {allowed_positions}"
                    )
                    self.max_size_limiter.max_positions = allowed_positions
                if self.max_size_limiter:
                    max_total_size = max_usd_size * allowed_positions
                    if self.max_size_limiter.max_total_size_usd != max_total_size:
                        logger.debug(
                            f"рџ”§ MaxSizeLimiter: РѕР±РЅРѕРІР»СЏРµРј max_total_size_usd {self.max_size_limiter.max_total_size_usd:.2f} в†’ {max_total_size:.2f}"
                        )
                        self.max_size_limiter.max_total_size_usd = max_total_size
                    if self.max_size_limiter.max_single_size_usd != max_usd_size:
                        logger.debug(
                            f"рџ”§ MaxSizeLimiter: РѕР±РЅРѕРІР»СЏРµРј max_single_size_usd {self.max_size_limiter.max_single_size_usd:.2f} в†’ {max_usd_size:.2f}"
                        )
                        self.max_size_limiter.max_single_size_usd = max_usd_size
            else:
                logger.error(
                    f"вќЊ max_open_positions РЅРµ СѓРєР°Р·Р°РЅ РёР»Рё СЂР°РІРµРЅ 0 РґР»СЏ РїСЂРѕС„РёР»СЏ {balance_profile.get('name', 'unknown')}!"
                )
                raise ValueError(
                    f"max_open_positions РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ СѓРєР°Р·Р°РЅ Рё > 0 РІ РєРѕРЅС„РёРіРµ РґР»СЏ РїСЂРѕС„РёР»СЏ {balance_profile.get('name', 'unknown')}"
                )

            if (
                signal_generator
                and hasattr(signal_generator, "regime_manager")
                and signal_generator.regime_manager
            ):
                try:
                    regime_key = (
                        symbol_regime
                        or signal_generator.regime_manager.get_current_regime()
                    )
                    if regime_key:
                        regime_params = self.config_manager.get_regime_params(
                            regime_key, symbol
                        )
                        multiplier = regime_params.get("position_size_multiplier")
                        if multiplier is not None:
                            base_usd_size *= multiplier
                            logger.debug(
                                f"Р РµР¶РёРј {regime_key}: multiplier={multiplier}"
                            )
                except Exception as e:
                    logger.warning(
                        f"РћС€РёР±РєР° Р°РґР°РїС‚Р°С†РёРё РїРѕРґ СЂРµР¶РёРј: {e}"
                    )

            has_conflict = signal.get("has_conflict", False)
            signal_strength = signal.get("strength", 0.5)

            # вњ… РњРћР”Р•Р РќРР—РђР¦РРЇ: РџРѕР»СѓС‡Р°РµРј Р°РґР°РїС‚РёРІРЅС‹Рµ РїР°СЂР°РјРµС‚СЂС‹ СЂРёСЃРєР° СЃ СѓС‡РµС‚РѕРј СЂРµР¶РёРјР° Рё Р±Р°Р»Р°РЅСЃР°
            adaptive_risk_params = self.config_manager.get_adaptive_risk_params(
                balance, symbol_regime, symbol, signal_generator=signal_generator
            )
            strength_multipliers = adaptive_risk_params.get("strength_multipliers", {})
            strength_thresholds = adaptive_risk_params.get("strength_thresholds", {})

            # вњ… РњРћР”Р•Р РќРР—РђР¦РРЇ: РСЃРїРѕР»СЊР·СѓРµРј Р°РґР°РїС‚РёРІРЅС‹Рµ strength_multipliers РёР· РєРѕРЅС„РёРіР°
            if has_conflict:
                strength_multiplier = strength_multipliers.get("conflict", 0.5)
                logger.debug(
                    f"вљЎ РљРѕРЅС„Р»РёРєС‚ RSI/EMA: СѓРјРµРЅСЊС€РµРЅРЅС‹Р№ СЂР°Р·РјРµСЂ РґР»СЏ Р±С‹СЃС‚СЂРѕРіРѕ СЃРєР°Р»СЊРїР° "
                    f"(strength={signal_strength:.2f}, multiplier={strength_multiplier})"
                )
            elif signal_strength > strength_thresholds.get("very_strong", 0.8):
                strength_multiplier = strength_multipliers.get("very_strong", 1.5)
                logger.debug(
                    f"РћС‡РµРЅСЊ СЃРёР»СЊРЅС‹Р№ СЃРёРіРЅР°Р» (strength={signal_strength:.2f}): multiplier={strength_multiplier}"
                )
            elif signal_strength > strength_thresholds.get("strong", 0.6):
                strength_multiplier = strength_multipliers.get("strong", 1.2)
                logger.debug(
                    f"РҐРѕСЂРѕС€РёР№ СЃРёРіРЅР°Р» (strength={signal_strength:.2f}): multiplier={strength_multiplier}"
                )
            elif signal_strength > strength_thresholds.get("medium", 0.4):
                strength_multiplier = strength_multipliers.get("medium", 1.0)
                logger.debug(
                    f"РЎСЂРµРґРЅРёР№ СЃРёРіРЅР°Р» (strength={signal_strength:.2f}): multiplier={strength_multiplier}"
                )
            else:
                strength_multiplier = strength_multipliers.get("weak", 0.8)
                logger.debug(
                    f"РЎР»Р°Р±С‹Р№ СЃРёРіРЅР°Р» (strength={signal_strength:.2f}): multiplier={strength_multiplier}"
                )

            # вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР•: Р”Р»СЏ РїСЂРѕРіСЂРµСЃСЃРёРІРЅС‹С… РїСЂРѕС„РёР»РµР№ СѓРјРµРЅСЊС€Р°РµРј multiplier
            # С‡С‚РѕР±С‹ РЅРµ РїРµСЂРµР·Р°РїРёСЃС‹РІР°С‚СЊ РїСЂРѕРіСЂРµСЃСЃРёРІРЅС‹Р№ СЂР°СЃС‡РµС‚ (СѓР¶Рµ РІС‹РїРѕР»РЅРµРЅ РІС‹С€Рµ РїСЂРё СЂР°СЃС‡РµС‚Рµ base_usd_size)
            original_multiplier = strength_multiplier
            if is_progressive:
                # Р”Р»СЏ РїСЂРѕРіСЂРµСЃСЃРёРІРЅС‹С… РїСЂРѕС„РёР»РµР№ РёСЃРїРѕР»СЊР·СѓРµРј РјРµРЅСЊС€РёР№ multiplier (0.9 РІРјРµСЃС‚Рѕ 0.8)
                # С‡С‚РѕР±С‹ РїСЂРѕРіСЂРµСЃСЃРёРІРЅС‹Р№ СЂР°СЃС‡РµС‚ СЂР°Р±РѕС‚Р°Р» РїСЂР°РІРёР»СЊРЅРѕ, РЅРѕ РјРЅРѕР¶РёС‚РµР»Рё РІСЃРµ СЂР°РІРЅРѕ РІР»РёСЏР»Рё
                progressive_multiplier = 0.9  # 90% РѕС‚ РѕР±С‹С‡РЅРѕРіРѕ multiplier (СѓРІРµР»РёС‡РµРЅРѕ СЃ 0.8)
                strength_multiplier = (
                    1.0 + (strength_multiplier - 1.0) * progressive_multiplier
                )
                logger.debug(
                    f"рџ“Љ РџСЂРѕРіСЂРµСЃСЃРёРІРЅС‹Р№ РїСЂРѕС„РёР»СЊ: СѓРјРµРЅСЊС€Р°РµРј multiplier РґРѕ {strength_multiplier:.2f} "
                    f"(Р±С‹Р»Рѕ Р±С‹ {original_multiplier:.2f} Р±РµР· РїСЂРѕРіСЂРµСЃСЃРёРІРЅРѕР№ Р°РґР°РїС‚Р°С†РёРё)"
                )

            # вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР•: РџСЂРёРјРµРЅСЏРµРј multiplier, РЅРѕ РѕРіСЂР°РЅРёС‡РёРІР°РµРј max_usd_size!
            base_usd_size *= strength_multiplier
            # вњ… РРЎРџР РђР’Р›Р•РќРћ: РЎС‚СЂРѕРіР°СЏ РїСЂРѕРІРµСЂРєР° max_position_size СЃ Р»РѕРіРёСЂРѕРІР°РЅРёРµРј РґРѕ/РїРѕСЃР»Рµ
            base_usd_size_before_cap = base_usd_size
            if base_usd_size > max_usd_size:
                base_usd_size = (
                    max_usd_size * 0.95
                )  # вњ… РџР РђР’РљРђ #7: 5% Р·Р°РїР°СЃ
                logger.warning(
                    f"вљ пёЏ Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё ${base_usd_size_before_cap:.2f} РїСЂРµРІС‹С€Р°РµС‚ max_position_size ${max_usd_size:.2f} РґР»СЏ {symbol}! "
                    f"РћРіСЂР°РЅРёС‡РёРІР°РµРј РґРѕ ${base_usd_size:.2f} (5% Р·Р°РїР°СЃ, СЃРёРіРЅР°Р» Р±С‹Р» СЃРёР»СЊРЅС‹Р№: strength_multiplier={strength_multiplier:.2f}x)"
                )
            logger.info(
                f"рџ’° Position size: ${base_usd_size_before_cap:.2f} в†’ ${base_usd_size:.2f} USD after cap "
                f"(max=${max_usd_size:.2f}, progressive={is_progressive}, multiplier={strength_multiplier:.2f})"
            )

            # вњ… РћРџРўРРњРР—РђР¦РРЇ #4: Р”РёРЅР°РјРёС‡РµСЃРєРёР№ СЂР°Р·РјРµСЂ РїРѕР·РёС†РёР№ РЅР° РѕСЃРЅРѕРІРµ РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚Рё (ATR-based)
            volatility_adjustment_enabled = False
            volatility_multiplier = 1.0
            try:
                volatility_config = getattr(
                    self.scalping_config, "volatility_adjustment", None
                )
                if volatility_config is None:
                    volatility_config = {}
                elif not isinstance(volatility_config, dict):
                    volatility_config = self.config_manager.to_dict(volatility_config)

                volatility_adjustment_enabled = volatility_config.get("enabled", False)

                if volatility_adjustment_enabled and symbol and price > 0:
                    base_atr_percent = volatility_config.get("base_atr_percent", 0.02)
                    min_multiplier = volatility_config.get("min_multiplier", 0.5)
                    max_multiplier = volatility_config.get("max_multiplier", 1.5)

                    regime_configs = volatility_config.get("by_regime", {})
                    if symbol_regime and symbol_regime.lower() in regime_configs:
                        regime_config = regime_configs[symbol_regime.lower()]
                        base_atr_percent = regime_config.get(
                            "base_atr_percent", base_atr_percent
                        )
                        min_multiplier = regime_config.get(
                            "min_multiplier", min_multiplier
                        )
                        max_multiplier = regime_config.get(
                            "max_multiplier", max_multiplier
                        )

                    # РџРѕР»СѓС‡Р°РµРј ATR С‡РµСЂРµР· signal_generator
                    current_atr_percent = None
                    try:
                        if signal_generator and hasattr(
                            signal_generator, "_get_market_data"
                        ):
                            market_data = await signal_generator._get_market_data(
                                symbol
                            )
                            # вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР• (27.12.2025): РСЃРїРѕР»СЊР·СѓРµРј Р°РґР°РїС‚РёРІРЅС‹Р№ ATR РїРµСЂРёРѕРґ
                            atr_period = 14  # Fallback
                            if signal_generator and hasattr(
                                signal_generator, "_get_regime_indicators_params"
                            ):
                                try:
                                    regime_params = (
                                        signal_generator._get_regime_indicators_params(
                                            symbol=symbol
                                        )
                                    )
                                    atr_period = regime_params.get("atr_period", 14)
                                except Exception:
                                    pass

                            if (
                                market_data
                                and market_data.ohlcv_data
                                and len(market_data.ohlcv_data) >= atr_period + 1
                            ):
                                from src.indicators import ATR

                                atr_indicator = ATR(period=atr_period)
                                high_data = [
                                    candle.high for candle in market_data.ohlcv_data
                                ]
                                low_data = [
                                    candle.low for candle in market_data.ohlcv_data
                                ]
                                close_data = [
                                    candle.close for candle in market_data.ohlcv_data
                                ]

                                atr_result = atr_indicator.calculate(
                                    high_data, low_data, close_data
                                )
                                if atr_result and atr_result.value > 0:
                                    atr_value = atr_result.value
                                    current_atr_percent = (
                                        atr_value / price
                                    ) * 100  # ATR РІ % РѕС‚ С†РµРЅС‹
                    except Exception as e:
                        logger.debug(
                            f"вљ пёЏ РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ ATR РґР»СЏ {symbol}: {e}"
                        )

                    # Р Р°СЃСЃС‡РёС‚С‹РІР°РµРј multiplier РЅР° РѕСЃРЅРѕРІРµ РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚Рё
                    if current_atr_percent is not None and current_atr_percent > 0:
                        raw_multiplier = base_atr_percent / (
                            current_atr_percent / 100.0
                        )
                        # вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР•: РџСЂРёРІРѕРґРёРј Рє float, С‡С‚РѕР±С‹ РёР·Р±РµР¶Р°С‚СЊ СѓРјРЅРѕР¶РµРЅРёСЏ СЃС‚СЂРѕРєРё
                        volatility_multiplier = float(
                            max(min_multiplier, min(raw_multiplier, max_multiplier))
                        )

                        logger.info(
                            f"  4a. Р’РѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ (ATR): С‚РµРєСѓС‰Р°СЏ={current_atr_percent:.4f}%, "
                            f"Р±Р°Р·РѕРІР°СЏ={base_atr_percent*100:.2f}%, multiplier={volatility_multiplier:.2f}x"
                        )

                        base_usd_size_before_vol = base_usd_size
                        base_usd_size *= volatility_multiplier
                        # вњ… РРЎРџР РђР’Р›Р•РќРћ: РЎС‚СЂРѕРіР°СЏ РїСЂРѕРІРµСЂРєР° max_position_size РїРѕСЃР»Рµ РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚Рё СЃ Р»РѕРіРёСЂРѕРІР°РЅРёРµРј
                        base_usd_size_before_vol_cap = base_usd_size
                        if base_usd_size > max_usd_size:
                            logger.warning(
                                f"вљ пёЏ Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё РїРѕСЃР»Рµ РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚Рё ${base_usd_size:.2f} "
                                f"РїСЂРµРІС‹С€Р°РµС‚ max_position_size ${max_usd_size:.2f} РґР»СЏ {symbol}! "
                                f"РћРіСЂР°РЅРёС‡РёРІР°РµРј РґРѕ ${max_usd_size:.2f} "
                                f"(volatility_multiplier={volatility_multiplier:.2f}x, strength_multiplier={strength_multiplier:.2f}x)"
                            )
                            base_usd_size = max_usd_size
                        if base_usd_size_before_vol_cap != base_usd_size:
                            logger.info(
                                f"рџ’° Position size after volatility: ${base_usd_size_before_vol_cap:.2f} в†’ ${base_usd_size:.2f} USD after cap"
                            )

                        if abs(volatility_multiplier - 1.0) > 0.01:
                            logger.info(
                                f"  4b. Р Р°Р·РјРµСЂ СЃРєРѕСЂСЂРµРєС‚РёСЂРѕРІР°РЅ РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊСЋ: "
                                f"${base_usd_size_before_vol:.2f} в†’ ${base_usd_size:.2f} "
                                f"({volatility_multiplier:.2f}x)"
                            )
                    else:
                        logger.debug(
                            f"  4a. Р’РѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ: ATR РЅРµ РґРѕСЃС‚СѓРїРµРЅ РґР»СЏ {symbol}, РёСЃРїРѕР»СЊР·СѓРµРј Р±Р°Р·РѕРІС‹Р№ СЂР°Р·РјРµСЂ"
                        )
            except Exception as e:
                logger.debug(
                    f"вљ пёЏ РћС€РёР±РєР° СЂР°СЃС‡РµС‚Р° РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚Рё РґР»СЏ {symbol}: {e}"
                )

            # 4. РџР РРњР•РќРЇР•Рњ Р›Р•Р’Р•Р РР”Р– (Futures) - РёР· signal РёР»Рё РёР· РєРѕРЅС„РёРіР°!
            # вњ… РРЎРџР РђР’Р›Р•РќРР•: РЎРЅР°С‡Р°Р»Р° РїС‹С‚Р°РµРјСЃСЏ РїРѕР»СѓС‡РёС‚СЊ leverage РёР· signal (Р°РґР°РїС‚РёРІРЅС‹Р№)
            leverage = None
            if signal:
                leverage = signal.get("leverage")
                if leverage and leverage > 0:
                    logger.debug(
                        f"вњ… РСЃРїРѕР»СЊР·СѓРµРј leverage={leverage}x РёР· signal (Р°РґР°РїС‚РёРІРЅС‹Р№)"
                    )

            # Fallback РЅР° РєРѕРЅС„РёРі, РµСЃР»Рё РЅРµ Р±С‹Р» СѓРєР°Р·Р°РЅ РІ signal
            if leverage is None or leverage <= 0:
                leverage = getattr(self.scalping_config, "leverage", None)
                if leverage and leverage > 0:
                    logger.debug(
                        f"вњ… РСЃРїРѕР»СЊР·СѓРµРј leverage={leverage}x РёР· РєРѕРЅС„РёРіР° (С„РёРєСЃРёСЂРѕРІР°РЅРЅС‹Р№)"
                    )

            if leverage is None or leverage <= 0:
                logger.error(
                    "вќЊ leverage РЅРµ СѓРєР°Р·Р°РЅ РІ signal Рё РЅРµ СѓРєР°Р·Р°РЅ РІ РєРѕРЅС„РёРіРµ РёР»Рё <= 0! РџСЂРѕРІРµСЂСЊС‚Рµ config_futures.yaml"
                )
                raise ValueError(
                    "leverage РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ СѓРєР°Р·Р°РЅ РІ signal РёР»Рё РІ РєРѕРЅС„РёРіРµ (РЅР°РїСЂРёРјРµСЂ, leverage: 3)"
                )
            # вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР•: base_usd_size СЌС‚Рѕ РќРћРњРРќРђР›Р¬РќРђРЇ СЃС‚РѕРёРјРѕСЃС‚СЊ (notional)
            margin_required_initial = (
                base_usd_size / leverage
            )  # РўСЂРµР±СѓРµРјР°СЏ РјР°СЂР¶Р° (РІ USD)
            margin_required = margin_required_initial

            # вњ… РџРµСЂРµСЃС‡РёС‚С‹РІР°РµРј min/max РёР· РЅРѕРјРёРЅР°Р»СЊРЅРѕР№ СЃС‚РѕРёРјРѕСЃС‚Рё РІ РјР°СЂР¶Сѓ РґР»СЏ РїСЂРѕРІРµСЂРѕРє
            min_margin_usd = min_usd_size / leverage
            max_margin_usd = max_usd_size / leverage

            # вњ… РњРћР”Р•Р РќРР—РђР¦РРЇ: РџРѕР»СѓС‡Р°РµРј РёСЃРїРѕР»СЊР·РѕРІР°РЅРЅСѓСЋ РјР°СЂР¶Сѓ СЃ Р±РёСЂР¶Рё (Р°РєС‚СѓР°Р»СЊРЅС‹Рµ РґР°РЅРЅС‹Рµ)
            used_margin = await self._get_used_margin()
            # РћР±РЅРѕРІР»СЏРµРј total_margin_used С‡РµСЂРµР· orchestrator
            if self.orchestrator and hasattr(self.orchestrator, "total_margin_used"):
                self.orchestrator.total_margin_used = used_margin

            # вњ… РњРћР”Р•Р РќРР—РђР¦РРЇ: РџРѕР»СѓС‡Р°РµРј Р°РґР°РїС‚РёРІРЅС‹Рµ РїР°СЂР°РјРµС‚СЂС‹ СЂРёСЃРєР° СЃ СѓС‡РµС‚РѕРј СЂРµР¶РёРјР° Рё Р±Р°Р»Р°РЅСЃР°
            adaptive_risk_params = self.config_manager.get_adaptive_risk_params(
                balance, symbol_regime, symbol, signal_generator=signal_generator
            )
            max_margin_percent = (
                adaptive_risk_params.get("max_margin_percent", 80.0) / 100.0
            )
            max_loss_per_trade_percent = (
                adaptive_risk_params.get("max_loss_per_trade_percent", 2.0) / 100.0
            )
            max_margin_safety_percent = (
                adaptive_risk_params.get("max_margin_safety_percent", 90.0) / 100.0
            )

            # вњ… РљР РРўРР§Р•РЎРљРћР• РЈР›РЈР§РЁР•РќРР• (04.01.2026): Р”РµС‚Р°Р»СЊРЅРѕРµ Р»РѕРіРёСЂРѕРІР°РЅРёРµ СЂР°СЃС‡РµС‚Р° margin РґР»СЏ РєР°Р¶РґРѕР№ РїР°СЂС‹
            logger.info(
                f"рџ“Љ [PARAMS_MARGIN] {symbol} ({symbol_regime or 'unknown'}): Р”Р•РўРђР›Р¬РќР«Р™ Р РђРЎР§Р•Рў РњРђР Р–Р:"
            )
            logger.info(
                f"  1. Р‘Р°Р»Р°РЅСЃРѕРІС‹Р№ РїСЂРѕС„РёР»СЊ: {balance_profile['name']}, Р±Р°Р»Р°РЅСЃ=${balance:.2f}"
            )
            logger.info(
                f"  2. Р‘Р°Р·РѕРІС‹Р№ СЂР°Р·РјРµСЂ РёР· РєРѕРЅС„РёРіР°: base_usd_size=${base_usd_size:.2f} (notional)"
            )
            logger.info(
                f"  3. Р›РёРјРёС‚С‹ РёР· РєРѕРЅС„РёРіР°: min=${min_usd_size:.2f}, max=${max_usd_size:.2f} (notional)"
            )
            logger.info(
                f"  4. Р›РµРІРµСЂРёРґР¶: {leverage}x в†’ РјР°СЂР¶Р° РґРѕ РѕРіСЂР°РЅРёС‡РµРЅРёР№: ${margin_required_initial:.2f} "
                f"(СЂР°СЃС‡РµС‚: ${base_usd_size:.2f} / {leverage}x = ${margin_required_initial:.2f})"
            )
            logger.info(
                f"  5. РСЃРїРѕР»СЊР·РѕРІР°РЅРЅР°СЏ РјР°СЂР¶Р°: ${used_margin:.2f}, РґРѕСЃС‚СѓРїРЅР°СЏ: ${balance - used_margin:.2f}"
            )

            # вњ… РњРћР”Р•Р РќРР—РђР¦РРЇ: РСЃРїРѕР»СЊР·СѓРµРј РёСЃРїРѕР»СЊР·РѕРІР°РЅРЅСѓСЋ РјР°СЂР¶Сѓ СЃ Р±РёСЂР¶Рё (Р°РєС‚СѓР°Р»СЊРЅС‹Рµ РґР°РЅРЅС‹Рµ)
            # 5. рџ›ЎпёЏ Р—РђР©РРўРђ: Max Margin Used (Р°РґР°РїС‚РёРІРЅС‹Р№ РїСЂРѕС†РµРЅС‚ РёР· РєРѕРЅС„РёРіР°)
            max_margin_allowed = balance * max_margin_percent
            available_margin = balance - used_margin

            logger.info(
                f"  6. Max margin percent: {max_margin_percent*100:.1f}% в†’ Р»РёРјРёС‚: ${max_margin_allowed:.2f}"
            )
            if used_margin + margin_required > max_margin_allowed:
                margin_required_before = margin_required
                margin_required = max(0, max_margin_allowed - used_margin)
                logger.warning(
                    f"     вљ пёЏ РћР“Р РђРќРР§Р•РќРћ: max_margin_allowed (${max_margin_allowed:.2f}) в†’ margin: ${margin_required_before:.2f} в†’ ${margin_required:.2f} (СѓРјРµРЅСЊС€РµРЅРѕ РЅР° ${margin_required_before - margin_required:.2f} РёР»Рё {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                )
                if margin_required < min_margin_usd:
                    logger.error(
                        f"вќЊ РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ СЃРІРѕР±РѕРґРЅРѕР№ РјР°СЂР¶Рё РґР»СЏ РѕС‚РєСЂС‹С‚РёСЏ РїРѕР·РёС†РёРё "
                        f"(РёСЃРїРѕР»СЊР·РѕРІР°РЅРѕ: ${used_margin:.2f}, РґРѕСЃС‚СѓРїРЅРѕ: ${available_margin:.2f}, "
                        f"С‚СЂРµР±СѓРµС‚СЃСЏ РјРёРЅРёРјСѓРј: ${min_margin_usd:.2f} РјР°СЂР¶Рё)"
                    )
                    return 0.0

            # вњ… РњРћР”Р•Р РќРР—РђР¦РРЇ: Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅР°СЏ РїСЂРѕРІРµСЂРєР° РЅР° РґРѕСЃС‚СѓРїРЅСѓСЋ РјР°СЂР¶Сѓ
            logger.info(f"  7. Р”РѕСЃС‚СѓРїРЅР°СЏ РјР°СЂР¶Р°: ${available_margin:.2f}")
            if margin_required > available_margin:
                margin_required_before = margin_required
                margin_required = max(0, available_margin)
                logger.warning(
                    f"     вљ пёЏ РћР“Р РђРќРР§Р•РќРћ: available_margin (${available_margin:.2f}) в†’ margin: ${margin_required_before:.2f} в†’ ${margin_required:.2f} (СѓРјРµРЅСЊС€РµРЅРѕ РЅР° ${margin_required_before - margin_required:.2f} РёР»Рё {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                )
                if margin_required < min_margin_usd:
                    logger.error(
                        f"вќЊ РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ РґРѕСЃС‚СѓРїРЅРѕР№ РјР°СЂР¶Рё РґР»СЏ РѕС‚РєСЂС‹С‚РёСЏ РїРѕР·РёС†РёРё "
                        f"(РґРѕСЃС‚СѓРїРЅРѕ: ${available_margin:.2f}, С‚СЂРµР±СѓРµС‚СЃСЏ РјРёРЅРёРјСѓРј: ${min_margin_usd:.2f} РјР°СЂР¶Рё)"
                    )
                    return 0.0

            # вњ… РќРћР’РћР•: Р”РёРЅР°РјРёС‡РµСЃРєРёР№ РєР°Рї РјР°СЂР¶Рё (РЈСЂРѕРІРµРЅСЊ 2: margin-per-trade)
            dynamic_margin_cap = None
            try:
                risk_config = getattr(self.scalping_config, "risk_config", {})
                if isinstance(risk_config, dict):
                    use_dynamic_cap = (
                        risk_config.get("max_margin_per_trade") is not None
                    )
                else:
                    use_dynamic_cap = hasattr(risk_config, "max_margin_per_trade")

                if use_dynamic_cap:
                    # РџРѕР»СѓС‡Р°РµРј РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ РґР»СЏ СЂР°СЃС‡РµС‚Р°
                    volatility_atr = None
                    try:
                        if signal_generator and hasattr(
                            signal_generator, "data_registry"
                        ):
                            data_registry = signal_generator.data_registry
                            if data_registry:
                                atr_data = await data_registry.get_indicator(
                                    symbol, "atr"
                                )  # вњ… РРЎРџР РђР’Р›Р•РќРћ: РґРѕР±Р°РІР»РµРЅ await
                                if atr_data and price > 0:
                                    volatility_atr = (
                                        float(atr_data) / price
                                    )  # ATR % РѕС‚ С†РµРЅС‹
                    except Exception as e:
                        logger.debug(
                            f"вљ пёЏ РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ РІРѕР»Р°С‚РёР»СЊРЅРѕСЃС‚СЊ РґР»СЏ dynamic_cap: {e}"
                        )

                    # РџРѕР»СѓС‡Р°РµРј РґРЅРµРІРЅРѕР№ PnL
                    daily_pnl = getattr(self, "daily_pnl", 0.0)

                    # Р Р°СЃСЃС‡РёС‚С‹РІР°РµРј РґРёРЅР°РјРёС‡РµСЃРєРёР№ РєР°Рї
                    dynamic_margin_cap = self._calculate_dynamic_margin_cap(
                        balance=balance,
                        symbol=symbol,
                        regime=symbol_regime or "trending",
                        volatility=volatility_atr,
                        daily_pnl=daily_pnl,
                        open_positions_margin=used_margin,
                    )

                    volatility_str = (
                        f"{volatility_atr*100:.2f}%"
                        if volatility_atr is not None
                        else "N/A"
                    )
                    logger.info(
                        f"  8a. Dynamic margin cap: ${dynamic_margin_cap:.2f} "
                        f"(volatility={volatility_str}, daily_pnl=${daily_pnl:.2f})"
                    )

                    if margin_required > dynamic_margin_cap:
                        margin_required_before = margin_required
                        margin_required = dynamic_margin_cap
                        logger.warning(
                            f"     вљ пёЏ РћР“Р РђРќРР§Р•РќРћ: dynamic_margin_cap (${dynamic_margin_cap:.2f}) в†’ margin: ${margin_required_before:.2f} в†’ ${margin_required:.2f} "
                            f"(СѓРјРµРЅСЊС€РµРЅРѕ РЅР° ${margin_required_before - margin_required:.2f} РёР»Рё {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                        )
            except Exception as e:
                logger.debug(
                    f"вљ пёЏ РћС€РёР±РєР° СЂР°СЃС‡РµС‚Р° dynamic_margin_cap: {e}"
                )

            # вњ… РќРћР’РћР•: Risk-based margin (РЈСЂРѕРІРµРЅСЊ 3: Margin Budget)
            risk_based_margin = None
            try:
                risk_config = getattr(self.scalping_config, "risk_config", {})
                if isinstance(risk_config, dict):
                    use_risk_based = risk_config.get("use_risk_based_sizing", False)
                else:
                    use_risk_based = getattr(
                        risk_config, "use_risk_based_sizing", False
                    )

                if use_risk_based and price > 0:
                    # РџРѕР»СѓС‡Р°РµРј risk_per_trade РёР· РєРѕРЅС„РёРіР°
                    risk_per_trade = max_loss_per_trade_percent  # РСЃРїРѕР»СЊР·СѓРµРј С‚РѕС‚ Р¶Рµ РїР°СЂР°РјРµС‚СЂ

                    # РџРѕР»СѓС‡Р°РµРј sl_percent
                    sl_percent = self._resolve_sl_percent_for_risk(
                        symbol, symbol_regime
                    )
                    # вњ… Р•Р”РРќР«Р™ РЎРўРђРќР”РђР Рў: sl_percent РІ РєРѕРЅС„РёРіРµ = РїСЂРѕС†РµРЅС‚РЅС‹Рµ РїСѓРЅРєС‚С‹ (0.8 = 0.8%)
                    # Р’ risk-based С„РѕСЂРјСѓР»Рµ РЅСѓР¶РµРЅ SL РІ РґРѕР»Рµ (0.008 = 0.8%)
                    sl_percent_decimal = pct_points_to_fraction(sl_percent)

                    # Р Р°СЃСЃС‡РёС‚С‹РІР°РµРј risk-based margin
                    risk_based_margin = self._calculate_risk_based_margin(
                        balance=balance,
                        risk_per_trade=risk_per_trade,
                        sl_distance_pct=sl_percent_decimal,
                        leverage=leverage,
                        price=price,
                    )

                    logger.info(
                        f"  8b. Risk-based margin: ${risk_based_margin:.2f} "
                        f"(risk={risk_per_trade*100:.2f}%, sl={sl_percent_decimal*100:.2f}%)"
                    )

                    if risk_based_margin > 0 and margin_required > risk_based_margin:
                        margin_required_before = margin_required
                        margin_required = risk_based_margin
                        logger.warning(
                            f"     вљ пёЏ РћР“Р РђРќРР§Р•РќРћ: risk_based_margin (${risk_based_margin:.2f}) в†’ margin: ${margin_required_before:.2f} в†’ ${margin_required:.2f} "
                            f"(СѓРјРµРЅСЊС€РµРЅРѕ РЅР° ${margin_required_before - margin_required:.2f} РёР»Рё {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                        )
            except Exception as e:
                logger.debug(
                    f"вљ пёЏ РћС€РёР±РєР° СЂР°СЃС‡РµС‚Р° risk_based_margin: {e}"
                )

            # 6. рџ›ЎпёЏ Р—РђР©РРўРђ: Max Loss per Trade (Р°РґР°РїС‚РёРІРЅС‹Р№ РїСЂРѕС†РµРЅС‚ РёР· РєРѕРЅС„РёРіР°)
            max_loss_usd = balance * max_loss_per_trade_percent
            sl_percent = self._resolve_sl_percent_for_risk(symbol, symbol_regime)

            # вњ… Р•Р”РРќР«Р™ РЎРўРђРќР”РђР Рў: sl_percent РІ РєРѕРЅС„РёРіРµ = РїСЂРѕС†РµРЅС‚РЅС‹Рµ РїСѓРЅРєС‚С‹ (0.8 = 0.8%)
            sl_percent_decimal = pct_points_to_fraction(sl_percent)

            max_safe_margin = (
                max_loss_usd / sl_percent_decimal
                if sl_percent_decimal > 0
                else float("inf")
            )

            logger.info(
                f"  8. Max loss per trade: {max_loss_per_trade_percent*100:.1f}% (${max_loss_usd:.2f}) в†’ max_safe_margin: ${max_safe_margin:.2f}"
            )
            if margin_required > max_safe_margin:
                margin_required_before = margin_required
                margin_required = max_safe_margin
                logger.warning(
                    f"     вљ пёЏ РћР“Р РђРќРР§Р•РќРћ: max_safe_margin (${max_safe_margin:.2f}) в†’ margin: ${margin_required_before:.2f} в†’ ${margin_required:.2f} (СѓРјРµРЅСЊС€РµРЅРѕ РЅР° ${margin_required_before - margin_required:.2f} РёР»Рё {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                )

            # 7. РџСЂРѕРІРµСЂРєР° РјР°СЂР¶Рё (Р°РґР°РїС‚РёРІРЅС‹Р№ РїСЂРѕС†РµРЅС‚ Р±РµР·РѕРїР°СЃРЅРѕСЃС‚Рё РёР· РєРѕРЅС„РёРіР° - С„РёРЅР°Р»СЊРЅР°СЏ РїСЂРѕРІРµСЂРєР°)
            max_margin_safety = balance * max_margin_safety_percent
            logger.info(
                f"  9. Max margin safety: {max_margin_safety_percent*100:.1f}% в†’ Р»РёРјРёС‚: ${max_margin_safety:.2f}"
            )
            if margin_required > max_margin_safety:
                margin_required_before = margin_required
                margin_required = max_margin_safety
                logger.warning(
                    f"     вљ пёЏ РћР“Р РђРќРР§Р•РќРћ: max_margin_safety (${max_margin_safety:.2f}) в†’ margin: ${margin_required_before:.2f} в†’ ${margin_required:.2f} (СѓРјРµРЅСЊС€РµРЅРѕ РЅР° ${margin_required_before - margin_required:.2f} РёР»Рё {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                )

            # 8. вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР•: РџСЂРёРјРµРЅСЏРµРј РѕРіСЂР°РЅРёС‡РµРЅРёСЏ Рє РњРђР Р–Р• (РЅРµ Рє notional!)
            margin_before_final = margin_required
            logger.info(
                f"  10. Р¤РёРЅР°Р»СЊРЅС‹Рµ Р»РёРјРёС‚С‹: min_margin=${min_margin_usd:.2f}, max_margin=${max_margin_usd:.2f}"
            )
            margin_usd = max(min_margin_usd, min(margin_required, max_margin_usd))

            logger.info(
                f"  11. РРўРћР“Рћ: margin=${margin_usd:.2f} (РЅР°С‡Р°Р»СЊРЅР°СЏ: ${margin_required_initial:.2f}, РїРѕСЃР»Рµ РѕРіСЂР°РЅРёС‡РµРЅРёР№: ${margin_before_final:.2f})"
            )
            if margin_usd < margin_required_initial:
                reduction_pct = (
                    (
                        (margin_required_initial - margin_usd)
                        / margin_required_initial
                        * 100
                    )
                    if margin_required_initial > 0
                    else 0
                )
                logger.warning(
                    f"     вљ пёЏ Р РђР—РњР•Р  РЈРњР•РќР¬РЁР•Рќ: ${margin_required_initial:.2f} в†’ ${margin_usd:.2f} (РЅР° ${margin_required_initial - margin_usd:.2f} РёР»Рё {reduction_pct:.1f}%)"
                )

            # 9. вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР•: РџРµСЂРµРІРѕРґРёРј РњРђР Р–РЈ РІ РєРѕР»РёС‡РµСЃС‚РІРѕ РјРѕРЅРµС‚
            position_size = (margin_usd * leverage) / price

            # вњ… РќРћР’РћР•: РЈС‡РёС‚С‹РІР°РµРј РѕРєСЂСѓРіР»РµРЅРёРµ РїСЂРё РєРѕРЅРІРµСЂС‚Р°С†РёРё РІ РєРѕРЅС‚СЂР°РєС‚С‹
            ct_val = None
            lot_sz = None
            min_sz = None

            try:
                instrument_details = await self.client.get_instrument_details(symbol)
                ct_val = instrument_details.get("ctVal", 0.01)
                lot_sz = instrument_details.get("lotSz", 0.01)
                min_sz = instrument_details.get("minSz", 0.01)

                from src.clients.futures_client import round_to_step

                size_in_contracts = position_size / ct_val
                rounded_size_in_contracts = round_to_step(size_in_contracts, lot_sz)

                if rounded_size_in_contracts < min_sz:
                    rounded_size_in_contracts = min_sz
                    logger.warning(
                        f"вљ пёЏ Р Р°Р·РјРµСЂ РїРѕСЃР»Рµ РѕРєСЂСѓРіР»РµРЅРёСЏ РјРµРЅСЊС€Рµ РјРёРЅРёРјСѓРјР°, РёСЃРїРѕР»СЊР·СѓРµРј РјРёРЅРёРјСѓРј: {min_sz}"
                    )

                real_position_size = rounded_size_in_contracts * ct_val
                real_notional_usd = real_position_size * price
                real_margin_usd = real_notional_usd / leverage

                # вњ… РљР РРўРР§Р•РЎРљРђРЇ РџР РћР’Р•Р РљРђ: РџСЂРѕРІРµСЂСЏРµРј, С‡С‚Рѕ СЂРµР°Р»СЊРЅС‹Р№ СЂР°Р·РјРµСЂ РїРѕСЃР»Рµ РѕРєСЂСѓРіР»РµРЅРёСЏ >= min_margin_usd
                if real_margin_usd < min_margin_usd:
                    logger.warning(
                        f"вљ пёЏ Р РµР°Р»СЊРЅС‹Р№ СЂР°Р·РјРµСЂ РїРѕСЃР»Рµ РѕРєСЂСѓРіР»РµРЅРёСЏ СЃР»РёС€РєРѕРј РјР°Р»РµРЅСЊРєРёР№: "
                        f"margin=${real_margin_usd:.2f} < min=${min_margin_usd:.2f}, "
                        f"СѓРІРµР»РёС‡РёРІР°РµРј РґРѕ РјРёРЅРёРјСѓРјР°"
                    )
                    real_margin_usd = min_margin_usd
                    real_notional_usd = real_margin_usd * leverage
                    real_position_size = real_notional_usd / price

                    real_size_in_contracts = real_position_size / ct_val
                    real_rounded_size_in_contracts = round_to_step(
                        real_size_in_contracts, lot_sz
                    )
                    if real_rounded_size_in_contracts < min_sz:
                        real_rounded_size_in_contracts = min_sz
                    real_position_size = real_rounded_size_in_contracts * ct_val
                    real_notional_usd = real_position_size * price
                    real_margin_usd = real_notional_usd / leverage

                    logger.info(
                        f"вњ… Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё СѓРІРµР»РёС‡РµРЅ РґРѕ РјРёРЅРёРјСѓРјР°: "
                        f"margin=${real_margin_usd:.2f}, "
                        f"notional=${real_notional_usd:.2f}, "
                        f"position_size={real_position_size:.6f} РјРѕРЅРµС‚"
                    )

                # вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР•: РџСЂРѕРІРµСЂСЏРµРј Р»РёРјРёС‚С‹ РџРћРЎР›Р• РѕРєСЂСѓРіР»РµРЅРёСЏ
                if real_notional_usd > max_usd_size:
                    logger.warning(
                        f"вљ пёЏ Р РµР°Р»СЊРЅС‹Р№ СЂР°Р·РјРµСЂ РїРѕСЃР»Рµ РѕРєСЂСѓРіР»РµРЅРёСЏ РїСЂРµРІС‹С€Р°РµС‚ Р»РёРјРёС‚: "
                        f"notional=${real_notional_usd:.2f} > max=${max_usd_size:.2f}, "
                        f"СѓРјРµРЅСЊС€Р°РµРј РґРѕ Р»РёРјРёС‚Р° СЃ СѓС‡РµС‚РѕРј РѕРєСЂСѓРіР»РµРЅРёСЏ"
                    )
                    import math

                    target_notional_usd = max_usd_size
                    target_margin_usd = target_notional_usd / leverage
                    target_position_size = target_notional_usd / price
                    target_size_in_contracts = target_position_size / ct_val
                    target_rounded_size_in_contracts = (
                        math.floor(target_size_in_contracts / lot_sz) * lot_sz
                    )

                    if target_rounded_size_in_contracts < min_sz:
                        min_notional_usd = min_sz * ct_val * price
                        if min_notional_usd > max_usd_size:
                            logger.error(
                                f"вќЊ РљР РРўРР§Р•РЎРљРђРЇ РћРЁРР‘РљРђ: РњРёРЅРёРјР°Р»СЊРЅС‹Р№ СЂР°Р·РјРµСЂ РїРѕР·РёС†РёРё ({min_notional_usd:.2f} USD) РїСЂРµРІС‹С€Р°РµС‚ Р»РёРјРёС‚ ({max_usd_size:.2f} USD)! "
                                f"РќРµРІРѕР·РјРѕР¶РЅРѕ РѕС‚РєСЂС‹С‚СЊ РїРѕР·РёС†РёСЋ РґР»СЏ {symbol}. "
                                f"РџСЂРѕРІРµСЂСЊС‚Рµ РєРѕРЅС„РёРіСѓСЂР°С†РёСЋ: min_position_usd Рё max_position_usd РІ config_futures.yaml"
                            )
                            return 0.0
                        else:
                            target_rounded_size_in_contracts = min_sz

                    real_position_size = target_rounded_size_in_contracts * ct_val
                    real_notional_usd = real_position_size * price
                    real_margin_usd = real_notional_usd / leverage

                    if real_notional_usd > max_usd_size:
                        logger.error(
                            f"вќЊ РљР РРўРР§Р•РЎРљРђРЇ РћРЁРР‘РљРђ: РњРёРЅРёРјР°Р»СЊРЅС‹Р№ СЂР°Р·РјРµСЂ РїРѕР·РёС†РёРё ({real_notional_usd:.2f} USD) РїСЂРµРІС‹С€Р°РµС‚ Р»РёРјРёС‚ ({max_usd_size:.2f} USD)! "
                            f"РќРµРІРѕР·РјРѕР¶РЅРѕ РѕС‚РєСЂС‹С‚СЊ РїРѕР·РёС†РёСЋ РґР»СЏ {symbol}. "
                            f"РџСЂРѕРІРµСЂСЊС‚Рµ РєРѕРЅС„РёРіСѓСЂР°С†РёСЋ: min_position_usd Рё max_position_usd РІ config_futures.yaml"
                        )
                        return 0.0

                    logger.info(
                        f"вњ… Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё СѓРјРµРЅСЊС€РµРЅ РґРѕ Р»РёРјРёС‚Р°: "
                        f"margin=${real_margin_usd:.2f}, "
                        f"notional=${real_notional_usd:.2f}, "
                        f"position_size={real_position_size:.6f} РјРѕРЅРµС‚"
                    )

                # Р›РѕРіРёСЂСѓРµРј РѕРєСЂСѓРіР»РµРЅРёРµ
                if abs(real_position_size - position_size) > 1e-8:
                    reduction_pct = (
                        ((position_size - real_position_size) / position_size * 100)
                        if position_size > 0
                        else 0
                    )
                    logger.warning(
                        f"вљ пёЏ Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё РёР·РјРµРЅРµРЅ РёР·-Р·Р° РѕРєСЂСѓРіР»РµРЅРёСЏ/РјРёРЅРёРјСѓРјР°: "
                        f"{position_size:.6f} в†’ {real_position_size:.6f} РјРѕРЅРµС‚ "
                        f"({reduction_pct:+.2f}%), "
                        f"notional: ${margin_usd * leverage:.2f} в†’ ${real_notional_usd:.2f}, "
                        f"margin: ${margin_usd:.2f} в†’ ${real_margin_usd:.2f}"
                    )
                else:
                    logger.info(
                        f"вњ… Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё РїРѕСЃР»Рµ РѕРєСЂСѓРіР»РµРЅРёСЏ РЅРµ РёР·РјРµРЅРёР»СЃСЏ: "
                        f"{position_size:.6f} РјРѕРЅРµС‚, "
                        f"notional=${real_notional_usd:.2f}, "
                        f"margin=${real_margin_usd:.2f}"
                    )

                position_size = real_position_size
                notional_usd = real_notional_usd
                margin_usd = real_margin_usd

            except Exception as e:
                logger.warning(
                    f"вљ пёЏ РќРµ СѓРґР°Р»РѕСЃСЊ СѓС‡РµСЃС‚СЊ РѕРєСЂСѓРіР»РµРЅРёРµ РїСЂРё СЂР°СЃС‡РµС‚Рµ СЂР°Р·РјРµСЂР° РїРѕР·РёС†РёРё РґР»СЏ {symbol}: {e}, "
                    f"РёСЃРїРѕР»СЊР·СѓРµРј СЂР°СЃС‡РµС‚РЅС‹Р№ СЂР°Р·РјРµСЂ Р±РµР· РѕРєСЂСѓРіР»РµРЅРёСЏ"
                )
                notional_usd = margin_usd * leverage

                if notional_usd > max_usd_size:
                    logger.warning(
                        f"вљ пёЏ РС‚РѕРіРѕРІС‹Р№ СЂР°Р·РјРµСЂ РїРѕР·РёС†РёРё РїСЂРµРІС‹С€Р°РµС‚ Р»РёРјРёС‚: "
                        f"notional=${notional_usd:.2f} > max=${max_usd_size:.2f}, "
                        f"СѓРјРµРЅСЊС€Р°РµРј СЂР°Р·РјРµСЂ РїРѕР·РёС†РёРё"
                    )
                    notional_usd = max_usd_size
                    margin_usd = notional_usd / leverage
                    position_size = notional_usd / price
                    logger.info(
                        f"вњ… Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё СѓРјРµРЅСЊС€РµРЅ РґРѕ Р»РёРјРёС‚Р°: "
                        f"notional=${notional_usd:.2f}, margin=${margin_usd:.2f}, "
                        f"position_size={position_size:.6f} РјРѕРЅРµС‚"
                    )

            # вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР•: Р¤РёРЅР°Р»СЊРЅР°СЏ РїСЂРѕРІРµСЂРєР° Р»РёРјРёС‚РѕРІ РџРћРЎР›Р• РІСЃРµС… РѕРєСЂСѓРіР»РµРЅРёР№
            if notional_usd > max_usd_size:
                logger.warning(
                    f"вљ пёЏ РС‚РѕРіРѕРІС‹Р№ СЂР°Р·РјРµСЂ РїРѕР·РёС†РёРё РїСЂРµРІС‹С€Р°РµС‚ Р»РёРјРёС‚: "
                    f"notional=${notional_usd:.2f} > max=${max_usd_size:.2f}, "
                    f"СѓРјРµРЅСЊС€Р°РµРј СЂР°Р·РјРµСЂ РїРѕР·РёС†РёРё"
                )
                notional_usd = max_usd_size
                margin_usd = notional_usd / leverage
                position_size = notional_usd / price
                logger.info(
                    f"вњ… Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё СѓРјРµРЅСЊС€РµРЅ РґРѕ Р»РёРјРёС‚Р°: "
                    f"notional=${notional_usd:.2f}, margin=${margin_usd:.2f}, "
                    f"position_size={position_size:.6f} РјРѕРЅРµС‚"
                )

            # 10. рџ›ЎпёЏ Р—РђР©РРўРђ: РџСЂРѕРІРµСЂСЏРµРј emergency stop Р drawdown РїРµСЂРµРґ РѕС‚РєСЂС‹С‚РёРµРј
            # FIX (2026-02-21): emergency unlock check РћР‘РЇР—РђРўР•Р›Р¬РќРћ Р”Рћ drawdown check!
            # Р‘РµР· СЌС‚РѕРіРѕ: drawdown returns False (emergency active) в†’ return 0.0 в†’ unlock РќРРљРћР“Р”Рђ РЅРµ РІС‹Р·С‹РІР°РµС‚СЃСЏ
            # в†’ Р±РѕС‚ Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅ РЅР°РІРµС‡РЅРѕ (7.5С‡ РїСЂРѕСЃС‚РѕСЏ РІ СЃРµСЃСЃРёРё 2026-02-20)
            if (
                self.orchestrator
                and hasattr(self.orchestrator, "_emergency_stop_active")
                and self.orchestrator._emergency_stop_active
            ):
                await self._check_emergency_stop_unlock()
                if self.orchestrator._emergency_stop_active:
                    logger.warning(
                        "вљ пёЏ Emergency stop Р°РєС‚РёРІРµРЅ - РїСЂРѕРїСѓСЃРєР°РµРј РїРѕР·РёС†РёСЋ (С‚РѕСЂРіРѕРІР»СЏ Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅР°)"
                    )
                    return 0.0

            if not await self._check_drawdown_protection():
                logger.warning(
                    "вљ пёЏ Drawdown protection Р°РєС‚РёРІРёСЂРѕРІР°РЅ - РїСЂРѕРїСѓСЃРєР°РµРј РїРѕР·РёС†РёСЋ"
                )
                return 0.0

            # вњ… РљР РРўРР§Р•РЎРљРћР• РРЎРџР РђР’Р›Р•РќРР• #5: РџСЂРѕРІРµСЂРєР° РјРёРЅРёРјР°Р»СЊРЅРѕРіРѕ СЂР°Р·РјРµСЂР° РїРµСЂРµРґ РІРѕР·РІСЂР°С‚РѕРј
            if symbol and price > 0:
                try:
                    # РџРѕР»СѓС‡Р°РµРј РґРµС‚Р°Р»Рё РёРЅСЃС‚СЂСѓРјРµРЅС‚Р° РґР»СЏ РїСЂРѕРІРµСЂРєРё РјРёРЅРёРјР°Р»СЊРЅРѕРіРѕ СЂР°Р·РјРµСЂР°
                    inst_details = await self.client.get_instrument_details(symbol)
                    ct_val = float(inst_details.get("ctVal") or 0.01)
                    min_sz = float(inst_details.get("minSz") or 0.01)

                    # РљРѕРЅРІРµСЂС‚РёСЂСѓРµРј СЂР°Р·РјРµСЂ РёР· РјРѕРЅРµС‚ РІ РєРѕРЅС‚СЂР°РєС‚С‹
                    size_in_contracts = position_size / ct_val if ct_val > 0 else 0

                    if size_in_contracts < min_sz:
                        # Р Р°Р·РјРµСЂ РјРµРЅСЊС€Рµ РјРёРЅРёРјСѓРјР° - СѓРІРµР»РёС‡РёРІР°РµРј РґРѕ РјРёРЅРёРјСѓРјР°
                        min_size_in_coins = min_sz * ct_val
                        logger.warning(
                            f"вљ пёЏ Р Р°СЃСЃС‡РёС‚Р°РЅРЅС‹Р№ СЂР°Р·РјРµСЂ РїРѕР·РёС†РёРё {symbol} РјРµРЅСЊС€Рµ РјРёРЅРёРјСѓРјР° Р±РёСЂР¶Рё: "
                            f"{size_in_contracts:.6f} РєРѕРЅС‚СЂР°РєС‚РѕРІ < {min_sz:.6f} РєРѕРЅС‚СЂР°РєС‚РѕРІ. "
                            f"РЈРІРµР»РёС‡РёРІР°РµРј РґРѕ РјРёРЅРёРјСѓРјР°: {position_size:.6f} в†’ {min_size_in_coins:.6f} РјРѕРЅРµС‚"
                        )
                        position_size = min_size_in_coins

                        # РџРµСЂРµСЃС‡РёС‚С‹РІР°РµРј notional Рё margin РґР»СЏ РЅРѕРІРѕРіРѕ СЂР°Р·РјРµСЂР°
                        notional_usd = position_size * price
                        margin_usd = (
                            notional_usd / leverage if leverage > 0 else notional_usd
                        )

                        logger.info(
                            f"рџ’° Р РђРЎР§Р•Рў РЎРљРћР Р Р•РљРўРР РћР’РђРќ: position_size={position_size:.6f} РјРѕРЅРµС‚ "
                            f"({min_sz:.6f} РєРѕРЅС‚СЂР°РєС‚РѕРІ), notional=${notional_usd:.2f}, margin=${margin_usd:.2f}"
                        )
                except Exception as e:
                    logger.warning(
                        f"вљ пёЏ РќРµ СѓРґР°Р»РѕСЃСЊ РїСЂРѕРІРµСЂРёС‚СЊ РјРёРЅРёРјР°Р»СЊРЅС‹Р№ СЂР°Р·РјРµСЂ РґР»СЏ {symbol}: {e}, "
                        f"РёСЃРїРѕР»СЊР·СѓРµРј СЂР°СЃСЃС‡РёС‚Р°РЅРЅС‹Р№ СЂР°Р·РјРµСЂ {position_size:.6f} РјРѕРЅРµС‚"
                    )

            # вњ… РќРћР’РћР• (26.12.2025): Р”РµС‚Р°Р»СЊРЅРѕРµ Р»РѕРіРёСЂРѕРІР°РЅРёРµ РёС‚РѕРіРѕРІРѕРіРѕ СЂР°СЃС‡РµС‚Р° СЂР°Р·РјРµСЂР° РїРѕР·РёС†РёРё
            logger.info("=" * 80)
            logger.info(
                f"рџ’° Р¤РРќРђР›Р¬РќР«Р™ Р РђРЎР§Р•Рў Р РђР—РњР•Р Рђ РџРћР—РР¦РР РґР»СЏ {symbol}:"
            )
            logger.info(
                f"   Р‘Р°Р»Р°РЅСЃ: ${balance:.2f} (РїСЂРѕС„РёР»СЊ: {balance_profile['name']})"
            )
            logger.info(
                f"   Р‘Р°Р·РѕРІС‹Р№ СЂР°Р·РјРµСЂ (notional): ${base_usd_size:.2f}"
            )
            if is_progressive:
                logger.info(
                    f"   РџСЂРѕРіСЂРµСЃСЃРёРІРЅС‹Р№ СЂР°СЃС‡РµС‚: ${size_at_min:.2f} в†’ ${size_at_max:.2f}"  # noqa: F821
                )

            # РџРѕР»СѓС‡Р°РµРј РІСЃРµ РјРЅРѕР¶РёС‚РµР»Рё РґР»СЏ Р»РѕРіРёСЂРѕРІР°РЅРёСЏ
            position_multiplier_used = None
            if symbol:
                symbol_profile = self.symbol_profiles.get(symbol, {})
                if symbol_profile:
                    symbol_dict = (
                        self.config_manager.to_dict(symbol_profile)
                        if not isinstance(symbol_profile, dict)
                        else symbol_profile
                    )
                    position_multiplier_used = symbol_dict.get("position_multiplier")

            if position_multiplier_used and position_multiplier_used != 1.0:
                logger.info(f"   Per-symbol multiplier: {position_multiplier_used}x")

            if strength_multiplier != 1.0:
                logger.info(
                    f"   Strength multiplier: {strength_multiplier:.2f}x (СЃРёР»Р° СЃРёРіРЅР°Р»Р°: {signal_strength:.2f})"
                )

            if volatility_multiplier != 1.0:
                logger.info(f"   Volatility multiplier: {volatility_multiplier:.2f}x")

            # РџРѕР»СѓС‡Р°РµРј regime multiplier
            regime_multiplier_used = None
            if symbol_regime:
                regime_params = self.config_manager.get_regime_params(
                    symbol_regime, symbol
                )
                regime_multiplier_used = regime_params.get("position_size_multiplier")
                if regime_multiplier_used and regime_multiplier_used != 1.0:
                    logger.info(
                        f"   Regime multiplier ({symbol_regime}): {regime_multiplier_used:.2f}x"
                    )

            logger.info(f"   Р›РµРІРµСЂРёРґР¶: {leverage}x")
            logger.info(
                f"   РњР°СЂР¶Р°: ${margin_usd:.2f} (Р»РёРјРёС‚: ${min_margin_usd:.2f}-${max_margin_usd:.2f})"
            )
            logger.info(f"   Notional: ${notional_usd:.2f}")
            logger.info(
                f"   РРўРћР“РћР’Р«Р™ СЂР°Р·РјРµСЂ РїРѕР·РёС†РёРё: {position_size:.6f} РјРѕРЅРµС‚ (${notional_usd:.2f} notional, ${margin_usd:.2f} margin)"
            )
            logger.info("=" * 80)

            return position_size

        except Exception as e:
            logger.error(
                f"РћС€РёР±РєР° СЂР°СЃС‡РµС‚Р° СЂР°Р·РјРµСЂР° РїРѕР·РёС†РёРё: {e}",
                exc_info=True,
            )
            return 0.0

    async def check_margin_safety(
        self,
        position_size_usd: float,
        current_positions: Dict[str, Any],
    ) -> bool:
        """
        РџСЂРѕРІРµСЂРєР° Р±РµР·РѕРїР°СЃРЅРѕСЃС‚Рё РјР°СЂР¶Рё.

        Args:
            position_size_usd: Р Р°Р·РјРµСЂ РЅРѕРІРѕР№ РїРѕР·РёС†РёРё
            current_positions: РўРµРєСѓС‰РёРµ РїРѕР·РёС†РёРё

        Returns:
            bool: True РµСЃР»Рё Р±РµР·РѕРїР°СЃРЅРѕ РѕС‚РєСЂС‹РІР°С‚СЊ
        """
        if not self.margin_monitor:
            return True

        try:
            # вњ… РРЎРџР РђР’Р›Р•РќРћ (28.12.2025): РџРµСЂРµРґР°РµРј orchestrator Рё data_registry РґР»СЏ РґРѕСЃС‚СѓРїР° Рє Р±Р°Р»Р°РЅСЃСѓ
            return await self.margin_monitor.check_safety(
                position_size_usd,
                current_positions,
                orchestrator=self.orchestrator,  # вњ… РџРµСЂРµРґР°РµРј orchestrator
                data_registry=self.data_registry,  # вњ… РџРµСЂРµРґР°РµРј data_registry
            )
        except Exception as e:
            logger.error(f"вќЊ Error checking margin safety: {e}")
            return False

    async def check_liquidation_risk(
        self,
        symbol: str,
        side: str,
        position_size_usd: float,
        entry_price: float,
    ) -> bool:
        """
        РџСЂРѕРІРµСЂРєР° СЂРёСЃРєР° Р»РёРєРІРёРґР°С†РёРё.

        Args:
            symbol: РўРѕСЂРіРѕРІС‹Р№ СЃРёРјРІРѕР»
            side: РЎС‚РѕСЂРѕРЅР° РїРѕР·РёС†РёРё
            position_size_usd: Р Р°Р·РјРµСЂ РїРѕР·РёС†РёРё
            entry_price: Р¦РµРЅР° РІС…РѕРґР°

        Returns:
            bool: True РµСЃР»Рё СЂРёСЃРє РїСЂРёРµРјР»РµРјС‹Р№
        """
        if not self.liquidation_protector:
            return True

        try:
            # рџ”ґ BUG #21 FIX: РџРѕР»СѓС‡Р°РµРј Р Р•РђР›Р¬РќРЈР® РјР°СЂР¶Сѓ РѕС‚ API, РЅРµ position_size
            current_price = entry_price  # Fallback: РёСЃРїРѕР»СЊР·СѓРµРј entry_price РµСЃР»Рё РЅРµ РјРѕР¶РµРј РїРѕР»СѓС‡РёС‚СЊ С‚РµРєСѓС‰СѓСЋ
            margin = None

            # РџС‹С‚Р°РµРјСЃСЏ РїРѕР»СѓС‡РёС‚СЊ С‚РµРєСѓС‰СѓСЋ С†РµРЅСѓ
            try:
                if self.data_registry:
                    ticker_data = await self.data_registry.get_ticker(symbol)
                    if ticker_data and "last" in ticker_data:
                        raw_last = ticker_data.get("last")
                        if raw_last is not None:
                            current_price = float(raw_last)
            except Exception:
                pass

            # FIX (2026-02-21): РџРѕР»СѓС‡Р°РµРј РјР°СЂР¶Сѓ РёР· active_positions (WS-driven) РІРјРµСЃС‚Рѕ REST.
            # Private WS positions channel РїСЂРёСЃС‹Р»Р°РµС‚ РїРѕР»Рµ "margin" РІ СЂРµР°Р»СЊРЅРѕРј РІСЂРµРјРµРЅРё.
            # REST fallback С‚РѕР»СЊРєРѕ РµСЃР»Рё WS margin == 0 (РЅРѕРІР°СЏ РїРѕР·РёС†РёСЏ, WS РµС‰С‘ РЅРµ РѕР±РЅРѕРІРёР»СЃСЏ).
            try:
                ws_margin = 0.0
                if self.orchestrator and hasattr(self.orchestrator, "active_positions"):
                    pos_data = self.orchestrator.active_positions.get(symbol, {})
                    ws_margin = float(pos_data.get("margin", 0) or 0)
                    if ws_margin > 0:
                        margin = ws_margin
                        logger.debug(
                            f"вњ“ РњР°СЂР¶Р° РґР»СЏ {symbol}: {margin} USDT [source=WS]"
                        )

                # REST fallback: С‚РѕР»СЊРєРѕ РµСЃР»Рё WS margin РЅРµ РїСЂРёС€С‘Р» РµС‰С‘
                if (margin is None or margin == 0) and self.client:
                    positions_data = await self.client.get_positions()
                    if positions_data:
                        for pos in positions_data:
                            if pos.get("instId") == f"{symbol}-SWAP":
                                margin = float(pos.get("margin", 0))
                                logger.debug(
                                    f"вњ“ РњР°СЂР¶Р° РґР»СЏ {symbol}: {margin} USDT [source=REST_FALLBACK]"
                                )
                                break
            except Exception as e:
                logger.warning(
                    f"вљ пёЏ РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ РјР°СЂР¶Сѓ: {e}"
                )

            # Fallback: РµСЃР»Рё РјР°СЂР¶Р° РЅРµ РїРѕР»СѓС‡РµРЅР°
            if margin is None or margin == 0:
                # РћС†РµРЅРёРІР°РµРј РјР°СЂР¶Сѓ РєР°Рє position_size / leverage
                estimated_leverage = (
                    self.config.risk.leverage
                    if hasattr(self.config.risk, "leverage")
                    else 10
                )
                margin = position_size_usd / estimated_leverage
                logger.warning(
                    f"вљ пёЏ РњР°СЂР¶Р° РЅРµ РїРѕР»СѓС‡РµРЅР° РѕС‚ API, РёСЃРїРѕР»СЊР·СѓРµРј РѕС†РµРЅРєСѓ: {margin} USDT "
                    f"(position_size={position_size_usd}, leverage={estimated_leverage})"
                )

            # вњ… Р¤РѕСЂРјРёСЂСѓРµРј РїРѕР·РёС†РёСЋ РєР°Рє dict РґР»СЏ LiquidationProtector
            position = {
                "side": side,
                "size": position_size_usd,
                "entry_price": entry_price,
                "avgPx": entry_price,
                "mark_price": current_price,
                "margin": margin,
            }
            # Р’С‹Р·С‹РІР°РµРј check_liquidation_risk СЃ РїСЂР°РІРёР»СЊРЅС‹РјРё Р°СЂРіСѓРјРµРЅС‚Р°РјРё
            return await self.liquidation_protector.check_liquidation_risk(
                symbol=symbol,
                position=position,
                balance=margin,
            )
        except Exception as e:
            logger.error(f"вќЊ Error checking liquidation risk: {e}")
            return False

    def get_adaptive_risk_params(
        self,
        balance: float,
        regime: Optional[str] = None,
        symbol: Optional[str] = None,
        signal_generator=None,
    ) -> Dict[str, Any]:
        """
        РџРѕР»СѓС‡РёС‚СЊ Р°РґР°РїС‚РёРІРЅС‹Рµ РїР°СЂР°РјРµС‚СЂС‹ СЂРёСЃРєР°.

        Р”РµР»РµРіРёСЂСѓРµС‚ РІ ConfigManager.

        Args:
            balance: РўРµРєСѓС‰РёР№ Р±Р°Р»Р°РЅСЃ
            regime: Р РµР¶РёРј СЂС‹РЅРєР°
            symbol: РўРѕСЂРіРѕРІС‹Р№ СЃРёРјРІРѕР»
            signal_generator: Signal generator

        Returns:
            Dict: РџР°СЂР°РјРµС‚СЂС‹ СЂРёСЃРєР°
        """
        return self.config_manager.get_adaptive_risk_params(
            balance, regime, symbol, signal_generator
        )
