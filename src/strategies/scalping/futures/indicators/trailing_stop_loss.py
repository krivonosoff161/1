"""
Trailing Stop Loss для Futures торговли.

Динамически подстраивает стоп-лосс под движение цены,
захватывая большую прибыль от волатильности.
"""

import time
from datetime import datetime
from typing import Optional, Tuple

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
        trading_fee_rate: float = 0.0010,  # ✅ ОБНОВЛЕНО: 0.10% на круг (0.05% вход + 0.05% выход для taker на OKX)
        loss_cut_percent: Optional[float] = None,
        timeout_loss_percent: Optional[float] = None,
        timeout_minutes: Optional[float] = None,
        min_holding_minutes: Optional[
            float
        ] = None,  # ✅ ЭТАП 4.4: Минимальное время удержания
        min_profit_to_close: Optional[
            float
        ] = None,  # ✅ ЭТАП 4.1: Минимальный профит для закрытия
        extend_time_on_profit: bool = False,  # ✅ ЭТАП 4.3: Продлевать время для прибыльных позиций
        extend_time_multiplier: float = 1.0,  # ✅ ЭТАП 4.3: Множитель продления времени
        leverage: float = 1.0,  # ✅ КРИТИЧЕСКОЕ: Leverage для правильного расчета loss_cut от маржи
        min_critical_hold_seconds: Optional[
            float
        ] = None,  # ✅ КРИТИЧЕСКОЕ: Минимальное время для критических убытков (из конфига)
        trail_growth_low_multiplier: float = 1.5,  # ✅ НОВОЕ: Множитель трейлинга для низкой прибыли (<0.5%)
        trail_growth_medium_multiplier: float = 2.0,  # ✅ НОВОЕ: Множитель трейлинга для средней прибыли (0.5-1.5%)
        trail_growth_high_multiplier: float = 3.0,  # ✅ НОВОЕ: Множитель трейлинга для высокой прибыли (>1.5%)
        debug_logger=None,  # ✅ DEBUG LOGGER для логирования
    ):
        """
        Инициализация Trailing Stop Loss.

        Args:
            initial_trail: Начальный трейлинг в % (по умолчанию 0.05%)
            max_trail: Максимальный трейлинг в % (по умолчанию 0.2%)
            min_trail: Минимальный трейлинг в % (по умолчанию 0.02%)
            trading_fee_rate: Комиссия на круг (открытие + закрытие) в долях (0.0010 = 0.10% для Market/Taker на OKX, проверено по реальным сделкам)
            leverage: Leverage позиции (по умолчанию 1.0) - используется для правильного расчета loss_cut от маржи
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
        self.entry_timestamp = 0.0
        # ✅ КРИТИЧЕСКОЕ: Сохраняем leverage для правильного расчета loss_cut от маржи
        self.leverage = max(1.0, float(leverage)) if leverage and leverage > 0 else 1.0
        self.loss_cut_percent = self._normalize_percent(loss_cut_percent)
        self.timeout_loss_percent = self._normalize_percent(timeout_loss_percent)
        self.timeout_minutes = (
            timeout_minutes if timeout_minutes and timeout_minutes > 0 else None
        )
        # ✅ ЭТАП 4.4: Минимальное время удержания позиции
        self.min_holding_minutes = (
            min_holding_minutes
            if min_holding_minutes and min_holding_minutes > 0
            else None
        )
        # ✅ ЭТАП 4.1: Минимальный профит для закрытия (нормализуем если нужно)
        self.min_profit_to_close = (
            self._normalize_percent(min_profit_to_close)
            if min_profit_to_close and min_profit_to_close > 0
            else None
        )
        # ✅ ЭТАП 4.3: Продлевание времени для прибыльных позиций
        self.extend_time_on_profit = extend_time_on_profit
        self.extend_time_multiplier = (
            extend_time_multiplier if extend_time_multiplier > 1.0 else 1.0
        )
        # ✅ КРИТИЧЕСКОЕ: Минимальное время для критических убытков (из конфига)
        self.min_critical_hold_seconds = (
            min_critical_hold_seconds
            if min_critical_hold_seconds and min_critical_hold_seconds > 0
            else None
        )
        self.aggressive_mode = False
        self.aggressive_step_profit = 0.0
        self.aggressive_step_trail = 0.0
        # ✅ НОВОЕ: Множители режимов из конфига (устанавливаются в orchestrator)
        self.regime_multiplier = None  # Будет установлено из конфига
        self.trend_strength_boost = None  # Будет установлено из конфига
        # ✅ НОВОЕ: Сохраняем trail_growth multipliers для адаптивного трейлинга
        self.trail_growth_low_multiplier = trail_growth_low_multiplier
        self.trail_growth_medium_multiplier = trail_growth_medium_multiplier
        self.trail_growth_high_multiplier = trail_growth_high_multiplier
        self.aggressive_max_trail: Optional[float] = max_trail
        self._next_trail_profit_target: Optional[float] = None
        self.debug_logger = debug_logger  # ✅ DEBUG LOGGER для логирования
        self._symbol: Optional[str] = None  # ✅ Сохраняем символ для логирования

    @staticmethod
    def _normalize_percent(value: Optional[float]) -> Optional[float]:
        """Конвертирует процент в долю и отбрасывает невалидные значения."""

        if value is None:
            return None
        if value <= 0:
            return None
        return value / 100.0 if value > 1 else value

    def initialize(self, entry_price: float, side: str, symbol: Optional[str] = None):
        """
        Инициализация трейлинг стопа для позиции.

        Args:
            entry_price: Цена входа
            side: Сторона позиции ("long" или "short")
            symbol: Торговый символ (опционально, для логирования)
        """
        self.entry_price = entry_price
        self.side = side
        self._symbol = symbol  # ✅ Сохраняем символ для логирования
        self.current_trail = self.initial_trail
        self.entry_timestamp = time.time()

        if side == "long":
            self.highest_price = entry_price
            self.lowest_price = float("inf")
        else:  # short
            self.highest_price = 0.0
            self.lowest_price = entry_price

        human_ts = datetime.fromtimestamp(self.entry_timestamp).isoformat()
        logger.info(
            f"TrailingStopLoss инициализирован: entry={entry_price}, "
            f"side={side}, trail={self.current_trail:.2%}, "
            f"entry_time={human_ts}"
        )
        if self.aggressive_mode and self.aggressive_step_profit > 0:
            self._next_trail_profit_target = self.aggressive_step_profit

    def enable_aggressive_mode(
        self,
        step_profit: float,
        step_trail: float,
        aggressive_max_trail: Optional[float] = None,
    ) -> None:
        """Включает агрессивное подтягивание трейла (используется для импульсных сделок)."""

        if step_profit <= 0 or step_trail <= 0:
            logger.debug(
                "TrailingStopLoss aggressive mode не активирован: шаги должны быть > 0"
            )
            return
        self.aggressive_mode = True
        self.aggressive_step_profit = step_profit
        self.aggressive_step_trail = step_trail
        if aggressive_max_trail and aggressive_max_trail > 0:
            self.aggressive_max_trail = aggressive_max_trail
        else:
            self.aggressive_max_trail = self.max_trail
        self._next_trail_profit_target = step_profit
        cap_display = (
            f"{self.aggressive_max_trail:.3%}"
            if self.aggressive_max_trail is not None
            else "auto"
        )
        logger.debug(
            f"TrailingStopLoss aggressive mode включён: step_profit={step_profit:.3%}, "
            f"step_trail={step_trail:.3%}, cap={cap_display}"
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
        profit_pct_total = self.get_profit_pct(current_price, include_fees=True)

        # Обновление экстремумов и трейлинга
        if self.side == "long":
            # Для лонга отслеживаем максимальную цену
            if current_price > self.highest_price:
                self.highest_price = current_price
                # Армирование: до достижения min_profit_to_close не усиливаем трейл
                trail_multiplier = None  # Инициализируем для логирования
                if (
                    getattr(self, "min_profit_to_close", None) is not None
                    and profit_pct_total < self.min_profit_to_close
                ):
                    self.current_trail = max(self.current_trail, self.initial_trail)
                    trail_multiplier = (
                        1.0  # Не используем multiplier, оставляем initial_trail
                    )
                else:
                    # Увеличиваем трейл при росте цены
                    # ✅ АДАПТИВНО: Используем trail_growth multipliers из конфига вместо захардкоженного 2.0
                    # Адаптируем множитель по уровню прибыли (low/medium/high)
                    if profit_pct_total < 0.005:  # < 0.5% - низкая прибыль
                        trail_multiplier = self.trail_growth_low_multiplier
                    elif profit_pct_total < 0.015:  # 0.5-1.5% - средняя прибыль
                        trail_multiplier = self.trail_growth_medium_multiplier
                    else:  # > 1.5% - высокая прибыль
                        trail_multiplier = self.trail_growth_high_multiplier

                    self.current_trail = min(
                        self.initial_trail
                        + max(profit_pct_total, 0.0) * trail_multiplier,
                        self.max_trail,
                    )
                logger.debug(
                    f"Long: новая максимальная цена={current_price:.2f}, "
                    f"трейл={self.current_trail:.2%}, профит={profit_pct_total:.2%} (net с комиссией), "
                    f"multiplier={trail_multiplier:.2f}x"
                    if trail_multiplier is not None
                    else "multiplier=N/A"
                )
        else:  # short
            # Для шорта отслеживаем минимальную цену
            if current_price < self.lowest_price:
                self.lowest_price = current_price
                # Армирование: до достижения min_profit_to_close не усиливаем трейл
                trail_multiplier = None  # Инициализируем для логирования
                if (
                    getattr(self, "min_profit_to_close", None) is not None
                    and profit_pct_total < self.min_profit_to_close
                ):
                    self.current_trail = max(self.current_trail, self.initial_trail)
                    trail_multiplier = (
                        1.0  # Не используем multiplier, оставляем initial_trail
                    )
                else:
                    # Увеличиваем трейл при падении цены
                    # ✅ АДАПТИВНО: Используем trail_growth multipliers из конфига вместо захардкоженного 2.0
                    # Адаптируем множитель по уровню прибыли (low/medium/high)
                    if profit_pct_total < 0.005:  # < 0.5% - низкая прибыль
                        trail_multiplier = self.trail_growth_low_multiplier
                    elif profit_pct_total < 0.015:  # 0.5-1.5% - средняя прибыль
                        trail_multiplier = self.trail_growth_medium_multiplier
                    else:  # > 1.5% - высокая прибыль
                        trail_multiplier = self.trail_growth_high_multiplier

                    self.current_trail = min(
                        self.initial_trail
                        + max(profit_pct_total, 0.0) * trail_multiplier,
                        self.max_trail,
                    )
                logger.debug(
                    f"Short: новая минимальная цена={current_price:.2f}, "
                    f"трейл={self.current_trail:.2%}, профит={profit_pct_total:.2%} (net с комиссией), "
                    f"multiplier={trail_multiplier:.2f}x"
                    if trail_multiplier is not None
                    else "multiplier=N/A"
                )

        if (
            self.aggressive_mode
            and self.aggressive_step_profit > 0
            and self.aggressive_step_trail > 0
            and profit_pct_total > 0
        ):
            target = self._next_trail_profit_target or self.aggressive_step_profit
            cap = self.aggressive_max_trail or self.max_trail
            updated = False
            while profit_pct_total >= target:
                new_trail = min(self.current_trail + self.aggressive_step_trail, cap)
                if new_trail <= self.current_trail + 1e-6:
                    target = profit_pct_total + self.aggressive_step_profit
                    break
                self.current_trail = new_trail
                updated = True
                target += self.aggressive_step_profit
            if updated:
                logger.debug(
                    f"🚀 Aggressive trailing tighten: trail={self.current_trail:.2%}, next_target={target:.3%}"
                )
            self._next_trail_profit_target = target

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
        else:  # short
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для SHORT стоп должен быть ВЫШЕ entry при инициализации (защита от роста)
            # При инициализации: lowest_price = entry_price, стоп = entry_price * (1 + trail%) (выше entry)
            # После обновления: если цена упала (lowest_price < entry_price), стоп следует за минимальной ценой (опускается)
            # Стоп может опускаться ниже entry, когда позиция в прибыли (это правильно для trailing stop!)

            if (
                self.lowest_price < float("inf")
                and self.lowest_price < self.entry_price
            ):
                # Цена упала ниже entry (позиция в прибыли) - стоп следует за минимальной ценой (опускается)
                # Стоп = lowest_price * (1 + trail%) (защита от отскока)
                # ✅ Стоп может быть ниже entry * (1 + trail%) - это правильно, потому что позиция в прибыли!
                stop_loss = self.lowest_price * (1 + self.current_trail)
                # ✅ ЗАЩИТА: стоп не должен быть ниже entry (базовая защита)
                # Но если цена упала значительно ниже entry, стоп может быть ниже entry * (1 + trail%)
                if stop_loss < self.entry_price:
                    # Если стоп опустился ниже entry, используем entry как минимальный стоп
                    # Это защищает от случая, когда trail очень маленький
                    stop_loss = max(
                        stop_loss, self.entry_price * (1 + self.initial_trail)
                    )
            else:
                # Цена еще не упала ниже entry или это инициализация - стоп выше entry
                # Стоп = entry_price * (1 + trail%) (защита от роста)
                stop_loss = self.entry_price * (1 + self.current_trail)

            return stop_loss

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

        # ✅ ИСПРАВЛЕНИЕ: Не учитываем комиссию в первые 10 секунд после открытия
        # (это время для установления реальной цены, учитывая спред и проскальзывание)
        if include_fees:
            seconds_since_open = (
                (time.time() - self.entry_timestamp) if self.entry_timestamp > 0 else 0
            )
            if seconds_since_open < 10.0:
                # В первые 10 секунд не учитываем комиссию (учитываем только спред)
                logger.debug(
                    f"⏱️ Позиция открыта {seconds_since_open:.1f} сек назад, "
                    f"комиссия не учитывается в profit_pct (учитываем только спред)"
                )
                return gross_profit_pct
            else:
                # После 10 секунд учитываем комиссию
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
    ) -> Tuple[bool, Optional[str]]:
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
            Tuple[bool, Optional[str]]: (True, причина_закрытия) если нужно закрыть, (False, None) если нет
        """
        stop_loss = self.get_stop_loss()
        # ⚠️ ИСПРАВЛЕНИЕ: Используем прибыль С УЧЕТОМ КОМИССИИ!
        profit_pct = self.get_profit_pct(current_price, include_fees=True)
        minutes_in_position = (
            (time.time() - self.entry_timestamp) / 60.0 if self.entry_timestamp else 0.0
        )
        entry_iso = (
            datetime.fromtimestamp(self.entry_timestamp).isoformat()
            if self.entry_timestamp
            else "n/a"
        )
        logger.debug(
            f"🔍 TrailingSL check: side={self.side}, price={current_price:.5f}, "
            f"stop={stop_loss:.5f}, profit={profit_pct:.3%}, "
            f"time_in_position={minutes_in_position:.2f} мин, "
            f"trail={self.current_trail:.3%}"
        )

        # ✅ DEBUG LOGGER: Логируем проверку TSL
        will_close = False  # Будет установлено в True если закроем

        # ✅ ЭТАП 4.4: Проверка минимального времени удержания
        effective_min_holding = self.min_holding_minutes
        # ✅ ЭТАП 4.3: Продлеваем время удержания для прибыльных позиций
        if (
            self.extend_time_on_profit
            and profit_pct > 0
            and effective_min_holding is not None
        ):
            # Применяем множитель продления времени для прибыльных позиций
            effective_min_holding = effective_min_holding * self.extend_time_multiplier

        # ✅ ПРАВКА #2: Проверка min_holding ПЕРЕД loss_cut (включая критические убытки)
        # ✅ ИСПРАВЛЕНО: Критический 2x loss_cut тоже проверяем с минимальной задержкой
        seconds_in_position = minutes_in_position * 60.0
        if self.loss_cut_percent is not None:
            loss_cut_from_price = self.loss_cut_percent / self.leverage
            critical_loss_cut_from_price = loss_cut_from_price * 2.0

            # ✅ ИСПРАВЛЕНО: Критический убыток (2x loss_cut) тоже проверяем с минимальной задержкой
            if profit_pct <= -critical_loss_cut_from_price:
                # ✅ ЗАЩИТА: Минимальная задержка даже для критических убытков (5 секунд)
                min_critical_hold_seconds = self.min_critical_hold_seconds or 5.0
                
                if seconds_in_position < min_critical_hold_seconds:
                    logger.debug(
                        f"⏱️ Критический loss_cut заблокирован (min_hold защита): "
                        f"прибыль {profit_pct:.2%} от цены <= -{critical_loss_cut_from_price:.2%}, "
                        f"но позиция держится {seconds_in_position:.1f} сек < {min_critical_hold_seconds:.1f} сек, "
                        f"не закрываем (entry_time={entry_iso}, branch=min_critical_hold_block)"
                    )
                    # ✅ DEBUG LOGGER: Логируем блокировку критического loss_cut
                    if self.debug_logger:
                        self.debug_logger.log_tsl_loss_cut_check(
                            symbol=getattr(self, "_symbol", "UNKNOWN"),
                            profit_pct=profit_pct,
                            loss_cut_from_price=critical_loss_cut_from_price,
                            will_close=False,  # Блокировано min_hold
                        )
                    return False, None  # НЕ закрываем - минимальная задержка
                
                # ✅ ЗАЩИТА: Проверяем, что убыток не из-за комиссии
                # Если profit_pct очень близок к -critical_loss_cut_from_price (в пределах комиссии),
                # возможно это просто комиссия, а не реальный убыток
                commission_threshold = self.trading_fee_rate * 1.5  # 1.5x комиссия как буфер
                if abs(profit_pct + critical_loss_cut_from_price) < commission_threshold:
                    logger.debug(
                        f"⚠️ Критический loss_cut может быть из-за комиссии: "
                        f"profit_pct={profit_pct:.4f}, critical={critical_loss_cut_from_price:.4f}, "
                        f"разница={abs(profit_pct + critical_loss_cut_from_price):.4f} < {commission_threshold:.4f}"
                    )
                    # Продолжаем, но логируем предупреждение
                
                loss_from_margin = abs(profit_pct) * self.leverage
                logger.warning(
                    f"🚨 Loss-cut КРИТИЧЕСКИЙ (2x): прибыль {profit_pct:.2%} от цены "
                    f"({loss_from_margin:.2%} от маржи) <= -{critical_loss_cut_from_price:.2%} от цены "
                    f"(-{self.loss_cut_percent * 2.0:.2%} от маржи, leverage={self.leverage}x), "
                    f"позиция будет закрыта (time_in_position={minutes_in_position:.2f} мин, "
                    f"entry_time={entry_iso}, branch=critical_loss_cut_2x)"
                )
                # ✅ DEBUG LOGGER: Логируем закрытие по критическому loss_cut
                if self.debug_logger:
                    self.debug_logger.log_tsl_loss_cut_check(
                        symbol=getattr(self, "_symbol", "UNKNOWN"),
                        profit_pct=profit_pct,
                        loss_cut_from_price=critical_loss_cut_from_price,
                        will_close=True,
                    )
                return (
                    True,
                    "critical_loss_cut_2x",
                )  # Закрываем по критическому loss_cut после минимальной задержки

        # ✅ ПРАВКА #2: Проверка min_holding ПЕРЕД обычным loss_cut
        if (
            effective_min_holding is not None
            and minutes_in_position < effective_min_holding
        ):
            # ✅ Проверяем loss_cut только если прошло min_holding (кроме критических)
            if self.loss_cut_percent is not None:
                loss_cut_from_price = self.loss_cut_percent / self.leverage
                if profit_pct <= -loss_cut_from_price:
                    loss_from_margin = abs(profit_pct) * self.leverage
                    logger.debug(
                        f"⏱️ Loss-cut заблокирован (min_holding защита): прибыль {profit_pct:.2%} от цены "
                        f"({loss_from_margin:.2%} от маржи) <= -{loss_cut_from_price:.2%} от цены, "
                        f"но позиция держится {minutes_in_position:.2f} мин < {effective_min_holding:.2f} мин, "
                        f"не закрываем (entry_time={entry_iso}, branch=min_holding_loss_cut_block)"
                    )
                    # ✅ DEBUG LOGGER: Логируем блокировку loss_cut
                    if self.debug_logger:
                        self.debug_logger.log_tsl_loss_cut_check(
                            symbol=getattr(self, "_symbol", "UNKNOWN"),
                            profit_pct=profit_pct,
                            loss_cut_from_price=loss_cut_from_price,
                            will_close=False,  # Блокировано min_holding
                        )
                    return False, None  # НЕ закрываем - min_holding защита активна!

            # Если не loss_cut - просто блокируем закрытие
            logger.debug(
                f"⏱️ Минимальное время удержания: позиция держится {minutes_in_position:.2f} мин < {effective_min_holding:.2f} мин, "
                f"не закрываем (profit={profit_pct:.2%}, entry_time={entry_iso}, branch=min_holding)"
            )
            # ✅ DEBUG LOGGER: Логируем блокировку min_holding
            if self.debug_logger:
                self.debug_logger.log_tsl_min_holding_block(
                    symbol=getattr(self, "_symbol", "UNKNOWN"),
                    minutes_in_position=minutes_in_position,
                    min_holding=effective_min_holding,
                    profit_pct=profit_pct,
                )
            return False, None

        # ✅ Жёсткое ограничение убытка
        # ✅ КРИТИЧЕСКОЕ: Учитываем leverage при сравнении loss_cut_percent
        # loss_cut_percent в конфиге указан как % от маржи (1.5% от маржи)
        # profit_pct рассчитывается от цены, поэтому нужно разделить loss_cut_percent на leverage для сравнения
        if self.loss_cut_percent is not None:
            # Приводим loss_cut_percent к процентам от цены (делим на leverage)
            loss_cut_from_price = self.loss_cut_percent / self.leverage
            # profit_pct уже учитывает комиссию, поэтому сравниваем напрямую
            if profit_pct <= -loss_cut_from_price:
                loss_from_margin = abs(profit_pct) * self.leverage
                logger.warning(
                    f"⚠️ Loss-cut: прибыль {profit_pct:.2%} от цены "
                    f"({loss_from_margin:.2%} от маржи) <= -{loss_cut_from_price:.2%} от цены "
                    f"(-{self.loss_cut_percent:.2%} от маржи, leverage={self.leverage}x), "
                    f"позиция будет закрыта "
                    f"(time_in_position={minutes_in_position:.2f} мин, entry_time={entry_iso}, branch=loss_cut)"
                )
                # ✅ DEBUG LOGGER: Логируем закрытие по loss_cut
                if self.debug_logger:
                    self.debug_logger.log_tsl_loss_cut_check(
                        symbol=getattr(self, "_symbol", "UNKNOWN"),
                        profit_pct=profit_pct,
                        loss_cut_from_price=loss_cut_from_price,
                        will_close=True,
                    )
                return True, "loss_cut"

        # ✅ Таймаут для убыточных позиций
        # ✅ КРИТИЧЕСКОЕ: Учитываем leverage при сравнении timeout_loss_percent
        # timeout_loss_percent в конфиге указан как % от маржи (1.0% от маржи)
        # profit_pct рассчитывается от цены, поэтому нужно разделить timeout_loss_percent на leverage для сравнения
        if (
            self.timeout_loss_percent is not None
            and self.timeout_minutes is not None
            and self.entry_timestamp > 0
        ):
            minutes_in_position = (time.time() - self.entry_timestamp) / 60.0
            # Приводим timeout_loss_percent к процентам от цены (делим на leverage)
            timeout_loss_from_price = self.timeout_loss_percent / self.leverage
            if (
                minutes_in_position >= self.timeout_minutes
                and profit_pct <= -timeout_loss_from_price
            ):
                loss_from_margin = abs(profit_pct) * self.leverage
                logger.warning(
                    f"⚠️ Timeout loss-cut: позиция держится {minutes_in_position:.2f} минут, "
                    f"прибыль {profit_pct:.2%} от цены ({loss_from_margin:.2%} от маржи) "
                    f"≤ -{timeout_loss_from_price:.2%} от цены (-{self.timeout_loss_percent:.2%} от маржи, leverage={self.leverage}x), "
                    f"закрываем (entry_time={entry_iso}, branch=timeout)"
                )
                # ✅ DEBUG LOGGER: Логируем закрытие по timeout
                if self.debug_logger:
                    self.debug_logger.log_tsl_timeout_check(
                        symbol=getattr(self, "_symbol", "UNKNOWN"),
                        minutes_in_position=minutes_in_position,
                        timeout_minutes=self.timeout_minutes,
                        profit_pct=profit_pct,
                        will_close=True,
                    )
                return True, "timeout"

        # Базовая проверка стоп-лосса
        if self.side == "long":
            price_hit_sl = current_price <= stop_loss
        else:  # short
            price_hit_sl = current_price >= stop_loss

        if not price_hit_sl:
            # ✅ DEBUG LOGGER: Логируем что не закрываем (цена не достигла SL)
            if self.debug_logger:
                self.debug_logger.log_tsl_check(
                    symbol=getattr(self, "_symbol", "UNKNOWN"),
                    minutes_in_position=minutes_in_position,
                    profit_pct=profit_pct,
                    current_price=current_price,
                    stop_loss=stop_loss,
                    will_close=False,
                )
            return False, None  # Цена не достигла стоп-лосса - не закрываем

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем min_holding_minutes ПЕРЕД закрытием по стоп-лоссу
        # (кроме loss_cut, который уже проверен выше)
        effective_min_holding = self.min_holding_minutes
        if (
            self.extend_time_on_profit
            and profit_pct > 0
            and effective_min_holding is not None
        ):
            effective_min_holding = effective_min_holding * self.extend_time_multiplier

        if (
            effective_min_holding is not None
            and minutes_in_position < effective_min_holding
        ):
            # Не закрываем по стоп-лоссу, если не прошло минимальное время удержания
            # (loss_cut уже проверен выше и имеет приоритет)
            logger.debug(
                f"⏱️ Минимальное время удержания: позиция держится {minutes_in_position:.2f} мин < {effective_min_holding:.2f} мин, "
                f"не закрываем по стоп-лоссу (profit={profit_pct:.2%}, entry_time={entry_iso}, branch=min_holding_before_sl)"
            )
            return False, None

        # ✅ ЭТАП 4.1: Проверка минимального профита для закрытия
        if profit_pct > 0 and self.min_profit_to_close is not None:
            # Не закрываем позицию, если профит меньше минимального
            if profit_pct < self.min_profit_to_close:
                logger.debug(
                    f"💰 Минимальный профит: позиция в прибыли {profit_pct:.2%} < {self.min_profit_to_close:.2%}, "
                    f"не закрываем (time_in_position={minutes_in_position:.2f} мин, entry_time={entry_iso}, branch=min_profit)"
                )
                return False, None

        # ⚠️ АДАПТИВНАЯ ЛОГИКА: Если позиция в прибыли и идет тренд/режим - даем больше места
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем множители из конфига (передаются из orchestrator)
        if profit_pct > 0:
            # Получаем множители из параметров (передаются из orchestrator через _get_trailing_sl_params)
            # Fallback значения (если не переданы из конфига)
            regime_multiplier = getattr(self, "regime_multiplier", None) or 1.0
            trend_strength_boost = getattr(self, "trend_strength_boost", None) or 1.0

            # Если множители не установлены, используем старую логику (для обратной совместимости)
            if regime_multiplier == 1.0 and not hasattr(self, "regime_multiplier"):
                if market_regime == "trending":
                    regime_multiplier = 1.5  # Fallback: в тренде больше места
                elif market_regime == "ranging":
                    regime_multiplier = 1.0  # Fallback: в боковике стандартно
                elif market_regime == "choppy":
                    regime_multiplier = 0.8  # Fallback: в хаосе меньше места

            # Если есть сильный тренд - дополнительный буст из конфига
            if trend_strength and trend_strength > 0.7:
                # Используем trend_strength_boost из конфига, если установлен
                if trend_strength_boost != 1.0:
                    regime_multiplier *= trend_strength_boost
                else:
                    # Fallback: старый буст (для обратной совместимости)
                    regime_multiplier *= 1.3

            # ✅ АДАПТИВНО: Приоритет закрытия при хорошей прибыли (параметры из конфига)
            # Если прибыль превышает порог, уменьшаем regime_multiplier для более быстрого закрытия
            high_profit_threshold = getattr(
                self, "high_profit_threshold", 0.01
            )  # ✅ АДАПТИВНО: Из конфига
            high_profit_max_factor = getattr(
                self, "high_profit_max_factor", 2.0
            )  # ✅ АДАПТИВНО: Из конфига
            high_profit_reduction_percent = getattr(
                self, "high_profit_reduction_percent", 30
            )  # ✅ АДАПТИВНО: Из конфига
            high_profit_min_reduction = getattr(
                self, "high_profit_min_reduction", 0.5
            )  # ✅ АДАПТИВНО: Из конфига

            effective_regime_multiplier = regime_multiplier

            if profit_pct > high_profit_threshold:
                # При высокой прибыли уменьшаем multiplier для более быстрого закрытия
                # Чем выше прибыль, тем меньше multiplier (но не меньше 1.0)
                profit_factor = min(
                    profit_pct / high_profit_threshold, high_profit_max_factor
                )  # ✅ АДАПТИВНО: Из конфига
                reduction_factor = max(
                    high_profit_min_reduction,
                    1.0
                    - (profit_factor - 1.0) * (high_profit_reduction_percent / 100.0),
                )  # ✅ АДАПТИВНО: Из конфига
                effective_regime_multiplier = max(
                    1.0, regime_multiplier * reduction_factor
                )
                logger.debug(
                    f"💰 Высокая прибыль {profit_pct:.2%} > {high_profit_threshold:.2%}: "
                    f"regime_multiplier {regime_multiplier:.2f} → {effective_regime_multiplier:.2f} "
                    f"(reduction_factor={reduction_factor:.2f}, threshold={high_profit_threshold:.2%})"
                )

            # Позиция в прибыли и (сильный тренд или trending режим) - даем больше места
            if effective_regime_multiplier > 1.0 or (
                trend_strength and trend_strength > 0.7
            ):
                # Даем больше места для отката (но с учетом приоритета закрытия при высокой прибыли)
                adjusted_trail = min(
                    self.current_trail * effective_regime_multiplier, self.max_trail
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
                            f"даем больше места: stop={adjusted_stop:.2f} vs текущий={current_price:.2f} "
                            f"(effective_multiplier={effective_regime_multiplier:.2f})"
                        )
                        return False, None
                else:  # short
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для SHORT используем ту же логику, что и в get_stop_loss()
                    # При инициализации: стоп = entry_price * (1 + trail%) (выше entry)
                    # После обновления: стоп = lowest_price * (1 + trail%) (следует за минимальной ценой)
                    # Стоп может опускаться ниже entry, когда позиция в прибыли (это правильно для trailing stop!)
                    if (
                        self.lowest_price < float("inf")
                        and self.lowest_price < self.entry_price
                    ):
                        # Цена упала ниже entry (позиция в прибыли) - стоп следует за минимальной ценой (опускается)
                        adjusted_stop = self.lowest_price * (1 + adjusted_trail)
                        # ✅ ЗАЩИТА: стоп не должен быть ниже entry (базовая защита)
                        if adjusted_stop < self.entry_price:
                            adjusted_stop = max(
                                adjusted_stop,
                                self.entry_price * (1 + self.initial_trail),
                            )
                    else:
                        # Цена еще не упала ниже entry или это инициализация - стоп выше entry
                        adjusted_stop = self.entry_price * (1 + adjusted_trail)

                    # Не закрываем если цена ниже скорректированного стопа (для SHORT цена должна подняться до стопа)
                    if current_price < adjusted_stop:
                        profit_gross = self.get_profit_pct(
                            current_price, include_fees=False
                        )
                        logger.debug(
                            f"📈 SHORT: Позиция в прибыли (net={profit_pct:.2%}, gross={profit_gross:.2%}), "
                            f"режим={market_regime or 'N/A'}, тренд={trend_strength:.2f if trend_strength else 'N/A'} - "
                            f"даем больше места: stop={adjusted_stop:.2f} vs текущий={current_price:.2f} "
                            f"(effective_multiplier={effective_regime_multiplier:.2f})"
                        )
                        return False, None

        # Если позиция в убытке - закрываем строже (обычная логика)
        close_reason = "trail_hit_profit"
        if profit_pct <= 0:
            close_reason = "trail_hit_loss"
            logger.info(
                f"⚠️ Позиция в убытке ({profit_pct:.2%}) - закрываем по трейлинг-стопу: "
                f"stop={stop_loss:.2f}, price={current_price:.2f}, "
                f"time_in_position={minutes_in_position:.2f} мин, entry_time={entry_iso}, branch=trail_hit_loss"
            )
        else:
            logger.info(
                f"✅ Фиксируем прибыль ({profit_pct:.2%}) по трейлинг-стопу: "
                f"stop={stop_loss:.2f}, price={current_price:.2f}, "
                f"time_in_position={minutes_in_position:.2f} мин, entry_time={entry_iso}, branch=trail_hit_profit"
            )

        # ✅ DEBUG LOGGER: Логируем финальное закрытие по TSL
        will_close = True
        if self.debug_logger:
            self.debug_logger.log_tsl_check(
                symbol=getattr(self, "_symbol", "UNKNOWN"),
                minutes_in_position=minutes_in_position,
                profit_pct=profit_pct,
                current_price=current_price,
                stop_loss=stop_loss,
                will_close=True,
            )

        return True, close_reason  # Закрываем по стоп-лоссу

    def reset(self):
        """Сброс всех данных трейлинга."""
        self.highest_price = 0.0
        self.lowest_price = float("inf")
        self.current_trail = self.initial_trail
        self.entry_price = 0.0
        self.side = None
        self.entry_timestamp = 0.0
        self._next_trail_profit_target = (
            self.aggressive_step_profit if self.aggressive_mode else None
        )
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
