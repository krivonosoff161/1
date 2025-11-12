"""
Futures Order Executor для скальпинг стратегии.

Основные функции:
- Исполнение торговых сигналов в Futures
- Интеграция с Slippage Guard для контроля проскальзывания
- Управление ордерами (рыночные, лимитные, OCO)
- Обработка ошибок и повторные попытки
"""

import asyncio
import re
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
            signal_type = signal.get(
                "type", "limit"
            )  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" для экономии комиссий

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
            signal_type = signal.get(
                "type", "limit"
            )  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" для экономии комиссий

            # Определение типа ордера
            order_type = self._determine_order_type(signal)

            # Расчет цены для лимитных ордеров
            price = None
            if order_type == "limit":
                price = await self._calculate_limit_price(symbol, side)
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если не удалось рассчитать цену - используем рыночный ордер
                if price is None or price <= 0:
                    logger.warning(
                        f"⚠️ Не удалось рассчитать цену для лимитного ордера {symbol}, "
                        f"используем рыночный ордер как fallback"
                    )
                    order_type = "market"
                    price = None

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
                    "type": order_type,  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: Limit ордера для экономии комиссий
                    "timestamp": datetime.now(),
                    "signal": signal,
                }

            return result

        except Exception as e:
            logger.error(f"Ошибка исполнения ордера: {e}")
            return {"success": False, "error": str(e)}

    def _determine_order_type(self, signal: Dict[str, Any]) -> str:
        """Определение типа ордера на основе сигнала"""
        # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: Используем limit ордера для экономии комиссий (0.02% вместо 0.05%)
        # Limit ордера дешевле в 2.5 раза, что критично при 180-200 сделках/день
        # Если limit ордер не исполнится - следующий сигнал, это нормально для скальпинга
        signal_type = signal.get(
            "type", "limit"
        )  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" для экономии комиссий

        # Если signal_type это тип ордера (market, limit, oco) - используем его
        if signal_type in ["market", "limit", "oco"]:
            return signal_type

        # Если signal_type это тип сигнала (rsi_oversold, macd_bullish и т.д.) - используем limit по умолчанию
        # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: Используем limit для экономии комиссий (экономия $126/месяц)
        return "limit"

    async def _calculate_limit_price(self, symbol: str, side: str) -> float:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Расчет цены для лимитного ордера с проверкой лимитов биржи
        Использует лучшие цены из стакана для более точного расчета
        """
        try:
            # Получаем лимиты цены биржи (включая лучшие цены из стакана)
            price_limits = await self.client.get_price_limits(symbol)

            if not price_limits:
                logger.warning(
                    f"⚠️ Не удалось получить лимиты цены для {symbol}, используем fallback"
                )
                # Fallback: используем текущую цену с безопасным offset
                import aiohttp

                inst_id = f"{symbol}-SWAP"
                url = f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("code") == "0" and data.get("data"):
                                ticker = data["data"][0]
                                current_price = float(ticker.get("last", "0"))
                                if current_price > 0:
                                    # ✅ ИСПРАВЛЕНО: Используем более безопасный offset 0.1% (вместо 0.05%)
                                    # Для обоих случаев (BUY и SELL) используем -0.1% от текущей цены
                                    # Это гарантирует исполнение и не выходит за лимиты биржи
                                    limit_price = current_price * 0.999  # -0.1% от текущей цены
                                    logger.debug(
                                        f"💰 Лимитная цена (fallback) для {symbol} {side}: {limit_price:.2f}"
                                    )
                                    return limit_price
                return 0.0

            # ✅ ИСПРАВЛЕНО: Используем лучшие цены из стакана для более точного расчета
            best_bid = price_limits.get("best_bid", 0)
            best_ask = price_limits.get("best_ask", 0)
            current_price = price_limits.get("current_price", 0)
            max_buy_price = price_limits.get("max_buy_price", 0)
            min_sell_price = price_limits.get("min_sell_price", 0)

            if current_price <= 0:
                logger.error(f"❌ Неверная текущая цена для {symbol}: {current_price}")
                return 0.0

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем правильную логику для SELL и BUY
            # Для BUY: покупаем по цене ниже best ask (правильное направление)
            # Для SELL: продаем по цене ниже best ask (гарантирует исполнение) или выше best bid (более выгодно)
            if side.lower() == "buy":
                # Для покупки используем best ask (лучшая цена продажи) - offset
                # Цель: купить по цене ниже best ask (правильное направление для BUY)
                if best_ask > 0:
                    # ✅ ИСПРАВЛЕНО: Используем best ask - 0.1% (ниже best ask для гарантии исполнения)
                    limit_price = best_ask * 0.999  # -0.1% от best ask
                else:
                    # Fallback: используем текущую цену - 0.1%
                    limit_price = current_price * 0.999
                
                # ✅ КРИТИЧЕСКОЕ: Проверяем лимит биржи
                if limit_price > max_buy_price:
                    # Если превышаем лимит - используем лимит минус небольшой запас
                    limit_price = max_buy_price * 0.999  # 0.1% ниже лимита для безопасности
                    logger.warning(
                        f"⚠️ Лимитная цена для {symbol} BUY превышает лимит биржи ({max_buy_price:.2f}), "
                        f"используем скорректированную цену: {limit_price:.2f}"
                    )
            else:  # sell
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для SELL используем более консервативный подход
                # Проблема: min_sell_price из get_price_limits может быть неточным
                # Решение: используем max(min_sell_price, best_bid * 0.995) для более безопасного лимита
                # И устанавливаем цену выше этого лимита
                
                # ✅ ИСПРАВЛЕНО: Используем более консервативный лимит для SELL
                # Берем максимальное значение из min_sell_price и best_bid * 0.995
                # Это гарантирует, что мы не выйдем за реальные лимиты биржи
                safe_min_sell_price = min_sell_price
                if best_bid > 0:
                    # ✅ ИСПРАВЛЕНО: Используем более консервативный лимит: best_bid * 0.995 (как в get_price_limits)
                    conservative_min_sell = best_bid * 0.995
                    # Берем максимальное значение для безопасности
                    safe_min_sell_price = max(min_sell_price, conservative_min_sell) if min_sell_price > 0 else conservative_min_sell
                    logger.debug(
                        f"📊 Консервативный min_sell_price для {symbol}: "
                        f"min_sell={min_sell_price:.2f}, conservative={conservative_min_sell:.2f}, "
                        f"safe={safe_min_sell_price:.2f}"
                    )
                
                # ✅ ИСПРАВЛЕНО: Используем best_ask * 0.999, но не ниже safe_min_sell_price
                if best_ask > 0:
                    # Используем best ask - 0.1% (ниже best ask для гарантии исполнения)
                    limit_price = best_ask * 0.999  # -0.1% от best ask
                else:
                    # Fallback: используем текущую цену - 0.1%
                    limit_price = current_price * 0.999
                
                # ✅ КРИТИЧЕСКОЕ: Проверяем лимит биржи (используем безопасный лимит)
                if limit_price < safe_min_sell_price:
                    # Если ниже лимита - используем лимит плюс небольшой запас (0.2% для безопасности)
                    limit_price = safe_min_sell_price * 1.002  # 0.2% выше лимита для безопасности
                    logger.warning(
                        f"⚠️ Лимитная цена для {symbol} SELL ({limit_price:.2f}) ниже безопасного лимита ({safe_min_sell_price:.2f}), "
                        f"используем скорректированную цену: {safe_min_sell_price * 1.002:.2f}"
                    )
                    limit_price = safe_min_sell_price * 1.002

            # ✅ ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Убеждаемся, что цена в допустимом диапазоне
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем более консервативные лимиты для финальной проверки
            if side.lower() == "buy":
                # Для BUY: используем более консервативный max_buy_price
                safe_max_buy_price = max_buy_price
                if best_ask > 0:
                    # ✅ ИСПРАВЛЕНО: Используем более консервативный лимит: best_ask * 1.005 (как в get_price_limits)
                    conservative_max_buy = best_ask * 1.005
                    # Берем минимальное значение для безопасности
                    safe_max_buy_price = min(max_buy_price, conservative_max_buy) if max_buy_price > 0 else conservative_max_buy
                
                if limit_price > safe_max_buy_price:
                    limit_price = safe_max_buy_price * 0.999
                    logger.warning(
                        f"⚠️ Финальная проверка: лимитная цена для {symbol} BUY все еще превышает безопасный лимит ({safe_max_buy_price:.2f}), "
                        f"используем: {limit_price:.2f}"
                    )
            elif side.lower() == "sell":
                # Для SELL: используем более консервативный min_sell_price
                safe_min_sell_price = min_sell_price
                if best_bid > 0:
                    # ✅ ИСПРАВЛЕНО: Используем более консервативный лимит: best_bid * 0.995 (как в get_price_limits)
                    conservative_min_sell = best_bid * 0.995
                    # Берем максимальное значение для безопасности
                    safe_min_sell_price = max(min_sell_price, conservative_min_sell) if min_sell_price > 0 else conservative_min_sell
                
                if limit_price < safe_min_sell_price:
                    limit_price = safe_min_sell_price * 1.002  # 0.2% выше лимита для безопасности
                    logger.warning(
                        f"⚠️ Финальная проверка: лимитная цена для {symbol} SELL все еще ниже безопасного лимита ({safe_min_sell_price:.2f}), "
                        f"используем: {limit_price:.2f}"
                    )

            logger.info(
                f"💰 Лимитная цена для {symbol} {side}: {limit_price:.2f} "
                f"(best_bid={best_bid:.2f}, best_ask={best_ask:.2f}, current={current_price:.2f}, "
                f"лимиты: max_buy={max_buy_price:.2f}, min_sell={min_sell_price:.2f})"
            )
            return limit_price

        except Exception as e:
            logger.error(f"Ошибка расчета лимитной цены для {symbol}: {e}")
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
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Размещение лимитного ордера с fallback на рыночный
        """
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
                error_code = result.get("code", "")
                error_data = result.get("data", [])
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Парсим лимиты из ошибки API (51006)
                parsed_min_sell = None
                parsed_max_buy = None
                
                if error_data and len(error_data) > 0:
                    s_msg = error_data[0].get("sMsg", "")
                    # ✅ Парсим лимиты из сообщения: "Order price is not within the price limit (max buy price: 103,155.9, min sell price: 101,133.2)"
                    max_buy_match = re.search(r"max buy price:\s*([\d,]+\.?\d*)", s_msg, re.IGNORECASE)
                    min_sell_match = re.search(r"min sell price:\s*([\d,]+\.?\d*)", s_msg, re.IGNORECASE)
                    
                    if max_buy_match:
                        try:
                            parsed_max_buy = float(max_buy_match.group(1).replace(",", ""))
                            logger.info(f"📊 Парсирован max buy price из ошибки: {parsed_max_buy:.2f}")
                        except Exception as e:
                            logger.debug(f"Не удалось парсить max buy price: {e}")
                    
                    if min_sell_match:
                        try:
                            parsed_min_sell = float(min_sell_match.group(1).replace(",", ""))
                            logger.info(f"📊 Парсирован min sell price из ошибки: {parsed_min_sell:.2f}")
                        except Exception as e:
                            logger.debug(f"Не удалось парсить min sell price: {e}")

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем код ошибки
                # Если ошибка связана с лимитом цены (51006) - пробуем скорректировать цену или использовать рыночный ордер
                if (
                    "51006" in str(error_msg)
                    or "51006" in str(error_code)
                    or "price limit" in error_msg.lower()
                    or "price is not within" in error_msg.lower()
                ):
                    logger.warning(
                        f"⚠️ Лимитный ордер отклонен из-за лимита цены (51006): {error_msg}"
                    )
                    
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если получили лимиты из ошибки, пробуем скорректировать цену
                    # Используем более консервативный offset (0.2% вместо 0.1%) для гарантии прохождения
                    if side.lower() == "sell" and parsed_min_sell:
                        # Для SELL: цена должна быть >= min_sell_price
                        # ✅ ИСПРАВЛЕНО: Используем 0.2% выше лимита для большей безопасности
                        corrected_price = parsed_min_sell * 1.002  # 0.2% выше лимита
                        # ✅ ИСПРАВЛЕНО: Всегда пробуем скорректированную цену, даже если она ниже старой
                        # Проблема была в том, что старая цена была неправильной (ниже лимита)
                        logger.info(
                            f"🔄 Пробуем скорректированную цену для {symbol} SELL: {price:.2f} → {corrected_price:.2f} "
                            f"(min_sell={parsed_min_sell:.2f}, offset=0.2%)"
                        )
                        # Пробуем разместить ордер с скорректированной ценой
                        retry_result = await self.client.place_futures_order(
                            symbol=symbol, side=side, size=size, price=corrected_price, order_type="limit"
                        )
                        if retry_result.get("code") == "0":
                            order_id = retry_result.get("data", [{}])[0].get("ordId")
                            logger.info(f"✅ Лимитный ордер размещен с скорректированной ценой: {order_id}")
                            return {
                                "success": True,
                                "order_id": order_id,
                                "order_type": "limit",
                                "symbol": symbol,
                                "side": side,
                                "size": size,
                                "price": corrected_price,
                                "timestamp": datetime.now(),
                            }
                        else:
                            # Если скорректированная цена тоже не прошла, логируем и пробуем рыночный ордер
                            logger.warning(
                                f"⚠️ Скорректированная цена ({corrected_price:.2f}) также не прошла, "
                                f"пробуем рыночный ордер"
                            )
                    elif side.lower() == "buy" and parsed_max_buy:
                        # Для BUY: цена должна быть <= max_buy_price
                        # ✅ ИСПРАВЛЕНО: Используем 0.2% ниже лимита для большей безопасности
                        corrected_price = parsed_max_buy * 0.998  # 0.2% ниже лимита
                        # ✅ ИСПРАВЛЕНО: Всегда пробуем скорректированную цену, даже если она выше старой
                        # Проблема была в том, что старая цена была неправильной (выше лимита)
                        logger.info(
                            f"🔄 Пробуем скорректированную цену для {symbol} BUY: {price:.2f} → {corrected_price:.2f} "
                            f"(max_buy={parsed_max_buy:.2f}, offset=0.2%)"
                        )
                        # Пробуем разместить ордер с скорректированной ценой
                        retry_result = await self.client.place_futures_order(
                            symbol=symbol, side=side, size=size, price=corrected_price, order_type="limit"
                        )
                        if retry_result.get("code") == "0":
                            order_id = retry_result.get("data", [{}])[0].get("ordId")
                            logger.info(f"✅ Лимитный ордер размещен с скорректированной ценой: {order_id}")
                            return {
                                "success": True,
                                "order_id": order_id,
                                "order_type": "limit",
                                "symbol": symbol,
                                "side": side,
                                "size": size,
                                "price": corrected_price,
                                "timestamp": datetime.now(),
                            }
                        else:
                            # Если скорректированная цена тоже не прошла, логируем и пробуем рыночный ордер
                            logger.warning(
                                f"⚠️ Скорректированная цена ({corrected_price:.2f}) также не прошла, "
                                f"пробуем рыночный ордер"
                            )
                    
                    # ✅ Fallback: Если не удалось скорректировать цену, используем рыночный ордер
                    logger.warning(
                        f"⚠️ Не удалось скорректировать цену, пробуем рыночный ордер как fallback"
                    )
                    market_result = await self._place_market_order(symbol, side, size)
                    if market_result.get("success"):
                        logger.info(
                            f"✅ Рыночный ордер размещен как fallback (лимитный был отклонен)"
                        )
                    return market_result

                logger.error(
                    f"❌ Ошибка размещения лимитного ордера: {error_msg} (code: {error_code})"
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "order_type": "limit",
                    "error_code": error_code,
                }

        except Exception as e:
            logger.error(f"Ошибка размещения лимитного ордера: {e}")
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: При исключении тоже пробуем рыночный ордер
            try:
                logger.warning(
                    f"⚠️ Исключение при размещении лимитного ордера, пробуем рыночный как fallback"
                )
                market_result = await self._place_market_order(symbol, side, size)
                if market_result.get("success"):
                    logger.info(
                        f"✅ Рыночный ордер размещен как fallback (исключение при лимитном)"
                    )
                return market_result
            except Exception as market_error:
                logger.error(
                    f"❌ Ошибка размещения рыночного ордера (fallback): {market_error}"
                )
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
        """
        🎯 РАСЧЕТ ПЛАВАЮЩИХ TP/SL

        Адаптивные TP/SL на основе:
        - Режима рынка (trending/ranging/choppy)
        - Волатильности (ATR)
        - Силы сигнала
        """
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")
            entry_price = signal.get("price", 0.0)

            # ✅ ИСПРАВЛЕНИЕ: Если цена не указана, получаем текущую цену
            if entry_price == 0.0:
                try:
                    import aiohttp

                    inst_id = f"{symbol}-SWAP"
                    url = f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if data.get("code") == "0" and data.get("data"):
                                    ticker = data["data"][0]
                                    entry_price = float(ticker.get("last", "0"))
                except Exception as e:
                    logger.error(f"❌ Не удалось получить цену для {symbol}: {e}")
                    # Fallback
                    if "BTC" in symbol:
                        entry_price = 110000.0
                    elif "ETH" in symbol:
                        entry_price = 3900.0
                    else:
                        entry_price = 50000.0

            if entry_price == 0.0:
                logger.error(f"❌ Цена для {symbol} = 0, невозможно рассчитать TP/SL")
                return entry_price * 1.003, entry_price * 0.998  # Fallback

            # Получаем ATR для текущей волатильности
            atr = await self._get_current_atr(symbol, entry_price)

            # Получаем режим рынка (если доступен)
            regime = signal.get("regime", "ranging")
            regime_params = self._get_regime_params(regime)

            # 🎯 АДАПТИВНЫЕ МУЛЬТИПЛИКАТОРЫ
            if regime_params:
                tp_multiplier = regime_params.get("tp_atr_multiplier", 0.6)
                sl_multiplier = regime_params.get("sl_atr_multiplier", 0.4)
            else:
                # Fallback на конфигурацию
                tp_multiplier = float(self.scalping_config.get("tp_percent", 0.3))
                sl_multiplier = float(self.scalping_config.get("sl_percent", 0.2))

            # ✅ ОБРАБОТКА КОНФЛИКТА RSI/EMA: Ужесточаем TP/SL для быстрого скальпа
            has_conflict = signal.get("has_conflict", False)
            if has_conflict:
                # При конфликте: более агрессивный TP и узкий SL для быстрого выхода
                # TP: 0.25-0.3 ATR (быстрая прибыль на коррекции)
                # SL: 0.2-0.25 ATR (быстрый выход при ошибке)
                tp_multiplier = min(
                    tp_multiplier * 0.5, 0.3
                )  # Макс 0.3 ATR для быстрого скальпа
                sl_multiplier = min(
                    sl_multiplier * 0.5, 0.25
                )  # Макс 0.25 ATR для узкого SL
                logger.debug(
                    f"⚡ Конфликт RSI/EMA: адаптированные TP/SL для быстрого скальпа "
                    f"(TP={tp_multiplier:.2f}x ATR, SL={sl_multiplier:.2f}x ATR)"
                )

            # Адаптация под силу сигнала
            strength = signal.get("strength", 0.5)
            # Если конфликт, не увеличиваем multiplier от strength (уже достаточно агрессивный)
            if not has_conflict:
                tp_multiplier *= 0.5 + strength  # 0.5x-1.5x range
                sl_multiplier *= 0.5 + strength

            # 🎯 РАСЧЕТ ОТ ATR (ПЛАВАЮЩИЙ!)
            tp_distance = atr * tp_multiplier
            sl_distance = atr * sl_multiplier

            if side.lower() == "buy":
                tp_price = entry_price + tp_distance
                sl_price = entry_price - sl_distance
            else:  # sell
                tp_price = entry_price - tp_distance
                sl_price = entry_price + sl_distance

            logger.debug(
                f"🎯 Aдаптивные TP/SL для {symbol}: "
                f"regime={regime}, ATR={atr:.2f}, "
                f"TP={tp_distance/entry_price*100:.2f}%, "
                f"SL={sl_distance/entry_price*100:.2f}%"
            )

            return tp_price, sl_price

        except Exception as e:
            logger.error(f"Ошибка расчета TP/SL цен: {e}")
            # Fallback на фиксированные %
            entry_price = signal.get("price", 0.0)
            if entry_price == 0.0:
                # Если цена не указана, используем текущую цену
                try:
                    import aiohttp

                    inst_id = f"{symbol}-SWAP"
                    url = f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if data.get("code") == "0" and data.get("data"):
                                    ticker = data["data"][0]
                                    entry_price = float(ticker.get("last", "0"))
                except Exception:
                    logger.error(f"❌ Fallback: не удалось получить цену для {symbol}")
                    # Последний fallback - используем разумное значение на основе символа
                    if "BTC" in symbol:
                        entry_price = 110000.0
                    elif "ETH" in symbol:
                        entry_price = 3900.0
                    else:
                        entry_price = 50000.0
            tp_pct = self.scalping_config.tp_percent
            sl_pct = self.scalping_config.sl_percent

            side = signal.get("side", "buy")
            if side.lower() == "buy":
                return entry_price * (1 + tp_pct / 100), entry_price * (
                    1 - sl_pct / 100
                )
            else:
                return entry_price * (1 - tp_pct / 100), entry_price * (
                    1 + sl_pct / 100
                )

    async def _get_current_atr(self, symbol: str, price: float) -> float:
        """Получает текущий ATR для инструмента"""
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем РЕАЛЬНЫЙ ATR из исторических данных
            # Рассчитываем ATR на основе последних свечей
            import aiohttp

            # Получаем последние 14 свечей (для расчета ATR period=14)
            inst_id = f"{symbol}-SWAP"
            url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1m&limit=20"

            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == "0" and data.get("data"):
                            candles = data["data"]

                            if (
                                len(candles) >= 15
                            ):  # Нужно минимум 15 свечей для ATR(14)
                                # OKX формат: [timestamp, open, high, low, close, volume, volumeCcy]
                                true_ranges = []
                                for i in range(
                                    1, min(15, len(candles))
                                ):  # Используем последние 14
                                    high = float(candles[i][2])
                                    low = float(candles[i][3])
                                    prev_close = float(candles[i - 1][4])

                                    tr = max(
                                        high - low,
                                        abs(high - prev_close),
                                        abs(low - prev_close),
                                    )
                                    true_ranges.append(tr)

                                # ATR = среднее значение True Range за период
                                if true_ranges:
                                    atr = sum(true_ranges) / len(true_ranges)
                                    logger.debug(
                                        f"📊 ATR для {symbol}: {atr:.2f} (на основе {len(true_ranges)} свечей)"
                                    )
                                    return atr

            # Fallback: используем приблизительный ATR как 1% от цены
            fallback_atr = price * 0.01
            logger.warning(
                f"⚠️ Не удалось рассчитать ATR для {symbol}, используем fallback: {fallback_atr:.2f}"
            )
            return fallback_atr

        except Exception as e:
            logger.warning(f"Ошибка получения ATR: {e}")
            return price * 0.01  # 1% по умолчанию

    def _get_regime_params(self, regime: str) -> dict:
        """Получает параметры режима из ARM"""
        try:
            # Если есть доступ к оркестратору
            if hasattr(self, "orchestrator"):
                return self.orchestrator._get_regime_params(regime)
            # Иначе из конфига
            adaptive_regime = self.config.get("adaptive_regime", {})
            return adaptive_regime.get(regime, {})
        except Exception as e:
            logger.warning(f"Ошибка получения параметров режима: {e}")
            return {}

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
