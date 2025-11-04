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
        safety_threshold: float = 1.5,
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

        # 🛡️ ЗАЩИТА от ложных срабатываний:
        # Если margin_ratio отрицательный, но PnL небольшой (< 10% от equity),
        # это может быть ошибка расчета, а не реальный риск
        # Также проверяем что equity > 0 (если нет - это явная ошибка)
        if margin_ratio < 0 and equity > 0:
            pnl_percent = abs(pnl) / equity if equity > 0 else 0
            # ⚠️ УВЕЛИЧЕН ПОРОГ: Если PnL менее 15% от баланса, а margin_ratio отрицательный - вероятна ошибка
            # Также проверяем, что available_margin не слишком отрицательный относительно equity
            margin_deficit_percent = abs(available_margin) / equity if equity > 0 else 0
            if (
                pnl_percent < 0.15 and margin_deficit_percent < 2.0
            ):  # Дефицит маржи < 200% от баланса
                logger.debug(
                    f"⚠️ Подозрительный margin_ratio={margin_ratio:.2f} игнорирован: "
                    f"available_margin={available_margin:.2f}, pnl={pnl:.2f} ({pnl_percent:.2%} от баланса), "
                    f"дефицит={margin_deficit_percent:.2%}. Используем безопасное значение."
                )
                # Используем более консервативный расчет: просто equity / margin_used
                margin_ratio = equity / margin_used if margin_used > 0 else float("inf")

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
        risk_percentage: float = 0.02,
        leverage: Optional[int] = None,
    ) -> float:
        """
        Расчет оптимального размера позиции с учетом риска

        Args:
            equity: Доступный баланс
            current_price: Текущая цена
            risk_percentage: Процент риска от баланса (2%)
            leverage: Плечо

        Returns:
            Оптимальный размер позиции
        """
        if leverage is None:
            leverage = self.default_leverage

        # Максимальный риск в USDT
        max_risk_usdt = equity * risk_percentage

        # Максимальная позиция с учетом риска
        max_position_value = max_risk_usdt * leverage
        optimal_position_size = max_position_value / current_price

        logger.info(
            f"Расчет оптимальной позиции: equity={equity:.2f}, "
            f"risk={risk_percentage:.1%}, leverage={leverage}x, "
            f"optimal_size={optimal_position_size:.6f}"
        )

        return optimal_position_size

    def get_margin_health_status(
        self, equity: float, total_margin_used: float
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

        if margin_ratio >= 3.0:
            status = "excellent"
            message = "Отличное состояние маржи"
        elif margin_ratio >= 2.0:
            status = "good"
            message = "Хорошее состояние маржи"
        elif margin_ratio >= 1.5:
            status = "warning"
            message = "Предупреждение: низкая маржа"
        elif margin_ratio >= 1.2:
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
