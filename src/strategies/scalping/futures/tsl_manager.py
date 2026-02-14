"""
TSL Manager для Futures торговли.

Управляет Trailing Stop Loss для всех позиций:
- Создание TSL для новых позиций
- Обновление TSL
- Проверка триггеров закрытия
- Интеграция с ConfigManager
"""

from typing import Any, Dict, Optional, Tuple

from loguru import logger

from .indicators.trailing_stop_loss import TrailingStopLoss


class TSLManager:
    """
    Менеджер Trailing Stop Loss для Futures.

    Централизует управление TSL для всех позиций.
    """

    def __init__(self, config_manager):
        """
        Args:
            config_manager: ConfigManager для получения параметров
        """
        self.config_manager = config_manager
        self.trailing_sl_by_symbol: Dict[str, TrailingStopLoss] = {}

        logger.info("✅ TSLManager initialized")

    def create_tsl_for_position(
        self,
        symbol: str,
        entry_price: float,
        side: str,
        regime: Optional[str] = None,
        leverage: float = 1.0,
    ) -> TrailingStopLoss:
        """
        Создать TSL для новой позиции.

        Args:
            symbol: Торговый символ
            entry_price: Цена входа
            side: Сторона позиции (long/short)
            regime: Режим рынка (опционально)
            leverage: Плечо

        Returns:
            TrailingStopLoss: Созданный TSL объект
        """
        # Получаем параметры TSL из конфига
        tsl_params = self.config_manager.get_trailing_sl_params(regime)
        maker_fee_rate = tsl_params.get("maker_fee_rate")
        taker_fee_rate = tsl_params.get("taker_fee_rate")
        trading_fee_rate = tsl_params.get("trading_fee_rate", maker_fee_rate)

        # Создаем TSL
        tsl = TrailingStopLoss(
            initial_trail=tsl_params.get("initial_trail", 0.005),
            max_trail=tsl_params.get("max_trail", 0.01),
            min_trail=tsl_params.get("min_trail", 0.003),
            trading_fee_rate=trading_fee_rate,
            maker_fee_rate=maker_fee_rate,
            taker_fee_rate=taker_fee_rate,
            loss_cut_percent=tsl_params.get("loss_cut_percent"),
            timeout_loss_percent=tsl_params.get("timeout_loss_percent"),
            timeout_minutes=tsl_params.get("timeout_minutes"),
            min_holding_minutes=tsl_params.get("min_holding_minutes"),
            min_profit_to_close=tsl_params.get("min_profit_to_close"),
            min_profit_for_extension=tsl_params.get("min_profit_for_extension"),
            extend_time_on_profit=tsl_params.get("extend_time_on_profit", False),
            extend_time_multiplier=tsl_params.get("extend_time_multiplier", 1.0),
            leverage=leverage,
            min_critical_hold_seconds=tsl_params.get("min_critical_hold_seconds", 30.0),
            trail_growth_low_multiplier=tsl_params.get(
                "trail_growth_low_multiplier", 1.5
            ),
            trail_growth_medium_multiplier=tsl_params.get(
                "trail_growth_medium_multiplier", 2.0
            ),
            trail_growth_high_multiplier=tsl_params.get(
                "trail_growth_high_multiplier", 3.0
            ),
        )

        # Инициализируем TSL
        tsl.start(entry_price, side)

        # Сохраняем в словарь
        self.trailing_sl_by_symbol[symbol] = tsl

        logger.info(
            f"✅ TSL created for {symbol}: "
            f"side={side}, entry=${entry_price:.4f}, "
            f"trail={tsl.initial_trail:.2%}"
        )

        return tsl

    def get_tsl(self, symbol: str) -> Optional[TrailingStopLoss]:
        """
        Получить TSL для символа.

        Args:
            symbol: Торговый символ

        Returns:
            TrailingStopLoss или None
        """
        return self.trailing_sl_by_symbol.get(symbol)

    def has_tsl(self, symbol: str) -> bool:
        """
        Проверить наличие TSL для символа.

        Args:
            symbol: Торговый символ

        Returns:
            bool: True если TSL существует
        """
        return symbol in self.trailing_sl_by_symbol

    def remove_tsl(self, symbol: str) -> Optional[TrailingStopLoss]:
        """
        Удалить TSL для символа.

        Args:
            symbol: Торговый символ

        Returns:
            TrailingStopLoss: Удаленный TSL или None
        """
        tsl = self.trailing_sl_by_symbol.pop(symbol, None)
        if tsl:
            logger.debug(f"✅ TSL removed for {symbol}")
        return tsl

    def update_tsl(self, symbol: str, current_price: float) -> Optional[float]:
        """
        Обновить TSL для символа.

        Args:
            symbol: Торговый символ
            current_price: Текущая цена

        Returns:
            Optional[float]: Новый stop_loss уровень или None
        """
        tsl = self.get_tsl(symbol)
        if not tsl:
            logger.warning(f"⚠️ TSL not found for {symbol}")
            return None

        # Обновляем TSL
        new_stop_loss = tsl.update(current_price)

        if new_stop_loss:
            logger.debug(
                f"🔄 TSL updated for {symbol}: "
                f"price=${current_price:.4f}, "
                f"new_sl=${new_stop_loss:.4f}"
            )

        return new_stop_loss

    async def check_should_close(
        self, symbol: str, current_price: float, **kwargs
    ) -> Tuple[bool, Optional[str]]:
        """
        Проверить нужно ли закрывать позицию по TSL (асинхронно).

        Args:
            symbol: Торговый символ
            current_price: Текущая цена
            **kwargs: дополнительные параметры для логики TSL

        Returns:
            Tuple[bool, Optional[str]]: (True, причина_закрытия) если нужно закрыть, (False, None) если нет
        """
        tsl = self.get_tsl(symbol)
        if not tsl:
            return (False, None)

        if current_price is None or float(current_price) <= 0:
            logger.warning(
                f"⚠️ TSLManager: пропуск проверки закрытия для {symbol} из-за невалидной цены ({current_price})"
            )
            return (False, None)

        # Вызов асинхронной логики TrailingStopLoss
        if hasattr(tsl, "should_close_position"):
            # Если should_close_position асинхронная
            result = tsl.should_close_position(current_price, **kwargs)
            if hasattr(result, "__await__"):
                return await result
            else:
                return result
        else:
            # Fallback: старый синхронный метод
            closed = tsl.should_close(current_price)
            return (closed, "legacy")

    def get_all_tsl(self) -> Dict[str, TrailingStopLoss]:
        """
        Получить все TSL.

        Returns:
            Dict: Словарь всех TSL по символам
        """
        return self.trailing_sl_by_symbol.copy()

    def get_tsl_count(self) -> int:
        """
        Получить количество активных TSL.

        Returns:
            int: Количество TSL
        """
        return len(self.trailing_sl_by_symbol)

    def get_tsl_stats(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получить статистику TSL для символа.

        Args:
            symbol: Торговый символ

        Returns:
            Dict: Статистика TSL или None
        """
        tsl = self.get_tsl(symbol)
        if not tsl:
            return None

        return {
            "symbol": symbol,
            "side": tsl.side,
            "entry_price": tsl.entry_price,
            "current_trail": tsl.current_trail,
            "highest_price": tsl.highest_price,
            "lowest_price": tsl.lowest_price,
            "initial_trail": tsl.initial_trail,
            "max_trail": tsl.max_trail,
            "min_trail": tsl.min_trail,
        }

    def clear_all_tsl(self) -> int:
        """
        Очистить все TSL.

        Returns:
            int: Количество удаленных TSL
        """
        count = len(self.trailing_sl_by_symbol)
        self.trailing_sl_by_symbol.clear()
        logger.info(f"✅ Cleared {count} TSL instances")
        return count
