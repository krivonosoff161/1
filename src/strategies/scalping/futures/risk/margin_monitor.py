"""
MarginMonitor - мониторинг маржи для Futures торговли.

TODO: Реализовать полную функциональность мониторинга маржи.
"""

from typing import Any, Dict, Optional

from loguru import logger


class MarginMonitor:
    """
    Мониторинг маржи для Futures торговли.

    TODO: Реализовать проверку маржи на основе:
    - Текущего баланса
    - Использованной маржи
    - Доступной маржи
    - Уровня маржи (margin ratio)
    """

    def __init__(self, config: Optional[dict] = None):
        """
        Инициализация MarginMonitor.

        Args:
            config: Конфигурация мониторинга маржи (опционально)
        """
        self.config = config or {}

    def check_margin_available(
        self, required_margin: float, current_balance: float, used_margin: float
    ) -> tuple[bool, str]:
        """
        Проверяет доступность маржи для новой позиции.

        Args:
            required_margin: Требуемая маржа для новой позиции
            current_balance: Текущий баланс
            used_margin: Уже использованная маржа

        Returns:
            (allowed, reason) - можно ли открыть позицию и почему
        """
        available_margin = current_balance - used_margin

        if required_margin > available_margin:
            reason = (
                f"Недостаточно маржи: требуется {required_margin:.2f}, "
                f"доступно {available_margin:.2f}"
            )
            return False, reason

        reason = (
            f"✅ Маржа доступна: требуется {required_margin:.2f}, "
            f"доступно {available_margin:.2f}"
        )
        return True, reason

    def get_margin_ratio(self, current_balance: float, used_margin: float) -> float:
        """
        Вычисляет коэффициент использования маржи.

        Args:
            current_balance: Текущий баланс
            used_margin: Использованная маржа

        Returns:
            Коэффициент использования маржи (0.0 - 1.0)
        """
        if current_balance <= 0:
            return 1.0

        return min(1.0, used_margin / current_balance)

    async def check_safety(
        self,
        position_size_usd: float,
        current_positions: Dict[str, Any],
        orchestrator: Optional[Any] = None,  # ✅ Для доступа к балансу
        data_registry: Optional[Any] = None,  # ✅ Альтернативный источник данных
    ) -> bool:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Проверяет безопасность маржи перед открытием позиции.

        Args:
            position_size_usd: Размер новой позиции в USD
            current_positions: Текущие позиции (для расчета общей маржи)
            orchestrator: Orchestrator для доступа к балансу (опционально)
            data_registry: DataRegistry для чтения баланса (опционально)

        Returns:
            bool: True если безопасно
        """
        try:
            # ✅ Получаем баланс и маржу из доступных источников
            current_balance = 0.0
            used_margin = 0.0

            # Приоритет 1: Orchestrator
            if orchestrator:
                try:
                    if hasattr(orchestrator, "client") and orchestrator.client:
                        current_balance = await orchestrator.client.get_balance() or 0.0
                    if hasattr(orchestrator, "_get_used_margin"):
                        used_margin = await orchestrator._get_used_margin() or 0.0
                except Exception as e:
                    logger.debug(
                        f"⚠️ MarginMonitor: Не удалось получить баланс из orchestrator: {e}"
                    )

            # Приоритет 2: DataRegistry (из orchestrator ~300)
            if (current_balance == 0.0 or used_margin == 0.0) and data_registry:
                try:
                    margin_data = await data_registry.get_margin()
                    balance_data = await data_registry.get_balance()
                    if margin_data:
                        used_margin = margin_data.get("used", 0.0)
                    if balance_data:
                        current_balance = balance_data.get(
                            "equity", balance_data.get("total", 0.0)
                        )
                    logger.debug(
                        f"✅ MarginMonitor: Данные получены из data_registry "
                        f"(balance=${current_balance:.2f}, used_margin=${used_margin:.2f})"
                    )
                except Exception as e:
                    logger.debug(
                        f"⚠️ MarginMonitor: Не удалось получить баланс из data_registry: {e}"
                    )

            # Fallback: если не получили данные
            if current_balance == 0.0:
                logger.warning(
                    "⚠️ MarginMonitor: Не удалось получить баланс, используем fallback 1000.0"
                )
                current_balance = 1000.0  # Fallback

            # ✅ Рассчитываем требуемую маржу (с учетом leverage)
            leverage = self.config.get("leverage", 5)  # Из конфига или fallback
            required_margin = position_size_usd / leverage

            # ✅ Проверяем доступность маржи
            available, reason = self.check_margin_available(
                required_margin, current_balance, used_margin
            )

            # ✅ Проверяем коэффициент использования маржи
            margin_ratio = self.get_margin_ratio(
                current_balance, used_margin + required_margin
            )
            max_margin_ratio = self.config.get(
                "max_margin_ratio", 0.8
            )  # Из конфига или 80%

            if not available:
                logger.warning(f"❌ MarginMonitor: Margin unsafe: {reason}")
                return False

            if margin_ratio > max_margin_ratio:
                logger.warning(
                    f"❌ MarginMonitor: Margin ratio too high: {margin_ratio:.2%} > {max_margin_ratio:.2%} "
                    f"(balance=${current_balance:.2f}, used=${used_margin:.2f}, required=${required_margin:.2f})"
                )
                return False

            logger.debug(
                f"✅ MarginMonitor: Margin safe: ratio={margin_ratio:.2%} <= {max_margin_ratio:.2%}, "
                f"available=${current_balance - used_margin:.2f} >= required=${required_margin:.2f}"
            )
            return True

        except Exception as e:
            logger.error(f"❌ MarginMonitor: Error in check_safety: {e}", exc_info=True)
            return False  # Безопаснее блокировать при ошибке
