"""
Slippage Guard для Futures торговли.

Основные функции:
- Контроль проскальзывания при исполнении ордеров
- Мониторинг спреда bid/ask
- Автоматическая отмена ордеров с большим проскальзыванием
- Оптимизация исполнения ордеров
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


class SlippageGuard:
    """
    Защита от проскальзывания для Futures торговли

    Функции:
    - Мониторинг спреда в реальном времени
    - Контроль проскальзывания ордеров
    - Автоматическая отмена проблемных ордеров
    - Оптимизация времени исполнения
    """

    def __init__(
        self,
        max_slippage_percent: float = 0.1,
        max_spread_percent: float = 0.05,
        order_timeout: float = 30.0,
        check_interval: float = 2.0,
    ):
        """
        Инициализация Slippage Guard

        Args:
            max_slippage_percent: Максимальное проскальзывание (0.1%)
            max_spread_percent: Максимальный спред (0.05%)
            order_timeout: Таймаут ордера (30 сек)
            check_interval: Интервал проверки (2 сек)
        """
        self.max_slippage_percent = max_slippage_percent
        self.max_spread_percent = max_spread_percent
        self.order_timeout = order_timeout
        self.check_interval = check_interval

        # Состояние мониторинга
        self.is_monitoring = False
        self.monitoring_task = None
        self.active_orders = {}  # order_id -> order_info
        self.price_history = {}  # symbol -> [prices]

        logger.info(
            f"SlippageGuard инициализирован: max_slippage={max_slippage_percent:.3f}%, "
            f"max_spread={max_spread_percent:.3f}%, timeout={order_timeout}с"
        )

    async def start_monitoring(self, client):
        """Запуск мониторинга проскальзывания"""
        if self.is_monitoring:
            logger.warning("Мониторинг проскальзывания уже запущен")
            return

        self.is_monitoring = True
        logger.info("Запуск мониторинга проскальзывания")

        self.monitoring_task = asyncio.create_task(self._monitoring_loop(client))

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

        logger.info("Мониторинг проскальзывания остановлен")

    async def _monitoring_loop(self, client):
        """Основной цикл мониторинга"""
        while self.is_monitoring:
            try:
                await self._check_active_orders(client)
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в мониторинге проскальзывания: {e}")
                await asyncio.sleep(self.check_interval)

    async def _check_active_orders(self, client):
        """Проверка активных ордеров"""
        try:
            # Получаем активные ордера
            orders = await client.get_active_orders()

            for order in orders:
                await self._analyze_order(order, client)

        except Exception as e:
            logger.error(f"Ошибка проверки активных ордеров: {e}")

    async def _analyze_order(self, order: Dict[str, Any], client):
        """Анализ отдельного ордера"""
        try:
            order_id = order.get("ordId")
            symbol = order.get("instId", "").replace("-SWAP", "")
            side = order.get("side")
            order_type = order.get("ordType")
            price = float(order.get("px", "0"))
            size = float(order.get("sz", "0"))

            if order_type not in ["market", "limit"]:
                return  # Только рыночные и лимитные ордера

            # Получаем текущие цены
            current_prices = await self._get_current_prices(client, symbol)
            if not current_prices:
                return

            bid_price = current_prices["bid"]
            ask_price = current_prices["ask"]
            mid_price = (bid_price + ask_price) / 2

            # Обновляем историю цен
            self._update_price_history(symbol, mid_price)

            # Анализ проскальзывания
            slippage_analysis = self._analyze_slippage(
                side, price, bid_price, ask_price, mid_price
            )

            # Проверка условий отмены
            should_cancel = self._should_cancel_order(
                order, slippage_analysis, current_prices
            )

            if should_cancel:
                await self._cancel_problematic_order(order_id, symbol, client)

        except Exception as e:
            logger.error(f"Ошибка анализа ордера: {e}")

    async def _get_current_prices(
        self, client, symbol: str
    ) -> Optional[Dict[str, float]]:
        """Получение текущих цен"""
        try:
            # Здесь нужно реализовать получение цен через WebSocket или REST API
            # Пока используем заглушку
            return {"bid": 50000.0, "ask": 50001.0, "last": 50000.5}
        except Exception as e:
            logger.error(f"Ошибка получения цен для {symbol}: {e}")
            return None

    def _update_price_history(self, symbol: str, price: float):
        """Обновление истории цен"""
        if symbol not in self.price_history:
            self.price_history[symbol] = []

        self.price_history[symbol].append({"price": price, "timestamp": datetime.now()})

        # Ограничиваем историю последними 100 точками
        if len(self.price_history[symbol]) > 100:
            self.price_history[symbol] = self.price_history[symbol][-100:]

    def _analyze_slippage(
        self,
        side: str,
        order_price: float,
        bid_price: float,
        ask_price: float,
        mid_price: float,
    ) -> Dict[str, Any]:
        """Анализ проскальзывания"""

        # Расчет спреда
        spread = ask_price - bid_price
        spread_percent = (spread / mid_price) * 100

        # Расчет ожидаемого проскальзывания
        if side.lower() == "buy":
            expected_price = ask_price
            slippage = (expected_price - order_price) / order_price * 100
        else:  # sell
            expected_price = bid_price
            slippage = (order_price - expected_price) / order_price * 100

        # Анализ волатильности
        volatility = self._calculate_volatility(order_price)

        return {
            "spread": spread,
            "spread_percent": spread_percent,
            "expected_price": expected_price,
            "slippage_percent": slippage,
            "volatility": volatility,
            "is_spread_acceptable": spread_percent <= self.max_spread_percent,
            "is_slippage_acceptable": abs(slippage) <= self.max_slippage_percent,
        }

    def _calculate_volatility(self, current_price: float) -> float:
        """Расчет волатильности"""
        # Упрощенный расчет волатильности
        # В реальности нужно использовать историю цен
        return 0.02  # 2% волатильность

    def _should_cancel_order(
        self,
        order: Dict[str, Any],
        slippage_analysis: Dict[str, Any],
        current_prices: Dict[str, float],
    ) -> bool:
        """Определение необходимости отмены ордера"""

        # Проверка времени ордера
        order_time = datetime.fromisoformat(
            order.get("cTime", "").replace("Z", "+00:00")
        )
        time_since_order = (datetime.now() - order_time).total_seconds()

        if time_since_order > self.order_timeout:
            logger.warning(
                f"Ордер {order.get('ordId')} превысил таймаут {self.order_timeout}с"
            )
            return True

        # Проверка спреда
        if not slippage_analysis["is_spread_acceptable"]:
            logger.warning(
                f"Спред слишком большой: {slippage_analysis['spread_percent']:.3f}%"
            )
            return True

        # Проверка проскальзывания
        if not slippage_analysis["is_slippage_acceptable"]:
            logger.warning(
                f"Проскальзывание слишком большое: {slippage_analysis['slippage_percent']:.3f}%"
            )
            return True

        return False

    async def _cancel_problematic_order(self, order_id: str, symbol: str, client):
        """Отмена проблемного ордера"""
        try:
            logger.warning(f"Отмена проблемного ордера: {order_id} ({symbol})")

            result = await client.cancel_order(symbol, order_id)

            if result.get("code") == "0":
                logger.info(f"✅ Ордер {order_id} успешно отменен")
            else:
                logger.error(f"❌ Ошибка отмены ордера {order_id}: {result}")

        except Exception as e:
            logger.error(f"Ошибка отмены ордера {order_id}: {e}")

    async def validate_order_before_placement(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: Optional[float],
        size: float,
        client,
    ) -> Tuple[bool, str]:
        """
        Валидация ордера перед размещением

        Returns:
            Tuple[bool, str] - (можно ли размещать, причина)
        """
        try:
            # Получаем текущие цены
            current_prices = await self._get_current_prices(client, symbol)
            if not current_prices:
                return False, "Не удалось получить текущие цены"

            bid_price = current_prices["bid"]
            ask_price = current_prices["ask"]
            mid_price = (bid_price + ask_price) / 2

            # Проверка спреда
            spread = ask_price - bid_price
            spread_percent = (spread / mid_price) * 100

            if spread_percent > self.max_spread_percent:
                return False, f"Спред слишком большой: {spread_percent:.3f}%"

            # Для лимитных ордеров проверяем проскальзывание
            if order_type == "limit" and price:
                slippage_analysis = self._analyze_slippage(
                    side, price, bid_price, ask_price, mid_price
                )

                if not slippage_analysis["is_slippage_acceptable"]:
                    return (
                        False,
                        f"Проскальзывание слишком большое: {slippage_analysis['slippage_percent']:.3f}%",
                    )

            return True, "Ордер валиден"

        except Exception as e:
            logger.error(f"Ошибка валидации ордера: {e}")
            return False, f"Ошибка валидации: {e}"

    def get_slippage_statistics(self) -> Dict[str, Any]:
        """Получение статистики проскальзывания"""
        stats = {
            "active_orders_count": len(self.active_orders),
            "monitored_symbols": list(self.price_history.keys()),
            "max_slippage_percent": self.max_slippage_percent,
            "max_spread_percent": self.max_spread_percent,
            "order_timeout": self.order_timeout,
            "is_monitoring": self.is_monitoring,
        }

        # Статистика по символам
        symbol_stats = {}
        for symbol, history in self.price_history.items():
            if len(history) >= 2:
                prices = [h["price"] for h in history]
                volatility = max(prices) - min(prices)
                symbol_stats[symbol] = {
                    "price_points": len(history),
                    "volatility": volatility,
                    "current_price": prices[-1] if prices else 0,
                }

        stats["symbol_statistics"] = symbol_stats

        return stats

    def set_parameters(
        self,
        max_slippage: Optional[float] = None,
        max_spread: Optional[float] = None,
        timeout: Optional[float] = None,
    ):
        """Обновление параметров"""
        if max_slippage is not None:
            self.max_slippage_percent = max_slippage
        if max_spread is not None:
            self.max_spread_percent = max_spread
        if timeout is not None:
            self.order_timeout = timeout

        logger.info(
            f"Параметры SlippageGuard обновлены: slippage={self.max_slippage_percent:.3f}%, "
            f"spread={self.max_spread_percent:.3f}%, timeout={self.order_timeout}с"
        )


# Пример использования
if __name__ == "__main__":
    # Создаем Slippage Guard
    guard = SlippageGuard(
        max_slippage_percent=0.1, max_spread_percent=0.05, order_timeout=30.0
    )

    print("SlippageGuard готов к работе")
    print(f"Статистика: {guard.get_slippage_statistics()}")
