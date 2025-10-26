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
            await self._check_tp_sl(position)

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

            # Получение баланса
            balance = await self.client.get_balance()

            # Расчет стоимости позиции
            position_value = abs(size) * current_price

            # Проверка безопасности через Margin Calculator
            is_safe, details = self.margin_calculator.is_position_safe(
                position_value,
                balance,
                current_price,
                entry_price,
                side,
                leverage,
                safety_threshold=1.5,
            )

            if not is_safe:
                margin_ratio = details["margin_ratio"]
                logger.warning(
                    f"⚠️ Позиция {symbol} небезопасна: маржа {margin_ratio:.1f}%"
                )

                # Дополнительные действия при низкой марже
                if margin_ratio < 1.2:
                    await self._emergency_close_position(position)

        except Exception as e:
            logger.error(f"Ошибка проверки безопасности позиции: {e}")

    async def _check_tp_sl(self, position: Dict[str, Any]):
        """Проверка Take Profit и Stop Loss"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            side = position.get("posSide", "long")
            entry_price = float(position.get("avgPx", "0"))
            current_price = float(position.get("markPx", "0"))

            if size == 0:
                return

            # Расчет PnL
            if side.lower() == "long":
                pnl_percent = (current_price - entry_price) / entry_price * 100
            else:  # short
                pnl_percent = (entry_price - current_price) / entry_price * 100

            # Проверка Take Profit
            tp_percent = self.scalping_config.tp_percent
            if pnl_percent >= tp_percent:
                logger.info(f"🎯 TP достигнут для {symbol}: {pnl_percent:.2f}%")
                await self._close_position_by_reason(position, "tp")
                return

            # Проверка Stop Loss
            sl_percent = self.scalping_config.sl_percent
            if pnl_percent <= -sl_percent:
                logger.info(f"🛑 SL сработал для {symbol}: {pnl_percent:.2f}%")
                await self._close_position_by_reason(position, "sl")
                return

        except Exception as e:
            logger.error(f"Ошибка проверки TP/SL: {e}")

    async def _close_position_by_reason(self, position: Dict[str, Any], reason: str):
        """Закрытие позиции по причине"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            side = position.get("posSide", "long")

            logger.info(f"🔄 Закрытие позиции {symbol} по причине: {reason}")

            # Определение стороны закрытия
            close_side = "sell" if side.lower() == "long" else "buy"

            # Размещение рыночного ордера на закрытие
            result = await self.client.place_futures_order(
                symbol=symbol, side=close_side, size=abs(size), order_type="market"
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

            # Расчет текущего PnL
            if side.lower() == "long":
                pnl = (current_price - entry_price) * abs(size)
            else:  # short
                pnl = (entry_price - current_price) * abs(size)

            # Обновление общего PnL
            self.management_stats["total_pnl"] += pnl

            logger.debug(f"📈 Позиция {symbol}: PnL = {pnl:.2f} USDT")

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
            positions = await self.client.get_positions(symbol)

            # Проверяем, что positions это dict с ключом "data"
            if not isinstance(positions, dict) or not positions.get("data"):
                logger.warning(f"Позиция {symbol} не найдена на бирже")
                return {"success": False, "error": "Позиция не найдена"}

            for pos_data in positions["data"]:
                inst_id = pos_data.get("instId", "").replace("-SWAP", "")
                if inst_id != symbol:
                    continue

                size = float(pos_data.get("pos", "0"))
                if size == 0:
                    logger.warning(f"Размер позиции {symbol} = 0")
                    continue

                side = pos_data.get("posSide", "long")

                logger.info(f"🔄 Закрытие позиции {symbol} {side} размер={size}")

                # Определение стороны закрытия
                close_side = "sell" if side.lower() == "long" else "buy"

                # ✅ Размещаем рыночный ордер на закрытие
                result = await self.client.place_futures_order(
                    symbol=symbol, side=close_side, size=abs(size), order_type="market"
                )

                if result.get("code") == "0":
                    logger.info(f"✅ Позиция {symbol} закрыта через API")
                    return {"success": True, "symbol": symbol}
                else:
                    error_msg = result.get("msg", "Неизвестная ошибка")
                    logger.error(f"❌ Ошибка закрытия {symbol}: {error_msg}")
                    return {"success": False, "error": error_msg}

            return {"success": False, "error": "Позиция не найдена"}

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

                # Расчет PnL
                if side.lower() == "long":
                    pnl = (current_price - entry_price) * abs(size)
                else:  # short
                    pnl = (entry_price - current_price) * abs(size)

                total_pnl += pnl

                position_details.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "size": size,
                        "entry_price": entry_price,
                        "current_price": current_price,
                        "pnl": pnl,
                        "pnl_percent": pnl / (abs(size) * entry_price) * 100,
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
