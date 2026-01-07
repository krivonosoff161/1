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
            except asyncio.TimeoutError:
                logger.warning(
                    f"⏱️ Таймаут при проверке активных ордеров, продолжаем мониторинг"
                )
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                # ✅ ИСПРАВЛЕНИЕ (07.01.2026): Логируем SSL и другие ошибки но продолжаем работу
                import traceback

                error_str = str(e).lower()
                if "ssl" in error_str or "application data" in error_str:
                    logger.warning(
                        f"⚠️ SSL ошибка в мониторинге проскальзывания (неопасно): {e}"
                    )
                else:
                    logger.error(
                        f"Ошибка в мониторинге проскальзывания: {e}\n{traceback.format_exc()}"
                    )
                await asyncio.sleep(self.check_interval)

    async def _check_active_orders(self, client):
        """Проверка активных ордеров"""
        try:
            # ✅ ИСПРАВЛЕНИЕ (07.01.2026): Таймаут для get_active_orders чтобы не зависать
            try:
                orders = await asyncio.wait_for(
                    client.get_active_orders(),
                    timeout=5.0,  # 5 секунд таймаут для получения активных ордеров
                )
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Таймаут при получении активных ордеров")
                return

            for order in orders:
                try:
                    await self._analyze_order(order, client)
                except Exception as e:
                    # ✅ ИСПРАВЛЕНИЕ: Продолжаем проверку остальных ордеров даже если один вызовет ошибку
                    order_id = order.get("ordId", "unknown")
                    logger.debug(f"Ошибка анализа ордера {order_id}: {e}")

        except Exception as e:
            # ✅ ИСПРАВЛЕНИЕ (07.01.2026): SSL ошибки из aiohttp не должны убивать мониторинг
            import traceback

            error_str = str(e).lower()
            if "ssl" in error_str or "application data" in error_str:
                logger.debug(
                    f"SSL ошибка при проверке активных ордеров (игнорируем): {e}"
                )
            else:
                logger.error(
                    f"Ошибка проверки активных ордеров: {e}\n{traceback.format_exc()}"
                )

    async def _analyze_order(self, order: Dict[str, Any], client):
        """Анализ отдельного ордера"""
        try:
            order_id = order.get("ordId")
            symbol = order.get("instId", "").replace("-SWAP", "")
            side = order.get("side")
            order_type = order.get("ordType")

            # ✅ ИСПРАВЛЕНО: Обработка пустой строки для market ордеров
            px_value = order.get("px") or "0"
            if not px_value or px_value == "":
                # Market ордера не имеют цены (px), пропускаем анализ
                if order_type == "market":
                    logger.debug(
                        f"Slippage Guard: пропускаем анализ market ордера {order_id} "
                        f"(market ордера не имеют цены px)"
                    )
                    return
                # Для других типов ордеров пытаемся получить текущую цену
                current_prices = await self._get_current_prices(client, symbol)
                if not current_prices:
                    logger.warning(
                        f"⚠️ Не удалось получить цену для {symbol}, пропускаем анализ ордера {order_id}"
                    )
                    return
                price = (
                    current_prices.get("last", 0)
                    if side.lower() == "buy"
                    else current_prices.get("bid", 0)
                )
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Проверка что цена > 0
                if price <= 0:
                    logger.debug(
                        f"SlippageGuard: Некорректная цена для {symbol}: {price}, пропускаем анализ ордера {order_id} "
                        f"(это нормально для ордеров, которые еще не обработаны биржей)"
                    )
                    return
            else:
                price = float(px_value)
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Проверка что цена > 0
                if price <= 0:
                    logger.debug(
                        f"SlippageGuard: Некорректная цена ордера для {symbol}: {price}, пропускаем анализ ордера {order_id} "
                        f"(это нормально для ордеров, которые еще не обработаны биржей)"
                    )
                    return

            size = float(order.get("sz", "0"))

            if order_type not in ["market", "limit"]:
                return  # Только рыночные и лимитные ордера

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: НЕ отменяем лимитные ордера!
            # Лимитные ордера не должны отменяться slippage guard, так как:
            # 1. Они размещаются по желаемой цене
            # 2. Отмена после размещения = потеря комиссии
            # 3. Лимитные ордера должны исполняться или отменяться вручную
            if order_type == "limit":
                logger.debug(
                    f"Slippage Guard: пропускаем проверку лимитного ордера {order_id} (не отменяем лимитные ордера)"
                )
                return

            # Получаем текущие цены
            current_prices = await self._get_current_prices(client, symbol)
            if not current_prices:
                return

            bid_price = current_prices.get("bid", 0)
            ask_price = current_prices.get("ask", 0)

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Защита от деления на ноль
            if bid_price <= 0 or ask_price <= 0:
                logger.warning(
                    f"⚠️ SlippageGuard: Некорректные цены для {symbol}: "
                    f"bid={bid_price}, ask={ask_price}, пропускаем анализ"
                )
                return

            mid_price = (bid_price + ask_price) / 2
            if mid_price <= 0:
                logger.warning(
                    f"⚠️ SlippageGuard: mid_price <= 0 для {symbol}: {mid_price}, пропускаем анализ"
                )
                return

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
            import traceback

            error_details = traceback.format_exc()
            logger.error(f"Ошибка анализа ордера: {e}\n" f"Traceback: {error_details}")

    async def _get_current_prices(
        self, client, symbol: str
    ) -> Optional[Dict[str, float]]:
        """
        ✅ ИСПРАВЛЕНО: Получение текущих цен через OKX API

        Args:
            client: OKX Futures Client
            symbol: Торговый символ (например, "BTC-USDT")

        Returns:
            Dict с bid, ask, last ценами или None при ошибке
        """
        try:
            # ✅ ИСПРАВЛЕНО (07.01.2026): Используем сессию из клиента или используем context manager
            # Конвертируем symbol в instId (добавляем -SWAP для фьючерсов)
            inst_id = symbol.replace("-USDT", "-USDT-SWAP")

            # Используем публичный API для получения ticker
            import aiohttp

            base_url = "https://www.okx.com"
            ticker_url = f"{base_url}/api/v5/market/ticker?instId={inst_id}"

            # ✅ ИСПРАВЛЕНИЕ: Используем context manager для гарантии закрытия сессии
            timeout = aiohttp.ClientTimeout(total=5, connect=2)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(ticker_url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("code") == "0" and data.get("data"):
                                ticker = data["data"][0]

                                bid_price = float(ticker.get("bidPx", "0") or "0")
                                ask_price = float(ticker.get("askPx", "0") or "0")
                                last_price = float(ticker.get("last", "0") or "0")

                                if bid_price > 0 and ask_price > 0:
                                    logger.debug(
                                        f"✅ SlippageGuard: Получены цены для {symbol}: "
                                        f"bid={bid_price:.2f}, ask={ask_price:.2f}, last={last_price:.2f}"
                                    )
                                    return {
                                        "bid": bid_price,
                                        "ask": ask_price,
                                        "last": last_price
                                        if last_price > 0
                                        else (bid_price + ask_price) / 2,
                                    }
                                else:
                                    logger.warning(
                                        f"⚠️ SlippageGuard: Некорректные цены для {symbol}: "
                                        f"bid={bid_price}, ask={ask_price}"
                                    )
                                    return None
                            else:
                                logger.warning(
                                    f"⚠️ SlippageGuard: Ошибка API для {symbol}: {data.get('msg', 'Unknown')}"
                                )
                                return None
                        else:
                            logger.warning(
                                f"⚠️ SlippageGuard: HTTP {resp.status} для {symbol}"
                            )
                            return None
            except asyncio.TimeoutError:
                logger.warning(
                    f"⏱️ SlippageGuard: Таймаут при получении цен для {symbol}"
                )
                return None

        except Exception as e:
            logger.error(f"❌ SlippageGuard: Ошибка получения цен для {symbol}: {e}")
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

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Защита от деления на ноль
        if mid_price <= 0:
            return {
                "spread": 0,
                "spread_percent": 0,
                "expected_price": mid_price,
                "slippage_percent": 0,
                "volatility": 0,
                "is_spread_acceptable": False,
                "is_slippage_acceptable": False,
            }

        # Расчет спреда
        spread = ask_price - bid_price
        spread_percent = (spread / mid_price) * 100 if mid_price > 0 else 0

        # Расчет ожидаемого проскальзывания
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Защита от деления на ноль
        expected_price = mid_price  # Fallback значение
        if order_price <= 0:
            slippage = 0
        else:
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
        try:
            c_time = order.get("cTime", "")
            if not c_time:
                # Если нет времени - пропускаем проверку таймаута
                logger.debug(f"Ордер {order.get('ordId')} не имеет времени создания")
                return False

            # OKX возвращает время в формате:
            # - Строка ISO: "2024-01-15T10:30:00.000Z"
            # - Timestamp в миллисекундах: "1705315800000" (строка или число)

            # Проверяем, это строка или число
            if isinstance(c_time, (int, float)):
                # Timestamp в миллисекундах
                order_time = datetime.fromtimestamp(c_time / 1000.0)
                from datetime import timezone

                order_time = order_time.replace(tzinfo=timezone.utc)
            elif isinstance(c_time, str):
                # Строка - пытаемся распарсить как ISO или timestamp
                try:
                    # Пробуем распарсить как timestamp (в миллисекундах)
                    timestamp_ms = float(c_time)
                    order_time = datetime.fromtimestamp(timestamp_ms / 1000.0)
                    from datetime import timezone

                    order_time = order_time.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    # Не timestamp - парсим как ISO строку
                    c_time_str = c_time.replace("Z", "+00:00")
                    # Если формат без миллисекунд - добавляем
                    if "+00:00" in c_time_str and "." not in c_time_str.split("+")[0]:
                        c_time_str = c_time_str.replace("+00:00", ".000+00:00")
                    order_time = datetime.fromisoformat(c_time_str)
                    # Если order_time не имеет timezone - добавляем UTC
                    if order_time.tzinfo is None:
                        from datetime import timezone

                        order_time = order_time.replace(tzinfo=timezone.utc)
            else:
                logger.warning(f"Неизвестный формат времени ордера: {type(c_time)}")
                return False

            # Вычисляем разницу во времени
            current_time = (
                datetime.now(order_time.tzinfo) if order_time.tzinfo else datetime.now()
            )
            time_since_order = (current_time - order_time).total_seconds()
        except (ValueError, AttributeError, TypeError) as e:
            logger.warning(
                f"Ошибка парсинга времени ордера {order.get('ordId')}: {e}, cTime={order.get('cTime')}, type={type(order.get('cTime'))}"
            )
            # Если не можем распарсить - пропускаем проверку таймаута (не критично)
            return False

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

            bid_price = current_prices.get("bid", 0)
            ask_price = current_prices.get("ask", 0)

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Защита от деления на ноль
            if bid_price <= 0 or ask_price <= 0:
                return False, f"Некорректные цены: bid={bid_price}, ask={ask_price}"

            mid_price = (bid_price + ask_price) / 2
            if mid_price <= 0:
                return False, f"mid_price <= 0: {mid_price}"

            # Проверка спреда
            spread = ask_price - bid_price
            spread_percent = (spread / mid_price) * 100 if mid_price > 0 else 0

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
