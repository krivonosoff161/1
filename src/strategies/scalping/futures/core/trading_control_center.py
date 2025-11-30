"""
TradingControlCenter - Центральный координатор торговой логики.

Отвечает за:
- Главный торговый цикл
- Управление позициями
- Обновление состояния
- Обновление статистики

Вынесено из orchestrator.py для разделения ответственности:
- orchestrator.py: инициализация/остановка модулей
- trading_control_center.py: торговая логика
"""

import asyncio
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

# ✅ НОВОЕ: Импорт для memory usage
try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("⚠️ psutil не установлен - memory usage не будет логироваться")


class TradingControlCenter:
    """
    Центральный координатор торговой логики.

    Координирует:
    - Генерацию и обработку сигналов
    - Управление позициями
    - Синхронизацию с биржей
    - Обновление статистики
    """

    def __init__(
        self,
        client: Any,  # OKXFuturesClient
        signal_generator: Any,  # FuturesSignalGenerator
        signal_coordinator: Any,  # SignalCoordinator
        position_manager: Any,  # FuturesPositionManager
        position_registry: Any,  # PositionRegistry
        data_registry: Any,  # DataRegistry
        order_coordinator: Any,  # OrderCoordinator
        trailing_sl_coordinator: Any,  # TrailingSLCoordinator
        performance_tracker: Any,  # PerformanceTracker
        trading_statistics: Any,  # TradingStatistics
        liquidation_guard: Any,  # LiquidationGuard
        config_manager: Any,  # ConfigManager
        scalping_config: Any,  # ScalpingConfig
        active_positions: Any,  # Прокси к position_registry
        normalize_symbol: Any,  # Метод нормализации символа
        sync_positions_with_exchange: Any,  # Метод синхронизации позиций
    ):
        """
        Инициализация TradingControlCenter.

        Args:
            client: Клиент биржи
            signal_generator: Генератор сигналов
            signal_coordinator: Координатор сигналов
            position_manager: Менеджер позиций
            position_registry: Реестр позиций
            data_registry: Реестр данных
            order_coordinator: Координатор ордеров
            trailing_sl_coordinator: Координатор Trailing SL
            performance_tracker: Трекер производительности
            trading_statistics: Статистика торговли
            liquidation_guard: Защита от ликвидации
            config_manager: Менеджер конфигурации
            scalping_config: Конфигурация скальпинга
            active_positions: Прокси к активным позициям
            normalize_symbol: Метод нормализации символа
            sync_positions_with_exchange: Метод синхронизации позиций
        """
        self.client = client
        self.signal_generator = signal_generator
        self.signal_coordinator = signal_coordinator
        self.position_manager = position_manager
        self.position_registry = position_registry
        self.data_registry = data_registry
        self.order_coordinator = order_coordinator
        self.trailing_sl_coordinator = trailing_sl_coordinator
        self.performance_tracker = performance_tracker
        self.trading_statistics = trading_statistics
        self.liquidation_guard = liquidation_guard
        self.config_manager = config_manager
        self.scalping_config = scalping_config
        self.active_positions = active_positions
        self._normalize_symbol = normalize_symbol
        self._sync_positions_with_exchange = sync_positions_with_exchange

        self.is_running = False

        # Внутренние состояния для периодических проверок
        self._last_adl_log_time = 0
        self._last_reversal_stats_log_time = 0
        # ✅ НОВОЕ: Для логирования memory usage (раз в 10 минут)
        self._last_memory_log_time = 0
        self._memory_log_interval = 600  # 10 минут

        logger.info("✅ TradingControlCenter инициализирован")

    async def run_main_loop(self) -> None:
        """
        Главный торговый цикл (бывший _main_trading_loop).

        Координирует все шаги торгового процесса:
        1. Обновление состояния
        2. Генерация сигналов
        3. Обработка сигналов
        4. Управление позициями
        5. Мониторинг ордеров
        6. Синхронизация с биржей
        7. Обновление статистики
        8. Проверка TSL
        """
        logger.info("🔄 TCC: Запуск основного торгового цикла")

        self.is_running = True
        loop_start_time = time.time()

        while self.is_running:
            try:
                cycle_start_time = time.perf_counter()

                # Проверяем is_running перед каждым шагом
                if not self.is_running:
                    break

                # ✅ НОВОЕ: Логирование memory usage раз в 10 минут
                current_time = time.time()
                if (
                    current_time - self._last_memory_log_time
                    >= self._memory_log_interval
                ):
                    await self._log_memory_usage()
                    self._last_memory_log_time = current_time

                # Обновление состояния
                state_start = time.perf_counter()
                await self.update_state()
                state_time = (time.perf_counter() - state_start) * 1000  # мс

                if not self.is_running:
                    break

                # Генерация сигналов
                signals_start = time.perf_counter()
                signals = await self.signal_generator.generate_signals()
                signals_time = (time.perf_counter() - signals_start) * 1000  # мс

                if len(signals) > 0:
                    logger.info(f"📊 TCC: Сгенерировано {len(signals)} сигналов")
                else:
                    logger.debug("📊 TCC: Сигналов не сгенерировано")

                if not self.is_running:
                    break

                # Обработка сигналов
                process_start = time.perf_counter()
                await self.signal_coordinator.process_signals(signals)
                process_time = (time.perf_counter() - process_start) * 1000  # мс

                if not self.is_running:
                    break

                # Управление позициями
                manage_start = time.perf_counter()
                await self.manage_positions()
                manage_time = (time.perf_counter() - manage_start) * 1000  # мс

                if not self.is_running:
                    break

                # Мониторинг лимитных ордеров (таймаут и замена на рыночные)
                monitor_start = time.perf_counter()
                await self.order_coordinator.monitor_limit_orders()
                monitor_time = (time.perf_counter() - monitor_start) * 1000  # мс

                if not self.is_running:
                    break

                # ✅ НОВОЕ: Логирование метрик производительности
                cycle_time = (time.perf_counter() - cycle_start_time) * 1000  # мс
                logger.debug(
                    f"⏱️ TCC Performance: cycle={cycle_time:.1f}ms, "
                    f"state={state_time:.1f}ms, signals={signals_time:.1f}ms, "
                    f"process={process_time:.1f}ms, manage={manage_time:.1f}ms, "
                    f"monitor={monitor_time:.1f}ms"
                )

                # Периодически обновляем статус ордеров в кэше
                await self.order_coordinator.update_orders_cache_status(
                    self._normalize_symbol
                )

                if not self.is_running:
                    break

                # Синхронизация локальных позиций с биржей
                await self._sync_positions_with_exchange()

                if not self.is_running:
                    break

                # Обновление статистики
                await self.update_performance()

                if not self.is_running:
                    break

                # Периодическая проверка TSL независимо от тикеров
                # Проверяем TSL каждые 1-2 секунды для всех открытых позиций
                await self.trailing_sl_coordinator.periodic_check()

                if not self.is_running:
                    break

                # Пауза между итерациями
                await asyncio.sleep(self.scalping_config.check_interval)

            except asyncio.CancelledError:
                logger.info("🛑 TCC: Торговый цикл отменен")
                break
            except Exception as e:
                logger.error(f"❌ TCC: Ошибка в торговом цикле: {e}")
                if self.is_running:
                    await asyncio.sleep(5)  # Пауза при ошибке
                else:
                    break

    async def manage_positions(self) -> None:
        """
        Управление открытыми позициями (бывший _manage_positions).

        Делегирует управление в position_manager и выполняет периодические проверки:
        - ADL мониторинг (раз в минуту)
        - Статистика разворотов (раз в 5 минут)
        """
        try:
            manage_start = time.perf_counter()

            # ✅ ИСПРАВЛЕНИЕ: Получаем актуальные позиции из PositionRegistry, а не из прокси
            all_positions = await self.position_registry.get_all_positions()
            positions_count = len(all_positions)

            if positions_count == 0:
                logger.debug("📊 TCC: Нет открытых позиций для анализа")
                return

            logger.debug(f"📊 TCC: Анализ {positions_count} позиций...")

            for symbol, position in all_positions.items():
                pos_start = time.perf_counter()
                await self.position_manager.manage_position(position)
                pos_time = (time.perf_counter() - pos_start) * 1000  # мс
                logger.debug(f"📊 TCC: {symbol} анализ завершен за {pos_time:.2f}ms")

            manage_time = (time.perf_counter() - manage_start) * 1000  # мс
            logger.debug(
                f"📊 TCC: Управление позициями завершено за {manage_time:.2f}ms ({positions_count} позиций)"
            )

            # ✅ НОВОЕ: Периодический мониторинг ADL для всех позиций
            # Логируем ADL для всех открытых позиций раз в минуту
            if hasattr(self, "_last_adl_log_time"):
                if time.time() - self._last_adl_log_time < 60:  # Раз в минуту
                    return
            else:
                self._last_adl_log_time = 0

            # Получаем актуальные данные позиций с биржи для ADL
            try:
                exchange_positions = await self.client.get_positions()
                adl_summary = []
                for pos in exchange_positions or []:
                    pos_size = float(pos.get("pos", "0") or 0)
                    if abs(pos_size) < 1e-8:
                        continue
                    inst_id = pos.get("instId", "")
                    if not inst_id:
                        continue
                    symbol = inst_id.replace("-SWAP", "")
                    adl_rank = pos.get("adlRank") or pos.get("adl")
                    if adl_rank is not None:
                        try:
                            adl_rank = int(adl_rank)
                            upl = float(pos.get("upl", "0") or 0)
                            margin = float(pos.get("margin", "0") or 0)
                            adl_status = (
                                "🔴 ВЫСОКИЙ"
                                if adl_rank >= 4
                                else "🟡 СРЕДНИЙ"
                                if adl_rank >= 2
                                else "🟢 НИЗКИЙ"
                            )
                            adl_summary.append(
                                {
                                    "symbol": symbol,
                                    "adl_rank": adl_rank,
                                    "status": adl_status,
                                    "upl": upl,
                                    "margin": margin,
                                }
                            )
                            # Обновляем ADL в active_positions
                            if symbol in self.active_positions:
                                self.active_positions[symbol]["adl_rank"] = adl_rank
                        except (ValueError, TypeError):
                            pass

                # Логируем сводку ADL для всех позиций
                if adl_summary:
                    adl_info = ", ".join(
                        [
                            f"{item['symbol']}: {item['status']} (rank={item['adl_rank']}, PnL={item['upl']:.2f} USDT)"
                            for item in adl_summary
                        ]
                    )
                    logger.info(f"📊 TCC: ADL мониторинг всех позиций: {adl_info}")

                    # Предупреждение при высоком ADL на любой позиции
                    high_adl_positions = [
                        item for item in adl_summary if item["adl_rank"] >= 4
                    ]
                    if high_adl_positions:
                        high_adl_info = ", ".join(
                            [
                                f"{item['symbol']} (rank={item['adl_rank']})"
                                for item in high_adl_positions
                            ]
                        )
                        logger.warning(
                            f"⚠️ TCC: ВЫСОКИЙ ADL обнаружен для позиций: {high_adl_info} "
                            f"(риск автоматического сокращения биржей)"
                        )

                self._last_adl_log_time = time.time()
            except Exception as e:
                logger.debug(f"⚠️ TCC: Не удалось получить ADL данные: {e}")

            # ✅ НОВОЕ: Периодический мониторинг статистики разворотов (раз в 5 минут)
            if hasattr(self, "_last_reversal_stats_log_time"):
                if (
                    time.time() - self._last_reversal_stats_log_time < 300
                ):  # Раз в 5 минут
                    pass
                else:
                    try:
                        if self.trading_statistics:
                            # Получаем статистику разворотов для всех символов и режимов
                            all_symbols = list(set(self.active_positions.keys()))
                            if all_symbols:
                                reversal_summary = []
                                for symbol in all_symbols:
                                    stats = self.trading_statistics.get_reversal_stats(
                                        symbol=symbol
                                    )
                                    if stats["total_reversals"] > 0:
                                        reversal_summary.append(
                                            f"{symbol}: {stats['total_reversals']} разворотов "
                                            f"(↓{stats['v_down_count']}, ↑{stats['v_up_count']}, "
                                            f"avg={stats['avg_price_change']:.2%})"
                                        )

                                if reversal_summary:
                                    reversal_info = ", ".join(reversal_summary)
                                    logger.info(
                                        f"📊 TCC: Статистика разворотов: {reversal_info}"
                                    )

                            # Общая статистика по режимам
                            for regime in ["trending", "ranging", "choppy"]:
                                stats = self.trading_statistics.get_reversal_stats(
                                    regime=regime
                                )
                                if stats["total_reversals"] > 0:
                                    logger.info(
                                        f"📊 TCC: Развороты в режиме {regime}: "
                                        f"{stats['total_reversals']} разворотов "
                                        f"(↓{stats['v_down_count']}, ↑{stats['v_up_count']})"
                                    )

                        self._last_reversal_stats_log_time = time.time()
                    except Exception as e:
                        logger.debug(
                            f"⚠️ TCC: Не удалось получить статистику разворотов: {e}"
                        )
            else:
                self._last_reversal_stats_log_time = 0

        except Exception as e:
            logger.error(f"❌ TCC: Ошибка управления позициями: {e}")

    async def update_state(self) -> None:
        """
        Обновление состояния системы (бывший _update_state).

        Синхронизирует позиции с биржей и проверяет здоровье маржи.
        """
        try:
            # ✅ Проверяем is_running перед выполнением операций
            if not self.is_running:
                return

            # Получение текущих позиций
            positions = await self.client.get_positions()

            if not self.is_running:
                return

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновление позиций через PositionRegistry с сохранением метаданных
            # Сохраняем существующие метаданные перед обновлением позиций
            all_registered = await self.position_registry.get_all_positions()
            all_metadata = await self.position_registry.get_all_metadata()

            # Удаляем позиции, которых больше нет на бирже
            exchange_symbols = set()
            for position in positions:
                symbol = position.get("instId", "").replace("-SWAP", "")
                size = float(position.get("pos", "0"))
                if abs(size) >= 1e-8:
                    exchange_symbols.add(symbol)

            # Удаляем позиции, которых нет на бирже
            for symbol in list(all_registered.keys()):
                if symbol not in exchange_symbols:
                    await self.position_registry.unregister_position(symbol)

            # Обновляем/регистрируем позиции с сохранением метаданных
            for position in positions:
                symbol = position.get("instId", "").replace("-SWAP", "")
                size = float(position.get("pos", "0"))
                if abs(size) >= 1e-8:
                    # ✅ КРИТИЧЕСКОЕ: Сохраняем существующие метаданные
                    existing_metadata = all_metadata.get(symbol)

                    # Получаем entry_price из position данных
                    try:
                        entry_price_from_api = float(position.get("avgPx", 0) or 0)
                    except (TypeError, ValueError):
                        entry_price_from_api = 0.0

                    # ✅ КРИТИЧЕСКОЕ: Получаем entry_time из API (cTime/uTime), если метаданных нет
                    entry_time_from_api = None
                    c_time = position.get("cTime")
                    u_time = position.get("uTime")
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

                    # Если метаданные уже есть, обновляем через update_position (без мутации)
                    if existing_metadata:
                        # ✅ КРИТИЧЕСКОЕ: Подготавливаем обновления для metadata (без мутации)
                        metadata_updates = {}

                        # Сохраняем entry_time, если он еще не установлен, но есть в API
                        if (
                            not existing_metadata.entry_time
                            or existing_metadata.entry_time == datetime.now()
                        ):
                            if entry_time_from_api:
                                metadata_updates["entry_time"] = entry_time_from_api

                        # Обновляем entry_price в метаданных если он изменился или отсутствует
                        if (
                            not existing_metadata.entry_price
                            or existing_metadata.entry_price == 0
                        ):
                            if entry_price_from_api > 0:
                                metadata_updates["entry_price"] = entry_price_from_api

                        # Получаем текущий режим из signal_generator если regime отсутствует
                        if not existing_metadata.regime:
                            regime = None
                            if hasattr(
                                self.signal_generator, "regime_managers"
                            ) and symbol in getattr(
                                self.signal_generator, "regime_managers", {}
                            ):
                                manager = self.signal_generator.regime_managers.get(
                                    symbol
                                )
                                if manager:
                                    regime_obj = manager.get_current_regime()
                                    if regime_obj:
                                        regime = (
                                            regime_obj.value.lower()
                                            if hasattr(regime_obj, "value")
                                            else str(regime_obj).lower()
                                        )
                            if not regime:
                                if (
                                    hasattr(self.signal_generator, "regime_manager")
                                    and self.signal_generator.regime_manager
                                ):
                                    regime_obj = (
                                        self.signal_generator.regime_manager.get_current_regime()
                                    )
                                    if regime_obj:
                                        regime = (
                                            regime_obj.value.lower()
                                            if hasattr(regime_obj, "value")
                                            else str(regime_obj).lower()
                                        )
                            if regime:
                                metadata_updates["regime"] = regime

                        # Обновляем position_side если отсутствует
                        pos_side_raw = position.get("posSide", "").lower()
                        if (
                            pos_side_raw in ["long", "short"]
                            and not existing_metadata.position_side
                        ):
                            metadata_updates["position_side"] = pos_side_raw

                        # ✅ Используем update_position для безопасного обновления (без мутации)
                        if metadata_updates:
                            await self.position_registry.update_position(
                                symbol=symbol,
                                position_updates=position,
                                metadata_updates=metadata_updates,
                            )
                        else:
                            # Если нет обновлений metadata, обновляем только position
                            await self.position_registry.update_position(
                                symbol=symbol,
                                position_updates=position,
                                metadata_updates=None,
                            )
                    else:
                        # Новая позиция - создаем метаданные
                        from .position_registry import PositionMetadata

                        # ✅ КРИТИЧЕСКОЕ: Используем entry_time из API, если доступно, иначе текущее время
                        entry_time_for_metadata = (
                            entry_time_from_api
                            if entry_time_from_api
                            else datetime.now()
                        )

                        # Получаем режим для новой позиции
                        regime = None
                        if hasattr(
                            self.signal_generator, "regime_managers"
                        ) and symbol in getattr(
                            self.signal_generator, "regime_managers", {}
                        ):
                            manager = self.signal_generator.regime_managers.get(symbol)
                            if manager:
                                regime = manager.get_current_regime()
                        if not regime:
                            if (
                                hasattr(self.signal_generator, "regime_manager")
                                and self.signal_generator.regime_manager
                            ):
                                regime = (
                                    self.signal_generator.regime_manager.get_current_regime()
                                )

                        # Определяем position_side
                        pos_side_raw = position.get("posSide", "").lower()
                        position_side = None
                        if pos_side_raw in ["long", "short"]:
                            position_side = pos_side_raw
                        else:
                            position_side = "long" if size > 0 else "short"

                        # Создаем метаданные для новой позиции
                        new_metadata = PositionMetadata(
                            entry_time=entry_time_for_metadata,  # ✅ КРИТИЧЕСКОЕ: Используем entry_time из API (cTime/uTime)
                            regime=regime,
                            entry_price=entry_price_from_api
                            if entry_price_from_api > 0
                            else None,
                            position_side=position_side,
                        )

                        await self.position_registry.register_position(
                            symbol=symbol,
                            position=position,
                            metadata=new_metadata,
                        )

            # ✅ Проверяем is_running перед API запросом
            if not self.is_running:
                return

            # Проверка здоровья маржи
            margin_status = await self.liquidation_guard.get_margin_status(self.client)

            if not self.is_running:
                return

            if margin_status.get("health_status", {}).get("status") == "critical":
                logger.critical("🚨 TCC: КРИТИЧЕСКОЕ СОСТОЯНИЕ МАРЖИ!")
                # Делегируем экстренное закрытие в orchestrator через callback
                # (это будет обработано в orchestrator._emergency_close_all_positions)

        except asyncio.CancelledError:
            logger.debug("🛑 TCC: Обновление состояния отменено при остановке")
            raise  # Пробрасываем дальше
        except Exception as e:
            # Не логируем ошибки при остановке
            if self.is_running:
                logger.error(f"❌ TCC: Ошибка обновления состояния: {e}")
            else:
                logger.debug(f"🛑 TCC: Обновление состояния прервано при остановке: {e}")

    async def update_performance(self) -> None:
        """
        Обновление статистики производительности (бывший _update_performance).

        Обновляет статистику через performance_tracker.
        """
        try:
            # Обновление статистики (update_stats не async, убираем await)
            self.performance_tracker.update_stats(self.active_positions)
            logger.debug("📈 TCC: Статистика обновлена")

        except Exception as e:
            logger.error(f"❌ TCC: Ошибка обновления статистики: {e}")

    async def stop(self) -> None:
        """
        Остановка торгового цикла.

        Устанавливает флаг is_running = False для корректной остановки цикла.
        """
        logger.info("🛑 TCC: Остановка торгового цикла")
        self.is_running = False

    async def _log_memory_usage(self) -> None:
        """
        ✅ НОВОЕ: Логирование использования памяти для проверки memory leak.

        Логирует:
        - Использование памяти (MB)
        - Количество позиций в PositionRegistry
        - Количество задач в asyncio
        - Количество метаданных
        """
        try:
            if not PSUTIL_AVAILABLE:
                return

            # Получаем использование памяти
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024  # MB

            # Получаем количество позиций
            positions = await self.position_registry.get_all_positions()
            positions_count = len(positions) if positions else 0

            # Получаем количество задач asyncio
            tasks_count = len(asyncio.all_tasks())

            # Получаем метаданные позиций
            metadata_count = 0
            if hasattr(self.position_registry, "_metadata"):
                metadata_count = len(self.position_registry._metadata)

            logger.info(
                f"💾 Memory Usage: {memory_mb:.1f} MB, "
                f"Positions: {positions_count}, "
                f"Metadata: {metadata_count}, "
                f"Tasks: {tasks_count}"
            )

        except Exception as e:
            logger.debug(f"⚠️ TCC: Ошибка логирования memory usage: {e}")
