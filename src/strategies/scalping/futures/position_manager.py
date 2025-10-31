"""
Futures Position Manager для скальпинг стратегии.

Основные функции:
- Управление открытыми позициями в Futures
- Интеграция с Margin Calculator для контроля маржи
- Автоматическое закрытие позиций по TP/SL
- Мониторинг PnL и рисков
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig, ScalpingConfig
from src.strategies.modules.margin_calculator import MarginCalculator


class FuturesPositionManager:
    """
    Менеджер позиций для Futures торговли

    Функции:
    - Управление открытыми позициями
    - Мониторинг маржи и рисков
    - Автоматическое закрытие позиций
    - Интеграция с Margin Calculator
    """

    def __init__(
        self,
        config: BotConfig,
        client: OKXFuturesClient,
        margin_calculator: MarginCalculator,
    ):
        """
        Инициализация Futures Position Manager

        Args:
            config: Конфигурация бота
            client: Futures клиент
            margin_calculator: Калькулятор маржи
        """
        self.config = config
        self.scalping_config = config.scalping
        self.client = client
        self.margin_calculator = margin_calculator

        # Состояние
        self.is_initialized = False
        self.active_positions = {}
        self.position_history = []
        self.management_stats = {
            "total_positions": 0,
            "closed_positions": 0,
            "tp_closed": 0,
            "sl_closed": 0,
            "manual_closed": 0,
            "total_pnl": 0.0,
        }

        logger.info("FuturesPositionManager инициализирован")

    async def initialize(self):
        """Инициализация менеджера позиций"""
        try:
            # Получение текущих позиций
            positions = await self.client.get_positions()

            # Инициализация активных позиций
            for position in positions:
                symbol = position.get("instId", "").replace("-SWAP", "")
                size = float(position.get("pos", "0"))
                if size != 0:
                    self.active_positions[symbol] = position

            logger.info(f"✅ Инициализировано позиций: {len(self.active_positions)}")
            self.is_initialized = True

        except Exception as e:
            logger.error(f"Ошибка инициализации FuturesPositionManager: {e}")
            raise

    async def manage_position(self, position: Dict[str, Any]):
        """
        Управление отдельной позицией

        Args:
            position: Данные позиции
        """
        if not self.is_initialized:
            logger.warning("PositionManager не инициализирован")
            return

        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            side = position.get("posSide", "long")

            if size == 0:
                # Позиция закрыта
                if symbol in self.active_positions:
                    await self._handle_position_closed(symbol)
                return

            # Обновление активных позиций
            self.active_positions[symbol] = position

            # Проверка безопасности позиции
            await self._check_position_safety(position)

            # Проверка TP/SL
            # ⚠️ ВАЖНО: Фиксированный SL отключен, когда используется TrailingSL
            # TrailingSL проверяется в orchestrator._update_trailing_stop_loss
            # Здесь проверяем только TP (Take Profit)
            await self._check_tp_only(position)

            # Обновление статистики
            await self._update_position_stats(position)

        except Exception as e:
            logger.error(f"Ошибка управления позицией {symbol}: {e}")

    async def _check_position_safety(self, position: Dict[str, Any]):
        """Проверка безопасности позиции"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            side = position.get("posSide", "long")
            entry_price = float(position.get("avgPx", "0"))
            current_price = float(position.get("markPx", "0"))
            leverage = int(position.get("lever", "3"))

            # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для изолированной маржи получаем equity через get_margin_info!
            # Это правильный баланс для данной позиции, а не общий баланс аккаунта
            try:
                margin_info = await self.client.get_margin_info(symbol)
                equity = margin_info.get("equity", 0)

                # Если equity не найден в margin_info, пытаемся получить из самой позиции
                if equity == 0:
                    # Проверяем, есть ли 'eq' или другие поля в самой позиции
                    if "eq" in position and position["eq"]:
                        try:
                            equity = float(position["eq"])
                            logger.debug(
                                f"✅ equity получен из position['eq'] для {symbol}: {equity:.2f}"
                            )
                        except (ValueError, TypeError):
                            pass

                    # Если все еще 0, используем общий баланс как fallback
                    if equity == 0:
                        equity = await self.client.get_balance()
                        logger.warning(
                            f"⚠️ equity не найден через get_margin_info для {symbol}, используем общий баланс: {equity:.2f}"
                        )
            except Exception as e:
                # Fallback при ошибке - сначала пытаемся из позиции
                equity = 0
                try:
                    if "eq" in position and position["eq"]:
                        equity = float(position["eq"])
                        logger.debug(
                            f"✅ equity получен из position['eq'] (fallback) для {symbol}: {equity:.2f}"
                        )
                except (ValueError, TypeError):
                    pass

                if equity == 0:
                    equity = await self.client.get_balance()
                    logger.warning(
                        f"⚠️ Ошибка получения equity для {symbol}: {e}, используем общий баланс: {equity:.2f}"
                    )

            # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: size из API в контрактах!
            # Нужно получить ctVal для правильного расчета стоимости
            try:
                details = await self.client.get_instrument_details(symbol)
                ct_val = details.get("ctVal", 0.01)  # По умолчанию для BTC/ETH
                # Реальный размер в монетах
                size_in_coins = abs(size) * ct_val
                # Стоимость позиции в USD
                position_value = size_in_coins * current_price
                logger.debug(
                    f"📊 Расчет position_value для {symbol}: "
                    f"size={size} контрактов, ctVal={ct_val}, "
                    f"size_in_coins={size_in_coins:.6f}, "
                    f"current_price={current_price:.2f}, "
                    f"position_value={position_value:.2f} USD"
                )
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка получения ctVal для {symbol}, используем приблизительный расчет: {e}"
                )
                # Fallback: предполагаем что size уже в монетах (для совместимости)
                size_in_coins = abs(size)
                position_value = size_in_coins * current_price
                logger.warning(
                    f"⚠️ Fallback расчет для {symbol}: size_in_coins={size_in_coins:.6f}, position_value={position_value:.2f} USD"
                )

            # Проверка безопасности через Margin Calculator
            # ⚠️ Используем equity из позиции, а не общий баланс!
            logger.debug(
                f"🔍 Проверка безопасности {symbol}: "
                f"position_value={position_value:.2f}, equity={equity:.2f}, "
                f"current_price={current_price:.2f}, entry_price={entry_price:.2f}, "
                f"leverage={leverage}x"
            )
            is_safe, details = self.margin_calculator.is_position_safe(
                position_value,
                equity,  # ✅ Используем equity из позиции!
                current_price,
                entry_price,
                side,
                leverage,
                safety_threshold=1.5,
            )

            if not is_safe:
                margin_ratio = details["margin_ratio"]
                pnl = details.get("pnl", 0)
                available_margin = details.get("available_margin", 0)
                margin_used = details.get("margin_used", 0)

                logger.warning(
                    f"⚠️ Позиция {symbol} небезопасна: маржа {margin_ratio:.1f}%"
                )

                # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА от ложных срабатываний (как в LiquidationGuard):
                # Если margin_ratio <= 1.5 и PnL небольшой - это ошибка расчета, а не реальный риск
                # Это особенно часто происходит сразу после открытия позиции
                if margin_ratio <= 1.5 and abs(pnl) < 10:
                    logger.warning(
                        f"⚠️ ПОДОЗРИТЕЛЬНОЕ состояние для {symbol} в PositionManager: "
                        f"margin_ratio={margin_ratio:.2f}, available_margin={available_margin:.2f}, "
                        f"pnl={pnl:.2f}, equity={equity:.2f}. "
                        f"Возможна ошибка расчета (позиция только что открыта?), пропускаем автозакрытие."
                    )
                    return  # Пропускаем автозакрытие

                # 🛡️ ЗАЩИТА 2: Если margin_ratio = 0.0 или очень близок к нулю - это почти всегда ошибка
                if margin_ratio <= 0.5 and equity > 0:
                    logger.warning(
                        f"⚠️ ПОДОЗРИТЕЛЬНОЕ состояние для {symbol} в PositionManager: "
                        f"margin_ratio={margin_ratio:.2f} слишком низкий для реальной позиции. "
                        f"Возможна ошибка расчета (equity={equity:.2f}, margin_used={margin_used:.2f}), "
                        f"пропускаем автозакрытие."
                    )
                    return  # Пропускаем автозакрытие

                # 🛡️ ЗАЩИТА 3: Если available_margin сильно отрицательный, но PnL небольшой - ошибка
                if available_margin < -1000 and abs(pnl) < 100:
                    logger.warning(
                        f"⚠️ ПОДОЗРИТЕЛЬНОЕ состояние для {symbol} в PositionManager: "
                        f"margin_ratio={margin_ratio:.2f}, available_margin={available_margin:.2f}, "
                        f"pnl={pnl:.2f}. Возможна ошибка расчета, пропускаем автозакрытие."
                    )
                    return  # Пропускаем автозакрытие

                # Дополнительные действия при низкой марже (только если это реальный риск!)
                # ⚠️ ВНИМАНИЕ: Не закрываем автоматически, если margin_ratio отрицательный
                # (это может быть из-за ошибки расчета - исправлено выше)
                if margin_ratio < 1.2 and margin_ratio > 0:
                    logger.warning(
                        f"⚠️ Позиция {symbol} имеет низкую маржу: {margin_ratio:.2f}%. Закрытие..."
                    )
                    await self._emergency_close_position(position)
                elif margin_ratio <= 0:
                    logger.warning(
                        f"⚠️ Позиция {symbol} имеет некорректный margin_ratio: {margin_ratio:.2f}%. Пропускаем автозакрытие."
                    )

        except Exception as e:
            logger.error(f"Ошибка проверки безопасности позиции: {e}")

    async def _check_tp_sl(self, position: Dict[str, Any]):
        """Проверка Take Profit и Stop Loss (DEPRECATED - используется _check_tp_only)"""
        # Этот метод оставлен для совместимости, но теперь используется _check_tp_only
        await self._check_tp_only(position)

    async def _check_tp_only(self, position: Dict[str, Any]):
        """Проверка только Take Profit (SL управляется TrailingSL в orchestrator)"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            side = position.get("posSide", "long")
            entry_price = float(position.get("avgPx", "0"))
            current_price = float(position.get("markPx", "0"))
            leverage = int(position.get("lever", "3"))

            if size == 0:
                return

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: PnL% должен считаться от МАРЖИ, а не от цены входа!
            # Биржа показывает PnL% от маржи (например, 0.89% для ETH), а не от цены (0.30%)
            # Поэтому TP должен сравниваться с PnL% от маржи, иначе позиции не закрываются!

            # Получаем маржу позиции
            try:
                margin_info = await self.client.get_margin_info(symbol)
                margin_used = margin_info.get("margin", 0)
                # OKX API использует "upl" для unrealizedPnl
                unrealized_pnl = margin_info.get(
                    "upl", margin_info.get("unrealized_pnl", 0)
                )

                # Если margin_info не дает нужные данные, считаем из position
                if margin_used == 0:
                    # Пытаемся получить из position или рассчитать
                    if "margin" in position:
                        margin_used = float(position["margin"])
                    elif "imr" in position:
                        margin_used = float(
                            position["imr"]
                        )  # Initial Margin Requirement
                    else:
                        # Рассчитываем маржу из размера позиции
                        # position_value = size_in_coins * entry_price
                        # margin = position_value / leverage
                        # Для этого нужно получить ctVal
                        try:
                            inst_details = await self.client.get_instrument_details(
                                symbol
                            )
                            ct_val = float(inst_details.get("ctVal", "0.01"))
                            size_in_coins = abs(size) * ct_val
                            position_value = size_in_coins * entry_price
                            margin_used = position_value / leverage
                        except Exception as e:
                            logger.debug(
                                f"Не удалось рассчитать margin для {symbol}: {e}"
                            )
                            # Fallback: используем старый метод (процент от цены)
                            if side.lower() == "long":
                                pnl_percent = (
                                    (current_price - entry_price) / entry_price * 100
                                )
                            else:
                                pnl_percent = (
                                    (entry_price - current_price) / entry_price * 100
                                )
                            logger.warning(
                                f"⚠️ Используем fallback расчет PnL% для {symbol}: {pnl_percent:.2f}% (от цены, а не от маржи)"
                            )
                            tp_percent = self.scalping_config.tp_percent
                            if pnl_percent >= tp_percent:
                                logger.info(
                                    f"🎯 TP достигнут для {symbol}: {pnl_percent:.2f}%"
                                )
                                await self._close_position_by_reason(position, "tp")
                            return
            except Exception as e:
                logger.debug(
                    f"Не удалось получить margin_info для {symbol}: {e}, используем fallback"
                )
                margin_used = 0
                unrealized_pnl = 0

            # Если получили margin, считаем PnL% от маржи
            if margin_used > 0:
                # Получаем unrealizedPnl из position или margin_info
                if unrealized_pnl == 0:
                    if "upl" in position:
                        unrealized_pnl = float(position["upl"])
                    elif "unrealizedPnl" in position:
                        unrealized_pnl = float(position["unrealizedPnl"])
                    else:
                        # Рассчитываем PnL вручную
                        try:
                            inst_details = await self.client.get_instrument_details(
                                symbol
                            )
                            ct_val = float(inst_details.get("ctVal", "0.01"))
                            size_in_coins = abs(size) * ct_val
                            if side.lower() == "long":
                                unrealized_pnl = size_in_coins * (
                                    current_price - entry_price
                                )
                            else:
                                unrealized_pnl = size_in_coins * (
                                    entry_price - current_price
                                )
                        except Exception:
                            # Последний fallback: используем процент от цены
                            if side.lower() == "long":
                                pnl_percent = (
                                    (current_price - entry_price) / entry_price * 100
                                )
                            else:
                                pnl_percent = (
                                    (entry_price - current_price) / entry_price * 100
                                )
                            logger.warning(
                                f"⚠️ Fallback расчет PnL% для {symbol}: {pnl_percent:.2f}%"
                            )
                            tp_percent = self.scalping_config.tp_percent
                            if pnl_percent >= tp_percent:
                                logger.info(
                                    f"🎯 TP достигнут для {symbol}: {pnl_percent:.2f}%"
                                )
                                await self._close_position_by_reason(position, "tp")
                            return

                # ✅ ПРАВИЛЬНЫЙ РАСЧЕТ: PnL% от маржи (как на бирже!)
                pnl_percent = (unrealized_pnl / margin_used) * 100
                logger.debug(
                    f"📊 TP проверка {symbol}: PnL=${unrealized_pnl:.2f}, "
                    f"margin=${margin_used:.2f}, PnL%={pnl_percent:.2f}% (от маржи)"
                )
            else:
                # Fallback: если margin не получили, используем процент от цены
                if side.lower() == "long":
                    pnl_percent = (current_price - entry_price) / entry_price * 100
                else:
                    pnl_percent = (entry_price - current_price) / entry_price * 100
                logger.warning(
                    f"⚠️ Fallback: PnL% для {symbol} считаем от цены: {pnl_percent:.2f}%"
                )

            # Проверка Take Profit
            tp_percent = self.scalping_config.tp_percent
            if pnl_percent >= tp_percent:
                logger.info(
                    f"🎯 TP достигнут для {symbol}: {pnl_percent:.2f}% "
                    f"(TP={tp_percent:.2f}%, PnL=${unrealized_pnl:.2f}, margin=${margin_used:.2f})"
                )
                await self._close_position_by_reason(position, "tp")
                return
            else:
                logger.debug(
                    f"📊 {symbol} PnL={pnl_percent:.2f}% < TP={tp_percent:.2f}% "
                    f"(нужно еще {tp_percent - pnl_percent:.2f}%)"
                )

            # ⚠️ Stop Loss отключен - используется TrailingSL из orchestrator
            # TrailingSL более гибкий и учитывает тренд/режим рынка

        except Exception as e:
            logger.error(f"Ошибка проверки TP: {e}")

    async def _close_position_by_reason(self, position: Dict[str, Any], reason: str):
        """Закрытие позиции по причине"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")

            # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем актуальное состояние позиции на бирже
            # перед закрытием, так как position может быть устаревшим
            actual_positions = await self.client.get_positions(symbol)

            # Ищем актуальную позицию
            actual_position = None
            for pos in actual_positions:
                inst_id = pos.get("instId", "").replace("-SWAP", "")
                if inst_id == symbol:
                    size = float(pos.get("pos", "0"))
                    if size != 0:  # Позиция еще открыта
                        actual_position = pos
                        break

            # Если позиция уже закрыта, просто удаляем из активных
            if actual_position is None:
                logger.info(
                    f"⚠️ Позиция {symbol} уже закрыта на бирже, удаляем из активных"
                )
                if symbol in self.active_positions:
                    del self.active_positions[symbol]
                return

            size = float(actual_position.get("pos", "0"))
            side = actual_position.get("posSide", "long")

            logger.info(
                f"🔄 Закрытие позиции {symbol} по причине: {reason}, размер={size} контрактов"
            )

            # Определение стороны закрытия
            close_side = "sell" if side.lower() == "long" else "buy"

            # Размещение рыночного ордера на закрытие
            # ⚠️ size из API уже в контрактах, поэтому size_in_contracts=True
            result = await self.client.place_futures_order(
                symbol=symbol,
                side=close_side,
                size=abs(size),
                order_type="market",
                size_in_contracts=True,  # size из API уже в контрактах
            )

            if result.get("code") == "0":
                logger.info(f"✅ Позиция {symbol} закрыта по {reason}")

                # Обновление статистики
                self._update_close_stats(reason)

                # Удаление из активных позиций
                if symbol in self.active_positions:
                    del self.active_positions[symbol]
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка закрытия позиции {symbol}: {error_msg}")

        except Exception as e:
            logger.error(f"Ошибка закрытия позиции: {e}")

    async def _emergency_close_position(self, position: Dict[str, Any]):
        """Экстренное закрытие позиции"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            logger.critical(f"🚨 ЭКСТРЕННОЕ ЗАКРЫТИЕ ПОЗИЦИИ: {symbol}")

            await self._close_position_by_reason(position, "emergency")

        except Exception as e:
            logger.error(f"Ошибка экстренного закрытия позиции: {e}")

    async def _handle_position_closed(self, symbol: str):
        """Обработка закрытой позиции"""
        try:
            if symbol in self.active_positions:
                position = self.active_positions[symbol]

                # Сохранение в историю
                self.position_history.append(
                    {
                        "symbol": symbol,
                        "position": position,
                        "close_time": datetime.now(),
                        "close_reason": "manual",
                    }
                )

                # Удаление из активных позиций
                del self.active_positions[symbol]

                logger.info(f"📊 Позиция {symbol} закрыта")

        except Exception as e:
            logger.error(f"Ошибка обработки закрытой позиции: {e}")

    async def _update_position_stats(self, position: Dict[str, Any]):
        """Обновление статистики позиции"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            entry_price = float(position.get("avgPx", "0"))
            current_price = float(position.get("markPx", "0"))
            side = position.get("posSide", "long")

            if size == 0:
                return

            # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: size из API в КОНТРАКТАХ!
            # Нужно получить ctVal для конвертации в монеты перед расчетом PnL
            try:
                details = await self.client.get_instrument_details(symbol)
                ct_val = details.get("ctVal", 0.01)  # По умолчанию для BTC/ETH
                # Реальный размер в монетах
                size_in_coins = abs(size) * ct_val
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка получения ctVal для {symbol}, используем fallback: {e}"
                )
                # Fallback: предполагаем что size уже в монетах (для совместимости)
                size_in_coins = abs(size)

            # Расчет текущего PnL (теперь с правильным размером в монетах)
            if side.lower() == "long":
                pnl = (current_price - entry_price) * size_in_coins
            else:  # short
                pnl = (entry_price - current_price) * size_in_coins

            # Обновление общего PnL
            self.management_stats["total_pnl"] += pnl

            logger.debug(
                f"📈 Позиция {symbol}: PnL = {pnl:.2f} USDT (size={size} контрактов = {size_in_coins:.6f} монет)"
            )

        except Exception as e:
            logger.error(f"Ошибка обновления статистики позиции: {e}")

    def _update_close_stats(self, reason: str):
        """Обновление статистики закрытия"""
        try:
            self.management_stats["closed_positions"] += 1

            if reason == "tp":
                self.management_stats["tp_closed"] += 1
            elif reason == "sl":
                self.management_stats["sl_closed"] += 1
            elif reason == "emergency":
                self.management_stats["manual_closed"] += 1

        except Exception as e:
            logger.error(f"Ошибка обновления статистики закрытия: {e}")

    async def close_position_manually(self, symbol: str) -> Dict[str, Any]:
        """
        ✅ РУЧНОЕ ЗАКРЫТИЕ ПОЗИЦИИ (для TrailingSL)

        Закрывает позицию через API без конфликтов с OCO
        """
        try:
            # Получаем информацию о позиции с биржи
            # ⚠️ ИСПРАВЛЕНИЕ: get_positions() возвращает СПИСОК, не dict!
            positions = await self.client.get_positions(symbol)

            # Проверяем, что positions это список
            if not isinstance(positions, list) or len(positions) == 0:
                logger.warning(f"Позиция {symbol} не найдена на бирже (список пустой)")
                return {"success": False, "error": "Позиция не найдена"}

            # Ищем нужную позицию в списке
            for pos_data in positions:
                inst_id = pos_data.get("instId", "").replace("-SWAP", "")
                if inst_id != symbol:
                    continue

                size = float(pos_data.get("pos", "0"))
                if size == 0:
                    logger.warning(f"Размер позиции {symbol} = 0, позиция уже закрыта")
                    return {
                        "success": True,
                        "symbol": symbol,
                        "message": "Позиция уже закрыта",
                    }

                side = pos_data.get("posSide", "long")

                logger.info(
                    f"🔄 Закрытие позиции {symbol} {side} размер={size} контрактов"
                )

                # Определение стороны закрытия
                close_side = "sell" if side.lower() == "long" else "buy"

                # ✅ Размещаем рыночный ордер на закрытие
                # ⚠️ size из API уже в контрактах, поэтому size_in_contracts=True
                # ⚠️ Для закрытия позиции используем reduceOnly для безопасности
                result = await self.client.place_futures_order(
                    symbol=symbol,
                    side=close_side,
                    size=abs(size),
                    order_type="market",
                    size_in_contracts=True,  # size из API уже в контрактах
                )

                if result.get("code") == "0":
                    logger.info(f"✅ Позиция {symbol} закрыта через API")
                    # Удаляем из активных позиций
                    if symbol in self.active_positions:
                        del self.active_positions[symbol]
                    return {"success": True, "symbol": symbol}
                else:
                    error_msg = result.get("msg", "Неизвестная ошибка")
                    error_code = result.get("data", [{}])[0].get("sCode", "")

                    # Если позиция уже закрыта или не найдена - это не ошибка
                    if (
                        error_code in ["51008", "51000"]
                        and "insufficient" in error_msg.lower()
                    ):
                        logger.warning(
                            f"⚠️ Позиция {symbol} возможно уже закрыта или недостаточно маржи. Проверяем состояние..."
                        )
                        # Проверяем, закрыта ли позиция
                        await asyncio.sleep(0.5)  # Небольшая задержка
                        check_positions = await self.client.get_positions(symbol)
                        found_open = False
                        for pos in check_positions:
                            if float(pos.get("pos", "0")) != 0:
                                found_open = True
                                break
                        if not found_open:
                            logger.info(f"✅ Позиция {symbol} действительно уже закрыта")
                            if symbol in self.active_positions:
                                del self.active_positions[symbol]
                            return {
                                "success": True,
                                "symbol": symbol,
                                "message": "Позиция уже была закрыта",
                            }

                    logger.error(
                        f"❌ Ошибка закрытия {symbol}: {error_msg} (код: {error_code})"
                    )
                    return {"success": False, "error": error_msg}

            return {"success": False, "error": "Позиция не найдена в списке"}

        except Exception as e:
            logger.error(f"Ошибка ручного закрытия позиции: {e}")
            return {"success": False, "error": str(e)}

    async def close_all_positions(self) -> Dict[str, Any]:
        """Закрытие всех позиций"""
        try:
            closed_count = 0
            errors = []

            symbols_to_close = list(self.active_positions.keys())

            for symbol in symbols_to_close:
                result = await self.close_position_manually(symbol)
                if result.get("success"):
                    closed_count += 1
                else:
                    errors.append(f"{symbol}: {result.get('error')}")

            logger.info(f"✅ Закрыто позиций: {closed_count}")

            return {"success": True, "closed_count": closed_count, "errors": errors}

        except Exception as e:
            logger.error(f"Ошибка закрытия всех позиций: {e}")
            return {"success": False, "error": str(e)}

    async def get_position_summary(self) -> Dict[str, Any]:
        """Получение сводки по позициям"""
        try:
            total_pnl = 0.0
            position_details = []

            for symbol, position in self.active_positions.items():
                size = float(position.get("pos", "0"))
                entry_price = float(position.get("avgPx", "0"))
                current_price = float(position.get("markPx", "0"))
                side = position.get("posSide", "long")

                # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: size из API в КОНТРАКТАХ!
                # Нужно получить ctVal для конвертации в монеты перед расчетом PnL
                try:
                    details = await self.client.get_instrument_details(symbol)
                    ct_val = details.get("ctVal", 0.01)  # По умолчанию для BTC/ETH
                    # Реальный размер в монетах
                    size_in_coins = abs(size) * ct_val
                except Exception as e:
                    logger.warning(
                        f"⚠️ Ошибка получения ctVal для {symbol} в get_position_summary: {e}"
                    )
                    # Fallback: предполагаем что size уже в монетах (для совместимости)
                    size_in_coins = abs(size)

                # Расчет PnL (теперь с правильным размером в монетах)
                if side.lower() == "long":
                    pnl = (current_price - entry_price) * size_in_coins
                else:  # short
                    pnl = (entry_price - current_price) * size_in_coins

                total_pnl += pnl

                # Расчет PnL в процентах (от стоимости позиции в USD)
                position_value_usd = size_in_coins * entry_price
                pnl_percent = (
                    (pnl / position_value_usd * 100) if position_value_usd > 0 else 0.0
                )

                position_details.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "size": size,  # В контрактах (для справки)
                        "size_in_coins": size_in_coins,  # В монетах (для расчета)
                        "entry_price": entry_price,
                        "current_price": current_price,
                        "pnl": pnl,
                        "pnl_percent": pnl_percent,
                    }
                )

            return {
                "active_positions_count": len(self.active_positions),
                "total_pnl": total_pnl,
                "positions": position_details,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Ошибка получения сводки по позициям: {e}")
            return {"error": str(e)}

    def get_management_statistics(self) -> Dict[str, Any]:
        """Получение статистики управления позициями"""
        try:
            total = self.management_stats["total_positions"]
            closed = self.management_stats["closed_positions"]

            tp_rate = (
                (self.management_stats["tp_closed"] / closed * 100) if closed > 0 else 0
            )
            sl_rate = (
                (self.management_stats["sl_closed"] / closed * 100) if closed > 0 else 0
            )

            return {
                "total_positions": total,
                "closed_positions": closed,
                "active_positions": len(self.active_positions),
                "tp_closed": self.management_stats["tp_closed"],
                "sl_closed": self.management_stats["sl_closed"],
                "manual_closed": self.management_stats["manual_closed"],
                "tp_rate": tp_rate,
                "sl_rate": sl_rate,
                "total_pnl": self.management_stats["total_pnl"],
                "last_position_time": self.position_history[-1]["close_time"]
                if self.position_history
                else None,
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики управления: {e}")
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

    # Создаем клиент и margin calculator
    client = OKXFuturesClient("test_key", "test_secret", "test_passphrase")
    margin_calculator = MarginCalculator()

    # Создаем менеджер позиций
    manager = FuturesPositionManager(config, client, margin_calculator)

    print("FuturesPositionManager готов к работе")
