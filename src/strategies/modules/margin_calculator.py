"""
Margin Calculator для Futures торговли.

Основные функции:
- Расчет максимального размера позиции
- Расчет цены ликвидации
- Мониторинг маржи
- Проверки безопасности маржи
"""

import math
from typing import Any, Dict, Optional, Tuple

from loguru import logger


class MarginCalculator:
    """
    Калькулятор маржи для Futures торговли

    Поддерживает:
    - Isolated margin (изолированная маржа)
    - Различные уровни левериджа
    - Расчет ликвидации
    - Безопасные зоны торговли
    """

    def __init__(
        self,
        default_leverage: int = 3,
        maintenance_margin_ratio: float = 0.01,
        initial_margin_ratio: float = 0.1,
    ):
        """
        Инициализация калькулятора маржи

        Args:
            default_leverage: Стандартное плечо (3x)
            maintenance_margin_ratio: Коэффициент поддерживающей маржи (1%)
            initial_margin_ratio: Коэффициент начальной маржи (10%)
        """
        self.default_leverage = default_leverage
        self.maintenance_margin_ratio = maintenance_margin_ratio
        self.initial_margin_ratio = initial_margin_ratio

        logger.info(
            f"MarginCalculator инициализирован: leverage={default_leverage}x, "
            f"maintenance={maintenance_margin_ratio:.1%}, initial={initial_margin_ratio:.1%}"
        )

    def calculate_max_position_size(
        self, equity: float, current_price: float, leverage: Optional[int] = None
    ) -> float:
        """
        Расчет максимального размера позиции

        Args:
            equity: Доступный баланс (USDT)
            current_price: Текущая цена актива
            leverage: Плечо (если None, используется default_leverage)

        Returns:
            Максимальный размер позиции в базовой валюте
        """
        if leverage is None:
            leverage = self.default_leverage

        # Максимальная позиция = (Баланс * Плечо) / Цена
        max_position_value = equity * leverage
        max_position_size = max_position_value / current_price

        logger.debug(
            f"Расчет максимальной позиции: equity={equity:.2f}, "
            f"leverage={leverage}x, price={current_price:.4f}, "
            f"max_size={max_position_size:.6f}"
        )

        return max_position_size

    def calculate_liquidation_price(
        self,
        side: str,
        entry_price: float,
        position_size: float,
        equity: float,
        leverage: Optional[int] = None,
    ) -> float:
        """
        Расчет цены ликвидации

        Args:
            side: Направление позиции ('buy' или 'sell')
            entry_price: Цена входа
            position_size: Размер позиции
            equity: Доступный баланс
            leverage: Плечо

        Returns:
            Цена ликвидации
        """
        if leverage is None:
            leverage = self.default_leverage

        # Расчет маржи
        position_value = position_size * entry_price
        margin_used = position_value / leverage

        # Расчет цены ликвидации
        if side.lower() == "buy":
            # Для лонга: LiqPrice = EntryPrice * (1 - (1/Leverage) + MaintenanceMarginRatio)
            liquidation_price = entry_price * (
                1 - (1 / leverage) + self.maintenance_margin_ratio
            )
        else:  # sell
            # Для шорта: LiqPrice = EntryPrice * (1 + (1/Leverage) - MaintenanceMarginRatio)
            liquidation_price = entry_price * (
                1 + (1 / leverage) - self.maintenance_margin_ratio
            )

        logger.debug(
            f"Расчет ликвидации: side={side}, entry={entry_price:.4f}, "
            f"size={position_size:.6f}, equity={equity:.2f}, "
            f"liq_price={liquidation_price:.4f}"
        )

        return liquidation_price

    def calculate_margin_ratio(
        self, position_value: float, equity: float, leverage: Optional[int] = None
    ) -> float:
        """
        Расчет коэффициента маржи

        Args:
            position_value: Стоимость позиции
            equity: Доступный баланс
            leverage: Плечо

        Returns:
            Коэффициент маржи (чем выше, тем безопаснее)
        """
        if leverage is None:
            leverage = self.default_leverage

        margin_used = position_value / leverage
        margin_ratio = equity / margin_used if margin_used > 0 else float("inf")

        logger.debug(
            f"Расчет коэффициента маржи: position_value={position_value:.2f}, "
            f"equity={equity:.2f}, leverage={leverage}x, "
            f"margin_ratio={margin_ratio:.2f}"
        )

        return margin_ratio

    def is_position_safe(
        self,
        position_value: float,
        equity: float,
        current_price: float,
        entry_price: float,
        side: str,
        leverage: Optional[int] = None,
        safety_threshold: Optional[float] = None,
        regime: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Проверка безопасности позиции

        Args:
            position_value: Стоимость позиции
            equity: Доступный баланс
            current_price: Текущая цена
            entry_price: Цена входа
            side: Направление позиции
            leverage: Плечо
            safety_threshold: Порог безопасности (1.5 = 150%)

        Returns:
            Tuple[bool, Dict] - (безопасна ли позиция, детали)
        """
        if leverage is None:
            leverage = self.default_leverage

        # ✅ АДАПТИВНО: Получаем safety_threshold из конфига по режиму
        # ПРИОРИТЕТ: конфиг -> fallback (сначала пытаемся из конфига, только если нет - fallback)
        if safety_threshold is None:
            try:
                if hasattr(self, "margin_config") and self.margin_config:
                    logger.debug(
                        f"🔍 Попытка загрузить safety_threshold из конфига: "
                        f"margin_config type={type(self.margin_config)}, "
                        f"regime={regime}"
                    )

                    # ✅ ИСПРАВЛЕНО: Универсальная обработка dict и Pydantic объектов
                    by_regime = None
                    if isinstance(self.margin_config, dict):
                        by_regime = self.margin_config.get("by_regime", {})
                        logger.debug(
                            f"🔍 by_regime (dict): {by_regime}, type={type(by_regime)}"
                        )
                    else:
                        # Пробуем получить как атрибут (Pydantic объект)
                        by_regime = getattr(self.margin_config, "by_regime", None)
                        logger.debug(
                            f"🔍 by_regime (attr): {by_regime}, type={type(by_regime)}"
                        )
                        # Если это Pydantic объект, конвертируем в dict
                        if by_regime and hasattr(by_regime, "dict"):
                            try:
                                by_regime = by_regime.dict()
                                logger.debug(
                                    f"🔍 by_regime конвертирован в dict: {by_regime}"
                                )
                            except:
                                pass
                        elif by_regime and hasattr(by_regime, "__dict__"):
                            try:
                                by_regime = dict(by_regime.__dict__)
                                logger.debug(
                                    f"🔍 by_regime конвертирован из __dict__: {by_regime}"
                                )
                            except:
                                pass

                    # ✅ ИСПРАВЛЕНО: Если regime=None, используем fallback на 'ranging' (стандартный режим)
                    regime_to_use = regime.lower() if regime else "ranging"
                    if not regime:
                        logger.debug(f"🔍 regime=None, используем fallback: 'ranging'")

                    if by_regime and regime_to_use:
                        # Получаем regime_config
                        regime_config = None
                        if isinstance(by_regime, dict):
                            regime_config = by_regime.get(regime_to_use)
                        elif hasattr(by_regime, regime_to_use):
                            regime_config = getattr(by_regime, regime_to_use, None)

                        logger.debug(
                            f"🔍 regime_config для {regime_to_use}: {regime_config}, type={type(regime_config)}"
                        )

                        # Конвертируем regime_config в dict если это Pydantic объект
                        if regime_config and not isinstance(regime_config, dict):
                            if hasattr(regime_config, "dict"):
                                try:
                                    regime_config = regime_config.dict()
                                    logger.debug(
                                        f"🔍 regime_config конвертирован в dict: {regime_config}"
                                    )
                                except:
                                    pass
                            elif hasattr(regime_config, "__dict__"):
                                try:
                                    regime_config = dict(regime_config.__dict__)
                                    logger.debug(
                                        f"🔍 regime_config конвертирован из __dict__: {regime_config}"
                                    )
                                except:
                                    pass

                        # Получаем safety_threshold
                        if regime_config:
                            if isinstance(regime_config, dict):
                                safety_threshold = regime_config.get("safety_threshold")
                            elif hasattr(regime_config, "safety_threshold"):
                                safety_threshold = getattr(
                                    regime_config, "safety_threshold", None
                                )
                            else:
                                safety_threshold = None

                            if safety_threshold is not None:
                                logger.info(
                                    f"✅ Загружен safety_threshold={safety_threshold} из конфига (regime={regime_to_use}{' (fallback)' if not regime else ''})"
                                )

            except Exception as e:
                logger.warning(
                    f"⚠️ Не удалось получить адаптивный safety_threshold: {e}, "
                    f"margin_config type={type(getattr(self, 'margin_config', None))}, "
                    f"regime={regime}"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Ошибка вместо fallback - safety_threshold ОБЯЗАТЕЛЕН в конфиге
            if safety_threshold is None:
                # Определяем regime_to_use для сообщения об ошибке
                regime_for_error = "ranging"  # По умолчанию
                if "regime_to_use" in locals():
                    regime_for_error = regime_to_use
                elif regime:
                    regime_for_error = regime.lower()

                regime_info = f" для regime={regime_for_error}" + (
                    " (использован fallback 'ranging')" if not regime else ""
                )
                raise ValueError(
                    f"❌ КРИТИЧЕСКАЯ ОШИБКА: safety_threshold не найден в конфиге{regime_info}! "
                    f"Добавьте в config_futures.yaml: futures_modules.margin.by_regime.{regime_for_error}.safety_threshold. "
                    f"margin_config type={type(getattr(self, 'margin_config', None))}"
                )

        # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: position_value уже в USD (size_in_coins * current_price)
        # Поэтому position_size (в монетах) = position_value / current_price
        # Это правильнее чем делить на entry_price, потому что position_value уже учитывает current_price
        position_size = position_value / current_price if current_price > 0 else 0

        # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование
        # logger.debug(f"🔍 margin_calculator: position_value={position_value:.2f} USD")

        if side.lower() == "buy" or side.lower() == "long":
            pnl = (current_price - entry_price) * position_size
        else:  # sell/short
            pnl = (entry_price - current_price) * position_size

        # Расчет маржи
        margin_used = position_value / leverage

        # 🔥 ИСПРАВЛЕННЫЙ РАСЧЕТ ДЛЯ ИЗОЛИРОВАННОЙ МАРЖИ:
        #
        # Для изолированной маржи OKX:
        # - equity позиции = margin (выделенная маржа) + unrealizedPnl
        # - margin_ratio должен показывать запас прочности
        #
        # ПРАВИЛЬНАЯ ФОРМУЛА для изолированной маржи:
        # margin_ratio = equity / margin_used
        # Это показывает, во сколько раз equity больше margin (запас прочности)
        #
        # Но если equity не найден и используется общий баланс (fallback):
        # - balance уже уменьшен на margin после открытия
        # - Нужно восстановить: total_balance = equity + margin_used

        # Проверяем: если equity очень мал или 0 - это fallback на общий баланс
        if equity <= 0 or (equity <= margin_used * 0.3 and abs(pnl) < 1.0):
            # Используется fallback - баланс уже уменьшен на margin
            # Восстанавливаем: если equity = balance_after, то balance_before = equity + margin_used
            if equity > 0:
                total_balance = (
                    equity + margin_used
                )  # Восстанавливаем баланс до открытия
                available_margin = total_balance - margin_used + pnl
            else:
                # equity = 0 - ошибка, но используем margin_used * 5 как безопасное значение
                available_margin = margin_used * 5  # margin_ratio = 5 (безопасно)
        elif abs(equity - margin_used) < margin_used * 0.1 and abs(pnl) < 1.0:
            # equity ≈ margin_used (новая позиция, PnL ≈ 0)
            # Для изолированной маржи: если equity = margin, это нормально
            # margin_ratio должен быть примерно 1, но это нормально для новой позиции
            # Используем простой расчет: available_margin = equity - margin_used = 0
            # Но это даст margin_ratio = 0, что неправильно!
            # Правильнее: использовать equity / margin_used напрямую для margin_ratio
            # Или: available_margin = equity - maintenance_margin (но его нет)
            # Временно: если equity ≈ margin, считаем что запас = margin (margin_ratio = 1)
            # Но лучше использовать более консервативный расчет
            available_margin = margin_used * 2  # Временная защита: margin_ratio = 2
        else:
            # equity найден правильно и не равен margin (есть PnL или другая ситуация)
            # Для изолированной маржи: equity = margin + PnL
            # available_margin = equity - margin_used = (margin + PnL) - margin = PnL
            # Но это слишком консервативно! Правильнее:
            # margin_ratio = equity / margin_used (показывает запас)
            # Но для consistency используем available_margin:
            available_margin = equity - margin_used + pnl

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Защита для малых позиций (XRP-USDT и т.д.)
            # Для очень малых позиций (margin_used < 5 USDT) возможны ошибки округления
            # Если available_margin отрицательный, но equity > margin_used, это ошибка расчета
            if (
                available_margin < 0
                and margin_used < 5.0
                and equity > margin_used * 0.5
            ):
                # Для малых позиций используем более консервативный расчет
                # Если equity > margin_used, значит есть запас, даже если available_margin отрицательный
                logger.debug(
                    f"⚠️ Исправление расчета для малой позиции: "
                    f"available_margin={available_margin:.2f}, equity={equity:.2f}, "
                    f"margin_used={margin_used:.2f}, pnl={pnl:.2f}. "
                    f"Используем equity-based расчет."
                )
                # Используем equity-based расчет для малых позиций
                available_margin = max(
                    0, equity - margin_used * 0.9
                )  # Оставляем 10% запас

        # ✅ ОПТИМИЗАЦИЯ: Логируем только при изменениях или проблемах (не каждый раз)
        # Убрано избыточное DEBUG логирование каждой проверки (экономия ~20% логов)
        # Можно включить обратно при необходимости отладки margin проблем
        # logger.debug(f"🔍 margin_calculator: equity={equity:.2f}, pnl={pnl:.2f}, margin_used={margin_used:.2f}")

        # Расчет коэффициента маржи
        # margin_ratio показывает, во сколько раз доступная маржа превышает использованную
        # Если available_margin < 0, то margin_ratio будет отрицательным = риск ликвидации!
        if margin_used > 0:
            margin_ratio = available_margin / margin_used
        else:
            margin_ratio = float("inf") if available_margin > 0 else float("-inf")

        logger.debug(
            f"🔍 margin_calculator: margin_ratio={margin_ratio:.2f} (до защиты)"
        )

        # 🛡️ УЛУЧШЕННАЯ ЗАЩИТА от ложных срабатываний:
        # Если margin_ratio отрицательный, но PnL небольшой (< 15% от equity),
        # это может быть ошибка расчета, а не реальный риск
        # Также проверяем что equity > 0 (если нет - это явная ошибка)
        if margin_ratio < 0 and equity > 0:
            pnl_percent = abs(pnl) / equity if equity > 0 else 0
            # ⚠️ УВЕЛИЧЕН ПОРОГ: Если PnL менее 15% от баланса, а margin_ratio отрицательный - вероятна ошибка
            # Также проверяем, что available_margin не слишком отрицательный относительно equity
            margin_deficit_percent = abs(available_margin) / equity if equity > 0 else 0

            # ✅ ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Для малых позиций более строгая проверка
            is_small_position = margin_used < 5.0
            pnl_threshold = (
                0.20 if is_small_position else 0.15
            )  # Для малых позиций порог выше
            deficit_threshold = (
                1.5 if is_small_position else 2.0
            )  # Для малых позиций более строгий порог

            if (
                pnl_percent < pnl_threshold
                and margin_deficit_percent < deficit_threshold
            ):  # Дефицит маржи в пределах разумного
                logger.debug(
                    f"⚠️ Подозрительный margin_ratio={margin_ratio:.2f} исправлен: "
                    f"available_margin={available_margin:.2f}, pnl={pnl:.2f} ({pnl_percent:.2%} от баланса), "
                    f"дефицит={margin_deficit_percent:.2%}, малая позиция={is_small_position}. "
                    f"Используем безопасное значение."
                )
                # Используем более консервативный расчет: просто equity / margin_used
                margin_ratio = equity / margin_used if margin_used > 0 else float("inf")

                # ✅ ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА: Если margin_ratio все еще отрицательный или очень мал,
                # устанавливаем минимальное безопасное значение
                if margin_ratio < 0.5:
                    logger.warning(
                        f"⚠️ margin_ratio={margin_ratio:.2f} все еще подозрительно низкий после исправления. "
                        f"Устанавливаем минимальное безопасное значение 1.0"
                    )
                    margin_ratio = 1.0  # Минимальное безопасное значение

        # Проверка безопасности
        is_safe = margin_ratio >= safety_threshold

        # Расчет цены ликвидации
        liquidation_price = self.calculate_liquidation_price(
            side, entry_price, position_size, equity, leverage
        )

        details = {
            "margin_ratio": margin_ratio,
            "available_margin": available_margin,
            "margin_used": margin_used,
            "pnl": pnl,
            "equity": equity,  # ✅ Добавляем equity для защит
            "liquidation_price": liquidation_price,
            "safety_threshold": safety_threshold,
            "distance_to_liquidation": abs(current_price - liquidation_price)
            / current_price
            * 100,
        }

        logger.info(
            f"Проверка безопасности позиции: safe={is_safe}, "
            f"margin_ratio={margin_ratio:.2f}, pnl={pnl:.2f}, "
            f"liq_price={liquidation_price:.4f}"
        )

        return is_safe, details

    def calculate_optimal_position_size(
        self,
        equity: float,
        current_price: float,
        risk_percentage: Optional[float] = None,
        leverage: Optional[int] = None,
        regime: Optional[str] = None,
        trading_statistics=None,
    ) -> float:
        """
        Расчет оптимального размера позиции с учетом риска и Kelly Criterion

        Args:
            equity: Доступный баланс
            current_price: Текущая цена
            risk_percentage: Процент риска от баланса (2%)
            leverage: Плечо
            regime: Режим рынка (для адаптации)
            trading_statistics: Модуль статистики для Kelly Criterion

        Returns:
            Оптимальный размер позиции
        """
        if leverage is None:
            leverage = self.default_leverage

        # ✅ АДАПТИВНО: Получаем risk_percentage из конфига по режиму
        # ПРИОРИТЕТ: конфиг -> fallback (сначала пытаемся из конфига, только если нет - fallback)
        if risk_percentage is None:
            try:
                if hasattr(self, "margin_config") and self.margin_config:
                    if isinstance(self.margin_config, dict):
                        by_regime = self.margin_config.get("by_regime", {})
                        if regime and by_regime:
                            regime_config = by_regime.get(regime.lower(), {})
                            if isinstance(regime_config, dict):
                                risk_percentage = regime_config.get("risk_percentage")
                                if risk_percentage is not None:
                                    logger.debug(
                                        f"✅ Загружен risk_percentage={risk_percentage} из конфига (regime={regime})"
                                    )
                    else:
                        by_regime = getattr(self.margin_config, "by_regime", None)
                        if by_regime and regime:
                            regime_config = getattr(by_regime, regime.lower(), None)
                            if regime_config:
                                risk_percentage = getattr(
                                    regime_config, "risk_percentage", None
                                )
                                if risk_percentage is not None:
                                    logger.debug(
                                        f"✅ Загружен risk_percentage={risk_percentage} из конфига (regime={regime})"
                                    )
            except Exception as e:
                logger.debug(f"⚠️ Не удалось получить адаптивный risk_percentage: {e}")

            # Fallback только если не удалось загрузить из конфига
            if risk_percentage is None:
                risk_percentage = 0.02  # Fallback 2%
                logger.debug(
                    f"⚠️ Используется fallback risk_percentage={risk_percentage}"
                )

        # ✅ НОВОЕ: Kelly Criterion для оптимизации размера позиции
        kelly_multiplier = 1.0
        if trading_statistics and regime:
            try:
                # ✅ ИСПРАВЛЕНО: Получаем статистику по режиму (символ не передается, используем общую статистику по режиму)
                # Это нормально, так как Kelly Criterion работает на уровне режима, а не символа
                win_rate = trading_statistics.get_win_rate(regime)
                avg_win, avg_loss = trading_statistics.get_avg_pnl(regime)

                # Kelly Criterion: f = (p * b - q) / b
                # где:
                #   p = win_rate (вероятность выигрыша)
                #   q = 1 - p (вероятность проигрыша)
                #   b = avg_win / abs(avg_loss) (risk/reward ratio)
                if avg_loss != 0 and abs(avg_loss) > 0.01:  # Избегаем деления на ноль
                    risk_reward_ratio = (
                        abs(avg_win / avg_loss) if avg_loss != 0 else 1.0
                    )
                    q = 1.0 - win_rate

                    # Kelly fraction
                    if risk_reward_ratio > 0:
                        kelly_fraction = (
                            win_rate * risk_reward_ratio - q
                        ) / risk_reward_ratio
                    else:
                        kelly_fraction = 0.0

                    # Ограничиваем Kelly (используем 25% от Kelly для безопасности)
                    # Если Kelly отрицательный - не торгуем (или очень маленький размер)
                    if kelly_fraction > 0:
                        kelly_fraction_safe = min(
                            kelly_fraction * 0.25, 0.1
                        )  # Максимум 10% от баланса
                        # Применяем множитель к risk_percentage
                        kelly_multiplier = max(
                            0.5, min(2.0, kelly_fraction_safe / risk_percentage)
                        )
                        logger.debug(
                            f"📊 Kelly Criterion для {regime}: "
                            f"win_rate={win_rate:.2%}, avg_win={avg_win:.2f}, avg_loss={avg_loss:.2f}, "
                            f"R/R={risk_reward_ratio:.2f}, kelly={kelly_fraction:.3f}, "
                            f"multiplier={kelly_multiplier:.2f}x"
                        )
                    else:
                        # Отрицательный Kelly - снижаем размер позиции
                        kelly_multiplier = 0.5
                        logger.debug(
                            f"⚠️ Kelly Criterion отрицательный для {regime} "
                            f"(win_rate={win_rate:.2%}, R/R={risk_reward_ratio:.2f}), "
                            f"снижаем размер позиции (multiplier={kelly_multiplier:.2f}x)"
                        )
            except Exception as e:
                logger.debug(
                    f"⚠️ Ошибка расчета Kelly Criterion: {e}, используем базовый risk_percentage"
                )

        # Максимальный риск в USDT (с учетом Kelly)
        adjusted_risk_percentage = risk_percentage * kelly_multiplier
        max_risk_usdt = equity * adjusted_risk_percentage

        # Максимальная позиция с учетом риска
        max_position_value = max_risk_usdt * leverage
        optimal_position_size = max_position_value / current_price

        logger.info(
            f"Расчет оптимальной позиции: equity={equity:.2f}, "
            f"risk={risk_percentage:.1%}, kelly_mult={kelly_multiplier:.2f}x, "
            f"adjusted_risk={adjusted_risk_percentage:.1%}, leverage={leverage}x, "
            f"optimal_size={optimal_position_size:.6f}"
        )

        return optimal_position_size

    def get_margin_health_status(
        self, equity: float, total_margin_used: float, regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получение статуса здоровья маржи

        Args:
            equity: Общий баланс
            total_margin_used: Общая использованная маржа

        Returns:
            Статус здоровья маржи
        """
        if total_margin_used == 0:
            return {
                "status": "excellent",
                "level": 100.0,
                "message": "Нет открытых позиций",
            }

        margin_ratio = equity / total_margin_used

        # ✅ АДАПТИВНО: Получаем пороги здоровья маржи из конфига по режиму
        thresholds = {
            "excellent": 3.0,
            "good": 2.0,
            "warning": 1.5,
            "danger": 1.2,
        }
        try:
            if hasattr(self, "margin_config") and self.margin_config:
                if isinstance(self.margin_config, dict):
                    by_regime = self.margin_config.get("by_regime", {})
                    if regime and by_regime:
                        regime_config = by_regime.get(regime.lower(), {})
                        if isinstance(regime_config, dict):
                            health_thresholds = regime_config.get(
                                "margin_health_thresholds", {}
                            )
                            if isinstance(health_thresholds, dict):
                                thresholds = health_thresholds
                else:
                    by_regime = getattr(self.margin_config, "by_regime", None)
                    if by_regime and regime:
                        regime_config = getattr(by_regime, regime.lower(), None)
                        if regime_config:
                            health_thresholds = getattr(
                                regime_config, "margin_health_thresholds", None
                            )
                            if health_thresholds:
                                thresholds = {
                                    "excellent": getattr(
                                        health_thresholds, "excellent", 3.0
                                    ),
                                    "good": getattr(health_thresholds, "good", 2.0),
                                    "warning": getattr(
                                        health_thresholds, "warning", 1.5
                                    ),
                                    "danger": getattr(health_thresholds, "danger", 1.2),
                                }
        except Exception as e:
            logger.debug(
                f"⚠️ Не удалось получить адаптивные пороги здоровья маржи: {e}, используем fallback"
            )

        if margin_ratio >= thresholds["excellent"]:
            status = "excellent"
            message = "Отличное состояние маржи"
        elif margin_ratio >= thresholds["good"]:
            status = "good"
            message = "Хорошее состояние маржи"
        elif margin_ratio >= thresholds["warning"]:
            status = "warning"
            message = "Предупреждение: низкая маржа"
        elif margin_ratio >= thresholds["danger"]:
            status = "danger"
            message = "ОПАСНО: критически низкая маржа"
        else:
            status = "critical"
            message = "КРИТИЧНО: риск ликвидации!"

        return {
            "status": status,
            "level": margin_ratio,
            "message": message,
            "equity": equity,
            "margin_used": total_margin_used,
            "available_margin": equity - total_margin_used,
        }


# Пример использования
if __name__ == "__main__":
    # Создаем калькулятор
    calculator = MarginCalculator(default_leverage=3)

    # Тестовые данные
    equity = 1000.0  # 1000 USDT
    current_price = 50000.0  # BTC цена
    entry_price = 49500.0  # Цена входа

    # Расчеты
    max_size = calculator.calculate_max_position_size(equity, current_price)
    print(f"Максимальный размер позиции: {max_size:.6f} BTC")

    # Проверка безопасности
    position_value = 1000.0  # 1000 USDT позиция
    is_safe, details = calculator.is_position_safe(
        position_value, equity, current_price, entry_price, "buy"
    )
    print(f"Позиция безопасна: {is_safe}")
    print(f"Детали: {details}")
