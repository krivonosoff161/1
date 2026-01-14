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

        # Интервал синхронизации: 30–60 сек
        base_interval_min = 0.5  # 30 секунд по умолчанию
        if self.scalping_config:
            sync_config = getattr(self.scalping_config, "sync", {})
            if isinstance(sync_config, dict):
                base_interval_min = sync_config.get(
                    "positions_sync_interval_minutes", 0.5
                )
            elif hasattr(sync_config, "positions_sync_interval_minutes"):
                base_interval_min = getattr(
                    sync_config, "positions_sync_interval_minutes", 0.5
                )

        sync_interval = base_interval_min * 60.0  # Конвертируем в секунды

        if not force and (now - self._last_positions_sync) < sync_interval:
            logger.debug(
                f"⏳ PositionSync: слишком рано для новой синхронизации (интервал {sync_interval}s)"
            )
            return

        # 🔴 BUG #12 FIX: Retry логика при REST ошибке (2-3 попытки с backoff)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                exchange_positions = await self.client.get_positions()
                break  # Успешно получили - выходим из цикла
            except Exception as e:
                if attempt < max_retries - 1:
                    # Exponential backoff: 0.5s, 1s, 2s
                    backoff_time = 0.5 * (2**attempt)
                    logger.warning(
                        f"⚠️ PositionSync попытка {attempt + 1}/{max_retries} ошибка: {e}. "
                        f"Повторная попытка через {backoff_time}s..."
                    )
                    await asyncio.sleep(backoff_time)
                else:
                    logger.warning(
                        f"⚠️ PositionSync: Не удалось синхронизировать позиции после {max_retries} попыток: {e}. "
                        f"Продолжаем с локальным state (может быть рассинхронизация)"
                    )
                    exchange_positions = []
                    # НЕ возвращаемся! Продолжаем с локальным state
                    break

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

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Логирование drift в файл для аудита
                try:
                    import os

                    drift_log_path = os.path.join("logs", "futures", "drift_log.txt")
                    os.makedirs(os.path.dirname(drift_log_path), exist_ok=True)

                    with open(drift_log_path, "a", encoding="utf-8") as f:
                        from datetime import datetime, timezone

                        timestamp = datetime.now(timezone.utc).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                        f.write(
                            f"{timestamp} | DRIFT_ADD | {symbol} | "
                            f"size={abs(pos_size):.6f} | side={'LONG' if pos_size > 0 else 'SHORT'} | "
                            f"entry=${float(pos.get('avgPx', 0)):.2f} | "
                            f"margin=${float(pos.get('margin', 0)):.2f}\n"
                        )
                except Exception as e_log:
                    logger.debug(f"⚠️ Не удалось записать DRIFT в лог файл: {e_log}")

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
                        # 🔴 BUG #19 FIX: используем биржевые времена cTime/openTime для DRIFT_ADD (если есть)
                        entry_ts_ms = None
                        for key in ["cTime", "openTime", "c_time", "open_time"]:
                            if key in pos and pos.get(key):
                                try:
                                    entry_ts_ms = float(pos.get(key))
                                    break
                                except Exception:
                                    entry_ts_ms = None

                        if entry_ts_ms:
                            entry_dt = datetime.fromtimestamp(
                                entry_ts_ms / 1000.0, tz=timezone.utc
                            )
                        else:
                            entry_dt = datetime.now(timezone.utc)

                        metadata = PositionMetadata(
                            entry_time=entry_dt,
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
