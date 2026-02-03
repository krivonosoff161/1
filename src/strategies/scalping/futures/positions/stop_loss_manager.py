"""
Stop Loss Manager - Управление Stop Loss для позиций.

Отвечает за проверку и закрытие позиций по Stop Loss.
"""

from typing import Any, Dict, Optional

from loguru import logger


class StopLossManager:
    """
    Менеджер Stop Loss для позиций.

    Проверяет достижение Stop Loss и закрывает позиции.
    """

    def __init__(
        self,
        client=None,
        position_registry=None,
        scalping_config=None,
        orchestrator=None,
        exit_analyzer=None,
        close_position_callback=None,
        get_sl_percent_callback=None,  # ✅ Новый callback для SL% (из position_manager)
    ):
        """
        Инициализация StopLossManager.

        Args:
            client: API клиент
            position_registry: Реестр позиций
            scalping_config: Конфигурация скальпинга
            orchestrator: Orchestrator для доступа к другим модулям
            exit_analyzer: ExitAnalyzer для проверки разворота
            close_position_callback: Callback для закрытия позиции
        """
        self.client = client
        self.position_registry = position_registry
        self.scalping_config = scalping_config
        self.orchestrator = orchestrator
        self.exit_analyzer = exit_analyzer
        self.close_position_callback = close_position_callback
        self.get_sl_percent_callback = get_sl_percent_callback

    async def check_sl(
        self, position: Dict[str, Any], current_price: Optional[float] = None
    ) -> bool:
        """
        Проверка Stop Loss для позиции.

        Args:
            position: Данные позиции с биржи
            current_price: Текущая цена (опционально)

        Returns:
            True если позиция закрыта по SL, False иначе
        """
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            entry_price = float(position.get("avgPx", "0"))

            # Используем markPx как основную цену для SL (маркировочная цена биржи)
            if current_price is None:
                current_price = float(position.get("markPx", "0"))

            if size == 0 or entry_price == 0 or current_price == 0:
                return False

            # ✅ ИСПРАВЛЕНИЕ #6 (04.01.2026): Параллельная проверка TSL и SL
            # Проверяем TSL и SL параллельно, используя более строгий (ближайший к цене) стоп
            tsl_result = None
            sl_result = None

            # Получаем режим для адаптивного SL
            regime = position.get("regime") or "ranging"
            sl_percent_base = self._get_sl_percent(symbol, regime)

            # Проверяем TSL параллельно
            if self.orchestrator and hasattr(
                self.orchestrator, "trailing_sl_coordinator"
            ):
                try:
                    # Получаем TSL результат через check_position
                    tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(symbol)
                    if tsl and hasattr(tsl, "is_active") and tsl.is_active():
                        # Проверяем TSL loss_cut
                        tsl_loss_cut = getattr(tsl, "loss_cut_percent", None)
                        if tsl_loss_cut is not None:
                            # loss_cut может быть в % (1.5) или в доле (0.015)
                            loss_cut_fraction = (
                                float(tsl_loss_cut) / 100.0
                                if float(tsl_loss_cut) > 1
                                else float(tsl_loss_cut)
                            )
                            # Рассчитываем TSL stop price
                            position_side = position.get("posSide", "long").lower()
                            if position_side == "long":
                                tsl_stop_price = entry_price * (1 - loss_cut_fraction)
                                tsl_triggered = current_price <= tsl_stop_price
                            else:
                                tsl_stop_price = entry_price * (1 + loss_cut_fraction)
                                tsl_triggered = current_price >= tsl_stop_price

                            if tsl_triggered:
                                tsl_result = {
                                    "should_close": True,
                                    "stop_price": tsl_stop_price,
                                    "reason": "tsl_loss_cut",
                                    "loss_cut_percent": tsl_loss_cut,
                                }
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка проверки TSL для {symbol}: {e}")

            # Проверяем статический SL параллельно
            try:
                position_side = position.get("posSide", "long").lower()
                if position_side == "long":
                    sl_stop_price = entry_price * (1 - sl_percent_base / 100.0)
                    sl_triggered = current_price <= sl_stop_price
                else:
                    sl_stop_price = entry_price * (1 + sl_percent_base / 100.0)
                    sl_triggered = current_price >= sl_stop_price

                if sl_triggered:
                    sl_result = {
                        "should_close": True,
                        "stop_price": sl_stop_price,
                        "reason": "static_sl",
                        "sl_percent": sl_percent_base,
                    }
            except Exception as e:
                logger.debug(f"⚠️ Ошибка проверки статического SL для {symbol}: {e}")

            # Используем более строгий (ближайший к цене) стоп
            if tsl_result and sl_result:
                position_side = position.get("posSide", "long").lower()
                if position_side == "long":
                    # Для лонга используем более высокий стоп (более строгий)
                    use_tsl = tsl_result["stop_price"] > sl_result["stop_price"]
                else:
                    # Для шорта используем более низкий стоп (более строгий)
                    use_tsl = tsl_result["stop_price"] < sl_result["stop_price"]

                selected_result = tsl_result if use_tsl else sl_result
                logger.debug(
                    f"🔒 SL+TSL для {symbol}: TSL stop={tsl_result['stop_price']:.2f}, "
                    f"SL stop={sl_result['stop_price']:.2f}, используем {'TSL' if use_tsl else 'SL'}"
                )
            else:
                selected_result = tsl_result or sl_result

            # Если выбран результат для закрытия, закрываем позицию
            if selected_result and selected_result.get("should_close"):
                logger.warning(
                    f"🚨 {selected_result['reason'].upper()} сработал для {symbol}: "
                    f"цена={current_price:.2f}, stop={selected_result['stop_price']:.2f}"
                )
                if self.close_position_callback:
                    await self.close_position_callback(
                        position, selected_result["reason"]
                    )
                    return True
                else:
                    logger.warning(
                        f"⚠️ close_position_callback не установлен для {symbol}"
                    )
                    return False

            # ✅ ИСПРАВЛЕНИЕ #5 (04.01.2026): Проверка min_hold_seconds_before_sl
            # Проверяем время удержания позиции перед закрытием по SL
            import time
            from datetime import datetime, timezone

            time_since_open = None
            try:
                entry_time = position.get("entry_time")
                if entry_time:
                    if isinstance(entry_time, datetime):
                        if entry_time.tzinfo is None:
                            entry_time = entry_time.replace(tzinfo=timezone.utc)
                        time_since_open = (
                            datetime.now(timezone.utc) - entry_time
                        ).total_seconds()
                    elif isinstance(entry_time, (int, float)):
                        # Unix timestamp
                        if entry_time > 1000000000000:  # milliseconds
                            entry_time = entry_time / 1000.0
                        time_since_open = time.time() - entry_time
            except Exception as e:
                logger.debug(
                    f"⚠️ Ошибка расчета времени удержания для SL проверки {symbol}: {e}"
                )

            # Получаем min_hold_seconds из metadata
            min_hold_seconds_before_sl = 30.0  # Fallback
            if self.position_registry:
                try:
                    metadata = await self.position_registry.get_metadata(symbol)
                    if metadata and metadata.min_holding_seconds:
                        min_hold_seconds_before_sl = metadata.min_holding_seconds
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка получения min_holding_seconds для {symbol}: {e}"
                    )

            # Если TSL или SL сработали, проверяем min_hold_seconds
            if selected_result and selected_result.get("should_close"):
                if (
                    time_since_open is not None
                    and time_since_open < min_hold_seconds_before_sl
                ):
                    logger.debug(
                        f"⏱️ {selected_result['reason'].upper()} заблокирован для {symbol}: "
                        f"позиция открыта {time_since_open:.1f} сек < {min_hold_seconds_before_sl:.1f} сек "
                        f"(защита от преждевременного закрытия)"
                    )
                    return False
                # Если min_hold_seconds пройден, закрываем (уже обработано выше)
                return True

            # Если ни TSL, ни SL не сработали, продолжаем проверку PnL для статического SL
            # (на случай если TSL не активен)
            sl_percent = sl_percent_base

            # Рассчитываем PnL% от маржи
            try:
                margin_used = float(position.get("margin", 0))
                if margin_used > 0:
                    try:
                        inst_details = await self.client.get_instrument_details(symbol)
                        ct_val = float(inst_details.get("ctVal", 0.01))
                        size_in_coins = abs(size) * ct_val
                    except Exception:
                        size_in_coins = abs(size)

                    position_side = position.get("posSide", "long").lower()
                    if position_side == "long":
                        unrealized_pnl = size_in_coins * (current_price - entry_price)
                    else:
                        unrealized_pnl = size_in_coins * (entry_price - current_price)

                    pnl_percent_from_margin = (unrealized_pnl / margin_used) * 100

                    # ✅ Проверяем SL
                    if pnl_percent_from_margin <= -sl_percent:
                        # ✅ НОВОЕ: Проверяем разворот перед закрытием по SL
                        reversal_detected = False
                        if self.exit_analyzer:
                            position_side = position.get("posSide", "long").lower()
                            try:
                                reversal_detected = (
                                    await self.exit_analyzer._check_reversal_signals(
                                        symbol, position_side
                                    )
                                )
                                if reversal_detected:
                                    logger.info(
                                        f"🔄 SL: Обнаружен разворот для {symbol} {position_side.upper()}, "
                                        f"но PnL={pnl_percent_from_margin:.2f}% <= -{sl_percent:.2f}% - "
                                        f"закрываем по SL"
                                    )
                            except Exception as e:
                                logger.debug(f"⚠️ Ошибка проверки разворота: {e}")

                        logger.warning(
                            f"🚨 SL сработал для {symbol}: "
                            f"PnL={pnl_percent_from_margin:.2f}% <= -{sl_percent:.2f}%"
                        )

                        # Закрываем позицию
                        if self.close_position_callback:
                            await self.close_position_callback(position, "sl")
                            return True
                        else:
                            logger.warning(
                                f"⚠️ close_position_callback не установлен для {symbol}"
                            )
                            return False
            except Exception as e:
                logger.debug(
                    f"⚠️ margin_used=0 для {symbol}, пропускаем проверку SL: {e}"
                )

            return False

        except Exception as e:
            logger.error(f"❌ Ошибка проверки SL для {symbol}: {e}", exc_info=True)
            return False

    def _get_sl_percent(self, symbol: str, regime: str) -> float:
        """
        Получение SL процента из конфига.

        Args:
            symbol: Торговый символ
            regime: Режим рынка

        Returns:
            SL процент
        """
        if self.get_sl_percent_callback:
            try:
                return float(self.get_sl_percent_callback(symbol, regime))
            except Exception as e:
                logger.debug(
                    f"⚠️ Ошибка получения SL% через callback: {e}, используем fallback"
                )
        try:
            # Получаем SL из конфига по режиму
            if self.scalping_config:
                sl_config = getattr(self.scalping_config, "sl_percent", {})
                if isinstance(sl_config, dict):
                    regime_sl = sl_config.get(regime.lower(), {})
                    if isinstance(regime_sl, dict):
                        symbol_sl = regime_sl.get(symbol, regime_sl.get("default", 1.0))
                        return float(symbol_sl) if symbol_sl else 1.0
                    else:
                        return float(regime_sl) if regime_sl else 1.0
                else:
                    return float(sl_config) if sl_config else 1.0
            return 1.0  # Fallback
        except Exception:
            return 1.0  # Fallback
