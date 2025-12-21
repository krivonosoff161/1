"""
Peak Profit Tracker - Отслеживание максимальной прибыли позиции.

Отвечает за обновление и хранение информации о пиковой прибыли позиции.
"""

from typing import Any, Dict, Optional

from loguru import logger


class PeakProfitTracker:
    """
    Трекер пиковой прибыли позиции.

    Отслеживает максимальную прибыль (peak_profit) для каждой позиции
    и обновляет метаданные.
    """

    def __init__(self, position_registry=None, client=None):
        """
        Инициализация PeakProfitTracker.

        Args:
            position_registry: Реестр позиций для обновления метаданных
            client: API клиент для получения данных позиции
        """
        self.position_registry = position_registry
        self.client = client

    async def update_peak_profit(
        self, position: Dict[str, Any], current_price: Optional[float] = None
    ) -> Optional[float]:
        """
        Обновление пиковой прибыли позиции.

        Args:
            position: Данные позиции с биржи
            current_price: Текущая цена (опционально)

        Returns:
            Обновленное значение peak_profit_usd или None
        """
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))

            if abs(size) < 1e-8:
                return None

            # Получаем текущую цену если не передана
            if current_price is None:
                try:
                    price_limits = await self.client.get_price_limits(symbol)
                    if price_limits:
                        current_price = price_limits.get("current_price", 0)
                except Exception as e:
                    logger.debug(f"⚠️ Не удалось получить цену для {symbol}: {e}")
                    return None

            # ✅ ИСПРАВЛЕНИЕ #2: Проверяем на None перед сравнением
            if current_price is None or current_price <= 0:
                return None

            entry_price = float(position.get("avgPx", "0"))
            if entry_price <= 0:
                return None

            # Определяем направление позиции
            pos_side = position.get("posSide", "long").lower()
            if pos_side not in ["long", "short"]:
                pos_side = "long" if size > 0 else "short"

            # Рассчитываем текущий PnL в USD
            try:
                inst_details = await self.client.get_instrument_details(symbol)
                ct_val = float(inst_details.get("ctVal", 0.01))
                size_in_coins = abs(size) * ct_val

                if pos_side == "long":
                    unrealized_pnl = size_in_coins * (current_price - entry_price)
                else:  # short
                    unrealized_pnl = size_in_coins * (entry_price - current_price)

                # Получаем текущий peak_profit из метаданных
                peak_profit_usd = 0.0
                if self.position_registry:
                    metadata = await self.position_registry.get_metadata(symbol)
                    if metadata:
                        if hasattr(metadata, "peak_profit_usd"):
                            peak_profit_value = metadata.peak_profit_usd
                        elif isinstance(metadata, dict):
                            peak_profit_value = metadata.get("peak_profit_usd", 0.0)
                        else:
                            peak_profit_value = 0.0

                        # ✅ ИСПРАВЛЕНИЕ #2: Приводим к float и проверяем на None
                        if peak_profit_value is not None:
                            try:
                                peak_profit_usd = float(peak_profit_value)
                            except (TypeError, ValueError):
                                peak_profit_usd = 0.0
                        else:
                            peak_profit_usd = 0.0

                # ✅ ИСПРАВЛЕНИЕ #2: Проверяем, что unrealized_pnl не None перед сравнением
                if unrealized_pnl is not None and peak_profit_usd is not None:
                    # Обновляем peak_profit если текущий PnL больше
                    if float(unrealized_pnl) > float(peak_profit_usd):
                        old_peak_profit = peak_profit_usd
                        peak_profit_usd = unrealized_pnl

                        # Обновляем метаданные
                        if self.position_registry:
                            await self.position_registry.update_position(
                                symbol=symbol,
                                metadata_updates={"peak_profit_usd": peak_profit_usd},
                            )

                        logger.debug(
                            f"📈 Peak profit обновлен для {symbol}: ${peak_profit_usd:.2f} "
                            f"(было ${old_peak_profit:.2f}, стало ${unrealized_pnl:.2f})"
                        )

                return peak_profit_usd

            except Exception as e:
                logger.debug(f"⚠️ Ошибка расчета peak_profit для {symbol}: {e}")
                return None

        except Exception as e:
            logger.error(f"❌ Ошибка обновления peak_profit: {e}", exc_info=True)
            return None
