"""
SmartExitCoordinator - "Умный" координатор закрытия позиций.

Использует индикаторы (RSI, MACD, Bollinger, ADX) для принятия решений о закрытии.
Работает в реальном времени через WebSocket (каждое обновление цены).
"""

from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from ..core.data_registry import DataRegistry
from ..core.position_registry import PositionRegistry


class SmartExitCoordinator:
    """
    "Умный" координатор закрытия позиций.

    Постоянно мониторит открытые позиции через WebSocket и принимает решения
    на основе анализа индикаторов в реальном времени.
    """

    def __init__(
        self,
        position_registry: PositionRegistry,
        data_registry: DataRegistry,
        close_position_callback: Callable[[str, str], Awaitable[None]],
        enabled: bool = True,
    ):
        """
        Инициализация SmartExitCoordinator.

        Args:
            position_registry: Реестр позиций
            data_registry: Реестр данных (индикаторы)
            close_position_callback: Функция для закрытия позиции
            enabled: Включен ли координатор (можно отключить через конфиг)
        """
        self.position_registry = position_registry
        self.data_registry = data_registry
        self.close_position_callback = close_position_callback
        self.enabled = enabled

        logger.info(f"✅ SmartExitCoordinator инициализирован (enabled={enabled})")

    async def check_position(
        self, symbol: str, position: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Проверить позицию с "умным" анализом индикаторов.

        Вызывается из WebSocketCoordinator.handle_ticker_data() для каждой позиции
        при каждом обновлении цены.

        Args:
            symbol: Торговый символ
            position: Данные позиции

        Returns:
            Решение о закрытии или None
        """
        if not self.enabled:
            return None

        try:
            size = float(position.get("pos", "0"))
            if size == 0:
                return None  # Позиция закрыта

            # Получаем рыночные данные и индикаторы
            market_data = await self.data_registry.get_market_data(symbol)
            if not market_data:
                return None  # Нет данных - пропускаем

            indicators = (
                market_data.indicators if hasattr(market_data, "indicators") else {}
            )

            # Получаем направление позиции
            side = position.get("posSide", "long").lower()

            # Применяем "умный" фильтр индикаторов
            should_close = await self._apply_smart_filter(symbol, side, indicators)

            if should_close:
                reason = "smart_indicator_filter"
                logger.info(
                    f"🧠 SmartExitCoordinator: Закрываем {symbol} {side.upper()} "
                    f"по умному фильтру индикаторов"
                )
                await self.close_position_callback(symbol, reason)
                return {"action": "close", "reason": reason}

            return None

        except Exception as e:
            logger.error(
                f"❌ SmartExitCoordinator: Ошибка проверки {symbol}: {e}",
                exc_info=True,
            )
            return None

    async def _apply_smart_filter(
        self, symbol: str, side: str, indicators: Dict[str, Any]
    ) -> bool:
        """
        Применить "умный" фильтр индикаторов.

        Проверяет RSI, MACD, Bollinger Bands для определения разворота тренда.
        Если индикаторы показывают разворот - разрешает закрытие.
        Если индикаторы показывают продолжение тренда - блокирует закрытие.

        Args:
            symbol: Торговый символ
            side: Направление позиции ("long" или "short")
            indicators: Словарь индикаторов

        Returns:
            True если нужно закрыть, False если нет
        """
        try:
            # 1. Проверка RSI - перекупленность/перепроданность
            rsi = indicators.get("RSI") or indicators.get("rsi")
            if rsi and isinstance(rsi, (int, float)):
                if side == "long":
                    if rsi > 70:
                        # LONG позиция, RSI перекуплен - разрешаем закрытие
                        logger.debug(
                            f"📊 SmartExit: {symbol} LONG, RSI={rsi:.1f} перекуплен, "
                            f"разрешаем закрытие"
                        )
                        return True
                    elif rsi < 50:
                        # LONG позиция, RSI не перекуплен - тренд может продолжиться
                        logger.debug(
                            f"📊 SmartExit: {symbol} LONG, RSI={rsi:.1f} не перекуплен, "
                            f"блокируем закрытие (тренд может продолжиться)"
                        )
                        return False  # Блокируем закрытие
                else:  # short
                    if rsi < 30:
                        # SHORT позиция, RSI перепродан - разрешаем закрытие
                        logger.debug(
                            f"📊 SmartExit: {symbol} SHORT, RSI={rsi:.1f} перепродан, "
                            f"разрешаем закрытие"
                        )
                        return True
                    elif rsi > 50:
                        # SHORT позиция, RSI не перепродан - тренд может продолжиться
                        logger.debug(
                            f"📊 SmartExit: {symbol} SHORT, RSI={rsi:.1f} не перепродан, "
                            f"блокируем закрытие (тренд может продолжиться)"
                        )
                        return False  # Блокируем закрытие

            # 2. Проверка MACD - разворот сигнала
            macd = indicators.get("MACD") or indicators.get("macd")
            if macd:
                if isinstance(macd, dict):
                    macd_line = macd.get("macd", 0)
                    signal_line = macd.get("signal", 0)
                else:
                    # Если MACD сохранен как отдельные значения
                    macd_line = indicators.get("macd", 0)
                    signal_line = indicators.get("macd_signal", 0)

                if macd_line and signal_line:
                    if side == "long":
                        if macd_line < signal_line:
                            # LONG позиция, MACD медвежий - разрешаем закрытие
                            logger.debug(
                                f"📊 SmartExit: {symbol} LONG, MACD медвежий "
                                f"(macd={macd_line:.4f} < signal={signal_line:.4f}), "
                                f"разрешаем закрытие"
                            )
                            return True
                        else:
                            # LONG позиция, MACD бычий - тренд может продолжиться
                            logger.debug(
                                f"📊 SmartExit: {symbol} LONG, MACD бычий "
                                f"(macd={macd_line:.4f} > signal={signal_line:.4f}), "
                                f"блокируем закрытие"
                            )
                            return False
                    else:  # short
                        if macd_line > signal_line:
                            # SHORT позиция, MACD бычий - разрешаем закрытие
                            logger.debug(
                                f"📊 SmartExit: {symbol} SHORT, MACD бычий "
                                f"(macd={macd_line:.4f} > signal={signal_line:.4f}), "
                                f"разрешаем закрытие"
                            )
                            return True
                        else:
                            # SHORT позиция, MACD медвежий - тренд может продолжиться
                            logger.debug(
                                f"📊 SmartExit: {symbol} SHORT, MACD медвежий "
                                f"(macd={macd_line:.4f} < signal={signal_line:.4f}), "
                                f"блокируем закрытие"
                            )
                            return False

            # 3. Если индикаторы не блокируют и не разрешают - не закрываем
            # (существующая логика PH/Profit Drawdown продолжает работать)
            return False

        except Exception as e:
            logger.debug(
                f"⚠️ SmartExitCoordinator: Ошибка применения фильтра для {symbol}: {e}"
            )
            return False  # В случае ошибки не закрываем
