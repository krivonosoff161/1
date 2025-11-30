"""
EntryManager - Управление открытием позиций.

Отвечает за:
- Открытие позиций на бирже
- Расчет размера позиции (делегирует в PositionSizer)
- Регистрацию в PositionRegistry
- Инициализацию Trailing Stop Loss
"""

from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from ..core.position_registry import PositionMetadata, PositionRegistry


class EntryManager:
    """
    Менеджер открытия позиций.

    Координирует процесс открытия позиций:
    1. Расчет размера позиции
    2. Размещение ордера на бирже
    3. Регистрация в PositionRegistry
    4. Инициализация Trailing Stop Loss
    """

    def __init__(
        self,
        position_registry: PositionRegistry,
        order_executor,  # FuturesOrderExecutor
        position_sizer=None,  # PositionSizer (будет создан в ЭТАПЕ 5)
    ):
        """
        Инициализация EntryManager.

        Args:
            position_registry: Реестр позиций
            order_executor: Исполнитель ордеров
            position_sizer: Калькулятор размера позиций (опционально)
        """
        self.position_registry = position_registry
        self.order_executor = order_executor
        self.position_sizer = position_sizer

        logger.info("✅ EntryManager инициализирован")

    def set_position_sizer(self, position_sizer):
        """Установить PositionSizer"""
        self.position_sizer = position_sizer
        logger.debug("✅ EntryManager: PositionSizer установлен")

    async def open_position(
        self,
        signal: Dict[str, Any],
        regime: Optional[str] = None,
        regime_params: Optional[Dict[str, Any]] = None,
        balance_profile: Optional[str] = None,
    ) -> bool:
        """
        Открыть позицию на основе сигнала.

        Args:
            signal: Торговый сигнал
            regime: Режим рынка (trending, ranging, choppy)
            regime_params: Параметры режима
            balance_profile: Профиль баланса (small, medium, large)

        Returns:
            True если позиция успешно открыта
        """
        try:
            symbol = signal.get("symbol")
            if not symbol:
                logger.error("❌ EntryManager: Сигнал не содержит symbol")
                return False

            # Проверяем, нет ли уже открытой позиции
            has_position = await self.position_registry.has_position(symbol)
            if has_position:
                logger.debug(f"ℹ️ EntryManager: Позиция {symbol} уже открыта")
                return False

            # 1. Расчет размера позиции
            position_size = await self._calculate_position_size(
                signal, regime, regime_params, balance_profile
            )

            if not position_size or position_size <= 0:
                logger.warning(
                    f"⚠️ EntryManager: Невалидный размер позиции для {symbol}"
                )
                return False

            # 2. Размещение ордера на бирже через OrderExecutor
            order_result = await self._place_order(signal, position_size)

            if not order_result or not order_result.get("success"):
                logger.error(
                    f"❌ EntryManager: Не удалось разместить ордер для {symbol}"
                )
                return False

            # 3. Получаем данные открытой позиции
            position_data = await self._get_position_data(symbol, order_result)

            # 4. Создаем метаданные позиции
            metadata = PositionMetadata(
                entry_time=datetime.now(),
                regime=regime,
                balance_profile=balance_profile,
                entry_price=position_data.get("entry_price"),
                position_side=position_data.get("position_side"),  # "long" или "short"
                order_id=order_result.get("order_id"),
                tp_percent=signal.get("tp_percent"),
                sl_percent=signal.get("sl_percent"),
                leverage=signal.get("leverage"),
                size_in_coins=position_size,
                margin_used=position_data.get("margin_used"),
            )

            # 5. Регистрация в PositionRegistry
            await self.position_registry.register_position(
                symbol=symbol,
                position=position_data,
                metadata=metadata,
            )

            logger.info(
                f"✅ EntryManager: Позиция {symbol} открыта и зарегистрирована "
                f"(size={position_size:.6f}, entry={position_data.get('entry_price'):.2f}, "
                f"side={position_data.get('position_side')}, regime={regime})"
            )

            return True

        except Exception as e:
            logger.error(
                f"❌ EntryManager: Ошибка открытия позиции для {signal.get('symbol', 'UNKNOWN')}: {e}",
                exc_info=True,
            )
            return False

    async def open_position_with_size(
        self,
        signal: Dict[str, Any],
        position_size: float,
        regime: Optional[str] = None,
        regime_params: Optional[Dict[str, Any]] = None,
        balance_profile: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        ✅ Открыть позицию с уже рассчитанным размером (обертка для signal_coordinator).

        Этот метод используется когда размер позиции уже рассчитан (например, через risk_manager).
        Он оборачивает order_executor.execute_signal() и дополнительно регистрирует позицию в PositionRegistry.

        Args:
            signal: Торговый сигнал
            position_size: Размер позиции в монетах (уже рассчитан)
            regime: Режим рынка (trending, ranging, choppy)
            regime_params: Параметры режима
            balance_profile: Профиль баланса (small, medium, large)

        Returns:
            Результат исполнения (как от order_executor.execute_signal()) или None
        """
        try:
            symbol = signal.get("symbol")
            if not symbol:
                logger.error("❌ EntryManager: Сигнал не содержит symbol")
                return {"success": False, "error": "Сигнал не содержит symbol"}

            # Проверяем, нет ли уже открытой позиции
            has_position = await self.position_registry.has_position(symbol)
            if has_position:
                logger.debug(f"ℹ️ EntryManager: Позиция {symbol} уже открыта")
                return {"success": False, "error": f"Позиция {symbol} уже открыта"}

            if position_size <= 0:
                logger.warning(
                    f"⚠️ EntryManager: Невалидный размер позиции для {symbol}: {position_size}"
                )
                return {
                    "success": False,
                    "error": f"Невалидный размер позиции: {position_size}",
                }

            # 1. Размещение ордера на бирже через OrderExecutor (используем уже рассчитанный размер)
            order_result = await self.order_executor.execute_signal(
                signal, position_size
            )

            if not order_result:
                logger.error(
                    f"❌ EntryManager: order_executor.execute_signal вернул None для {symbol}"
                )
                return {"success": False, "error": "order_executor вернул None"}

            if not order_result.get("success"):
                logger.error(
                    f"❌ EntryManager: Не удалось разместить ордер для {symbol}"
                )
                return order_result  # Возвращаем результат, даже если неуспешный

            # 2. Получаем данные открытой позиции с биржи
            try:
                # Ждем немного для синхронизации позиций на бирже
                import asyncio

                await asyncio.sleep(1)

                # Получаем позицию с биржи
                # ✅ Получаем client через order_executor
                if hasattr(self.order_executor, "client"):
                    client = self.order_executor.client
                    positions = await client.get_positions()
                else:
                    logger.warning(
                        "⚠️ EntryManager: order_executor не имеет атрибута client, "
                        "не можем получить позицию с биржи"
                    )
                    positions = []
                inst_id = f"{symbol}-SWAP"

                position_data = None
                for pos in positions:
                    pos_inst_id = pos.get("instId", "")
                    pos_size = abs(float(pos.get("pos", "0")))

                    if (
                        pos_inst_id == inst_id or pos_inst_id == symbol
                    ) and pos_size > 0.000001:
                        # Определяем side позиции
                        pos_side_raw = pos.get("posSide", "").lower()
                        if pos_side_raw in ["long", "short"]:
                            position_side = pos_side_raw
                        else:
                            position_side = (
                                "long" if float(pos.get("pos", "0")) > 0 else "short"
                            )

                        # ✅ КРИТИЧЕСКОЕ: Получаем entry_time из API (cTime/uTime) для правильной инициализации
                        entry_time_from_api = None
                        c_time = pos.get("cTime")
                        u_time = pos.get("uTime")
                        entry_time_str = c_time or u_time
                        if entry_time_str:
                            try:
                                entry_timestamp_ms = int(entry_time_str)
                                entry_timestamp_sec = entry_timestamp_ms / 1000.0
                                entry_time_from_api = datetime.fromtimestamp(
                                    entry_timestamp_sec
                                )
                            except (ValueError, TypeError):
                                pass

                        position_data = {
                            "symbol": symbol,
                            "instId": pos.get("instId", ""),
                            "pos": pos.get("pos", "0"),
                            "posSide": position_side,
                            "avgPx": pos.get("avgPx", "0"),
                            "markPx": pos.get("markPx", pos.get("avgPx", "0")),
                            "size": pos_size,
                            "entry_price": float(pos.get("avgPx", "0")),
                            "position_side": position_side,
                            "margin_used": float(pos.get("margin", "0"))
                            if pos.get("margin")
                            else 0.0,
                            "entry_time": entry_time_from_api,  # ✅ Сохраняем entry_time из API, если доступно
                        }
                        break

                # Если позицию не нашли, используем данные из order_result
                if not position_data:
                    logger.warning(
                        f"⚠️ EntryManager: Позиция {symbol} не найдена на бирже после открытия, "
                        f"используем данные из order_result"
                    )
                    side = signal.get("side", "").lower()
                    position_data = {
                        "symbol": symbol,
                        "instId": f"{symbol}-SWAP",
                        "pos": str(position_size)
                        if side == "buy"
                        else str(-position_size),
                        "posSide": "long" if side == "buy" else "short",
                        "avgPx": signal.get("price", "0"),
                        "markPx": signal.get("price", "0"),
                        "size": position_size,
                        "entry_price": signal.get("price", 0.0),
                        "position_side": "long" if side == "buy" else "short",
                        "margin_used": 0.0,  # Будет рассчитано позже
                    }

            except Exception as e:
                logger.warning(
                    f"⚠️ EntryManager: Ошибка получения данных позиции с биржи для {symbol}: {e}, "
                    f"используем упрощенные данные"
                )
                side = signal.get("side", "").lower()
                position_data = {
                    "symbol": symbol,
                    "instId": f"{symbol}-SWAP",
                    "pos": str(position_size) if side == "buy" else str(-position_size),
                    "posSide": "long" if side == "buy" else "short",
                    "avgPx": signal.get("price", "0"),
                    "markPx": signal.get("price", "0"),
                    "size": position_size,
                    "entry_price": signal.get("price", 0.0),
                    "position_side": "long" if side == "buy" else "short",
                    "margin_used": 0.0,
                }

            # 3. Создаем метаданные позиции
            # ✅ КРИТИЧЕСКОЕ: Используем entry_time из API, если доступно, иначе datetime.now() (для новых позиций)
            entry_time_for_metadata = position_data.get("entry_time")
            if not entry_time_for_metadata:
                entry_time_for_metadata = (
                    datetime.now()
                )  # Для новых позиций используем текущее время

            # ✅ ПРОВЕРКА: Режим должен быть определен адаптивно!
            final_regime = regime or signal.get("regime")
            if not final_regime:
                logger.warning(
                    f"⚠️ КРИТИЧНО: Режим не определен для {symbol} при сохранении metadata! "
                    f"regime={regime}, signal.regime={signal.get('regime')}. "
                    f"Позиция будет использовать fallback 'ranging' в ExitAnalyzer"
                )
            
            metadata = PositionMetadata(
                entry_time=entry_time_for_metadata,  # ✅ Используем entry_time из API или текущее время
                regime=final_regime,  # Может быть None - ExitAnalyzer использует динамический режим
                balance_profile=balance_profile,
                entry_price=position_data.get("entry_price"),
                position_side=position_data.get("position_side"),
                order_id=order_result.get("order_id"),
                tp_percent=signal.get("tp_percent"),
                sl_percent=signal.get("sl_percent"),
                leverage=signal.get("leverage"),
                size_in_coins=position_size,
                margin_used=position_data.get("margin_used"),
            )

            # 4. Регистрация в PositionRegistry
            await self.position_registry.register_position(
                symbol=symbol,
                position=position_data,
                metadata=metadata,
            )

            logger.info(
                f"✅ EntryManager: Позиция {symbol} открыта и зарегистрирована в PositionRegistry "
                f"(size={position_size:.6f}, entry={position_data.get('entry_price'):.2f}, "
                f"side={position_data.get('position_side')}, regime={regime})"
            )

            # 5. Возвращаем результат, как от order_executor.execute_signal()
            return order_result

        except Exception as e:
            logger.error(
                f"❌ EntryManager: Ошибка открытия позиции для {signal.get('symbol', 'UNKNOWN')}: {e}",
                exc_info=True,
            )
            return None

    async def _calculate_position_size(
        self,
        signal: Dict[str, Any],
        regime: Optional[str] = None,
        regime_params: Optional[Dict[str, Any]] = None,
        balance_profile: Optional[str] = None,
    ) -> Optional[float]:
        """
        Рассчитать размер позиции.

        Делегирует в PositionSizer, если он установлен.
        Иначе использует упрощенный расчет.

        Args:
            signal: Торговый сигнал
            regime: Режим рынка
            regime_params: Параметры режима
            balance_profile: Профиль баланса

        Returns:
            Размер позиции в монетах или None
        """
        if self.position_sizer:
            # Делегируем в PositionSizer
            return await self.position_sizer.calculate_position_size(
                signal, regime, regime_params, balance_profile
            )

        # Упрощенный расчет (fallback)
        symbol = signal.get("symbol")
        price = signal.get("price", 1.0)
        base_size_usd = 100.0  # Базовый размер в USD

        # Упрощенный расчет: размер в монетах = размер в USD / цена
        position_size = base_size_usd / price

        logger.debug(
            f"ℹ️ EntryManager: Использован упрощенный расчет размера для {symbol}: "
            f"{position_size:.6f} монет (${base_size_usd:.2f} @ ${price:.2f})"
        )

        return position_size

    async def _place_order(
        self, signal: Dict[str, Any], position_size: float
    ) -> Optional[Dict[str, Any]]:
        """
        Разместить ордер на бирже.

        Делегирует в OrderExecutor.

        Args:
            signal: Торговый сигнал
            position_size: Размер позиции в монетах

        Returns:
            Результат размещения ордера или None
        """
        try:
            # Делегируем в OrderExecutor
            # Метод зависит от реализации OrderExecutor
            if hasattr(self.order_executor, "execute_signal"):
                result = await self.order_executor.execute_signal(signal, position_size)
                if result:
                    return {
                        "success": result.get("success", False),
                        "order_id": result.get("order_id"),
                        "order_type": result.get("order_type"),
                        "entry_price": result.get("entry_price"),
                        "position_side": result.get("position_side"),
                        "size": position_size,
                        "margin_used": result.get("margin_used"),
                    }
                return None
            elif hasattr(self.order_executor, "place_order"):
                # Прямое размещение ордера
                side = signal.get("side", "").lower()
                from src.models import OrderSide

                order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

                order = await self.order_executor.place_order(
                    symbol=signal.get("symbol"),
                    side=order_side,
                    quantity=position_size,
                )

                return {
                    "success": order is not None,
                    "order_id": order.id if order else None,
                }
            else:
                logger.error(
                    "❌ EntryManager: OrderExecutor не имеет метода execute_signal или place_order"
                )
                return None

        except Exception as e:
            logger.error(
                f"❌ EntryManager: Ошибка размещения ордера: {e}", exc_info=True
            )
            return None

    async def _get_position_data(
        self, symbol: str, order_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Получить данные открытой позиции с биржи.

        Args:
            symbol: Торговый символ
            order_result: Результат размещения ордера

        Returns:
            Данные позиции
        """
        # Получаем данные позиции с биржи
        # Это упрощенная версия - в реальности нужно получить данные с биржи
        return {
            "symbol": symbol,
            "order_id": order_result.get("order_id"),
            "entry_price": order_result.get("entry_price", 0.0),
            "position_side": order_result.get("position_side", "long"),
            "size": order_result.get("size", 0.0),
            "margin_used": order_result.get("margin_used", 0.0),
        }
