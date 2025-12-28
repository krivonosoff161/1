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

            # Получаем текущую цену
            if current_price is None:
                try:
                    price_limits = await self.client.get_price_limits(symbol)
                    if price_limits:
                        current_price = price_limits.get("current_price", 0)
                    else:
                        current_price = float(position.get("markPx", "0"))
                except Exception:
                    current_price = float(position.get("markPx", "0"))

            if size == 0 or entry_price == 0 or current_price == 0:
                return False

            # ✅ Проверяем только если TSL не активен
            if self.orchestrator:
                if hasattr(self.orchestrator, "trailing_sl_coordinator"):
                    tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(symbol)
                    if tsl:
                        return False  # TSL активен - проверка SL не нужна

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Защита от преждевременного закрытия
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

            # Минимальное время удержания перед закрытием по SL (30 секунд)
            min_hold_seconds_before_sl = 30.0
            if (
                time_since_open is not None
                and time_since_open < min_hold_seconds_before_sl
            ):
                logger.debug(
                    f"⏱️ SL проверка для {symbol}: позиция открыта {time_since_open:.1f} сек назад < {min_hold_seconds_before_sl} сек, "
                    f"пропускаем проверку SL (защита от преждевременного закрытия)"
                )
                return False

            # Получаем режим для адаптивного SL
            regime = position.get("regime") or "ranging"
            sl_percent = self._get_sl_percent(symbol, regime)

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
