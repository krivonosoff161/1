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
    ):
        """
        Инициализация Trailing Stop Loss.

        Args:
            initial_trail: Начальный трейлинг в % (по умолчанию 0.05%)
            max_trail: Максимальный трейлинг в % (по умолчанию 0.2%)
            min_trail: Минимальный трейлинг в % (по умолчанию 0.02%)
        """
        self.initial_trail = initial_trail
        self.max_trail = max_trail
        self.min_trail = min_trail
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
                profit_pct = (current_price - self.entry_price) / self.entry_price
                self.current_trail = min(
                    self.initial_trail + profit_pct * 2, self.max_trail
                )
                logger.debug(
                    f"Long: новая максимальная цена={current_price:.2f}, "
                    f"трейл={self.current_trail:.2%}, профит={profit_pct:.2%}"
                )
        else:  # short
            # Для шорта отслеживаем минимальную цену
            if current_price < self.lowest_price:
                self.lowest_price = current_price
                # Увеличиваем трейл при падении цены
                profit_pct = (self.entry_price - current_price) / self.entry_price
                self.current_trail = min(
                    self.initial_trail + profit_pct * 2, self.max_trail
                )
                logger.debug(
                    f"Short: новая минимальная цена={current_price:.2f}, "
                    f"трейл={self.current_trail:.2%}, профит={profit_pct:.2%}"
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
            if self.highest_price == 0:
                return self.entry_price * (1 - self.current_trail)
            return self.highest_price * (1 - self.current_trail)
        else:
            # Для шорта стоп-лосс выше минимальной цены
            if self.lowest_price == float("inf"):
                return self.entry_price * (1 + self.current_trail)
            return self.lowest_price * (1 + self.current_trail)

    def get_profit_pct(self, current_price: float) -> float:
        """
        Получение текущей прибыли в процентах.

        Args:
            current_price: Текущая цена

        Returns:
            Прибыль в процентах
        """
        if self.entry_price == 0:
            return 0.0

        if self.side == "long":
            return (current_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - current_price) / self.entry_price

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

    def should_close_position(self, current_price: float) -> bool:
        """
        Проверка, нужно ли закрывать позицию по стоп-лоссу.

        Args:
            current_price: Текущая цена

        Returns:
            True если цена достигла стоп-лосса
        """
        stop_loss = self.get_stop_loss()

        if self.side == "long":
            # Для лонга закрываем если цена упала ниже стоп-лосса
            return current_price <= stop_loss
        else:
            # Для шорта закрываем если цена поднялась выше стоп-лосса
            return current_price >= stop_loss

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
