"""
Take Profit Manager - Управление Take Profit для позиций.

Отвечает за проверку и закрытие позиций по Take Profit.
"""

from typing import Any, Dict, Optional

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
                leverage = getattr(self.scalping_config, "leverage", 5) or 5
                pnl_percent = pnl_percent * leverage

            # Получаем TP из конфига
            regime = position.get("regime") or "ranging"
            tp_percent = self._get_tp_percent(symbol, regime, current_price)

            # ✅ НОВОЕ: Проверка peak_profit - не закрывать если текущая прибыль < 70% от peak
            if pnl_percent > 0:  # Только для прибыльных позиций
                if self.position_registry:
                    metadata = await self.position_registry.get_metadata(symbol)
                    if metadata:
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
                                return False  # Не закрываем

            # Проверяем достижение TP
            if pnl_percent >= tp_percent:
                logger.info(
                    f"🎯 TP достигнут для {symbol}: {pnl_percent:.2f}% >= {tp_percent:.2f}%"
                )

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

