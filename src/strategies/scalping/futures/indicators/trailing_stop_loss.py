"""
Trailing Stop Loss для Futures торговли.

Динамически подстраивает стоп-лосс под движение цены,
захватывая большую прибыль от волатильности.
"""

from typing import Optional

from loguru import logger


class TrailingStopLoss:
    """
    Динамический стоп-лосс для Futures.

    Подстраивает стоп-лосс под движение цены:
    - Для лонга: движется вверх с ценой
    - Для шорта: движется вниз с ценой
    - Защищает прибыль при разворотах

    Attributes:
        initial_trail: Начальный трейлинг в процентах
        max_trail: Максимальный трейлинг в процентах
        min_trail: Минимальный трейлинг в процентах
        highest_price: Максимальная цена (для лонга)
        lowest_price: Минимальная цена (для шорта)
        current_trail: Текущий трейлинг
    """

    def __init__(
        self,
        initial_trail: float = 0.05,
        max_trail: float = 0.2,
        min_trail: float = 0.02,
        trading_fee_rate: float = 0.001,  # 0.1% на круг (0.05% вход + 0.05% выход для taker)
    ):
        """
        Инициализация Trailing Stop Loss.

        Args:
            initial_trail: Начальный трейлинг в % (по умолчанию 0.05%)
            max_trail: Максимальный трейлинг в % (по умолчанию 0.2%)
            min_trail: Минимальный трейлинг в % (по умолчанию 0.02%)
            trading_fee_rate: Комиссия на круг (открытие + закрытие) в долях (0.001 = 0.1%)
        """
        self.initial_trail = initial_trail
        self.max_trail = max_trail
        self.min_trail = min_trail
        self.trading_fee_rate = (
            trading_fee_rate  # Комиссия на весь цикл (открытие + закрытие)
        )
        self.current_trail = initial_trail
        self.highest_price = 0.0
        self.lowest_price = float("inf")
        self.entry_price = 0.0
        self.side = None

    def initialize(self, entry_price: float, side: str):
        """
        Инициализация трейлинг стопа для позиции.

        Args:
            entry_price: Цена входа
            side: Сторона позиции ("long" или "short")
        """
        self.entry_price = entry_price
        self.side = side
        self.current_trail = self.initial_trail

        if side == "long":
            self.highest_price = entry_price
            self.lowest_price = float("inf")
        else:  # short
            self.highest_price = 0.0
            self.lowest_price = entry_price

        logger.info(
            f"TrailingStopLoss инициализирован: entry={entry_price}, "
            f"side={side}, trail={self.current_trail:.2%}"
        )

    def update(self, current_price: float) -> Optional[float]:
        """
        Обновление трейлинга и расчет нового стоп-лосса.

        Args:
            current_price: Текущая цена актива

        Returns:
            Новый стоп-лосс или None если не нужно менять
        """
        if self.side is None or self.entry_price == 0:
            return None

        old_stop_loss = self.get_stop_loss()

        # Обновление экстремумов и трейлинга
        if self.side == "long":
            # Для лонга отслеживаем максимальную цену
            if current_price > self.highest_price:
                self.highest_price = current_price
                # Увеличиваем трейл при росте цены
                # ⚠️ ИСПРАВЛЕНИЕ: Используем прибыль С УЧЕТОМ КОМИССИИ для расчета трейла!
                profit_pct = self.get_profit_pct(current_price, include_fees=True)
                self.current_trail = min(
                    self.initial_trail + profit_pct * 2, self.max_trail
                )
                logger.debug(
                    f"Long: новая максимальная цена={current_price:.2f}, "
                    f"трейл={self.current_trail:.2%}, профит={profit_pct:.2%} (net с комиссией)"
                )
        else:  # short
            # Для шорта отслеживаем минимальную цену
            if current_price < self.lowest_price:
                self.lowest_price = current_price
                # Увеличиваем трейл при падении цены
                # ⚠️ ИСПРАВЛЕНИЕ: Используем прибыль С УЧЕТОМ КОМИССИИ для расчета трейла!
                profit_pct = self.get_profit_pct(current_price, include_fees=True)
                self.current_trail = min(
                    self.initial_trail + profit_pct * 2, self.max_trail
                )
                logger.debug(
                    f"Short: новая минимальная цена={current_price:.2f}, "
                    f"трейл={self.current_trail:.2%}, профит={profit_pct:.2%} (net с комиссией)"
                )

        new_stop_loss = self.get_stop_loss()

        # Возвращаем новый стоп-лосс только если он изменился
        if new_stop_loss != old_stop_loss:
            logger.info(
                f"Новый стоп-лосс: {old_stop_loss:.2f} → {new_stop_loss:.2f} "
                f"(трейл={self.current_trail:.2%})"
            )
            return new_stop_loss

        return None

    def get_stop_loss(self) -> float:
        """
        Получение текущего стоп-лосса.

        Returns:
            Текущая цена стоп-лосса
        """
        if self.side is None or self.entry_price == 0:
            return 0.0

        if self.side == "long":
            # Для лонга стоп-лосс ниже максимальной цены
            # ⚠️ ИСПРАВЛЕНИЕ: highest_price не должна быть 0 для лонга после initialize
            # Используем max(highest_price, entry_price) для безопасности
            effective_highest = (
                max(self.highest_price, self.entry_price)
                if self.highest_price > 0
                else self.entry_price
            )
            return effective_highest * (1 - self.current_trail)
        else:
            # Для шорта стоп-лосс выше минимальной цены
            # Используем min(lowest_price, entry_price) для безопасности
            effective_lowest = (
                min(self.lowest_price, self.entry_price)
                if self.lowest_price < float("inf")
                else self.entry_price
            )
            return effective_lowest * (1 + self.current_trail)

    def get_profit_pct(self, current_price: float, include_fees: bool = True) -> float:
        """
        Получение текущей прибыли в процентах с учетом комиссии.

        Args:
            current_price: Текущая цена
            include_fees: Учитывать ли комиссию при расчете прибыли (по умолчанию True)

        Returns:
            Прибыль в процентах (с учетом комиссии, если include_fees=True)
        """
        if self.entry_price == 0:
            return 0.0

        # Базовая прибыль без комиссии
        if self.side == "long":
            gross_profit_pct = (current_price - self.entry_price) / self.entry_price
        else:
            gross_profit_pct = (self.entry_price - current_price) / self.entry_price

        # Вычитаем комиссию (открытие + закрытие)
        if include_fees:
            net_profit_pct = gross_profit_pct - self.trading_fee_rate
            return net_profit_pct
        else:
            return gross_profit_pct

    def get_distance_to_stop_pct(self, current_price: float) -> float:
        """
        Получение расстояния до стоп-лосса в процентах.

        Args:
            current_price: Текущая цена

        Returns:
            Расстояние до стоп-лосса в процентах
        """
        stop_loss = self.get_stop_loss()

        if self.side == "long":
            return (current_price - stop_loss) / current_price
        else:
            return (stop_loss - current_price) / current_price

    def should_close_position(
        self,
        current_price: float,
        min_profit_pct: Optional[float] = None,
        trend_strength: Optional[float] = None,
        market_regime: Optional[str] = None,
    ) -> bool:
        """
        Проверка, нужно ли закрывать позицию по стоп-лоссу.

        ⚠️ УЛУЧШЕННАЯ ЛОГИКА: Учитывает PnL и тренд
        - Если позиция в прибыли и идет тренд, даем больше места для отката
        - Если позиция в убытке, закрываем строже

        Args:
            current_price: Текущая цена
            min_profit_pct: Минимальный % прибыли для удержания позиции (если указан)
            trend_strength: Сила тренда 0-1 (если указан, >0.7 = сильный тренд)
            market_regime: Режим рынка ("trending", "ranging", "choppy")

        Returns:
            True если цена достигла стоп-лосса
        """
        stop_loss = self.get_stop_loss()
        # ⚠️ ИСПРАВЛЕНИЕ: Используем прибыль С УЧЕТОМ КОМИССИИ!
        profit_pct = self.get_profit_pct(current_price, include_fees=True)

        # Базовая проверка стоп-лосса
        if self.side == "long":
            price_hit_sl = current_price <= stop_loss
        else:  # short
            price_hit_sl = current_price >= stop_loss

        if not price_hit_sl:
            return False  # Цена не достигла стоп-лосса - не закрываем

        # ⚠️ АДАПТИВНАЯ ЛОГИКА: Если позиция в прибыли и идет тренд/режим - даем больше места
        if profit_pct > 0:
            # Определяем множитель адаптации на основе режима и тренда
            regime_multiplier = 1.0
            if market_regime == "trending":
                # В тренде даем больше места для отката
                regime_multiplier = 1.5
            elif market_regime == "ranging":
                # В боковике стандартно
                regime_multiplier = 1.0
            elif market_regime == "choppy":
                # В хаосе даем меньше места (строже)
                regime_multiplier = 0.8

            # Если есть сильный тренд - дополнительный буст
            if trend_strength and trend_strength > 0.7:
                regime_multiplier *= 1.3  # Дополнительный буст при сильном тренде

            # Позиция в прибыли и (сильный тренд или trending режим) - даем больше места
            if regime_multiplier > 1.0 or (trend_strength and trend_strength > 0.7):
                # Даем больше места для отката
                adjusted_trail = min(
                    self.current_trail * regime_multiplier, self.max_trail
                )
                if self.side == "long":
                    effective_highest = (
                        max(self.highest_price, self.entry_price)
                        if self.highest_price > 0
                        else self.entry_price
                    )
                    adjusted_stop = effective_highest * (1 - adjusted_trail)
                    # Не закрываем если цена выше скорректированного стопа
                    if current_price > adjusted_stop:
                        profit_gross = self.get_profit_pct(
                            current_price, include_fees=False
                        )
                        logger.debug(
                            f"📈 LONG: Позиция в прибыли (net={profit_pct:.2%}, gross={profit_gross:.2%}), "
                            f"режим={market_regime or 'N/A'}, тренд={trend_strength:.2f if trend_strength else 'N/A'} - "
                            f"даем больше места: stop={adjusted_stop:.2f} vs текущий={current_price:.2f}"
                        )
                        return False
                else:  # short
                    effective_lowest = (
                        min(self.lowest_price, self.entry_price)
                        if self.lowest_price < float("inf")
                        else self.entry_price
                    )
                    adjusted_stop = effective_lowest * (1 + adjusted_trail)
                    # Не закрываем если цена ниже скорректированного стопа
                    if current_price < adjusted_stop:
                        profit_gross = self.get_profit_pct(
                            current_price, include_fees=False
                        )
                        logger.debug(
                            f"📈 SHORT: Позиция в прибыли (net={profit_pct:.2%}, gross={profit_gross:.2%}), "
                            f"режим={market_regime or 'N/A'}, тренд={trend_strength:.2f if trend_strength else 'N/A'} - "
                            f"даем больше места: stop={adjusted_stop:.2f} vs текущий={current_price:.2f}"
                        )
                        return False

        # Если позиция в убытке - закрываем строже (обычная логика)
        if profit_pct <= 0:
            logger.debug(
                f"⚠️ Позиция в убытке ({profit_pct:.2%}) - закрываем по стоп-лоссу: "
                f"stop={stop_loss:.2f}, price={current_price:.2f}"
            )

        return True  # Закрываем по стоп-лоссу

    def reset(self):
        """Сброс всех данных трейлинга."""
        self.highest_price = 0.0
        self.lowest_price = float("inf")
        self.current_trail = self.initial_trail
        self.entry_price = 0.0
        self.side = None
        logger.info("TrailingStopLoss сброшен")

    def __repr__(self) -> str:
        """Строковое представление трейлинга."""
        return (
            f"TrailingStopLoss("
            f"side={self.side}, "
            f"entry={self.entry_price:.2f}, "
            f"trail={self.current_trail:.2%}, "
            f"stop={self.get_stop_loss():.2f}"
            f")"
        )
