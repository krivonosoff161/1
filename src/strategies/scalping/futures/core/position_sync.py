"""
Position Sync - Синхронизация позиций с биржей.

Вынесено из orchestrator.py для улучшения модульности.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger


class PositionSync:
    """
    Синхронизатор позиций с биржей.

    Отвечает за:
    - Синхронизацию локальных позиций с данными биржи
    - Обновление метаданных позиций
    - Обработку DRIFT_ADD и DRIFT_REMOVE
    """

    def __init__(
        self,
        client=None,
        position_registry=None,
        active_positions=None,
        max_size_limiter=None,
        trailing_sl_coordinator=None,
        last_orders_cache=None,
        normalize_symbol_callback=None,
        scalping_config=None,
        fast_adx=None,
        signal_generator=None,
        data_registry=None,
        config_manager=None,
        get_used_margin_callback=None,
    ):
        """
        Инициализация PositionSync.

        Args:
            client: API клиент
            position_registry: Реестр позиций
            active_positions: Словарь активных позиций (прокси к position_registry)
            max_size_limiter: Ограничитель размера позиций
            trailing_sl_coordinator: Координатор Trailing SL
            last_orders_cache: Кэш последних ордеров
            normalize_symbol_callback: Callback для нормализации символа
            scalping_config: Конфигурация скальпинга
            fast_adx: FastADX индикатор
            signal_generator: Генератор сигналов
        """
        self.client = client
        self.position_registry = position_registry
        self.active_positions = active_positions
        self.max_size_limiter = max_size_limiter
        self.trailing_sl_coordinator = trailing_sl_coordinator
        self.last_orders_cache = last_orders_cache
        self.normalize_symbol_callback = normalize_symbol_callback
        self.scalping_config = scalping_config
        self.fast_adx = fast_adx
        self.signal_generator = signal_generator
        self.data_registry = data_registry
        self.config_manager = config_manager
        self.get_used_margin_callback = get_used_margin_callback

        # ✅ Блокировки для предотвращения race condition
        self._drift_locks: Dict[str, asyncio.Lock] = {}

        self._last_positions_sync = 0.0

    async def sync_positions_with_exchange(self, force: bool = False) -> None:
        """
        ✅ МОДЕРНИЗАЦИЯ: Синхронизирует локальные позиции и лимиты с фактическими данными биржи.

        Обновляет:
        - active_positions
        - position_registry
        - max_size_limiter.position_sizes
        - trailing_sl_coordinator (инициализация TSL для DRIFT_ADD позиций)

        Args:
            force: Принудительная синхронизация (игнорирует интервал)
        """
        now = time.time()

        # ✅ АДАПТИВНО: Интервал синхронизации из конфига
        base_interval_min = 5.0  # Fallback
        if self.scalping_config:
            sync_config = getattr(self.scalping_config, "sync", {})
            if isinstance(sync_config, dict):
                base_interval_min = sync_config.get(
                    "positions_sync_interval_minutes", 5.0
                )
            elif hasattr(sync_config, "positions_sync_interval_minutes"):
                base_interval_min = getattr(
                    sync_config, "positions_sync_interval_minutes", 5.0
                )

        sync_interval = base_interval_min * 60.0  # Конвертируем в секунды

        if not force and (now - self._last_positions_sync) < sync_interval:
            return

        try:
            exchange_positions = await self.client.get_positions()
        except Exception as e:
            logger.debug(f"⚠️ Не удалось синхронизировать позиции с биржей: {e}")
            return

        self._last_positions_sync = now
        seen_symbols: set[str] = set()
        total_margin = 0.0

        for pos in exchange_positions or []:
            try:
                pos_size = float(pos.get("pos", "0") or 0)
            except (TypeError, ValueError):
                pos_size = 0.0

            if abs(pos_size) < 1e-8:
                continue

            inst_id = pos.get("instId", "")
            if not inst_id:
                continue

            symbol = inst_id.replace("-SWAP", "")
            seen_symbols.add(symbol)

            # ✅ FIX: DRIFT_ADD log — позиция на бирже, но нет в реестре
            is_drift_add = symbol not in self.active_positions
            if is_drift_add:
                logger.warning(
                    f"⚠️ DRIFT_ADD {symbol}: Позиция найдена на бирже, но отсутствует в локальном реестре. "
                    f"Размер={abs(pos_size):.6f}, сторона={'long' if pos_size > 0 else 'short'}. "
                    f"Регистрируем..."
                )
                # ✅ ИСПРАВЛЕНИЕ: Для DRIFT_ADD позиций регистрируем, а не обновляем
                if self.position_registry:
                    try:
                        # Получаем данные для регистрации
                        pos_side = pos.get("posSide", "").lower()
                        if pos_side not in ["long", "short"]:
                            pos_side = "long" if pos_size > 0 else "short"

                        # Безопасный парсинг данных
                        try:
                            avgpx_str = str(pos.get("avgPx", "0")).strip()
                            entry_price = float(avgpx_str) if avgpx_str else 0.0
                        except (ValueError, TypeError):
                            entry_price = 0.0

                        try:
                            margin_str = str(pos.get("margin", "0")).strip()
                            margin_used = float(margin_str) if margin_str else 0.0
                        except (ValueError, TypeError):
                            margin_used = 0.0

                        # Получаем ctVal для расчета размера в монетах
                        try:
                            inst_details = await self.client.get_instrument_details(
                                symbol
                            )
                            ct_val = float(inst_details.get("ctVal", "0.01"))
                            size_in_coins = abs(pos_size) * ct_val
                        except Exception:
                            size_in_coins = abs(pos_size)

                        # ✅ ИСПРАВЛЕНО: Создаем словарь position и PositionMetadata
                        from .position_registry import PositionMetadata

                        # Создаем словарь position с данными из биржи
                        position_dict = pos.copy()

                        # Создаем метаданные
                        metadata = PositionMetadata(
                            entry_time=datetime.now(
                                timezone.utc
                            ),  # Используем текущее время, т.к. точное время входа неизвестно
                            position_side=pos_side,
                            entry_price=entry_price if entry_price > 0 else None,
                            size_in_coins=size_in_coins,
                            margin_used=margin_used,
                        )

                        # Регистрируем позицию
                        await self.position_registry.register_position(
                            symbol=symbol,
                            position=position_dict,
                            metadata=metadata,
                        )
                        logger.info(
                            f"✅ DRIFT_ADD {symbol}: Позиция зарегистрирована в реестре "
                            f"(side={pos_side}, size={abs(pos_size):.6f}, entry=${entry_price:.2f})"
                        )
                    except Exception as e:
                        logger.error(
                            f"❌ Ошибка регистрации DRIFT_ADD позиции {symbol}: {e}"
                        )
            else:
                # Обновляем существующую позицию в реестре
                if self.position_registry:
                    await self.position_registry.update_position(
                        symbol=symbol,
                        position_updates=pos,
                    )

            # Обновляем active_positions
            if symbol not in self.active_positions:
                self.active_positions[symbol] = {}
            self.active_positions[symbol].update(pos)

            # Обновляем max_size_limiter
            try:
                inst_details = await self.client.get_instrument_details(symbol)
                ct_val = float(inst_details.get("ctVal", "0.01"))
                size_in_coins = abs(pos_size) * ct_val
                # ✅ ИСПРАВЛЕНИЕ: Безопасный парсинг avgPx
                try:
                    avgpx_str = str(pos.get("avgPx", "0")).strip()
                    entry_price = float(avgpx_str) if avgpx_str else 0.0
                except (ValueError, TypeError):
                    entry_price = 0.0

                if entry_price > 0:
                    self.max_size_limiter.position_sizes[symbol] = (
                        size_in_coins * entry_price
                    )
            except Exception as e:
                logger.debug(f"⚠️ Ошибка обновления max_size_limiter для {symbol}: {e}")

        # Удаляем позиции, которых нет на бирже
        stale_symbols = set(self.active_positions.keys()) - seen_symbols
        for symbol in list(stale_symbols):
            logger.warning(f"DRIFT_REMOVE {symbol} not on exchange")
            self.active_positions.pop(symbol, None)

            # Удаляем TSL
            if self.trailing_sl_coordinator:
                tsl = self.trailing_sl_coordinator.remove_tsl(symbol)
                if tsl:
                    tsl.reset()

            # Удаляем из max_size_limiter
            if self.max_size_limiter and symbol in self.max_size_limiter.position_sizes:
                self.max_size_limiter.remove_position(symbol)

            # Обновляем кэш ордеров
            if self.normalize_symbol_callback and self.last_orders_cache:
                normalized_symbol = self.normalize_symbol_callback(symbol)
                if normalized_symbol in self.last_orders_cache:
                    self.last_orders_cache[normalized_symbol]["status"] = "closed"

        logger.debug(
            f"✅ Синхронизация позиций завершена: {len(seen_symbols)} активных позиций"
        )
