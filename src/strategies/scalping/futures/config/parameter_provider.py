"""
Parameter Provider - �զ+���-�-T� T¦-TǦ��- ���-��T�TǦ��-��T� ���-T��-�-��T�T��-�- T¦-T����-�-����.

�ަ-��T�����TǦ��-�-��T� TƦ��-T�T��-�������-�-�-�-�-T˦� �+�-T�T�Tæ� �� ���-T��-�-��T�T��-�- ���� T��-������TǦ-T�T� ��T�T¦-TǦ-�����-�-:
- ConfigManager
- RegimeManager
- Symbol profiles
- Adaptive risk parameters

��T����+�-T¦-T��-Tɦ-��T� �+Tæ-����T��-�-�-�-���� ���-�+�- �� �-�-��T�����TǦ��-�-��T� ���-�-T���T�T¦��-T¦-�-T�T�T� ���-T��-�-��T�T��-�-.
"""

from dataclasses import asdict
from typing import Any, Dict, Optional

from loguru import logger

from ..parameters.parameter_orchestrator import ParameterOrchestrator
from .config_manager import ConfigManager


class ParameterProvider:
    """
    �զ+���-�-T� T¦-TǦ��- ���-��T�TǦ��-��T� ���-T��-�-��T�T��-�- T¦-T����-�-����.

    �ަ-Tʦ��+���-TϦ�T� �+�-T�T�Tæ� �� ���-T��-�-��T�T��-�- ���� T��-������TǦ-T�T� ��T�T¦-TǦ-�����-�- �� ��T����+�-T�T¦-�-��TϦ�T�
    ���+���-T˦� ���-T¦�T�TĦ���T� �+��T� �-T���T� �-�-�+Tæ����� T���T�T¦��-T�.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        regime_manager=None,  # AdaptiveRegimeManager (�-��TƦ��-�-�-��Ț-�-)
        data_registry=None,  # DataRegistry (�-��TƦ��-�-�-��Ț-�-)
        parameter_orchestrator: Optional[ParameterOrchestrator] = None,
        strict_mode: bool = False,
    ):
        """
        �ئ-��TƦ��-�������-TƦ�T� Parameter Provider.

        Args:
            config_manager: ConfigManager �+��T� �+�-T�T�Tæ��- �� ���-�-TĦ���T�T��-TƦ���
            regime_manager: AdaptiveRegimeManager �+��T� T��������--T�����TƦ�TĦ�TǦ-T�T� ���-T��-�-��T�T��-�- (�-��TƦ��-�-�-��Ț-�-)
            data_registry: DataRegistry �+��T� T¦���T�Tɦ�T� T��������-�-�- (�-��TƦ��-�-�-��Ț-�-)
        """
        self.config_manager = config_manager
        self.regime_manager = regime_manager
        self.data_registry = data_registry
        self.parameter_orchestrator = parameter_orchestrator
        self.strict_mode = bool(strict_mode)

        # ��T�T� �+��T� TǦ-T�T¦- ��T����-��Ț�Tæ��-T�T� ���-T��-�-��T�T��-�-
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_ttl_seconds = 300.0  # ��� �ئ�ߦ�ЦҦۦզݦ� (28.12.2025): ��-������TǦ��-�- T� 60 �+�- 300 T�����Tæ-�+ (5 �-���-T�T�) �+��T� T��-�������-��T� �-�-��T�Tæ�����

        logger.info("��� ParameterProvider ���-��TƦ��-��������T��-�-�-�-")

    def _resolve_bundle(
        self,
        symbol: str,
        regime: Optional[str] = None,
        market_data: Optional[Any] = None,
        balance: Optional[float] = None,
        include_signal: bool = True,
        include_exit: bool = True,
        include_order: bool = True,
        include_risk: bool = True,
        include_patterns: bool = True,
    ):
        if not self.parameter_orchestrator:
            return None
        bundle = self.parameter_orchestrator.resolve_bundle(
            symbol=symbol,
            regime=regime,
            market_data=market_data,
            balance=balance,
            include_signal=include_signal,
            include_exit=include_exit,
            include_order=include_order,
            include_risk=include_risk,
            include_patterns=include_patterns,
        )
        if not bundle.status.valid:
            logger.error(
                f"PARAM_ORCH invalid for {symbol} ({regime or 'auto'}): {bundle.status.errors}"
            )
            return None
        return bundle

    @staticmethod
    def _bundle_to_dict(bundle_section):
        if bundle_section is None:
            return None
        try:
            return asdict(bundle_section)
        except Exception:
            return None

    def get_regime_params(
        self,
        symbol: str,
        regime: Optional[str] = None,
        balance: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        �ߦ-��T�TǦ�T�T� ���-T��-�-��T�T�T� �+��T� T��������-�- T�T˦-���-.

        Args:
            symbol: ��-T����-�-T˦� T����-�-�-��
            regime: �দ�����- T�T˦-���- (trending/ranging/choppy). ��T����� None, �-��T����+����TϦ�T�T�T� �-�-T¦-�-�-T¦�TǦ�T�����
            balance: �⦦��T�Tɦ��� �-�-���-�-T� (�+��T� �-�+�-��T¦��-�-T�T� ���-T��-�-��T�T��-�-)

        Returns:
            �᦬�-�-�-T�T� T� ���-T��-�-��T�T��-�-�� T��������-�-:
            {
                "min_score_threshold": float,
                "max_trades_per_hour": int,
                "position_size_multiplier": float,
                "tp_atr_multiplier": float,
                "sl_atr_multiplier": float,
                "max_holding_minutes": int,
                "cooldown_after_loss_minutes": int,
                ...
            }
        """
        try:
            if self.parameter_orchestrator:
                bundle = self._resolve_bundle(
                    symbol=symbol,
                    regime=regime,
                    balance=balance,
                    include_signal=True,
                    include_exit=True,
                    include_order=False,
                    include_risk=True,
                    include_patterns=False,
                )
                if bundle:
                    params = {}
                    if bundle.signal:
                        params.update(
                            {
                                "min_score_threshold": bundle.signal.min_score_threshold,
                                "max_trades_per_hour": bundle.signal.max_trades_per_hour,
                                "position_size_multiplier": bundle.signal.position_size_multiplier,
                                "min_adx": bundle.signal.min_adx,
                                "min_signal_strength": bundle.signal.min_signal_strength,
                            }
                        )
                    if bundle.exit:
                        params.update(
                            {
                                "tp_atr_multiplier": bundle.exit.tp_atr_multiplier,
                                "sl_atr_multiplier": bundle.exit.sl_atr_multiplier,
                                "max_holding_minutes": bundle.exit.max_holding_minutes,
                                "min_holding_minutes": bundle.exit.min_holding_minutes,
                                "tp_percent": bundle.exit.tp_percent,
                                "sl_percent": bundle.exit.sl_percent,
                                "tp_min_percent": bundle.exit.tp_min_percent,
                                "sl_min_percent": bundle.exit.sl_min_percent,
                            }
                        )
                    if bundle.risk:
                        params.update(
                            {
                                "leverage": bundle.risk.leverage,
                                "position_size_usd": bundle.risk.position_size_usd,
                                "min_position_usd": bundle.risk.min_position_usd,
                                "max_position_usd": bundle.risk.max_position_usd,
                                "max_open_positions": bundle.risk.max_open_positions,
                                "max_position_percent": bundle.risk.max_position_percent,
                            }
                        )
                    return params
                if self.strict_mode:
                    return {}
            # �ަ�T����+����TϦ��- T��������- ��T����� �-�� Tæ��-���-�-
            if not regime:
                regime = self._get_current_regime(symbol)

            # �ߦ-��T�TǦ-���- ���-T��-�-��T�T�T� ���� ConfigManager
            regime_params = self.config_manager.get_regime_params(regime)

            # ��T����-���-TϦ��- �-�+�-��T¦��-�-T˦� ���-T��-�-��T�T�T� ��T����� �-�-���-�-T� Tæ��-���-�-
            if balance is not None:
                adaptive_params = self.config_manager.get_adaptive_risk_params(
                    balance, regime
                )
                # �ަ-Tʦ��+���-TϦ��- ���-T��-�-��T�T�T� (�-�+�-��T¦��-�-T˦� ���-��T�T� ��T����-T���T¦�T�)
                regime_params = {**regime_params, **adaptive_params}

            return regime_params

        except Exception as e:
            logger.warning(
                f"������ ParameterProvider: ��TȦ��-���- ���-��T�TǦ��-��T� ���-T��-�-��T�T��-�- T��������-�- �+��T� {symbol}: {e}"
            )
            # �Ҧ-���-T��-Tɦ-���- �+��TĦ-��T¦-T˦� ���-T��-�-��T�T�T�
            return self._get_default_regime_params()

    def get_exit_params(
        self,
        symbol: str,
        regime: Optional[str] = None,
        # ��� �ݦަҦަ� (05.01.2026): �ަ�TƦ��-�-�-��Ț-T˦� ���-�-T¦���T�T� �+��T� �-�+�-��T¦-TƦ���
        balance: Optional[float] = None,
        current_pnl: Optional[float] = None,  # �⦦��T�Tɦ��� P&L ���-����TƦ��� �- %
        drawdown: Optional[float] = None,  # �⦦��T�Tɦ-T� ��T��-T��-�+���- �- %
        position_size: Optional[float] = None,  # ��-���-��T� ���-����TƦ���
        margin_used: Optional[float] = None,  # ��T����-��Ț�Tæ��-�-T� �-�-T����-
    ) -> Dict[str, Any]:
        """
        �ߦ-��T�TǦ�T�T� ���-T��-�-��T�T�T� �-T�TŦ-�+�- (TP/SL) �+��T� T��������-�-.

        ��� �ݦަҦަ� (05.01.2026): �ߦ-�+�+��T������-�-��T� �-�+�-��T¦��-�-T˦� ���-T��-�-��T�T�T� �-�- �-T��-�-�-�� ���-�-T¦���T�T¦-.

        Args:
            symbol: ��-T����-�-T˦� T����-�-�-��
            regime: �দ�����- T�T˦-���-. ��T����� None, �-��T����+����TϦ�T�T�T� �-�-T¦-�-�-T¦�TǦ�T�����
            balance: �⦦��T�Tɦ��� �-�-���-�-T� (�+��T� �-�+�-��T¦-TƦ��� ���- �-�-���-�-T�T�)
            current_pnl: �⦦��T�Tɦ��� P&L ���-����TƦ��� �- % (�+��T� T��-T�TȦ�T����-��T� TP)
            drawdown: �⦦��T�Tɦ-T� ��T��-T��-�+���- �- % (�+��T� Tæ���T�T¦-TǦ��-��T� SL)
            position_size: ��-���-��T� ���-����TƦ��� (�+��T� ���-T�T�����T¦�T��-�-���� T���T����-)
            margin_used: ��T����-��Ț�Tæ��-�-T� �-�-T����- (�+��T� ��T��-�-��T����� �-�����-���-T��-�-T�T¦�)

        Returns:
            �᦬�-�-�-T�T� T� ���-T��-�-��T�T��-�-�� �-T�TŦ-�+�- (�-�+�-��T¦��-�-T˦-�� ��T����� ���-�-T¦���T�T� ����T����+�-�-):
            {
                "tp_atr_multiplier": float,
                "sl_atr_multiplier": float,
                "max_holding_minutes": int,
                "emergency_loss_threshold": float,
                ...
            }
        """
        try:
            if self.parameter_orchestrator:
                bundle = self._resolve_bundle(
                    symbol=symbol,
                    regime=regime,
                    balance=balance,
                    include_signal=False,
                    include_exit=True,
                    include_order=False,
                    include_risk=False,
                    include_patterns=False,
                )
                if bundle and bundle.exit:
                    return self._bundle_to_dict(bundle.exit)
                if self.strict_mode:
                    return {}
            # �ަ�T����+����TϦ��- T��������- ��T����� �-�� Tæ��-���-�-
            if not regime:
                regime = self._get_current_regime(symbol)

            # ✅ L1-6 FIX: Используем консолидированный метод вместо прямого чтения
            exit_params = self.config_manager.get_consolidated_exit_params(
                symbol, regime
            )

            # ��� �ڦ�ئ�ئ�զ�ڦަ� �ئ�ߦ�ЦҦۦզݦئ� (28.12.2025): �ڦ-�-�-��T�T¦-TƦ�T� T¦����-�- �+��T� �-T���T� TǦ�T����-�-T�T� ���-T��-�-��T�T��-�-
            # ��T����+�-T¦-T��-Tɦ-��T� TypeError ��T��� T�T��-�-�-���-���� str �� int/float
            def _to_float(value: Any, name: str, default: float = 0.0) -> float:
                """Helper �+��T� �-�����-���-T��-�-�� ���-�-�-��T�T¦-TƦ��� �- float"""
                if value is None:
                    return default
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        logger.warning(
                            f"������ ParameterProvider: �ݦ� Tæ+�-���-T�T� ���-�-�-��T�T¦�T��-�-�-T�T� {name}={value} �- float, "
                            f"��T����-��Ț�Tæ��- default={default}"
                        )
                        return default
                return default

            # �ڦ-�-�-��T�T¦�T�Tæ��- ����T�TǦ��-T˦� ���-T��-�-��T�T�T�
            if exit_params:
                exit_params["max_holding_minutes"] = _to_float(
                    exit_params.get("max_holding_minutes"),
                    "max_holding_minutes",
                    25.0
                    if regime and regime.lower() == "ranging"
                    else 120.0,  # Default �+��T� ranging: 25.0, ���-�-TǦ� 120.0
                )
                exit_params["sl_atr_multiplier"] = _to_float(
                    exit_params.get("sl_atr_multiplier"),
                    "sl_atr_multiplier",
                    2.0,  # ��� Default Tæ-������TǦ��- T� 1.5 �+�- 2.0
                )
                exit_params["tp_atr_multiplier"] = _to_float(
                    exit_params.get("tp_atr_multiplier"), "tp_atr_multiplier", 1.0
                )
                exit_params["min_profit_for_extension"] = _to_float(
                    exit_params.get("min_profit_for_extension"),
                    "min_profit_for_extension",
                    0.4,
                )
                exit_params["extension_percent"] = _to_float(
                    exit_params.get("extension_percent"), "extension_percent", 100.0
                )
                exit_params["min_holding_minutes"] = _to_float(
                    exit_params.get("min_holding_minutes"),
                    "min_holding_minutes",
                    0.5,  # ��� Default �+��T� ranging: 0.5 �-���-T�T�T�
                )

            # ��� �ߦ�ئަ�ئ�զ� 1 (29.12.2025): ��T��-�-��T����- by_symbol �+��T� per-symbol ���-T��-�-��T�T��-�-
            # ��� �ݦަҦަ� (03.01.2026): �ۦ-����T��-�-�-�-���� ��T�T¦-TǦ-�����-�- ���-T��-�-��T�T��-�- �+��T� ���-�-���-�-�-��T� T��-�-�-T�T� �-�-T¦-
            sources_log = []

            # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ (23.01.2026): Проверяем exit_params ПОСЛЕ базовых _to_float
            if exit_params:
                logger.debug(
                    f"🔍 [PARAM_PROVIDER_TRACE] {symbol} ({regime}): ПОСЛЕ базовых _to_float | "
                    f"sl_atr={exit_params.get('sl_atr_multiplier')}, "
                    f"sl_min={exit_params.get('sl_min_percent')}, "
                    f"min_hold={exit_params.get('min_holding_minutes')}"
                )

            if symbol and hasattr(self.config_manager, "_raw_config_dict"):
                config_dict = self.config_manager._raw_config_dict
                by_symbol = config_dict.get("by_symbol", {})
                symbol_config = by_symbol.get(symbol, {})
                if isinstance(symbol_config, dict):
                    # �ߦ�T����-��T����+����TϦ��- ���-T��-�-��T�T�T� ���� by_symbol (��T����-T���T¦�T� �-T�TȦ� exit_params.{regime})
                    per_symbol_keys = [
                        "sl_atr_multiplier",
                        "tp_atr_multiplier",
                        "max_holding_minutes",
                    ]
                    for key in per_symbol_keys:
                        if key in symbol_config:
                            old_value = exit_params.get(key)
                            exit_params[key] = _to_float(
                                symbol_config[key],
                                key,
                                exit_params.get(
                                    key,
                                    2.0
                                    if "sl_atr" in key
                                    else 1.0
                                    if "tp_atr" in key
                                    else 25.0,
                                ),
                            )
                            sources_log.append(
                                f"{key}={exit_params[key]} (by_symbol, �-T˦��-={old_value})"
                            )
                    # ��� �ڦ�ئ�ئ�զ�ڦަ� ��ۦ���զݦئ� �ۦަӦئ�ަҦЦݦئ� (03.01.2026): �Ԧ�T¦-��Ț-�-�� ���-����T��-�-�-�-���� ��T�T¦-TǦ-�����-�-
                    logger.info(
                        f"���� [PARAMS] {symbol} ({regime}): exit_params "
                        f"sl_atr={exit_params.get('sl_atr_multiplier', 'N/A')}, "
                        f"tp_atr={exit_params.get('tp_atr_multiplier', 'N/A')}, "
                        f"max_holding={exit_params.get('max_holding_minutes', 'N/A')}�-���-, "
                        f"min_holding={exit_params.get('min_holding_minutes', 'N/A')}�-���- | "
                        f"��T�T¦-TǦ-������: {', '.join(sources_log) if sources_log else 'exit_params.' + regime}"
                    )

            # ��� �ݦަҦަ� (05.01.2026): ��T����-���-TϦ��- �-�+�-��T¦-TƦ�T� ��T����� ����T����+�-�- ���-�-T¦���T�T�
            if balance is not None or current_pnl is not None or drawdown is not None:
                exit_params = self._apply_adaptive_exit_params(
                    exit_params, symbol, regime, balance, current_pnl, drawdown
                )

            return exit_params or {}

        except Exception as e:
            logger.warning(
                f"������ ParameterProvider: ��TȦ��-���- ���-��T�TǦ��-��T� exit_params �+��T� {symbol}: {e}"
            )
            return {}

    def _apply_adaptive_exit_params(
        self,
        base_params: Dict[str, Any],
        symbol: str,
        regime: Optional[str],
        balance: Optional[float],
        current_pnl: Optional[float],
        drawdown: Optional[float],
    ) -> Dict[str, Any]:
        """
        ��� �ݦަҦަ� (06.01.2026): ��T����-���-��T�T� �-�+�-��T¦��-�-T�T� ���-������T� �� ���-T��-�-��T�T��-�- �-T�TŦ-�+�-.

        ��T����-��Ț�Tæ�T� �����-�-�-T�T� ���-T¦�T����-��T�TƦ�T� ���- �-�-���-�-T�T� �+��T� T��-T�TǦ�T¦- TP/SL �-�-�-����T¦�������.

        Args:
            base_params: �Ѧ-���-�-T˦� ���-T��-�-��T�T�T� �-T�TŦ-�+�-
            symbol: ��-T����-�-T˦� T����-�-�-��
            regime: �দ�����- T�T˦-���-
            balance: �⦦��T�Tɦ��� �-�-���-�-T�
            current_pnl: �⦦��T�Tɦ��� P&L ���-����TƦ��� �- %
            drawdown: �⦦��T�Tɦ-T� ��T��-T��-�+���- �- %

        Returns:
            �Ц+�-��T¦��-�-T˦� ���-T��-�-��T�T�T� �-T�TŦ-�+�-
        """
        try:
            # ��T��-�-��T�TϦ��-, �-����T�TǦ��-�- ���� �-�+�-��T¦-TƦ�T�
            adaptive_config = self._get_adaptive_exit_config()
            if not adaptive_config.get("enabled", False):
                logger.debug(
                    "������ �Ц+�-��T¦��-�-T˦� ���-T��-�-��T�T�T� �-T¦���T�TǦ��-T� �- ���-�-TĦ���T�T��-TƦ���"
                )
                return base_params

            # �ڦ-����T�Tæ��- �-�-���-�-T˦� ���-T��-�-��T�T�T�
            adaptive_params = base_params.copy()

            # �ߦ-��T�TǦ-���- �-�-���-�-T˦� �-�-�-����T¦�����
            tp_base = base_params.get("tp_atr_multiplier", 2.0)
            sl_base = base_params.get("sl_atr_multiplier", 1.5)

            # �Ц+�-��T¦-TƦ�T� ���- �-�-���-�-T�T� (�����-�-�-T˦� TĦ-��T¦-T�)
            if balance is not None:
                (
                    balance_factor_tp,
                    balance_factor_sl,
                ) = self._calculate_balance_adaptation_factors(balance)
                adaptive_params["tp_atr_multiplier"] = tp_base * balance_factor_tp
                adaptive_params["sl_atr_multiplier"] = sl_base * balance_factor_sl

                logger.debug(
                    f"���- [ADAPTIVE] {symbol}: �Ѧ-���-�-T� ${balance:.0f} ��� "
                    f"TP: {tp_base:.2f} +� {balance_factor_tp:.3f} = {adaptive_params['tp_atr_multiplier']:.2f}, "
                    f"SL: {sl_base:.2f} +� {balance_factor_sl:.3f} = {adaptive_params['sl_atr_multiplier']:.2f}"
                )

            # �Ц+�-��T¦-TƦ�T� ���- P&L ���-����TƦ���
            if current_pnl is not None:
                pnl_factor = self._calculate_pnl_adaptation_factor(current_pnl)
                if pnl_factor != 1.0:
                    adaptive_params["tp_atr_multiplier"] *= pnl_factor
                    logger.debug(
                        f"���� [ADAPTIVE] {symbol}: P&L {current_pnl:.1f}% ��� "
                        f"TP T��-T�TȦ�T����-���� +�{pnl_factor:.3f} = {adaptive_params['tp_atr_multiplier']:.2f}"
                    )

            # �Ц+�-��T¦-TƦ�T� ���- ��T��-T��-�+����
            if drawdown is not None:
                drawdown_factor = self._calculate_drawdown_adaptation_factor(drawdown)
                if drawdown_factor != 1.0:
                    adaptive_params["sl_atr_multiplier"] *= drawdown_factor
                    logger.debug(
                        f"���� [ADAPTIVE] {symbol}: ��T��-T��-�+���- {drawdown:.1f}% ��� "
                        f"SL Tæ���T�T¦-TǦ��-���� +�{drawdown_factor:.3f} = {adaptive_params['sl_atr_multiplier']:.2f}"
                    )

            # �ަ�T��-�-��TǦ��-��T� �-�- TĦ��-�-��Ț-T˦� ���-�-TǦ��-��T�
            adaptive_params["tp_atr_multiplier"] = min(
                max(adaptive_params["tp_atr_multiplier"], 1.0), 5.0
            )
            adaptive_params["sl_atr_multiplier"] = min(
                max(adaptive_params["sl_atr_multiplier"], 0.5), 3.0
            )

            if balance is None:
                balance = 0.0
            if current_pnl is None:
                current_pnl = 0.0
            if drawdown is None:
                drawdown = 0.0

            # �ۦ-����T��-�-�-�-���� ��T¦-���-�-T�T� �-�+�-��T¦��-�-T�T� ���-T��-�-��T�T��-�-
            logger.info(
                f"���� [ADAPTIVE] {symbol} ({regime}): �䦬�-�-��Ț-T˦� ���-T��-�-��T�T�T� ��� "
                f"TP: {adaptive_params['tp_atr_multiplier']:.2f}, "
                f"SL: {adaptive_params['sl_atr_multiplier']:.2f} | "
                f"�ڦ-�-T¦���T�T�: �-�-���-�-T�=${balance:.0f}, P&L={current_pnl:.1f}%, ��T��-T��-�+���-={drawdown:.1f}%"
            )

            return adaptive_params

        except Exception as e:
            logger.warning(
                f"������ ParameterProvider: ��TȦ��-���- ��T����-���-���-��T� �-�+�-��T¦��-�-T�T� ���-T��-�-��T�T��-�- �+��T� {symbol}: {e}"
            )
            return base_params

    def get_smart_close_params(
        self, regime: str, symbol: Optional[str] = None
    ) -> Dict[str, float]:
        """
        �ߦ-��T�TǦ�T�T� �-�+�-��T¦��-�-T˦� ���-T��-�-��T�T�T� Smart Close �+��T� T��������-�-.

        ��T����-T���T¦�T�:
        1. by_symbol.{symbol}.smart_close.{regime}
        2. exit_params.smart_close.{regime}
        3. Default ���-�-TǦ��-��T�

        Args:
            regime: �দ�����- T�T˦-���- (trending, ranging, choppy)
            symbol: ��-T����-�-T˦� T����-�-�-�� (�-��TƦ��-�-�-��Ț-�-, �+��T� per-symbol ���-T��-�-��T�T��-�-)

        Returns:
            {
                'reversal_score_threshold': float,
                'trend_against_threshold': float
            }
        """
        defaults = {"reversal_score_threshold": 2.0, "trend_against_threshold": 0.7}

        try:
            # ��� �ߦ�ئަ�ئ�զ� 1: by_symbol.{symbol}.smart_close.{regime}
            if symbol and hasattr(self.config_manager, "_raw_config_dict"):
                config_dict = self.config_manager._raw_config_dict
                by_symbol = config_dict.get("by_symbol", {})
                symbol_config = by_symbol.get(symbol, {})
                if isinstance(symbol_config, dict):
                    smart_close_config = symbol_config.get("smart_close", {})
                    if isinstance(smart_close_config, dict):
                        regime_config = smart_close_config.get(regime, {})
                        if isinstance(regime_config, dict):
                            reversal_threshold = regime_config.get(
                                "reversal_score_threshold"
                            )
                            trend_threshold = regime_config.get(
                                "trend_against_threshold"
                            )
                            if (
                                reversal_threshold is not None
                                or trend_threshold is not None
                            ):
                                params = defaults.copy()
                                if reversal_threshold is not None:
                                    params["reversal_score_threshold"] = float(
                                        reversal_threshold
                                    )
                                if trend_threshold is not None:
                                    params["trend_against_threshold"] = float(
                                        trend_threshold
                                    )
                                logger.debug(
                                    f"��� ParameterProvider: Smart Close ���-T��-�-��T�T�T� �+��T� {symbol} ({regime}) "
                                    f"���-��T�TǦ��-T� ���� by_symbol: reversal={params['reversal_score_threshold']}, "
                                    f"trend={params['trend_against_threshold']}"
                                )
                                return params

            # ��� �ߦ�ئަ�ئ�զ� 2: exit_params.smart_close.{regime}
            if hasattr(self.config_manager, "_raw_config_dict"):
                config_dict = self.config_manager._raw_config_dict
                exit_params = config_dict.get("exit_params", {})
                if isinstance(exit_params, dict):
                    smart_close_config = exit_params.get("smart_close", {})
                    if isinstance(smart_close_config, dict):
                        regime_config = smart_close_config.get(regime, {})
                        if isinstance(regime_config, dict):
                            reversal_threshold = regime_config.get(
                                "reversal_score_threshold"
                            )
                            trend_threshold = regime_config.get(
                                "trend_against_threshold"
                            )
                            if (
                                reversal_threshold is not None
                                or trend_threshold is not None
                            ):
                                params = defaults.copy()
                                if reversal_threshold is not None:
                                    params["reversal_score_threshold"] = float(
                                        reversal_threshold
                                    )
                                if trend_threshold is not None:
                                    params["trend_against_threshold"] = float(
                                        trend_threshold
                                    )
                                logger.debug(
                                    f"��� ParameterProvider: Smart Close ���-T��-�-��T�T�T� �+��T� {regime} "
                                    f"���-��T�TǦ��-T� ���� exit_params: reversal={params['reversal_score_threshold']}, "
                                    f"trend={params['trend_against_threshold']}"
                                )
                                return params
        except Exception as e:
            logger.debug(
                f"������ ParameterProvider: ��TȦ��-���- ���-��T�TǦ��-��T� Smart Close ���-T��-�-��T�T��-�- �+��T� {symbol or 'default'} ({regime}): {e}"
            )

        # �ߦ- Tæ-�-��TǦ-�-��T� �-�-���-T��-Tɦ-���- T�T¦-�-�+�-T�T¦-T˦� ���-�-TǦ��-��T�
        logger.debug(
            f"��� ParameterProvider: Smart Close ���-T��-�-��T�T�T� �+��T� {regime} - ��T����-��Ț�T�T�T�T�T� default: "
            f"reversal={defaults['reversal_score_threshold']}, trend={defaults['trend_against_threshold']}"
        )
        return defaults

    def get_symbol_params(self, symbol: str) -> Dict[str, Any]:
        """
        �ߦ-��T�TǦ�T�T� ���-T��-�-��T�T�T� �+��T� ���-�-��T���T¦-�-���- T����-�-�-���-.

        Args:
            symbol: ��-T����-�-T˦� T����-�-�-��

        Returns:
            �᦬�-�-�-T�T� T� ���-T��-�-��T�T��-�-�� T����-�-�-���- ���� symbol_profiles
        """
        try:
            return self.config_manager.get_symbol_profile(symbol) or {}
        except Exception as e:
            logger.warning(
                f"������ ParameterProvider: ��TȦ��-���- ���-��T�TǦ��-��T� ���-T��-�-��T�T��-�- T����-�-�-���- {symbol}: {e}"
            )
            return {}

    def get_indicator_params(
        self, symbol: str, regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        �ߦ-��T�TǦ�T�T� ���-T��-�-��T�T�T� ���-�+�����-T¦-T��-�- �+��T� T��������-�-.

        Args:
            symbol: ��-T����-�-T˦� T����-�-�-��
            regime: �দ�����- T�T˦-���-. ��T����� None, �-��T����+����TϦ�T�T�T� �-�-T¦-�-�-T¦�TǦ�T�����

        Returns:
            �᦬�-�-�-T�T� T� ���-T��-�-��T�T��-�-�� ���-�+�����-T¦-T��-�-:
            {
                "rsi_period": int,
                "rsi_overbought": float,
                "rsi_oversold": float,
                "atr_period": int,
                "sma_fast": int,
                "sma_slow": int,
                "ema_fast": int,
                "ema_slow": int,
                ...
            }
        """
        try:
            # �ަ�T����+����TϦ��- T��������- ��T����� �-�� Tæ��-���-�-
            if not regime:
                regime = self._get_current_regime(symbol)

            # �ߦ-��T�TǦ-���- ���-T��-�-��T�T�T� T��������-�-
            regime_params = self.get_regime_params(symbol, regime)

            # �ئ��-�������-���- ���-T��-�-��T�T�T� ���-�+�����-T¦-T��-�-
            indicators = regime_params.get("indicators", {})
            if isinstance(indicators, dict):
                indicators = indicators.copy()
            elif hasattr(indicators, "__dict__"):
                indicators = indicators.__dict__.copy()
            else:
                indicators = {}

            # ��� �ߦ�ئަ�ئ�զ� 2 (29.12.2025): ��T��-�-��T����- by_symbol.{symbol}.indicators �+��T� per-symbol ���-T��-�-��T�T��-�-
            if symbol and hasattr(self.config_manager, "_raw_config_dict"):
                config_dict = self.config_manager._raw_config_dict
                by_symbol = config_dict.get("by_symbol", {})
                symbol_config = by_symbol.get(symbol, {})
                if isinstance(symbol_config, dict):
                    symbol_indicators = symbol_config.get("indicators", {})
                    if isinstance(symbol_indicators, dict):
                        # �ߦ�T����-��T����+����TϦ��- ���-T��-�-��T�T�T� ���� by_symbol (��T����-T���T¦�T� �-T�TȦ� regime)
                        indicators.update(symbol_indicators)
                        logger.debug(
                            f"��� ParameterProvider: �ئ-�+�����-T¦-T�T� �+��T� {symbol} ���-��T�TǦ��-T� ���� by_symbol: "
                            f"{list(symbol_indicators.keys())}"
                        )

            return indicators

        except Exception as e:
            logger.warning(
                f"������ ParameterProvider: ��TȦ��-���- ���-��T�TǦ��-��T� ���-T��-�-��T�T��-�- ���-�+�����-T¦-T��-�- �+��T� {symbol}: {e}"
            )
            return {}

    def get_rsi_thresholds(
        self, symbol: str, regime: Optional[str] = None
    ) -> Dict[str, float]:
        """
        �ߦ-��T�TǦ�T�T� ���-T��-���� RSI �+��T� T��������-�- �� T����-�-�-���-.

        Args:
            symbol: ��-T����-�-T˦� T����-�-�-��
            regime: �দ�����- T�T˦-���-. ��T����� None, �-��T����+����TϦ�T�T�T� �-�-T¦-�-�-T¦�TǦ�T�����

        Returns:
            {
                'overbought': float,
                'oversold': float,
                'period': int
            }
        """
        try:
            indicator_params = self.get_indicator_params(symbol, regime)
            return {
                "overbought": indicator_params.get("rsi_overbought", 70),
                "oversold": indicator_params.get("rsi_oversold", 30),
                "period": indicator_params.get("rsi_period", 14),
            }
        except Exception as e:
            logger.warning(
                f"������ ParameterProvider: ��TȦ��-���- ���-��T�TǦ��-��T� RSI ���-T��-���-�- �+��T� {symbol}: {e}"
            )
            return {"overbought": 70, "oversold": 30, "period": 14}

    def get_module_params(
        self, symbol: str, regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        �ߦ-��T�TǦ�T�T� ���-T��-�-��T�T�T� �-�-�+Tæ����� (TĦ���T�T�T��-�-) �+��T� T��������-�-.

        Args:
            symbol: ��-T����-�-T˦� T����-�-�-��
            regime: �দ�����- T�T˦-���-. ��T����� None, �-��T����+����TϦ�T�T�T� �-�-T¦-�-�-T¦�TǦ�T�����

        Returns:
            �᦬�-�-�-T�T� T� ���-T��-�-��T�T��-�-�� �-�-�+Tæ�����:
            {
                "mtf_block_opposite": bool,
                "mtf_score_bonus": int,
                "correlation_threshold": float,
                "max_correlated_positions": int,
                ...
            }
        """
        try:
            # �ަ�T����+����TϦ��- T��������- ��T����� �-�� Tæ��-���-�-
            if not regime:
                regime = self._get_current_regime(symbol)

            # �ߦ-��T�TǦ-���- ���-T��-�-��T�T�T� T��������-�-
            regime_params = self.get_regime_params(symbol, regime)

            # �ئ��-�������-���- ���-T��-�-��T�T�T� �-�-�+Tæ�����
            modules = regime_params.get("modules", {})
            if isinstance(modules, dict):
                return modules
            elif hasattr(modules, "__dict__"):
                return modules.__dict__
            else:
                return {}

        except Exception as e:
            logger.warning(
                f"������ ParameterProvider: ��TȦ��-���- ���-��T�TǦ��-��T� ���-T��-�-��T�T��-�- �-�-�+Tæ����� �+��T� {symbol}: {e}"
            )
            return {}

    def get_risk_params(
        self, symbol: str, balance: float, regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        �ߦ-��T�TǦ�T�T� ���-T��-�-��T�T�T� Tæ�T��-�-�����-��T� T���T����-�-��.

        Args:
            symbol: ��-T����-�-T˦� T����-�-�-��
            balance: �⦦��T�Tɦ��� �-�-���-�-T�
            regime: �দ�����- T�T˦-���-. ��T����� None, �-��T����+����TϦ�T�T�T� �-�-T¦-�-�-T¦�TǦ�T�����

        Returns:
            �᦬�-�-�-T�T� T� ���-T��-�-��T�T��-�-�� T���T����-:
            {
                "max_margin_per_trade": float,
                "max_daily_loss_percent": float,
                "max_drawdown_percent": float,
                "min_balance_usd": float,
                ...
            }
        """
        try:
            if self.parameter_orchestrator:
                bundle = self._resolve_bundle(
                    symbol=symbol,
                    regime=regime,
                    balance=balance,
                    include_signal=False,
                    include_exit=False,
                    include_order=False,
                    include_risk=True,
                    include_patterns=False,
                )
                if bundle and bundle.risk:
                    return self._bundle_to_dict(bundle.risk)
                if self.strict_mode:
                    return {}
            # �ަ�T����+����TϦ��- T��������- ��T����� �-�� Tæ��-���-�-
            if not regime:
                regime = self._get_current_regime(symbol)

            # �ߦ-��T�TǦ-���- �-�+�-��T¦��-�-T˦� ���-T��-�-��T�T�T� T���T����-
            risk_params = self.config_manager.get_adaptive_risk_params(balance, regime)

            return risk_params

        except Exception as e:
            logger.warning(
                f"������ ParameterProvider: ��TȦ��-���- ���-��T�TǦ��-��T� ���-T��-�-��T�T��-�- T���T����- �+��T� {symbol}: {e}"
            )
            return {}

    def get_trailing_sl_params(
        self, symbol: str, regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        �ߦ-��T�TǦ�T�T� ���-T��-�-��T�T�T� Trailing Stop Loss.

        Args:
            symbol: ��-T����-�-T˦� T����-�-�-��
            regime: �দ�����- T�T˦-���-. ��T����� None, �-��T����+����TϦ�T�T�T� �-�-T¦-�-�-T¦�TǦ�T�����

        Returns:
            �᦬�-�-�-T�T� T� ���-T��-�-��T�T��-�-�� TSL
        """
        try:
            # �ަ�T����+����TϦ��- T��������- ��T����� �-�� Tæ��-���-�-
            if not regime:
                regime = self._get_current_regime(symbol)

            return self.config_manager.get_trailing_sl_params(regime=regime) or {}
        except Exception as e:
            logger.warning(
                f"������ ParameterProvider: ��TȦ��-���- ���-��T�TǦ��-��T� TSL ���-T��-�-��T�T��-�- �+��T� {symbol}: {e}"
            )
            return {}

    def _get_current_regime(self, symbol: str) -> str:
        """
        �ߦ-��T�TǦ�T�T� T¦���T�Tɦ��� T��������- T�T˦-���- �+��T� T����-�-�-���-.

        ��� �ئ�ߦ�ЦҦۦզݦئ� #22 (04.01.2026): �ۦ-����T�Tæ��- fallback T��������- "ranging"
        """
        """
        �ߦ-��T�TǦ�T�T� T¦���T�Tɦ��� T��������- T�T˦-���- �+��T� T����-�-�-���-.

        Args:
            symbol: ��-T����-�-T˦� T����-�-�-��

        Returns:
            �দ�����- T�T˦-���- (trending/ranging/choppy) ������ "ranging" ���- Tæ-�-��TǦ-�-��T�
        """
        try:
            # ��T��-�-Tæ��- ���-��T�TǦ�T�T� ���� DataRegistry (T����-T�T��-�-�-T˦� �-��T¦-�+)
            if self.data_registry:
                regime = self.data_registry.get_regime_name_sync(symbol)
                if regime:
                    return regime.lower()

            # ��T��-�-Tæ��- ���-��T�TǦ�T�T� ���� RegimeManager
            if self.regime_manager:
                regime = self.regime_manager.get_current_regime()
                if regime:
                    return (
                        regime.lower()
                        if isinstance(regime, str)
                        else str(regime).lower()
                    )

        except Exception as e:
            logger.warning(
                f"������ ParameterProvider: ��TȦ��-���- �-��T����+�������-��T� T��������-�- �+��T� {symbol}: {e}"
            )

        # ��� �ئ�ߦ�ЦҦۦզݦئ� #22 (04.01.2026): �ۦ-����T�Tæ��- fallback T��������- "ranging"
        logger.warning(
            f"������ ParameterProvider: �দ�����- �-�� �-��T����+�������- �+��T� {symbol}, ��T����-��Ț�Tæ�T�T�T� fallback 'ranging'"
        )
        return "ranging"

    def _get_default_regime_params(self) -> Dict[str, Any]:
        """
        �ߦ-��T�TǦ�T�T� �+��TĦ-��T¦-T˦� ���-T��-�-��T�T�T� T��������-�-.

        Returns:
            �᦬�-�-�-T�T� T� �+��TĦ-��T¦-T˦-�� ���-T��-�-��T�T��-�-��
        """
        return {
            "min_score_threshold": 2.0,
            "max_trades_per_hour": 10,
            "position_size_multiplier": 1.0,
            "tp_atr_multiplier": 2.0,
            "sl_atr_multiplier": 1.5,
            "max_holding_minutes": 15,
            "cooldown_after_loss_minutes": 5,
        }

    def clear_cache(self, key: Optional[str] = None) -> None:
        """
        ��TǦ�T�T¦�T�T� ��T�T� ���-T��-�-��T�T��-�-.

        Args:
            key: �ڦ�T�T� �+��T� �-TǦ�T�T¦��� (��T����� None - �-TǦ�T�T¦�T�T� �-��T�T� ��T�T�)
        """
        if key:
            self._cache.pop(key, None)
            self._cache_timestamps.pop(key, None)
        else:
            self._cache.clear()
            self._cache_timestamps.clear()
            logger.debug("��� ParameterProvider: ��T�T� �-TǦ�Tɦ��-")

    def get_cached_value(self, key: str) -> Optional[Any]:
        """
        �ߦ-��T�TǦ�T�T� ���-�-TǦ��-���� ���� ��T�TȦ-.

        Args:
            key: �ڦ�T�T� ��T�TȦ-

        Returns:
            �צ-�-TǦ��-���� ���� ��T�TȦ- ������ None
        """
        import time

        if key not in self._cache:
            return None

        cache_time = self._cache_timestamps.get(key, 0)
        current_time = time.time()

        if current_time - cache_time > self._cache_ttl_seconds:
            # ��T�T� T�T�T¦-T�����
            return None

        return self._cache[key]

    def set_cached_value(self, key: str, value: Any) -> None:
        """
        ��-T�T��-�-��T�T� ���-�-TǦ��-���� �- ��T�T�.

        Args:
            key: �ڦ�T�T� ��T�TȦ-
            value: �צ-�-TǦ��-���� �+��T� ��T�TȦ�T��-�-�-�-��T�
        """
        import time

        self._cache[key] = value
        self._cache_timestamps[key] = time.time()

    def _adapt_by_balance(
        self, balance: float, exit_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        ��� �ݦަҦަ� (05.01.2026): �Ц+�-��T¦-TƦ�T� TP/SL ���- �-�-���-�-T�T�.

        Args:
            balance: �⦦��T�Tɦ��� �-�-���-�-T�
            exit_params: �Ѧ-���-�-T˦� ���-T��-�-��T�T�T� �-T�TŦ-�+�-

        Returns:
            �᦬�-�-�-T�T� T� �-�+�-��T¦�T��-�-�-�-�-T˦-�� ���-T��-�-��T�T��-�-�� (��T����� ��T����-���-���-�- �-�+�-��T¦-TƦ�T�)
        """
        # �ߦ-��T�TǦ-���- ���-�-TĦ���T�T��-TƦ�T� �-�+�-��T¦-TƦ���
        adaptive_config = self._get_adaptive_exit_config()

        if not adaptive_config.get("enabled", False):
            return {}

        balance_config = adaptive_config.get("balance_adaptation", {})
        if not balance_config:
            return {}

        # �ަ�T����+����TϦ��- ��T��-TĦ���T� �-�-���-�-T��-
        if balance < 1500:
            profile = "small"
        elif balance < 3500:
            profile = "medium"
        else:
            profile = "large"

        profile_config = balance_config.get(profile, {})
        if not profile_config:
            return {}

        # ��T����-���-TϦ��- �-�-�-����T¦�����
        tp_multiplier = profile_config.get("tp_multiplier", 1.0)
        sl_multiplier = profile_config.get("sl_multiplier", 1.0)

        base_tp = exit_params.get("tp_atr_multiplier", 2.0)
        base_sl = exit_params.get("sl_atr_multiplier", 1.5)

        adapted = {}
        if tp_multiplier != 1.0:
            adapted["tp_atr_multiplier"] = base_tp * tp_multiplier
        if sl_multiplier != 1.0:
            adapted["sl_atr_multiplier"] = base_sl * sl_multiplier

        return adapted

    def _adapt_tp_by_pnl(
        self, current_pnl: float, exit_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        ��� �ݦަҦަ� (05.01.2026): ��-T�TȦ�T����-���� TP ��T��� T�����Ț-�-�- P&L.

        Args:
            current_pnl: �⦦��T�Tɦ��� P&L ���-����TƦ��� �- %
            exit_params: �Ѧ-���-�-T˦� ���-T��-�-��T�T�T� �-T�TŦ-�+�-

        Returns:
            �᦬�-�-�-T�T� T� �-�+�-��T¦�T��-�-�-�-�-T˦- TP (��T����� ��T����-���-���-�- �-�+�-��T¦-TƦ�T�)
        """
        # �ߦ-��T�TǦ-���- ���-�-TĦ���T�T��-TƦ�T� �-�+�-��T¦-TƦ���
        adaptive_config = self._get_adaptive_exit_config()

        if not adaptive_config.get("enabled", False):
            return {}

        pnl_config = adaptive_config.get("pnl_adaptation", {})
        if not pnl_config.get("enabled", False):
            return {}

        base_tp = exit_params.get("tp_atr_multiplier", 2.0)
        extension_threshold = pnl_config.get(
            "extension_threshold", 0.8
        )  # 80% �-T� �-�-���-�-�-���- TP
        max_extension = pnl_config.get("max_extension", 0.5)  # �ܦ-��T� +0.5x
        extension_factor = pnl_config.get(
            "extension_factor", 0.3
        )  # �ڦ-T�T�TĦ�TƦ����-T�

        # ��T����� P&L Tæ��� ��T����-T�T����� ���-T��-�� T��-T�TȦ�T����-��T�
        threshold_pnl = base_tp * extension_threshold
        if current_pnl > threshold_pnl:
            # ��-T�T�TǦ�T�T˦-�-���- T��-T�TȦ�T����-����
            excess_pnl = current_pnl - threshold_pnl
            extension = min(excess_pnl * extension_factor, max_extension)
            new_tp = base_tp + extension

            return {"tp_atr_multiplier": new_tp}

        return {}

    def _adapt_sl_by_drawdown(
        self, drawdown: float, exit_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        ��� �ݦަҦަ� (05.01.2026): �㦦��T�T¦-TǦ��-���� SL ��T��� ��T��-T��-�+����.

        ��-���- 2 - �-Tæ+��T� T����-�������-�-�-�-�- ���-������.

        Args:
            drawdown: �⦦��T�Tɦ-T� ��T��-T��-�+���- �- %
            exit_params: �Ѧ-���-�-T˦� ���-T��-�-��T�T�T� �-T�TŦ-�+�-

        Returns:
            �᦬�-�-�-T�T� T� �-�+�-��T¦�T��-�-�-�-�-T˦- SL (��T����� ��T����-���-���-�- �-�+�-��T¦-TƦ�T�)
        """
        # �ߦ-��T�TǦ-���- ���-�-TĦ���T�T��-TƦ�T� �-�+�-��T¦-TƦ���
        adaptive_config = self._get_adaptive_exit_config()

        if not adaptive_config.get("enabled", False):
            return {}

        drawdown_config = adaptive_config.get("drawdown_adaptation", {})
        if not drawdown_config.get("enabled", False):
            return {}

        base_sl = exit_params.get("sl_atr_multiplier", 1.5)
        tightening_threshold = drawdown_config.get("tightening_threshold", 5.0)  # 5%
        max_tightening = drawdown_config.get("max_tightening", 0.3)  # �ܦ-��T� +0.3x
        tightening_factor = drawdown_config.get(
            "tightening_factor", 0.1
        )  # �ڦ-T�T�TĦ�TƦ����-T�

        # ��T����� ��T��-T��-�+���- > ���-T��-���-, Tæ���T�T¦-TǦ-���- SL
        if drawdown > tightening_threshold:
            excess_drawdown = drawdown - tightening_threshold
            tightening = min(excess_drawdown * tightening_factor, max_tightening)
            new_sl = base_sl + tightening

            return {"sl_atr_multiplier": new_sl}

        return {}

    def _calculate_balance_adaptation_factors(
        self, balance: float
    ) -> tuple[float, float]:
        """
        ��-T�T�TǦ�T¦-T�T� ���-T�T�TĦ�TƦ����-T�T� �-�+�-��T¦-TƦ��� ���- �-�-���-�-T�T� (�����-�-�-�-T� ���-T¦�T����-��T�TƦ�T�).

        ��T����-��Ț�Tæ�T� �����-�����-T�T� ���-T¦�T����-��T�TƦ�T� �-�����+T� ���-T��-���-�-�� �+��T� �����-�-�-�-���- ����T���TŦ-�+�-.

        Returns:
            (tp_factor, sl_factor)
        """
        # �ߦ-T��-���� ���� T¦�T�T¦�T��-�-�-�-��T�
        SMALL_THRESHOLD = 1500  # < $1500 - ���-�-T���T��-�-T¦��-�-T˦�
        LARGE_THRESHOLD = 3500  # >= $3500 - �-��T���T�T����-�-T˦�

        # �ڦ-T�T�TĦ�TƦ����-T�T� �+��T� ���-���+�-���- �+���-���-���-�-�-
        SMALL_TP = (
            0.9  # �ڦ-�-T���T��-�-T¦��-�-T˦� TP �+��T� �-��������T� �-�-���-�-T��-�-
        )
        SMALL_SL = 0.9  # �㦦��T�T¦-TǦ��-�-T˦� SL �+��T� �-��������T� �-�-���-�-T��-�-
        MEDIUM_TP = 1.0  # ��T¦-�-�+�-T�T¦-T˦� TP
        MEDIUM_SL = 1.0  # ��T¦-�-�+�-T�T¦-T˦� SL
        LARGE_TP = 1.1  # �Ц�T���T�T����-�-T˦� TP �+��T� �-T�T��-����T� �-�-���-�-T��-�-
        LARGE_SL = 1.0  # ��T¦-�-�+�-T�T¦-T˦� SL �+��T� �-T�T��-����T� �-�-���-�-T��-�-

        if balance < SMALL_THRESHOLD:
            # ��T� $500 �+�- SMALL_THRESHOLD: ���-T¦�T����-��T�TƦ�T� �-T� ���-�-T���T��-�-T¦��-�-�-���- �� T�T¦-�-�+�-T�T¦-�-�-T�
            if balance <= 500:
                # ��TǦ��-T� �-���������� �-�-���-�-T� - �-�-��T����-�-��Ț-�- ���-�-T���T��-�-T¦��-�-T˦�
                tp_factor = 0.8
                sl_factor = 0.8
            else:
                # �ۦ��-�����-�-T� ���-T¦�T����-��T�TƦ�T� �-T� 0.8 �+�- 0.9
                ratio = (balance - 500) / (SMALL_THRESHOLD - 500)
                tp_factor = 0.8 + (SMALL_TP - 0.8) * ratio
                sl_factor = 0.8 + (SMALL_SL - 0.8) * ratio

        elif balance < LARGE_THRESHOLD:
            # ��T� SMALL_THRESHOLD �+�- LARGE_THRESHOLD: ���-T¦�T����-��T�TƦ�T� �-T� 0.9 �+�- 1.0
            ratio = (balance - SMALL_THRESHOLD) / (LARGE_THRESHOLD - SMALL_THRESHOLD)
            tp_factor = SMALL_TP + (MEDIUM_TP - SMALL_TP) * ratio
            sl_factor = SMALL_SL + (MEDIUM_SL - SMALL_SL) * ratio

        else:
            # ��T� LARGE_THRESHOLD �� �-T�TȦ�: ���-T¦�T����-��T�TƦ�T� �-T� 1.0 �+�- 1.1 (�+�- �-�-���-�-T��- $5000)
            if balance >= 5000:
                tp_factor = LARGE_TP
                sl_factor = LARGE_SL
            else:
                ratio = (balance - LARGE_THRESHOLD) / (5000 - LARGE_THRESHOLD)
                tp_factor = MEDIUM_TP + (LARGE_TP - MEDIUM_TP) * ratio
                sl_factor = MEDIUM_SL + (LARGE_SL - MEDIUM_SL) * ratio

        return tp_factor, sl_factor

    def _calculate_pnl_adaptation_factor(self, current_pnl: float) -> float:
        """
        ��-T�T�TǦ�T¦-T�T� ���-T�T�TĦ�TƦ����-T� �-�+�-��T¦-TƦ��� ���- P&L ���-����TƦ���.

        ��T��� ���-���-����T¦���Ț-�-�- P&L T��-T�TȦ�T�TϦ�T� TP �+��T� ���-TŦ-�-T¦- ��T����-T˦���.
        """
        # ��-T�TȦ�T����-���� TP ��T��� T�����Ț-�-�- ��T��-TĦ�T¦�
        if current_pnl > 5.0:  # > 5%
            extension = min((current_pnl - 5.0) * 0.3, 0.5)  # �ܦ-��T� +0.5x
            return 1.0 + extension
        return 1.0

    def _calculate_drawdown_adaptation_factor(self, drawdown: float) -> float:
        """
        ��-T�T�TǦ�T¦-T�T� ���-T�T�TĦ�TƦ����-T� �-�+�-��T¦-TƦ��� ���- ��T��-T��-�+����.

        ��T��� �-T�T��-���-�� ��T��-T��-�+���� Tæ���T�T¦-TǦ-��T� SL �+��T� ���-Tɦ�T�T� ���-����T¦-���-.
        """
        # �㦦��T�T¦-TǦ��-���� SL ��T��� ��T��-T��-�+����
        if drawdown > 5.0:  # > 5%
            tightening = min((drawdown - 5.0) * 0.1, 0.3)  # �ܦ-��T� +0.3x
            return 1.0 + tightening
        return 1.0

    def _get_adaptive_exit_config(self) -> Dict[str, Any]:
        """
        ��� �ݦަҦަ� (05.01.2026): �ߦ-��T�TǦ�T�T� ���-�-TĦ���T�T��-TƦ�T� �-�+�-��T¦��-�-T�T� ���-T��-�-��T�T��-�- �-T�TŦ-�+�-.

        Returns:
            �᦬�-�-�-T�T� T� ���-�-TĦ���T�T��-TƦ����� �-�+�-��T¦-TƦ���
        """
        try:
            if hasattr(self.config_manager, "_raw_config_dict"):
                config_dict = self.config_manager._raw_config_dict
                return config_dict.get("adaptive_exit_params", {})
        except Exception as e:
            logger.debug(
                f"������ ParameterProvider: ��TȦ��-���- ���-��T�TǦ��-��T� adaptive_exit_params: {e}"
            )

        # �Ҧ-���-T��-Tɦ-���- �+��TĦ-��T¦-T�T� ���-�-TĦ���T�T��-TƦ�T�
        return {
            "enabled": False,  # �ߦ- Tæ-�-��TǦ-�-��T� �-T˦���T�TǦ��-�-
            "balance_adaptation": {
                "small": {"tp_multiplier": 0.9, "sl_multiplier": 0.9},
                "medium": {"tp_multiplier": 1.0, "sl_multiplier": 1.0},
                "large": {"tp_multiplier": 1.1, "sl_multiplier": 1.0},
            },
            "pnl_adaptation": {
                "enabled": True,
                "extension_threshold": 0.8,
                "max_extension": 0.5,
                "extension_factor": 0.3,
            },
            "drawdown_adaptation": {
                "enabled": False,  # ��-���- 2
                "tightening_threshold": 5.0,
                "max_tightening": 0.3,
                "tightening_factor": 0.1,
            },
        }
