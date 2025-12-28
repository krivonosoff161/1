"""
EntryManager - Управление открытием позиций.

Отвечает за:
- Открытие позиций на бирже
- Расчет размера позиции (делегирует в PositionSizer)
- Регистрацию в PositionRegistry
- Инициализацию Trailing Stop Loss
"""

import asyncio
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
        self.performance_tracker = None  # Будет установлен из orchestrator
        self.conversion_metrics = None  # ✅ НОВОЕ (26.12.2025): ConversionMetrics для отслеживания конверсии

        logger.info("✅ EntryManager инициализирован")

    def set_position_sizer(self, position_sizer):
        """Установить PositionSizer"""
        self.position_sizer = position_sizer
        logger.debug("✅ EntryManager: PositionSizer установлен")

    def set_performance_tracker(self, performance_tracker):
        """Установить PerformanceTracker для логирования"""
        self.performance_tracker = performance_tracker
        logger.debug("✅ EntryManager: PerformanceTracker установлен")

    def set_conversion_metrics(self, conversion_metrics):
        """
        ✅ НОВОЕ (26.12.2025): Установить ConversionMetrics для отслеживания конверсии сигналов.

        Args:
            conversion_metrics: Экземпляр ConversionMetrics
        """
        self.conversion_metrics = conversion_metrics
        logger.debug("✅ EntryManager: ConversionMetrics установлен")

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

            # ✅ УЛУЧШЕНИЕ: Синхронизация реестра с биржей перед открытием позиции
            # Проверяем, нет ли уже открытой позиции в реестре
            has_position = await self.position_registry.has_position(symbol)
            if has_position:
                logger.debug(f"ℹ️ EntryManager: Позиция {symbol} уже открыта в реестре")
                return False

            # ✅ НОВОЕ: Дополнительная проверка на бирже (синхронизация)
            # Получаем актуальные позиции с биржи для проверки
            try:
                exchange_positions = await self.client.get_positions(symbol)
                for pos in exchange_positions:
                    inst_id = pos.get("instId", "").replace("-SWAP", "")
                    if inst_id == symbol:
                        pos_size = float(pos.get("pos", "0"))
                        if abs(pos_size) >= 1e-8:  # Позиция существует на бирже
                            pos_side = pos.get("posSide", "long").lower()
                            signal_side = signal.get("side", "buy").lower()
                            signal_position_side = (
                                "long" if signal_side == "buy" else "short"
                            )

                            logger.warning(
                                f"⚠️ EntryManager: Позиция {symbol} {pos_side.upper()} уже существует на бирже "
                                f"(size={pos_size:.6f}), блокируем открытие новой позиции {signal_position_side.upper()}"
                            )
                            return False
            except Exception as e:
                logger.warning(
                    f"⚠️ EntryManager: Ошибка проверки позиций на бирже для {symbol}: {e}. "
                    f"Продолжаем открытие позиции (может быть race condition)"
                )

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
            from datetime import timezone

            now_utc = datetime.now(timezone.utc)
            metadata = PositionMetadata(
                entry_time=now_utc,
                # ✅ Трассировка: устойчивый position_id для склейки событий (entry/partial/final)
                # Формат: SYMBOL:epoch_ms:order_id
                position_id=f"{symbol}:{int(now_utc.timestamp()*1000)}:{order_result.get('order_id','')}",
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
                f"(size={position_size:.6f}, entry={position_data.get('entry_price'):.6f}, "
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
                                # ✅ ИСПРАВЛЕНО: Добавляем timezone.utc для правильного timestamp
                                from datetime import timezone

                                entry_time_from_api = datetime.fromtimestamp(
                                    entry_timestamp_sec, tz=timezone.utc
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

                # Если позицию не нашли, делаем retry с задержкой
                if not position_data:
                    logger.warning(
                        f"⚠️ EntryManager: Позиция {symbol} не найдена сразу, ждём 0.5 сек и делаем retry..."
                    )
                    await asyncio.sleep(0.5)

                    # Retry получения позиции
                    try:
                        positions_retry = await client.get_positions()
                        for pos in positions_retry:
                            pos_inst_id = pos.get("instId", "")
                            pos_size = abs(float(pos.get("pos", "0")))
                            if (
                                pos_inst_id == inst_id or pos_inst_id == symbol
                            ) and pos_size > 0.000001:
                                pos_side_raw = pos.get("posSide", "").lower()
                                position_side = (
                                    pos_side_raw
                                    if pos_side_raw in ["long", "short"]
                                    else (
                                        "long"
                                        if float(pos.get("pos", "0")) > 0
                                        else "short"
                                    )
                                )

                                # ✅ FIX: Получаем ТОЧНУЮ цену avgPx с биржи
                                real_entry_price = float(pos.get("avgPx", "0"))
                                logger.info(
                                    f"✅ Retry успешен! Получена реальная entry_price={real_entry_price:.6f} для {symbol}"
                                )

                                position_data = {
                                    "symbol": symbol,
                                    "instId": pos.get("instId", ""),
                                    "pos": pos.get("pos", "0"),
                                    "posSide": position_side,
                                    "avgPx": pos.get("avgPx", "0"),
                                    "markPx": pos.get("markPx", pos.get("avgPx", "0")),
                                    "size": pos_size,
                                    "entry_price": real_entry_price,
                                    "position_side": position_side,
                                    "margin_used": float(pos.get("margin", "0"))
                                    if pos.get("margin")
                                    else 0.0,
                                }
                                break
                    except Exception as retry_e:
                        logger.warning(f"⚠️ Retry не удался: {retry_e}")

                # Если всё ещё не нашли — используем order_result.price (лимитная цена)
                if not position_data:
                    logger.warning(
                        f"⚠️ EntryManager: Позиция {symbol} не найдена на бирже после retry, "
                        f"используем цену из order_result"
                    )
                    side = signal.get("side", "").lower()
                    # ✅ FIX: Используем order_result.price (лимитная цена) вместо signal.price (может быть округлена)
                    fallback_price = order_result.get("price", signal.get("price", 0.0))
                    if isinstance(fallback_price, str):
                        fallback_price = (
                            float(fallback_price) if fallback_price else 0.0
                        )
                    logger.info(
                        f"📊 Fallback entry_price={fallback_price:.6f} для {symbol} (из order_result)"
                    )

                    position_data = {
                        "symbol": symbol,
                        "instId": f"{symbol}-SWAP",
                        "pos": str(position_size)
                        if side == "buy"
                        else str(-position_size),
                        "posSide": "long" if side == "buy" else "short",
                        "avgPx": str(fallback_price),
                        "markPx": str(fallback_price),
                        "size": position_size,
                        "entry_price": fallback_price,
                        "position_side": "long" if side == "buy" else "short",
                        "margin_used": 0.0,  # Будет рассчитано позже
                    }

            except Exception as e:
                logger.warning(
                    f"⚠️ EntryManager: Ошибка получения данных позиции с биржи для {symbol}: {e}, "
                    f"используем данные из order_result"
                )
                side = signal.get("side", "").lower()
                # ✅ FIX: Используем order_result.price вместо signal.price
                fallback_price = order_result.get("price", signal.get("price", 0.0))
                if isinstance(fallback_price, str):
                    fallback_price = float(fallback_price) if fallback_price else 0.0
                logger.info(
                    f"📊 Exception fallback entry_price={fallback_price:.6f} для {symbol}"
                )

                position_data = {
                    "symbol": symbol,
                    "instId": f"{symbol}-SWAP",
                    "pos": str(position_size) if side == "buy" else str(-position_size),
                    "posSide": "long" if side == "buy" else "short",
                    "avgPx": str(fallback_price),
                    "markPx": str(fallback_price),
                    "size": position_size,
                    "entry_price": fallback_price,
                    "position_side": "long" if side == "buy" else "short",
                    "margin_used": 0.0,
                }

            # 3. Создаем метаданные позиции
            # ✅ КРИТИЧЕСКОЕ: Используем entry_time из API, если доступно, иначе datetime.now(timezone.utc) (для новых позиций)
            entry_time_for_metadata = position_data.get("entry_time")
            if not entry_time_for_metadata:
                from datetime import timezone

                entry_time_for_metadata = datetime.now(
                    timezone.utc
                )  # Для новых позиций используем текущее время в UTC

            # ✅ ПРОВЕРКА: Режим должен быть определен адаптивно!
            final_regime = regime or signal.get("regime")
            if not final_regime:
                logger.warning(
                    f"⚠️ КРИТИЧНО: Режим не определен для {symbol} при сохранении metadata! "
                    f"regime={regime}, signal.regime={signal.get('regime')}. "
                    f"Позиция будет использовать fallback 'ranging' в ExitAnalyzer"
                )

            # ✅ НОВОЕ: Получаем min_holding_seconds из regime_params для сохранения в metadata
            min_holding_seconds = None
            if regime_params and isinstance(regime_params, dict):
                min_holding_minutes = regime_params.get("min_holding_minutes")
                if min_holding_minutes is not None:
                    min_holding_seconds = float(min_holding_minutes) * 60.0

            metadata = PositionMetadata(
                entry_time=entry_time_for_metadata,  # ✅ Используем entry_time из API или текущее время
                position_id=f"{symbol}:{int(entry_time_for_metadata.timestamp()*1000)}:{order_result.get('order_id','')}",
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
                min_holding_seconds=min_holding_seconds,  # ✅ НОВОЕ: Сохраняем min_holding из конфига
            )

            # 4. Регистрация в PositionRegistry
            await self.position_registry.register_position(
                symbol=symbol,
                position=position_data,
                metadata=metadata,
            )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Сохраняем режим в position_data для active_positions
            if final_regime:
                position_data["regime"] = final_regime
                logger.debug(
                    f"✅ EntryManager: Режим {final_regime} сохранен в position_data для {symbol}"
                )

            # ✅ КРИТИЧЕСКОЕ УЛУЧШЕНИЕ ЛОГИРОВАНИЯ (26.12.2025): Добавляем детальную информацию при открытии
            tp_percent = signal.get("tp_percent") or metadata.tp_percent if metadata and hasattr(metadata, "tp_percent") else None
            sl_percent = signal.get("sl_percent") or metadata.sl_percent if metadata and hasattr(metadata, "sl_percent") else None
            leverage = signal.get("leverage") or metadata.leverage if metadata and hasattr(metadata, "leverage") else None
            
            log_parts = [
                f"✅ EntryManager: Позиция {symbol} открыта и зарегистрирована",
                f"size={position_size:.6f}",
                f"entry_price={position_data.get('entry_price'):.6f}",
                f"side={position_data.get('position_side')}",
                f"regime={final_regime or 'unknown'}",
            ]
            
            if tp_percent:
                log_parts.append(f"TP={tp_percent:.2f}%")
            if sl_percent:
                log_parts.append(f"SL={sl_percent:.2f}%")
            if leverage:
                log_parts.append(f"leverage={leverage}x")
            
            logger.info(" | ".join(log_parts))

            # ✅ НОВОЕ (26.12.2025): Записываем исполненный сигнал в метрики
            if hasattr(self, 'conversion_metrics') and self.conversion_metrics:
                try:
                    signal_type = signal.get("source", "unknown")
                    self.conversion_metrics.record_signal_executed(
                        symbol=symbol,
                        signal_type=signal_type,
                        regime=final_regime
                    )
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка записи метрики исполненного сигнала для {symbol}: {e}")

            # ✅ НОВОЕ: Логирование открытия позиции в CSV
            if self.performance_tracker:
                try:
                    self.performance_tracker.record_position_open(
                        symbol=symbol,
                        side=position_data.get("position_side", "long"),
                        entry_price=position_data.get("entry_price", 0.0),
                        size=position_size,
                        regime=final_regime or "unknown",
                        order_id=order_result.get("order_id"),
                        order_type=order_result.get("order_type", "limit"),
                    )
                    logger.debug(
                        f"✅ EntryManager: Открытие позиции {symbol} записано в CSV"
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ EntryManager: Ошибка записи открытия позиции в CSV: {e}"
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
