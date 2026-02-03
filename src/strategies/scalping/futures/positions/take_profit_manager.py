"""
Take Profit Manager - Управление Take Profit для позиций.

Отвечает за проверку и закрытие позиций по Take Profit.
"""

from typing import Any, Dict, Optional, Tuple

from loguru import logger


class TakeProfitManager:
    """
    Менеджер Take Profit для позиций.

    Проверяет достижение Take Profit и закрывает позиции.
    """

    def __init__(
        self,
        client=None,
        position_registry=None,
        scalping_config=None,
        orchestrator=None,
        close_position_callback=None,
        get_tp_percent_callback=None,  # ✅ НОВОЕ: Callback для получения TP%
    ):
        """
        Инициализация TakeProfitManager.

        Args:
            client: API клиент
            position_registry: Реестр позиций
            scalping_config: Конфигурация скальпинга
            orchestrator: Orchestrator для доступа к другим модулям
            close_position_callback: Callback для закрытия позиции
            get_tp_percent_callback: Callback для получения TP% (из position_manager)
        """
        self.client = client
        self.position_registry = position_registry
        self.scalping_config = scalping_config
        self.orchestrator = orchestrator
        self.close_position_callback = close_position_callback
        self.get_tp_percent_callback = get_tp_percent_callback

    def _get_effective_leverage(
        self, position: Dict[str, Any], metadata: Optional[Any] = None
    ) -> float:
        leverage = None
        if metadata:
            if hasattr(metadata, "leverage") and metadata.leverage:
                leverage = metadata.leverage
            elif isinstance(metadata, dict):
                leverage = metadata.get("leverage")
        if leverage is None and isinstance(position, dict):
            leverage = position.get("lever") or position.get("leverage")
        if leverage is None and self.scalping_config:
            leverage = getattr(self.scalping_config, "leverage", None)
        try:
            leverage = float(leverage)
        except (TypeError, ValueError):
            leverage = None
        if not leverage or leverage <= 0:
            leverage = 1.0
        return max(1.0, leverage)

    def _get_fee_rates(self) -> Tuple[float, float]:
        commission_config = (
            getattr(self.scalping_config, "commission", {})
            if self.scalping_config
            else {}
        )
        maker_fee_rate = None
        taker_fee_rate = None
        trading_fee_rate = None
        if isinstance(commission_config, dict):
            maker_fee_rate = commission_config.get("maker_fee_rate")
            taker_fee_rate = commission_config.get("taker_fee_rate")
            trading_fee_rate = commission_config.get("trading_fee_rate")
        else:
            maker_fee_rate = getattr(commission_config, "maker_fee_rate", None)
            taker_fee_rate = getattr(commission_config, "taker_fee_rate", None)
            trading_fee_rate = getattr(commission_config, "trading_fee_rate", None)

        def _to_float(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        maker_fee_rate = _to_float(maker_fee_rate)
        taker_fee_rate = _to_float(taker_fee_rate)
        trading_fee_rate = _to_float(trading_fee_rate)

        if maker_fee_rate is None and trading_fee_rate is not None:
            maker_fee_rate = trading_fee_rate
        if taker_fee_rate is None:
            if trading_fee_rate is not None:
                if trading_fee_rate > 0.0003:
                    taker_fee_rate = trading_fee_rate / 2.0
                    if maker_fee_rate is None:
                        maker_fee_rate = trading_fee_rate / 2.0
                else:
                    taker_fee_rate = trading_fee_rate

        if maker_fee_rate is None:
            maker_fee_rate = 0.0002
        if taker_fee_rate is None:
            taker_fee_rate = 0.0005
        if taker_fee_rate <= maker_fee_rate:
            taker_fee_rate = max(taker_fee_rate, maker_fee_rate * 2.0)

        return maker_fee_rate, taker_fee_rate

    async def check_tp(
        self, position: Dict[str, Any], current_price: Optional[float] = None
    ) -> bool:
        """
        Проверка Take Profit для позиции.

        Args:
            position: Данные позиции с биржи
            current_price: Текущая цена (опционально)

        Returns:
            True если позиция закрыта по TP, False иначе
        """
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))

            if abs(size) < 1e-8:
                return False

            side = position.get("posSide", "long").lower()
            entry_price = float(position.get("avgPx", "0"))

            # Используем markPx как основную цену для TP (маркировочная цена биржи)
            if current_price is None:
                current_price = float(position.get("markPx", "0"))

            if current_price <= 0 or entry_price <= 0:
                return False

            # Получаем margin и unrealized_pnl для расчета PnL% от маржи
            margin_used = None
            unrealized_pnl = None

            try:
                margin_str = position.get("margin") or position.get("imr") or "0"
                if margin_str and str(margin_str).strip() and str(margin_str) != "0":
                    margin_used = float(margin_str)
                upl_str = position.get("upl") or position.get("unrealizedPnl") or "0"
                if upl_str and str(upl_str).strip() and str(upl_str) != "0":
                    unrealized_pnl = float(upl_str)
            except (ValueError, TypeError):
                pass

            metadata = None
            if self.position_registry:
                try:
                    metadata = await self.position_registry.get_metadata(symbol)
                except Exception:
                    metadata = None

            leverage = self._get_effective_leverage(position, metadata)

            # Рассчитываем PnL% от маржи
            if margin_used and margin_used > 0 and unrealized_pnl is not None:
                pnl_percent = (unrealized_pnl / margin_used) * 100
            else:
                # Fallback: рассчитываем от цены
                if side == "long":
                    pnl_percent = ((current_price - entry_price) / entry_price) * 100
                else:
                    pnl_percent = ((entry_price - current_price) / entry_price) * 100

                # Конвертируем в % от маржи с учетом leverage
                pnl_percent = pnl_percent * leverage

            # Получаем TP из конфига
            regime = position.get("regime") or "ranging"
            tp_percent = self._get_tp_percent(symbol, regime, current_price)

            # ✅ НОВОЕ: Проверка peak_profit - не закрывать если текущая прибыль < 70% от peak
            if pnl_percent > 0 and metadata:  # Only for profitable positions
                peak_profit_usd = 0.0
                if hasattr(metadata, "peak_profit_usd"):
                    peak_profit_usd = metadata.peak_profit_usd
                elif isinstance(metadata, dict):
                    peak_profit_usd = metadata.get("peak_profit_usd", 0.0)

                if peak_profit_usd > 0 and margin_used and margin_used > 0:
                    peak_profit_pct = (peak_profit_usd / margin_used) * 100
                    if pnl_percent < peak_profit_pct * 0.7:
                        logger.info(
                            f"🛡️ TP: Не закрываем {symbol} - "
                            f"текущая прибыль {pnl_percent:.2f}% < 70% от peak {peak_profit_pct:.2f}%"
                        )
                        return False

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (30.12.2025): Проверка min_holding перед закрытием по TP
            # Проверяем время удержания позиции перед закрытием по TP
            from datetime import datetime, timezone

            min_holding_seconds = None
            time_since_open = None

            try:
                # Получаем min_holding_seconds из метаданных позиции
                if metadata:
                    if hasattr(metadata, "min_holding_seconds"):
                        min_holding_seconds = metadata.min_holding_seconds
                    elif isinstance(metadata, dict):
                        min_holding_seconds = metadata.get("min_holding_seconds")

                    # Получаем entry_time из метаданных
                    entry_time = None
                    if hasattr(metadata, "entry_time"):
                        entry_time = metadata.entry_time
                    elif isinstance(metadata, dict):
                        entry_time = metadata.get("entry_time")

                    if entry_time and min_holding_seconds:
                        if isinstance(entry_time, datetime):
                            if entry_time.tzinfo is None:
                                entry_time = entry_time.replace(tzinfo=timezone.utc)
                            time_since_open = (
                                datetime.now(timezone.utc) - entry_time
                            ).total_seconds()
                        elif isinstance(entry_time, (int, float)):
                            # Unix timestamp
                            entry_timestamp = float(entry_time)
                            if entry_timestamp > 1000000000000:  # milliseconds
                                entry_timestamp = entry_timestamp / 1000.0
                            time_since_open = (
                                datetime.now(timezone.utc).timestamp() - entry_timestamp
                            )

                        # Check min_holding
                        if (
                            time_since_open is not None
                            and min_holding_seconds
                            and time_since_open < min_holding_seconds
                        ):
                            logger.debug(
                                f"⏱️ TP заблокирован для {symbol}: "
                                f"время удержания {time_since_open:.1f} сек < {min_holding_seconds:.1f} сек "
                                f"(PnL {pnl_percent:.2f}% >= TP {tp_percent:.2f}%)"
                            )
                            return False  # TP заблокирован из-за min_holding
            except Exception as e:
                logger.debug(f"⚠️ Ошибка проверки min_holding для TP {symbol}: {e}")
                # Продолжаем без проверки min_holding при ошибке

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (03.01.2026): Учитываем комиссии при проверке TP
            # pnl_percent - это Gross PnL (без комиссий), нужно учесть комиссии перед сравнением
            # Получаем комиссию из конфига
            commission_config = getattr(self.scalping_config, "commission", {})
            maker_fee_rate, taker_fee_rate = self._get_fee_rates()

            entry_order_type = None
            if metadata and getattr(metadata, "order_type", None):
                entry_order_type = str(metadata.order_type).lower()
            elif isinstance(metadata, dict) and metadata.get("order_type"):
                entry_order_type = str(metadata.get("order_type")).lower()
            elif isinstance(position, dict) and position.get("order_type"):
                entry_order_type = str(position.get("order_type")).lower()

            if entry_order_type and (
                "limit" in entry_order_type or "post" in entry_order_type
            ):
                entry_fee_rate = maker_fee_rate
            else:
                entry_fee_rate = taker_fee_rate

            exit_fee_rate = taker_fee_rate
            commission_pct_from_margin = (
                (entry_fee_rate + exit_fee_rate) * leverage * 100
            )

            slippage_buffer_pct = 0.15
            tp_buffer_pct = 0.0
            try:
                if isinstance(commission_config, dict):
                    slippage_buffer_pct = float(
                        commission_config.get("slippage_buffer_percent", 0.15) or 0.15
                    )
                    tp_buffer_pct = float(
                        commission_config.get("tp_buffer_percent", 0.0) or 0.0
                    )
                else:
                    slippage_buffer_pct = float(
                        getattr(commission_config, "slippage_buffer_percent", 0.15)
                        or 0.15
                    )
                    tp_buffer_pct = float(
                        getattr(commission_config, "tp_buffer_percent", 0.0) or 0.0
                    )
            except (TypeError, ValueError):
                slippage_buffer_pct = 0.15
                tp_buffer_pct = 0.0

            # Add commissions, slippage and buffer to TP for gross PnL check
            tp_percent_with_commission = (
                tp_percent
                + commission_pct_from_margin
                + slippage_buffer_pct
                + tp_buffer_pct
            )
            if pnl_percent >= tp_percent_with_commission:
                # Проверяем, что Net PnL (после комиссий) положительный
                net_pnl_percent = pnl_percent - commission_pct_from_margin
                if net_pnl_percent > 0:
                    logger.info(
                        f"🎯 TP достигнут для {symbol}: Gross PnL {pnl_percent:.2f}% >= TP {tp_percent:.2f}% + комиссия {commission_pct_from_margin:.2f}% + slippage {slippage_buffer_pct:.2f}% + buffer {tp_buffer_pct:.2f}% = {tp_percent_with_commission:.2f}% (Net PnL: {net_pnl_percent:.2f}%)"
                    )
                else:
                    logger.debug(
                        f"⚠️ TP не закрываем {symbol}: Gross PnL {pnl_percent:.2f}% >= TP с комиссией {tp_percent_with_commission:.2f}%, но Net PnL {net_pnl_percent:.2f}% <= 0"
                    )
                    return False

                # Закрываем позицию
                if self.close_position_callback:
                    await self.close_position_callback(position, "tp")
                    return True
                else:
                    logger.warning(
                        f"⚠️ close_position_callback не установлен для {symbol}"
                    )
                    return False

            return False

        except Exception as e:
            logger.error(f"❌ Ошибка проверки TP для {symbol}: {e}", exc_info=True)
            return False

    def _get_tp_percent(
        self, symbol: str, regime: str, current_price: Optional[float] = None
    ) -> float:
        """
        Получение TP процента из конфига.

        Args:
            symbol: Торговый символ
            regime: Режим рынка
            current_price: Текущая цена (для ATR-based расчета)

        Returns:
            TP процент
        """
        # ✅ РЕФАКТОРИНГ: Используем callback из position_manager если доступен
        if self.get_tp_percent_callback:
            try:
                return self.get_tp_percent_callback(symbol, regime, current_price)
            except Exception as e:
                logger.debug(
                    f"⚠️ Ошибка получения TP% через callback: {e}, используем fallback"
                )

        # Fallback: получаем TP из конфига по режиму
        try:
            if self.scalping_config:
                tp_config = getattr(self.scalping_config, "tp_percent", {})
                if isinstance(tp_config, dict):
                    regime_tp = tp_config.get(regime.lower(), {})
                    if isinstance(regime_tp, dict):
                        symbol_tp = regime_tp.get(symbol, regime_tp.get("default", 2.0))
                        return float(symbol_tp) if symbol_tp else 2.0
                    else:
                        return float(regime_tp) if regime_tp else 2.0
                else:
                    return float(tp_config) if tp_config else 2.0
            return 2.0  # Fallback
        except Exception:
            return 2.0  # Fallback
