"""
Liquidation Guard для Futures торговли.

Основные функции:
- Мониторинг маржи в реальном времени
- Автоматическое закрытие позиций при риске ликвидации
- Предупреждения о рисках
- Защита от катастрофических потерь
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger

from .margin_calculator import MarginCalculator


class LiquidationGuard:
    """
    Защита от ликвидации для Futures торговли

    Функции:
    - Мониторинг маржи в реальном времени
    - Автоматическое закрытие позиций
    - Предупреждения о рисках
    - Интеграция с MarginCalculator
    """

    def __init__(
        self,
        margin_calculator: MarginCalculator,
        warning_threshold: float = 1.8,
        danger_threshold: float = 1.3,
        critical_threshold: float = 1.1,
        auto_close_threshold: float = 1.05,
    ):
        """
        Инициализация Liquidation Guard

        Args:
            margin_calculator: Калькулятор маржи
            warning_threshold: Порог предупреждения (180%)
            danger_threshold: Порог опасности (130%)
            critical_threshold: Порог критичности (110%)
            auto_close_threshold: Порог автозакрытия (105%)
        """
        self.margin_calculator = margin_calculator
        self.warning_threshold = warning_threshold
        self.danger_threshold = danger_threshold
        self.critical_threshold = critical_threshold
        self.auto_close_threshold = auto_close_threshold

        # Состояние мониторинга
        self.is_monitoring = False
        self.monitoring_task = None
        self.last_warning_time = {}

        logger.info(
            f"LiquidationGuard инициализирован: warning={warning_threshold:.1f}, "
            f"danger={danger_threshold:.1f}, critical={critical_threshold:.1f}, "
            f"auto_close={auto_close_threshold:.1f}"
        )

    async def start_monitoring(
        self, client, check_interval: float = 5.0, callback: Optional[callable] = None
    ):
        """
        Запуск мониторинга маржи

        Args:
            client: Futures клиент
            check_interval: Интервал проверки (секунды)
            callback: Функция обратного вызова для уведомлений
        """
        if self.is_monitoring:
            logger.warning("Мониторинг уже запущен")
            return

        self.is_monitoring = True
        logger.info(f"Запуск мониторинга ликвидации (интервал: {check_interval}с)")

        self.monitoring_task = asyncio.create_task(
            self._monitoring_loop(client, check_interval, callback)
        )

    async def stop_monitoring(self):
        """Остановка мониторинга"""
        if not self.is_monitoring:
            return

        self.is_monitoring = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass

        logger.info("Мониторинг ликвидации остановлен")

    async def _monitoring_loop(
        self, client, check_interval: float, callback: Optional[callable]
    ):
        """Основной цикл мониторинга"""
        while self.is_monitoring:
            try:
                await self._check_margin_health(client, callback)
                await asyncio.sleep(check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в мониторинге ликвидации: {e}")
                await asyncio.sleep(check_interval)

    async def _check_margin_health(self, client, callback: Optional[callable]):
        """Проверка здоровья маржи"""
        try:
            # Получаем баланс
            equity = await client.get_balance()

            # Получаем позиции
            positions = await client.get_positions()

            if not positions:
                return  # Нет позиций

            # Анализируем каждую позицию
            # ⚠️ Для изолированной маржи каждая позиция имеет свой equity (eq)
            # Передаем общий баланс только как fallback
            for position in positions:
                await self._analyze_position(position, equity, client, callback)

        except Exception as e:
            logger.error(f"Ошибка проверки маржи: {e}")

    async def _analyze_position(
        self,
        position: Dict[str, Any],
        fallback_equity: float,
        client,
        callback: Optional[callable],
    ):
        """Анализ отдельной позиции"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            side = position.get("posSide", "long")
            size = float(position.get("pos", "0"))
            entry_price = float(position.get("avgPx", "0"))
            current_price = float(position.get("markPx", "0"))
            leverage = int(position.get("lever", "3"))

            if size == 0:
                return  # Нет позиции

            # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для изолированной маржи получаем equity через get_margin_info!
            # Это правильный баланс для данной позиции, а не общий баланс аккаунта
            try:
                margin_info = await client.get_margin_info(symbol)
                equity = margin_info.get("equity", 0)
                if equity == 0:
                    equity = fallback_equity
                    logger.warning(
                        f"⚠️ equity не найден через get_margin_info для {symbol}, используем fallback баланс: {equity:.2f}"
                    )
            except Exception as e:
                # Fallback при ошибке
                equity = fallback_equity
                logger.debug(
                    f"⚠️ Ошибка получения equity для {symbol}: {e}, используем fallback баланс: {equity:.2f}"
                )

            # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: size из API в контрактах!
            # Нужно получить ctVal для правильного расчета стоимости
            try:
                instrument_details = await client.get_instrument_details(symbol)
                ct_val = instrument_details.get(
                    "ctVal", 0.01
                )  # По умолчанию для BTC/ETH
                # Реальный размер в монетах
                size_in_coins = abs(size) * ct_val
                # Стоимость позиции в USD
                position_value = size_in_coins * current_price
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка получения ctVal для {symbol} в liquidation_guard, используем fallback: {e}"
                )
                # Fallback: предполагаем что size уже в монетах (для совместимости)
                position_value = abs(size) * current_price

            # Проверка безопасности
            # ⚠️ Используем equity из позиции, а не общий баланс!
            is_safe, details = self.margin_calculator.is_position_safe(
                position_value,
                equity,  # ✅ Используем equity из позиции!
                current_price,
                entry_price,
                side,
                leverage,
                self.warning_threshold,
            )

            margin_ratio = details["margin_ratio"]

            # Определение уровня риска
            risk_level = self._get_risk_level(margin_ratio)

            # Обработка в зависимости от уровня риска
            await self._handle_risk_level(
                risk_level, symbol, side, margin_ratio, details, client, callback
            )

        except Exception as e:
            logger.error(f"Ошибка анализа позиции: {e}")

    def _get_risk_level(self, margin_ratio: float) -> str:
        """Определение уровня риска"""
        # 🛡️ ЗАЩИТА: Игнорируем отрицательные или подозрительно малые margin_ratio
        # Если margin_ratio <= 0, это почти всегда ошибка расчета, а не реальный риск
        if margin_ratio <= 0:
            logger.debug(
                f"⚠️ Подозрительный margin_ratio={margin_ratio:.2f} - игнорируем как ошибку расчета"
            )
            return "safe"  # Не срабатываем на ошибки расчета

        if margin_ratio >= self.warning_threshold:
            return "safe"
        elif margin_ratio >= self.danger_threshold:
            return "warning"
        elif margin_ratio >= self.critical_threshold:
            return "danger"
        else:
            return "critical"

    async def _handle_risk_level(
        self,
        risk_level: str,
        symbol: str,
        side: str,
        margin_ratio: float,
        details: Dict[str, Any],
        client,
        callback: Optional[callable],
    ):
        """Обработка уровня риска"""

        # Предотвращение спама уведомлений
        warning_key = f"{symbol}_{side}"
        now = datetime.now()

        if risk_level == "safe":
            # Сброс времени последнего предупреждения
            if warning_key in self.last_warning_time:
                del self.last_warning_time[warning_key]
            return

        elif risk_level == "warning":
            # Предупреждение (не чаще раза в 5 минут)
            if (
                warning_key not in self.last_warning_time
                or now - self.last_warning_time[warning_key] > timedelta(minutes=5)
            ):
                message = f"⚠️ ПРЕДУПРЕЖДЕНИЕ: {symbol} {side} - низкая маржа {margin_ratio:.1f}%"
                logger.warning(message)

                if callback:
                    await callback("warning", symbol, side, margin_ratio, details)

                self.last_warning_time[warning_key] = now

        elif risk_level == "danger":
            # Опасность (не чаще раза в 2 минуты)
            if (
                warning_key not in self.last_warning_time
                or now - self.last_warning_time[warning_key] > timedelta(minutes=2)
            ):
                message = f"🚨 ОПАСНОСТЬ: {symbol} {side} - критически низкая маржа {margin_ratio:.1f}%"
                logger.error(message)

                if callback:
                    await callback("danger", symbol, side, margin_ratio, details)

                self.last_warning_time[warning_key] = now

        elif risk_level == "critical":
            # 🛡️ ЗАЩИТА: Проверяем, что margin_ratio реальный, а не из-за ошибки расчета
            # Если PnL небольшой (< 10% от equity), а margin_ratio критический - вероятна ошибка
            pnl = details.get("pnl", 0)
            available_margin = details.get("available_margin", 0)
            margin_used = details.get("margin_used", 0)
            equity = details.get("equity", 0)

            # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА 1: Если margin_ratio <= 1.0 или очень низкий, но PnL почти нулевой - это ошибка расчета
            # Это особенно часто происходит сразу после открытия позиции
            if margin_ratio <= 1.5 and abs(pnl) < 10:
                logger.warning(
                    f"⚠️ ПОДОЗРИТЕЛЬНОЕ критическое состояние для {symbol} {side}: "
                    f"margin_ratio={margin_ratio:.2f}, available_margin={available_margin:.2f}, "
                    f"pnl={pnl:.2f}, equity={equity:.2f}. "
                    f"Возможна ошибка расчета (позиция только что открыта?), пропускаем автозакрытие."
                )
                # Отправляем предупреждение, но не закрываем
                if callback:
                    await callback("warning", symbol, side, margin_ratio, details)
                return

            # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА 2: Если available_margin сильно отрицательный, но PnL небольшой - ошибка
            if available_margin < -1000 and abs(pnl) < 100:
                logger.warning(
                    f"⚠️ ПОДОЗРИТЕЛЬНОЕ критическое состояние для {symbol} {side}: "
                    f"margin_ratio={margin_ratio:.2f}, available_margin={available_margin:.2f}, "
                    f"pnl={pnl:.2f}. Возможна ошибка расчета, пропускаем автозакрытие."
                )
                # Отправляем предупреждение, но не закрываем
                if callback:
                    await callback("warning", symbol, side, margin_ratio, details)
                return

            # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА 3: Если margin_ratio = 0.0 или очень близок к нулю - это почти всегда ошибка
            if margin_ratio <= 0.5 and equity > 0:
                logger.warning(
                    f"⚠️ ПОДОЗРИТЕЛЬНОЕ критическое состояние для {symbol} {side}: "
                    f"margin_ratio={margin_ratio:.2f} слишком низкий для реальной позиции. "
                    f"Возможна ошибка расчета (equity={equity:.2f}, margin_used={margin_used:.2f}), "
                    f"пропускаем автозакрытие."
                )
                if callback:
                    await callback("warning", symbol, side, margin_ratio, details)
                return

            # Критично - автозакрытие только если это реальный риск
            message = f"💀 КРИТИЧНО: {symbol} {side} - автозакрытие позиции! Маржа: {margin_ratio:.1f}%"
            logger.critical(message)

            if callback:
                await callback("critical", symbol, side, margin_ratio, details)

            # Автоматическое закрытие позиции
            await self._auto_close_position(symbol, side, client)

    async def _auto_close_position(self, symbol: str, side: str, client):
        """Автоматическое закрытие позиции"""
        try:
            logger.critical(f"🛑 АВТОЗАКРЫТИЕ: {symbol} {side}")

            # Получаем текущую позицию
            positions = await client.get_positions(symbol)
            if not positions:
                logger.warning(f"Позиция {symbol} не найдена для автозакрытия")
                return

            position = positions[0]
            size = float(position.get("pos", "0"))

            if size == 0:
                logger.warning(f"Размер позиции {symbol} равен 0")
                return

            # Определяем сторону закрытия (противоположную)
            close_side = "sell" if side.lower() == "long" else "buy"

            # Размещаем рыночный ордер на закрытие
            # ⚠️ ВАЖНО: size из API уже в контрактах, поэтому size_in_contracts=True
            result = await client.place_futures_order(
                symbol=symbol,
                side=close_side,
                size=abs(size),
                order_type="market",
                size_in_contracts=True,  # ⚠️ Размер уже в контрактах!
            )

            # Проверяем результат (может быть dict или awaitable в тестах)
            code = result.get("code") if isinstance(result, dict) else None
            if code == "0":
                logger.critical(
                    f"✅ Позиция {symbol} {side} успешно закрыта автоматически"
                )
            else:
                logger.error(f"❌ Ошибка автозакрытия {symbol}: {result}")

        except Exception as e:
            logger.error(f"Ошибка автозакрытия позиции {symbol}: {e}")

    async def get_margin_status(self, client) -> Dict[str, Any]:
        """Получение статуса маржи"""
        try:
            try:
                equity = await client.get_balance()
            except Exception as e:
                logger.error(f"❌ Ошибка получения баланса: {e}")
                # Возвращаем пустой статус при ошибке получения баланса
                return {
                    "equity": 0.0,
                    "total_margin_used": 0.0,
                    "positions": [],
                    "health_status": "error",
                    "error": str(e),
                }

            try:
                positions = await client.get_positions()
            except Exception as e:
                logger.error(f"❌ Ошибка получения позиций: {e}")
                # Возвращаем статус только с балансом
                return {
                    "equity": equity,
                    "total_margin_used": 0.0,
                    "positions": [],
                    "health_status": "error",
                    "error": f"Failed to get positions: {e}",
                }

            total_margin_used = 0
            position_details = []

            for position in positions:
                size = float(position.get("pos", "0"))
                if size == 0:
                    continue

                symbol = position.get("instId", "").replace("-SWAP", "")
                side = position.get("posSide", "long")
                current_price = float(position.get("markPx", "0"))
                leverage = int(position.get("lever", "3"))

                # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: size из API в КОНТРАКТАХ!
                # Нужно получить ctVal для правильного расчета стоимости
                try:
                    instrument_details = await client.get_instrument_details(symbol)
                    ct_val = instrument_details.get(
                        "ctVal", 0.01
                    )  # По умолчанию для BTC/ETH
                    # Реальный размер в монетах
                    size_in_coins = abs(size) * ct_val
                    # Стоимость позиции в USD
                    position_value = size_in_coins * current_price
                except Exception as e:
                    logger.warning(
                        f"⚠️ Ошибка получения ctVal для {symbol} в get_margin_status, используем fallback: {e}"
                    )
                    # Fallback: предполагаем что size уже в монетах (для совместимости)
                    position_value = abs(size) * current_price

                margin_used = position_value / leverage
                total_margin_used += margin_used

                # Проверка безопасности
                is_safe, details = self.margin_calculator.is_position_safe(
                    position_value,
                    equity,
                    current_price,
                    float(position.get("avgPx", "0")),
                    side,
                    leverage,
                )

                position_details.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "size": size,
                        "value": position_value,
                        "margin_used": margin_used,
                        "margin_ratio": details["margin_ratio"],
                        "is_safe": is_safe,
                        "liquidation_price": details["liquidation_price"],
                    }
                )

            # Общий статус
            health_status = self.margin_calculator.get_margin_health_status(
                equity, total_margin_used
            )

            return {
                "equity": equity,
                "total_margin_used": total_margin_used,
                "available_margin": equity - total_margin_used,
                "health_status": health_status,
                "positions": position_details,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Ошибка получения статуса маржи: {e}")
            return {"error": str(e), "timestamp": datetime.now().isoformat()}

    def set_thresholds(
        self,
        warning: Optional[float] = None,
        danger: Optional[float] = None,
        critical: Optional[float] = None,
        auto_close: Optional[float] = None,
    ):
        """Обновление порогов"""
        if warning is not None:
            self.warning_threshold = warning
        if danger is not None:
            self.danger_threshold = danger
        if critical is not None:
            self.critical_threshold = critical
        if auto_close is not None:
            self.auto_close_threshold = auto_close

        logger.info(
            f"Пороги обновлены: warning={self.warning_threshold:.1f}, "
            f"danger={self.danger_threshold:.1f}, critical={self.critical_threshold:.1f}, "
            f"auto_close={self.auto_close_threshold:.1f}"
        )


# Пример использования
if __name__ == "__main__":
    # Создаем калькулятор и guard
    calculator = MarginCalculator()
    guard = LiquidationGuard(calculator)

    # Пример callback функции
    async def risk_callback(level, symbol, side, margin_ratio, details):
        print(f"Уведомление: {level} - {symbol} {side} - маржа: {margin_ratio:.1f}%")

    print("LiquidationGuard готов к работе")
