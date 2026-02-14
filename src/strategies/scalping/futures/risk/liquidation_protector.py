"""
LiquidationProtector - защита от ликвидации позиций.

✅ ИСПРАВЛЕНИЕ #18 (04.01.2026): Реализован STUB модуль LiquidationProtector
"""

from typing import Any, Dict, Optional, Tuple

from loguru import logger


class LiquidationProtector:
    """
    Защита от ликвидации позиций.

    Проверяет риск ликвидации на основе:
    - Текущей маржи
    - Размера позиции
    - Цены ликвидации
    - Волатильности рынка
    """

    def __init__(
        self,
        config_manager=None,
        margin_calculator=None,
        config: Optional[dict] = None,
    ):
        """
        Инициализация LiquidationProtector.

        Args:
            config_manager: ConfigManager для получения параметров (опционально)
            margin_calculator: MarginCalculator для расчета ликвидации (опционально)
            config: Конфигурация защиты от ликвидации (опционально, для обратной совместимости)
        """
        self.config_manager = config_manager
        self.margin_calculator = margin_calculator
        self.config = config or {}

        # Порог безопасности: минимальное расстояние до ликвидации (50% от ликвидационной цены)
        # ✅ ИСПРАВЛЕНО: config может быть Pydantic моделью или словарем
        if isinstance(self.config, dict):
            self.safety_threshold = self.config.get("safety_threshold", 0.5)  # 50%
        else:
            # Если это Pydantic модель, используем getattr
            self.safety_threshold = getattr(self.config, "safety_threshold", 0.5)  # 50%

        logger.info(
            f"✅ LiquidationProtector инициализирован "
            f"(safety_threshold={self.safety_threshold:.1%})"
        )

    async def check_liquidation_risk(
        self,
        symbol: str,
        position: Dict[str, Any],
        balance: float,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Проверяет риск ликвидации позиции.

        Args:
            symbol: Торговый символ
            position: Данные позиции (содержит side, size, entry_price, mark_price, margin)
            balance: Текущий баланс

        Returns:
            Tuple[bool, Dict]: (is_safe, details)
            - is_safe: True если риск ликвидации приемлем, False если высокий риск
            - details: Детали проверки (liquidation_price, current_price, distance_pct, etc.)
        """
        try:
            if not self.margin_calculator:
                logger.warning(
                    f"⚠️ LiquidationProtector: margin_calculator не доступен для {symbol}, "
                    f"позиция считается безопасной"
                )
                return True, {
                    "safe": True,
                    "reason": "margin_calculator_not_available",
                    "symbol": symbol,
                }

            # Получаем данные позиции
            position_side = position.get(
                "posSide", position.get("side", "long")
            ).lower()
            entry_price = float(position.get("avgPx", position.get("entry_price", 0)))
            current_price = float(
                position.get(
                    "markPx",
                    position.get("mark_price", position.get("current_price", 0)),
                )
            )
            position_size = float(position.get("pos", position.get("size", 0)))
            margin_used = float(position.get("margin", position.get("margin_used", 0)))

            if entry_price <= 0 or current_price <= 0 or abs(position_size) < 1e-8:
                logger.warning(
                    f"⚠️ LiquidationProtector: Некорректные данные позиции для {symbol}, "
                    f"позиция считается небезопасной"
                )
                return False, {
                    "safe": False,
                    "reason": "invalid_position_data",
                    "symbol": symbol,
                }

            # Рассчитываем цену ликвидации
            try:
                liquidation_price = self.margin_calculator.calculate_liquidation_price(
                    side=position_side,
                    entry_price=entry_price,
                    position_size=abs(position_size),
                    equity=balance,
                    leverage=None,  # Используется из конфига
                )
            except Exception as e:
                logger.warning(
                    f"⚠️ LiquidationProtector: Ошибка расчета ликвидации для {symbol}: {e}"
                )
                return False, {
                    "safe": False,
                    "reason": "liquidation_calculation_error",
                    "error": str(e),
                    "symbol": symbol,
                }

            if liquidation_price <= 0:
                logger.warning(
                    f"⚠️ LiquidationProtector: Некорректная цена ликвидации для {symbol}, "
                    f"позиция считается небезопасной"
                )
                return False, {
                    "safe": False,
                    "reason": "invalid_liquidation_price",
                    "symbol": symbol,
                }

            # Рассчитываем расстояние до ликвидации в процентах
            if position_side == "long":
                distance_pct = (
                    (current_price - liquidation_price) / current_price
                ) * 100.0
            else:  # short
                distance_pct = (
                    (liquidation_price - current_price) / current_price
                ) * 100.0

            # Проверяем безопасность: расстояние должно быть больше safety_threshold
            safety_threshold_pct = self.safety_threshold * 100.0
            is_safe = distance_pct > safety_threshold_pct

            details = {
                "safe": is_safe,
                "liquidation_price": liquidation_price,
                "current_price": current_price,
                "entry_price": entry_price,
                "distance_pct": distance_pct,
                "safety_threshold_pct": safety_threshold_pct,
                "position_side": position_side,
                "margin_used": margin_used,
                "symbol": symbol,
            }

            if not is_safe:
                logger.warning(
                    f"🚨 LiquidationProtector: ВЫСОКИЙ РИСК ЛИКВИДАЦИИ для {symbol} "
                    f"{position_side.upper()}: расстояние до ликвидации {distance_pct:.2f}% < "
                    f"порога безопасности {safety_threshold_pct:.2f}% "
                    f"(liquidation={liquidation_price:.2f}, current={current_price:.2f})"
                )
            else:
                logger.debug(
                    f"✅ LiquidationProtector: Позиция {symbol} {position_side.upper()} безопасна: "
                    f"расстояние до ликвидации {distance_pct:.2f}% > порога {safety_threshold_pct:.2f}%"
                )

            return is_safe, details

        except Exception as e:
            logger.error(
                f"❌ LiquidationProtector: Ошибка проверки риска ликвидации для {symbol}: {e}",
                exc_info=True,
            )
            # В случае ошибки считаем позицию небезопасной
            return False, {
                "safe": False,
                "reason": "error",
                "error": str(e),
                "symbol": symbol,
            }

    # 🔴 BUG #20 FIX: УДАЛЕНА SYNC ВЕРСИЯ которая всегда возвращала True (отключала защиту)
    # था была на L197-224, теперь используется только async версия выше
    # async def check_liquidation_risk() - единственный правильный способ
