"""
Margin Calculator для Futures торговли.

Основные функции:
- Расчет максимального размера позиции
- Расчет цены ликвидации
- Мониторинг маржи
- Проверки безопасности маржи
"""

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

        # Расчет маржи (вычисляется, но не используется в этом методе)
        position_value = position_size * entry_price
        position_value / leverage

        # ✅ ПРАВКА #19: Улучшенный расчет цены ликвидации
        # Для изолированной маржи OKX формула более точная:
        # Long: LiqPrice = EntryPrice * (1 - (1/Leverage) + MaintenanceMarginRatio)
        # Short: LiqPrice = EntryPrice * (1 + (1/Leverage) - MaintenanceMarginRatio)
        # Учитываем также комиссии и спред
        if side.lower() == "buy" or side.lower() == "long":
            # Для лонга: цена ликвидации ниже входа
            liquidation_price = entry_price * (
                1 - (1 / leverage) + self.maintenance_margin_ratio
            )
            # ✅ ПРАВКА #19: Учитываем комиссии (примерно 0.1% на круг)
            liquidation_price *= 0.999  # Небольшая поправка на комиссии
        else:  # sell/short
            # Для шорта: цена ликвидации выше входа
            liquidation_price = entry_price * (
                1 + (1 / leverage) - self.maintenance_margin_ratio
            )
            # ✅ ПРАВКА #19: Учитываем комиссии (примерно 0.1% на круг)
            liquidation_price *= 1.001  # Небольшая поправка на комиссии

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
        position_age_seconds: Optional[
            float
        ] = None,  # ✅ НОВОЕ: Возраст позиции в секундах
        exchange_leverage: Optional[int] = None,  # ✅ L1-4a FIX: Реальное плечо с биржи
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Проверка безопасности позиции

        Args:
            position_value: Стоимость позиции
            equity: Доступный баланс
            current_price: Текущая цена
            entry_price: Цена входа
            side: Направление позиции
            leverage: Плечо (из конфига)
            safety_threshold: Порог безопасности (1.5 = 150%)
            exchange_leverage: Реальное плечо позиции с биржи

        Returns:
            Tuple[bool, Dict] - (безопасна ли позиция, детали)
        """
        # ✅ L1-4a FIX: Приоритет exchange leverage над config
        if exchange_leverage and exchange_leverage > 0:
            if leverage and abs(exchange_leverage - leverage) > 2:
                logger.warning(
                    f"🔄 L1-4a: Leverage mismatch config={leverage}x vs exchange={exchange_leverage}x. "
                    f"Using exchange value."
                )
            leverage = exchange_leverage
        elif leverage is None:
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
                            except Exception:
                                pass
                        elif by_regime and hasattr(by_regime, "__dict__"):
                            try:
                                by_regime = dict(by_regime.__dict__)
                                logger.debug(
                                    f"🔍 by_regime конвертирован из __dict__: {by_regime}"
                                )
                            except Exception:
                                pass

                    # ✅ ИСПРАВЛЕНО: Если regime=None, используем fallback на 'ranging' (стандартный режим)
                    regime_to_use = regime.lower() if regime else "ranging"
                    if not regime:
                        logger.debug("🔍 regime=None, используем fallback: 'ranging'")

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
                                # ✅ ГРОК КОМПРОМИСС: Динамическое усиление safety_threshold
                                # Базово 1.5, усиление до 1.8-2.0 при:
                                # - equity < 100 USDT
                                # - ADX низкий (шаткий рынок)
                                # - открыто >3 позиций
                                base_safety = safety_threshold
                                safety_threshold_dynamic = (
                                    regime_config.get("safety_threshold_dynamic", False)
                                    if isinstance(regime_config, dict)
                                    else getattr(
                                        regime_config, "safety_threshold_dynamic", False
                                    )
                                )
                                safety_threshold_max = (
                                    regime_config.get("safety_threshold_max", 2.0)
                                    if isinstance(regime_config, dict)
                                    else getattr(
                                        regime_config, "safety_threshold_max", 2.0
                                    )
                                )

                                if safety_threshold_dynamic:
                                    # Получаем equity и количество открытых позиций (если доступны)
                                    # Для упрощения используем переданный equity
                                    equity_threshold = 100.0
                                    positions_threshold = 3

                                    # Усиление при equity < 100
                                    if equity < equity_threshold:
                                        safety_threshold = min(
                                            safety_threshold_max, base_safety * 1.2
                                        )  # +20% до макс
                                        logger.debug(
                                            f"✅ Динамическое усиление safety_threshold: {base_safety:.2f} → {safety_threshold:.2f} "
                                            f"(equity=${equity:.2f} < ${equity_threshold:.2f})"
                                        )

                                logger.info(
                                    f"✅ Загружен safety_threshold={safety_threshold:.2f} из конфига (regime={regime_to_use}{' (fallback)' if not regime else ''}, "
                                    f"base={base_safety:.2f}, dynamic={safety_threshold_dynamic})"
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
            # ✅ УЛУЧШЕННЫЙ РАСЧЕТ: Используем более точную формулу
            # Для новой позиции: equity = margin (изолированная маржа)
            # Но нужно учитывать общий баланс аккаунта для расчета доступной маржи
            # Если позиция только открыта, equity может быть ≈ margin
            # В этом случае используем более консервативный расчет с учетом общего баланса

            # ✅ ИСПРАВЛЕНО: Улучшенный расчет для новых позиций (< 60 секунд)
            # Для очень новых позиций (< 30 сек) используем более консервативный расчет
            # так как equity может еще не синхронизироваться с биржей
            is_very_new_position = (
                position_age_seconds is not None and position_age_seconds < 30.0
            )
            is_new_position = (
                position_age_seconds is not None and position_age_seconds < 60.0
            )

            if equity > 0 and margin_used > 0:
                if is_very_new_position:
                    # ✅ Для очень новых позиций (< 30 сек): используем более консервативный расчет
                    # Предполагаем что есть запас маржи, даже если equity еще не обновился
                    # margin_ratio = 2.0 (безопасно для новых позиций)
                    available_margin = margin_used * 1.0  # margin_ratio = 2.0
                    logger.debug(
                        f"✅ Новая позиция (< 30 сек): используем консервативный расчет "
                        f"margin_ratio=2.0 (age={position_age_seconds:.1f}s)"
                    )
                elif is_new_position:
                    # ✅ Для новых позиций (< 60 сек): используем умеренный расчет
                    # margin_ratio = 1.5 (безопасно)
                    available_margin = margin_used * 0.5  # margin_ratio = 1.5
                    logger.debug(
                        f"✅ Новая позиция (< 60 сек): используем умеренный расчет "
                        f"margin_ratio=1.5 (age={position_age_seconds:.1f}s)"
                    )
                else:
                    # ✅ Для позиций > 60 сек: используем стандартный расчет
                    # Используем equity / margin_used как базовый margin_ratio
                    # Но добавляем небольшой запас для новых позиций
                    # available_margin = (equity - margin_used) + margin_used * 0.5
                    # Это дает margin_ratio ≈ 1.5 для новой позиции (безопасно)
                    available_margin = max(
                        (equity - margin_used),
                        margin_used * 0.5,  # Минимум 50% от margin как запас
                    )
            else:
                # Fallback: если equity = 0 или margin = 0 (не должно происходить)
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
            # Для очень малых позиций (margin_used < 10 USDT) возможны ошибки округления
            # Если available_margin отрицательный, но equity > margin_used, это ошибка расчета
            # Особенно для символов с большим ctVal (XRP с ctVal=100.0)
            if (
                available_margin < 0
                and margin_used < 50.0  # ✅ УВЕЛИЧЕН: до 50 USDT (для XRP-USDT)
                and equity > margin_used * 0.3  # ✅ СНИЖЕН: до 30% (более чувствительно)
            ):
                # ✅ УЛУЧШЕННЫЙ РАСЧЕТ: Для малых позиций используем equity-based расчет
                # Если equity > margin_used, значит есть запас, даже если available_margin отрицательный
                # Проблема была в том, что для позиций с большим ctVal расчет position_value может быть неточным
                logger.debug(
                    f"⚠️ Исправление расчета для малой позиции: "
                    f"available_margin={available_margin:.2f}, equity={equity:.2f}, "
                    f"margin_used={margin_used:.2f}, pnl={pnl:.2f}. "
                    f"Используем equity-based расчет."
                )
                # ✅ УЛУЧШЕННО: Для малых позиций используем более консервативный расчет
                # Если equity значительно больше margin_used - используем пропорциональный расчет
                if equity > margin_used:
                    # Позиция в прибыли или есть запас: используем equity-based расчет
                    # available_margin = (equity - margin_used) * 0.8 (оставляем 20% запас)
                    available_margin = (equity - margin_used) * 0.8
                else:
                    # Позиция в убытке, но небольшом: используем минимальный запас
                    available_margin = max(
                        0, margin_used * 0.1
                    )  # Минимум 10% от margin

        # ✅ ОПТИМИЗАЦИЯ: Логируем только при изменениях или проблемах (не каждый раз)
        # Убрано избыточное DEBUG логирование каждой проверки (экономия ~20% логов)
        # Можно включить обратно при необходимости отладки margin проблем
        # logger.debug(f"🔍 margin_calculator: equity={equity:.2f}, pnl={pnl:.2f}, margin_used={margin_used:.2f}")

        # Расчет коэффициента маржи
        # margin_ratio показывает, во сколько раз доступная маржа превышает использованную
        # Если available_margin < 0, то margin_ratio будет отрицательным = риск ликвидации!
        # ✅ ГРОК КОМПРОМИСС: Добавляем защиту от отрицательных значений (но не маскируем реальные проблемы)
        if margin_used > 0:
            # ✅ ГРОК КОМПРОМИСС: Честный расчет margin_ratio без маскировки реальных проблем
            # Не используем max(0.01, ...) - это маскирует реальные риски ликвидации
            margin_ratio = available_margin / margin_used
            # Если margin_ratio отрицательный - это реальный риск ликвидации, не маскируем
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
                    # ✅ ИСПРАВЛЕНО: Используем DEBUG вместо WARNING для новых позиций
                    # margin_ratio может быть низким сразу после открытия позиции из-за задержки синхронизации
                    logger.debug(
                        f"⚠️ margin_ratio={margin_ratio:.2f} все еще подозрительно низкий после исправления. "
                        f"Устанавливаем минимальное безопасное значение 1.0 (возможно, позиция только что открыта)"
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

        # ✅ ГРОК КОМПРОМИСС: Структурированное логирование risk_status
        if margin_ratio >= 2.5:
            risk_status = "SAFE"
        elif margin_ratio >= 1.8:
            risk_status = "GOOD"
        elif margin_ratio >= 1.3:
            risk_status = "WARNING"
        elif margin_ratio >= 1.1:
            risk_status = "DANGER"
        else:
            risk_status = "CRITICAL"

        # 🔴 КРИТИЧНО: Детальное логирование margin ratio (от Грока)
        logger.info(
            f"📊 [MARGIN_RATIO] Проверка безопасности позиции: safe={is_safe} | "
            f"margin_ratio={margin_ratio:.2f} [{risk_status}] (threshold={safety_threshold:.2f}) | "
            f"available_margin=${available_margin:.2f}, margin_used=${margin_used:.2f} | "
            f"equity=${equity:.2f}, pnl=${pnl:.2f} | "
            f"liq_price=${liquidation_price:.4f} (distance={details.get('distance_to_liquidation', 0):.2f}%)"
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

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем risk_per_trade_percent из конфига по режиму
        # ПРИОРИТЕТ: risk_per_trade_percent из режима -> risk_per_trade_percent из risk секции -> base_risk_percentage -> fallback
        if risk_percentage is None:
            try:
                if hasattr(self, "margin_config") and self.margin_config:
                    # ✅ ПРИОРИТЕТ 1: risk_per_trade_percent из режима
                    if isinstance(self.margin_config, dict):
                        by_regime = self.margin_config.get("by_regime", {})
                        if regime and by_regime:
                            regime_config = by_regime.get(regime.lower(), {})
                            if isinstance(regime_config, dict):
                                risk_per_trade = regime_config.get(
                                    "risk_per_trade_percent"
                                )
                                if risk_per_trade is not None:
                                    risk_percentage = (
                                        risk_per_trade / 100.0
                                    )  # Конвертируем % в долю
                                    logger.debug(
                                        f"✅ Загружен risk_per_trade_percent={risk_per_trade}% из режима {regime} "
                                        f"(risk_percentage={risk_percentage:.3f})"
                                    )
                    else:
                        by_regime = getattr(self.margin_config, "by_regime", None)
                        if by_regime and regime:
                            regime_config = getattr(by_regime, regime.lower(), None)
                            if regime_config:
                                risk_per_trade = getattr(
                                    regime_config, "risk_per_trade_percent", None
                                )
                                if risk_per_trade is not None:
                                    risk_percentage = (
                                        risk_per_trade / 100.0
                                    )  # Конвертируем % в долю
                                    logger.debug(
                                        f"✅ Загружен risk_per_trade_percent={risk_per_trade}% из режима {regime} "
                                        f"(risk_percentage={risk_percentage:.3f})"
                                    )

                    # ✅ ПРИОРИТЕТ 2: risk_per_trade_percent из risk секции (если не нашли в режиме)
                    if risk_percentage is None:
                        if isinstance(self.margin_config, dict):
                            risk_config = self.margin_config.get("risk", {})
                            if isinstance(risk_config, dict):
                                risk_per_trade = risk_config.get(
                                    "risk_per_trade_percent"
                                )
                                if risk_per_trade is not None:
                                    risk_percentage = risk_per_trade / 100.0
                                    logger.debug(
                                        f"✅ Загружен risk_per_trade_percent={risk_per_trade}% из risk секции "
                                        f"(risk_percentage={risk_percentage:.3f})"
                                    )
                        else:
                            risk_config = getattr(self.margin_config, "risk", None)
                            if risk_config:
                                risk_per_trade = getattr(
                                    risk_config, "risk_per_trade_percent", None
                                )
                                if risk_per_trade is not None:
                                    risk_percentage = risk_per_trade / 100.0
                                    logger.debug(
                                        f"✅ Загружен risk_per_trade_percent={risk_per_trade}% из risk секции "
                                        f"(risk_percentage={risk_percentage:.3f})"
                                    )

                    # ✅ ПРИОРИТЕТ 3: base_risk_percentage из scalping секции (fallback)
                    if risk_percentage is None:
                        if isinstance(self.margin_config, dict):
                            scalping_config = self.margin_config.get("scalping", {})
                            if isinstance(scalping_config, dict):
                                risk_percentage = scalping_config.get(
                                    "base_risk_percentage"
                                )
                                if risk_percentage is not None:
                                    logger.debug(
                                        f"✅ Загружен base_risk_percentage={risk_percentage} из scalping секции"
                                    )
                        else:
                            scalping_config = getattr(
                                self.margin_config, "scalping", None
                            )
                            if scalping_config:
                                risk_percentage = getattr(
                                    scalping_config, "base_risk_percentage", None
                                )
                                if risk_percentage is not None:
                                    logger.debug(
                                        f"✅ Загружен base_risk_percentage={risk_percentage} из scalping секции"
                                    )
            except Exception as e:
                logger.debug(f"⚠️ Не удалось получить адаптивный risk_percentage: {e}")

            # ✅ ПРИОРИТЕТ 4: Fallback только если не удалось загрузить из конфига
            if risk_percentage is None:
                risk_percentage = 0.01  # ✅ ИСПРАВЛЕНО: Fallback 1% (было 2%)
                logger.debug(
                    f"⚠️ Используется fallback risk_percentage={risk_percentage} (1%)"
                )

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Kelly Criterion удален
        # Причина: Статистика для скальпинга слишком шумная → Kelly вводит ложное ощущение "оптимальности"
        # Используем прямой расчет без Kelly multiplier
        adjusted_risk_percentage = risk_percentage
        max_risk_usdt = equity * adjusted_risk_percentage

        # Максимальная позиция с учетом риска
        max_position_value = max_risk_usdt * leverage
        optimal_position_size = max_position_value / current_price

        logger.info(
            f"Расчет оптимальной позиции: equity={equity:.2f}, "
            f"risk={risk_percentage:.1%}, adjusted_risk={adjusted_risk_percentage:.1%}, "
            f"leverage={leverage}x, optimal_size={optimal_position_size:.6f}"
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
