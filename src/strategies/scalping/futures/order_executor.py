"""
Futures Order Executor для скальпинг стратегии.

Основные функции:
- Исполнение торговых сигналов в Futures
- Интеграция с Slippage Guard для контроля проскальзывания
- Управление ордерами (рыночные, лимитные, OCO)
- Обработка ошибок и повторные попытки
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig, ScalpingConfig
from src.strategies.modules.slippage_guard import SlippageGuard


class FuturesOrderExecutor:
    """
    Исполнитель ордеров для Futures торговли

    Функции:
    - Исполнение торговых сигналов
    - Управление различными типами ордеров
    - Интеграция с Slippage Guard
    - Обработка ошибок и повторные попытки
    """

    def __init__(
        self, config: BotConfig, client: OKXFuturesClient, slippage_guard: SlippageGuard
    ):
        """
        Инициализация Futures Order Executor

        Args:
            config: Конфигурация бота
            client: Futures клиент
            slippage_guard: Защита от проскальзывания
        """
        self.config = config
        self.scalping_config = config.scalping
        self.client = client
        self.slippage_guard = slippage_guard

        # Состояние
        self.is_initialized = False
        self.active_orders = {}
        self.order_history = []
        self.execution_stats = {
            "total_orders": 0,
            "successful_orders": 0,
            "failed_orders": 0,
            "cancelled_orders": 0,
        }

        logger.info("FuturesOrderExecutor инициализирован")

    async def initialize(self):
        """Инициализация исполнителя ордеров"""
        try:
            # Проверка подключения к клиенту
            balance = await self.client.get_balance()
            logger.info(
                f"✅ Подключение к Futures клиенту установлено. Баланс: {balance:.2f} USDT"
            )

            self.is_initialized = True
            logger.info("✅ FuturesOrderExecutor инициализирован")

        except Exception as e:
            logger.error(f"Ошибка инициализации FuturesOrderExecutor: {e}")
            raise

    async def execute_signal(
        self, signal: Dict[str, Any], position_size: float
    ) -> Dict[str, Any]:
        """
        Исполнение торгового сигнала

        Args:
            signal: Торговый сигнал
            position_size: Размер позиции

        Returns:
            Результат исполнения
        """
        if not self.is_initialized:
            return {"success": False, "error": "Executor не инициализирован"}

        try:
            symbol = signal.get("symbol")
            side = signal.get("side")
            signal_type = signal.get("type", "market")

            logger.info(
                f"🎯 Исполнение сигнала: {symbol} {side} размер={position_size:.6f}"
            )

            # Валидация сигнала через Slippage Guard
            (
                is_valid,
                reason,
            ) = await self.slippage_guard.validate_order_before_placement(
                symbol=symbol,
                side=side,
                order_type="market",
                price=None,
                size=position_size,
                client=self.client,
            )

            if not is_valid:
                logger.warning(f"Сигнал не прошел валидацию: {reason}")
                return {"success": False, "error": f"Валидация не пройдена: {reason}"}

            # Исполнение ордера
            result = await self._execute_order(signal, position_size)

            # Обновление статистики
            self._update_execution_stats(result)

            return result

        except Exception as e:
            logger.error(f"Ошибка исполнения сигнала: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_order(
        self, signal: Dict[str, Any], position_size: float
    ) -> Dict[str, Any]:
        """Исполнение ордера"""
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")
            signal_type = signal.get("type", "market")

            # Определение типа ордера
            order_type = self._determine_order_type(signal)

            # Расчет цены для лимитных ордеров
            price = None
            if order_type == "limit":
                price = await self._calculate_limit_price(symbol, side)

            # Размещение ордера
            if order_type == "market":
                result = await self._place_market_order(symbol, side, position_size)
            elif order_type == "limit":
                result = await self._place_limit_order(
                    symbol, side, position_size, price
                )
            elif order_type == "oco":
                result = await self._place_oco_order(signal, position_size)
            else:
                raise ValueError(f"Неподдерживаемый тип ордера: {order_type}")

            # Сохранение ордера
            if result.get("success"):
                order_id = result.get("order_id")
                self.active_orders[order_id] = {
                    "symbol": symbol,
                    "side": side,
                    "size": position_size,
                    "type": order_type,
                    "timestamp": datetime.now(),
                    "signal": signal,
                }

            return result

        except Exception as e:
            logger.error(f"Ошибка исполнения ордера: {e}")
            return {"success": False, "error": str(e)}

    def _determine_order_type(self, signal: Dict[str, Any]) -> str:
        """Определение типа ордера на основе сигнала"""
        signal_type = signal.get("type", "market")

        # Маппинг типов сигналов на типы ордеров
        if signal_type in [
            "rsi_oversold",
            "rsi_overbought",
            "bb_oversold",
            "bb_overbought",
        ]:
            return "market"  # Быстрое исполнение для отскоков
        elif signal_type in [
            "macd_bullish",
            "macd_bearish",
            "ma_bullish",
            "ma_bearish",
        ]:
            return "limit"  # Лимитные ордера для трендовых сигналов
        else:
            return "market"  # По умолчанию рыночные ордера

    async def _calculate_limit_price(self, symbol: str, side: str) -> float:
        """Расчет цены для лимитного ордера"""
        try:
            # Получение текущих цен
            # Здесь нужно интегрироваться с WebSocket или REST API
            current_price = 50000.0  # Заглушка

            # Расчет цены с учетом спреда
            if side.lower() == "buy":
                # Для покупки - немного ниже текущей цены
                limit_price = current_price * 0.999
            else:  # sell
                # Для продажи - немного выше текущей цены
                limit_price = current_price * 1.001

            return limit_price

        except Exception as e:
            logger.error(f"Ошибка расчета лимитной цены: {e}")
            return 0.0

    async def _place_market_order(
        self, symbol: str, side: str, size: float
    ) -> Dict[str, Any]:
        """Размещение рыночного ордера"""
        try:
            logger.info(f"📈 Размещение рыночного ордера: {symbol} {side} {size:.6f}")

            result = await self.client.place_futures_order(
                symbol=symbol, side=side, size=size, order_type="market"
            )

            if result.get("code") == "0":
                order_id = result.get("data", [{}])[0].get("ordId")
                logger.info(f"✅ Рыночный ордер размещен: {order_id}")

                return {
                    "success": True,
                    "order_id": order_id,
                    "order_type": "market",
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "timestamp": datetime.now(),
                }
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка размещения рыночного ордера: {error_msg}")

                return {"success": False, "error": error_msg, "order_type": "market"}

        except Exception as e:
            logger.error(f"Ошибка размещения рыночного ордера: {e}")
            return {"success": False, "error": str(e)}

    async def _place_limit_order(
        self, symbol: str, side: str, size: float, price: float
    ) -> Dict[str, Any]:
        """Размещение лимитного ордера"""
        try:
            logger.info(
                f"📊 Размещение лимитного ордера: {symbol} {side} {size:.6f} @ {price:.2f}"
            )

            result = await self.client.place_futures_order(
                symbol=symbol, side=side, size=size, price=price, order_type="limit"
            )

            if result.get("code") == "0":
                order_id = result.get("data", [{}])[0].get("ordId")
                logger.info(f"✅ Лимитный ордер размещен: {order_id}")

                return {
                    "success": True,
                    "order_id": order_id,
                    "order_type": "limit",
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "price": price,
                    "timestamp": datetime.now(),
                }
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка размещения лимитного ордера: {error_msg}")

                return {"success": False, "error": error_msg, "order_type": "limit"}

        except Exception as e:
            logger.error(f"Ошибка размещения лимитного ордера: {e}")
            return {"success": False, "error": str(e)}

    async def _place_oco_order(
        self, signal: Dict[str, Any], size: float
    ) -> Dict[str, Any]:
        """Размещение OCO ордера"""
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")

            # Расчет цен TP и SL
            tp_price, sl_price = await self._calculate_tp_sl_prices(signal, size)

            logger.info(
                f"🎯 Размещение OCO ордера: {symbol} {side} {size:.6f} TP:{tp_price:.2f} SL:{sl_price:.2f}"
            )

            result = await self.client.place_oco_order(
                symbol=symbol,
                side=side,
                size=size,
                tp_price=tp_price,
                sl_price=sl_price,
            )

            if result.get("code") == "0":
                order_id = result.get("data", [{}])[0].get("ordId")
                logger.info(f"✅ OCO ордер размещен: {order_id}")

                return {
                    "success": True,
                    "order_id": order_id,
                    "order_type": "oco",
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                    "timestamp": datetime.now(),
                }
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка размещения OCO ордера: {error_msg}")

                return {"success": False, "error": error_msg, "order_type": "oco"}

        except Exception as e:
            logger.error(f"Ошибка размещения OCO ордера: {e}")
            return {"success": False, "error": str(e)}

    async def _calculate_tp_sl_prices(
        self, signal: Dict[str, Any], size: float
    ) -> Tuple[float, float]:
        """Расчет цен Take Profit и Stop Loss"""
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")
            entry_price = signal.get("price", 50000.0)  # Заглушка

            # Получение параметров TP/SL из конфигурации
            tp_percent = self.scalping_config.tp_percent
            sl_percent = self.scalping_config.sl_percent

            # Адаптация под силу сигнала
            strength = signal.get("strength", 0.5)
            tp_percent *= strength
            sl_percent *= strength

            if side.lower() == "buy":
                # Для лонга: TP выше входа, SL ниже входа
                tp_price = entry_price * (1 + tp_percent / 100)
                sl_price = entry_price * (1 - sl_percent / 100)
            else:  # sell
                # Для шорта: TP ниже входа, SL выше входа
                tp_price = entry_price * (1 - tp_percent / 100)
                sl_price = entry_price * (1 + sl_percent / 100)

            return tp_price, sl_price

        except Exception as e:
            logger.error(f"Ошибка расчета TP/SL цен: {e}")
            # Возвращаем безопасные значения
            entry_price = signal.get("price", 50000.0)
            return entry_price * 1.01, entry_price * 0.99

    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Отмена ордера"""
        try:
            logger.info(f"🛑 Отмена ордера: {order_id} ({symbol})")

            result = await self.client.cancel_order(symbol, order_id)

            if result.get("code") == "0":
                logger.info(f"✅ Ордер {order_id} отменен")

                # Удаление из активных ордеров
                if order_id in self.active_orders:
                    del self.active_orders[order_id]

                return {"success": True, "order_id": order_id}
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка отмены ордера: {error_msg}")

                return {"success": False, "error": error_msg}

        except Exception as e:
            logger.error(f"Ошибка отмены ордера: {e}")
            return {"success": False, "error": str(e)}

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Отмена всех ордеров"""
        try:
            cancelled_count = 0
            errors = []

            # Получение активных ордеров
            orders_to_cancel = []
            for order_id, order_info in self.active_orders.items():
                if symbol is None or order_info["symbol"] == symbol:
                    orders_to_cancel.append((order_id, order_info["symbol"]))

            # Отмена ордеров
            for order_id, order_symbol in orders_to_cancel:
                result = await self.cancel_order(order_id, order_symbol)
                if result.get("success"):
                    cancelled_count += 1
                else:
                    errors.append(f"{order_id}: {result.get('error')}")

            logger.info(f"✅ Отменено ордеров: {cancelled_count}")

            return {
                "success": True,
                "cancelled_count": cancelled_count,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"Ошибка отмены всех ордеров: {e}")
            return {"success": False, "error": str(e)}

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Получение статуса ордера"""
        try:
            # Здесь нужно интегрироваться с API для получения статуса ордера
            # Пока используем заглушку

            if order_id in self.active_orders:
                order_info = self.active_orders[order_id]
                return {
                    "order_id": order_id,
                    "status": "active",
                    "symbol": order_info["symbol"],
                    "side": order_info["side"],
                    "size": order_info["size"],
                    "type": order_info["type"],
                    "timestamp": order_info["timestamp"],
                }
            else:
                return {"order_id": order_id, "status": "not_found"}

        except Exception as e:
            logger.error(f"Ошибка получения статуса ордера: {e}")
            return {"error": str(e)}

    def _update_execution_stats(self, result: Dict[str, Any]):
        """Обновление статистики исполнения"""
        try:
            self.execution_stats["total_orders"] += 1

            if result.get("success"):
                self.execution_stats["successful_orders"] += 1
            else:
                self.execution_stats["failed_orders"] += 1

            # Сохранение в историю
            self.order_history.append({"timestamp": datetime.now(), "result": result})

            # Ограничение истории последними 1000 записями
            if len(self.order_history) > 1000:
                self.order_history = self.order_history[-1000:]

        except Exception as e:
            logger.error(f"Ошибка обновления статистики: {e}")

    def get_execution_statistics(self) -> Dict[str, Any]:
        """Получение статистики исполнения"""
        try:
            total = self.execution_stats["total_orders"]
            successful = self.execution_stats["successful_orders"]
            failed = self.execution_stats["failed_orders"]

            success_rate = (successful / total * 100) if total > 0 else 0

            return {
                "total_orders": total,
                "successful_orders": successful,
                "failed_orders": failed,
                "cancelled_orders": self.execution_stats["cancelled_orders"],
                "success_rate": success_rate,
                "active_orders_count": len(self.active_orders),
                "last_order_time": self.order_history[-1]["timestamp"]
                if self.order_history
                else None,
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики исполнения: {e}")
            return {"error": str(e)}


# Пример использования
if __name__ == "__main__":
    # Создаем конфигурацию
    config = BotConfig(
        api_key="test_key",
        secret_key="test_secret",
        passphrase="test_passphrase",
        sandbox=True,
    )

    # Создаем клиент и slippage guard
    client = OKXFuturesClient("test_key", "test_secret", "test_passphrase")
    slippage_guard = SlippageGuard()

    # Создаем исполнитель ордеров
    executor = FuturesOrderExecutor(config, client, slippage_guard)

    print("FuturesOrderExecutor готов к работе")
