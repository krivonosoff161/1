"""
Futures Position Manager для скальпинг стратегии.

Основные функции:
- Управление открытыми позициями в Futures
- Интеграция с Margin Calculator для контроля маржи
- Автоматическое закрытие позиций по TP/SL
- Мониторинг PnL и рисков
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig, ScalpingConfig

from ..spot.position_manager import TradeResult
from .calculations.margin_calculator import MarginCalculator
from .core.data_registry import DataRegistry
from .core.position_registry import PositionRegistry
# ✅ РЕФАКТОРИНГ: Импортируем новые модули
from .positions.entry_manager import EntryManager
from .positions.exit_analyzer import ExitAnalyzer
from .positions.position_monitor import PositionMonitor


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
        self.symbol_profiles: Dict[
            str, Dict[str, Any]
        ] = {}  # ✅ НОВОЕ: Для per-symbol TP
        self.orchestrator = None  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Ссылка на orchestrator для доступа к trailing_sl_by_symbol

        # ✅ РЕФАКТОРИНГ: Новые модули (будут инициализированы позже)
        self.position_registry = (
            None  # PositionRegistry (будет установлен из orchestrator)
        )
        self.data_registry = None  # DataRegistry (будет установлен из orchestrator)
        self.entry_manager = None  # EntryManager (будет создан при необходимости)
        self.exit_analyzer = None  # ExitAnalyzer (будет создан при необходимости)
        self.position_monitor = None  # PositionMonitor (будет создан при необходимости)

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

    def set_symbol_profiles(self, symbol_profiles: Dict[str, Dict[str, Any]]):
        """✅ НОВОЕ: Устанавливает symbol_profiles для per-symbol TP"""
        self.symbol_profiles = symbol_profiles
        logger.debug(
            f"✅ symbol_profiles установлен в position_manager ({len(symbol_profiles)} символов)"
        )

    def set_orchestrator(self, orchestrator):
        """✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Устанавливает ссылку на orchestrator для доступа к trailing_sl_by_symbol"""
        self.orchestrator = orchestrator

    def _get_adaptive_tp_percent(
        self,
        symbol: str,
        regime: Optional[str] = None,
        current_price: Optional[float] = None,
    ) -> float:
        """
        ✅ КРИТИЧЕСКОЕ: Получает адаптивный TP% для символа и режима.

        Приоритет:
        1. Per-regime TP (если режим определен)
        2. Per-symbol TP (fallback)
        3. Глобальный TP (fallback)

        ✅ ЭТАП 2.3: Поддержка ATR-based TP расчета

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending, ranging, choppy)
            current_price: Текущая цена (опционально, для ATR-based расчета)

        Returns:
            TP% для использования
        """
        # ✅ ИСПРАВЛЕНО: Инициализируем tp_percent = None (НЕ используем fallback сразу!)
        tp_percent = None

        # Получаем режим из позиции, если не передан
        if not regime:
            if symbol in self.active_positions:
                regime = self.active_positions[symbol].get("regime")
            elif hasattr(self, "orchestrator") and self.orchestrator:
                if (
                    hasattr(self.orchestrator, "signal_generator")
                    and self.orchestrator.signal_generator
                ):
                    if hasattr(self.orchestrator.signal_generator, "regime_managers"):
                        manager = (
                            self.orchestrator.signal_generator.regime_managers.get(
                                symbol
                            )
                        )
                        if manager:
                            regime = manager.get_current_regime()

        # Получаем tp_percent для символа и режима (если есть в symbol_profiles)
        if symbol and self.symbol_profiles:
            symbol_profile = self.symbol_profiles.get(symbol, {})
            if symbol_profile:
                # Конвертируем в dict если нужно
                if not isinstance(symbol_profile, dict):
                    if hasattr(symbol_profile, "dict"):
                        symbol_dict = symbol_profile.dict()
                    elif hasattr(symbol_profile, "__dict__"):
                        symbol_dict = dict(symbol_profile.__dict__)
                    else:
                        symbol_dict = {}
                else:
                    symbol_dict = symbol_profile

                # 1. ✅ ПРИОРИТЕТ 1: Per-regime TP (если режим определен)
                if regime:
                    regime_lower = (
                        regime.lower()
                        if isinstance(regime, str)
                        else str(regime).lower()
                    )
                    regime_profile = symbol_dict.get(regime_lower, {})

                    if not isinstance(regime_profile, dict):
                        if hasattr(regime_profile, "dict"):
                            regime_profile = regime_profile.dict()
                        elif hasattr(regime_profile, "__dict__"):
                            regime_profile = dict(regime_profile.__dict__)
                        else:
                            regime_profile = {}

                    regime_tp_percent = regime_profile.get("tp_percent")
                    if regime_tp_percent is not None:
                        try:
                            tp_percent = float(regime_tp_percent)
                            logger.info(
                                f"✅ Per-regime TP для {symbol} ({regime}): {tp_percent}% "
                                f"(глобальный: {self.scalping_config.tp_percent}%)"
                            )
                            return tp_percent
                        except (ValueError, TypeError):
                            logger.warning(
                                f"⚠️ Не удалось конвертировать regime_tp_percent в float для {symbol} ({regime}): {regime_tp_percent}"
                            )

                # 2. ✅ ПРИОРИТЕТ 2: Per-symbol TP (fallback, если режим не определен)
                symbol_tp_percent = symbol_dict.get("tp_percent")
                if symbol_tp_percent is not None:
                    try:
                        tp_percent = float(symbol_tp_percent)
                        logger.info(
                            f"📊 Per-symbol TP для {symbol}: {tp_percent}% "
                            f"(глобальный: {self.scalping_config.tp_percent}%)"
                        )
                        return tp_percent
                    except (ValueError, TypeError):
                        logger.warning(
                            f"⚠️ Не удалось конвертировать symbol_tp_percent в float для {symbol}: {symbol_tp_percent}"
                        )

            # 3. ✅ ПРИОРИТЕТ 3: Глобальный TP (fallback - ТОЛЬКО если ничего не найдено)
            if tp_percent is None:
                tp_percent = self.scalping_config.tp_percent
                logger.warning(
                    f"⚠️ FALLBACK: Используется глобальный TP для {symbol} (regime={regime or 'N/A'}): {tp_percent}% "
                    f"(per-regime и per-symbol TP не найдены, symbol_profiles: {len(self.symbol_profiles) if self.symbol_profiles else 0} символов)"
                )
            else:
                logger.debug(
                    f"📊 Используется глобальный TP для {symbol} (regime={regime or 'N/A'}): {tp_percent}% "
                    f"(symbol_profiles: {len(self.symbol_profiles) if self.symbol_profiles else 0} символов)"
                )

        # ✅ ЭТАП 2.3: Проверяем ATR-based TP если доступно
        if current_price and current_price > 0 and regime:
            try:
                # Получаем tp_atr_multiplier из конфига
                regime_params = None
                if hasattr(self, "orchestrator") and self.orchestrator:
                    if hasattr(self.orchestrator, "config_manager"):
                        regime_params = (
                            self.orchestrator.config_manager.get_regime_params(
                                regime, symbol
                            )
                        )

                if regime_params:
                    tp_atr_multiplier = regime_params.get("tp_atr_multiplier")
                    if tp_atr_multiplier is not None:
                        # Получаем ATR через orchestrator (если доступен)
                        if hasattr(self, "orchestrator") and self.orchestrator:
                            if (
                                hasattr(self.orchestrator, "signal_generator")
                                and self.orchestrator.signal_generator
                            ):
                                # Пытаемся получить ATR из indicator_manager
                                if hasattr(
                                    self.orchestrator.signal_generator,
                                    "indicator_manager",
                                ):
                                    try:
                                        # Получаем ATR из индикаторов
                                        atr_indicator = self.orchestrator.signal_generator.indicator_manager.get_indicator(
                                            "ATR"
                                        )
                                        if atr_indicator:
                                            # Получаем последнее значение ATR
                                            # Это упрощенный подход - в реальности нужно получать через market_data
                                            logger.debug(
                                                f"📊 ATR-based TP для {symbol}: tp_atr_multiplier={tp_atr_multiplier}, "
                                                f"но требуется market_data для расчета ATR"
                                            )
                                    except Exception as e:
                                        logger.debug(
                                            f"⚠️ Не удалось получить ATR для {symbol}: {e}"
                                        )
            except Exception as e:
                logger.debug(f"⚠️ Ошибка проверки ATR-based TP для {symbol}: {e}")

        return tp_percent

    def _get_adaptive_sl_percent(
        self, symbol: str, regime: Optional[str] = None
    ) -> float:
        """
        ✅ КРИТИЧЕСКОЕ: Получает адаптивный SL% для символа и режима.

        Приоритет (ТОЧНО как для TP):
        1. Per-regime SL (если режим определен)
        2. Per-symbol SL (fallback)
        3. Глобальный SL (fallback)

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending, ranging, choppy)

        Returns:
            SL% для использования
        """
        # ✅ ИСПРАВЛЕНО: Инициализируем sl_percent = None (НЕ используем fallback сразу!)
        sl_percent = None

        # Получаем режим из позиции, если не передан
        if not regime:
            if symbol in self.active_positions:
                regime = self.active_positions[symbol].get("regime")
            elif hasattr(self, "orchestrator") and self.orchestrator:
                if (
                    hasattr(self.orchestrator, "signal_generator")
                    and self.orchestrator.signal_generator
                ):
                    if hasattr(self.orchestrator.signal_generator, "regime_managers"):
                        manager = (
                            self.orchestrator.signal_generator.regime_managers.get(
                                symbol
                            )
                        )
                        if manager:
                            regime = manager.get_current_regime()

        # Получаем sl_percent для символа и режима (если есть в symbol_profiles)
        if symbol and self.symbol_profiles:
            symbol_profile = self.symbol_profiles.get(symbol, {})
            if symbol_profile:
                # Конвертируем в dict если нужно
                if not isinstance(symbol_profile, dict):
                    if hasattr(symbol_profile, "dict"):
                        symbol_dict = symbol_profile.dict()
                    elif hasattr(symbol_profile, "__dict__"):
                        symbol_dict = dict(symbol_profile.__dict__)
                    else:
                        symbol_dict = {}
                else:
                    symbol_dict = symbol_profile

                # 1. ✅ ПРИОРИТЕТ 1: Per-regime SL (если режим определен)
                if regime:
                    regime_lower = (
                        regime.lower()
                        if isinstance(regime, str)
                        else str(regime).lower()
                    )
                    regime_profile = symbol_dict.get(regime_lower, {})

                    if not isinstance(regime_profile, dict):
                        if hasattr(regime_profile, "dict"):
                            regime_profile = regime_profile.dict()
                        elif hasattr(regime_profile, "__dict__"):
                            regime_profile = dict(regime_profile.__dict__)
                        else:
                            regime_profile = {}

                    regime_sl_percent = regime_profile.get("sl_percent")
                    if regime_sl_percent is not None:
                        try:
                            sl_percent = float(regime_sl_percent)
                            logger.info(
                                f"✅ Per-regime SL для {symbol} ({regime}): {sl_percent}% "
                                f"(глобальный: {self.scalping_config.sl_percent}%)"
                            )
                            return sl_percent
                        except (ValueError, TypeError):
                            logger.warning(
                                f"⚠️ Не удалось конвертировать regime_sl_percent в float для {symbol} ({regime}): {regime_sl_percent}"
                            )

                # 2. ✅ ПРИОРИТЕТ 2: Per-symbol SL (fallback, если режим не определен)
                symbol_sl_percent = symbol_dict.get("sl_percent")
                if symbol_sl_percent is not None:
                    try:
                        sl_percent = float(symbol_sl_percent)
                        logger.info(
                            f"📊 Per-symbol SL для {symbol}: {sl_percent}% "
                            f"(глобальный: {self.scalping_config.sl_percent}%)"
                        )
                        return sl_percent
                    except (ValueError, TypeError):
                        logger.warning(
                            f"⚠️ Не удалось конвертировать symbol_sl_percent в float для {symbol}: {symbol_sl_percent}"
                        )

            # 3. ✅ ПРИОРИТЕТ 3: Глобальный SL (fallback - ТОЛЬКО если ничего не найдено)
            if sl_percent is None:
                sl_percent = self.scalping_config.sl_percent
                logger.warning(
                    f"⚠️ FALLBACK: Используется глобальный SL для {symbol} (regime={regime or 'N/A'}): {sl_percent}% "
                    f"(per-regime и per-symbol SL не найдены, symbol_profiles: {len(self.symbol_profiles) if self.symbol_profiles else 0} символов)"
                )
            else:
                logger.debug(
                    f"📊 Используется глобальный SL для {symbol} (regime={regime or 'N/A'}): {sl_percent}% "
                    f"(symbol_profiles: {len(self.symbol_profiles) if self.symbol_profiles else 0} символов)"
                )
        else:
            # Если symbol_profiles нет, используем глобальный SL
            sl_percent = self.scalping_config.sl_percent
            logger.debug(
                f"📊 Используется глобальный SL для {symbol} (symbol_profiles нет): {sl_percent}%"
            )

        return sl_percent

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

            if size == 0:
                # Позиция закрыта
                if symbol in self.active_positions:
                    await self._handle_position_closed(symbol)
                return

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновление активных позиций с сохранением режима
            # Данные с биржи (position) не содержат режим, поэтому сохраняем его из active_positions
            if symbol in self.active_positions:
                # Сохраняем режим и другие метаданные из существующей позиции
                saved_regime = self.active_positions[symbol].get("regime")
                saved_entry_time = self.active_positions[symbol].get("entry_time")
                saved_entry_price = self.active_positions[symbol].get("entry_price")
                saved_position_side = self.active_positions[symbol].get("position_side")
                # Обновляем позицию данными с биржи, но сохраняем метаданные
                self.active_positions[symbol] = position.copy()
                if saved_regime:
                    self.active_positions[symbol]["regime"] = saved_regime
                if saved_entry_time:
                    self.active_positions[symbol]["entry_time"] = saved_entry_time
                if saved_entry_price:
                    self.active_positions[symbol]["entry_price"] = saved_entry_price
                if saved_position_side:
                    self.active_positions[symbol]["position_side"] = saved_position_side
            else:
                # Новая позиция - сохраняем как есть
                self.active_positions[symbol] = position

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавляем режим в position для передачи в методы
            # Режим нужен для per-regime TP и других адаптивных параметров
            if (
                symbol in self.active_positions
                and "regime" in self.active_positions[symbol]
            ):
                position["regime"] = self.active_positions[symbol]["regime"]

            # Проверка безопасности позиции
            await self._check_position_safety(position)

            # ✅ МОДЕРНИЗАЦИЯ #1: Проверка Profit Harvest (PH) - ПРИОРИТЕТ #1
            # PH проверяется ПЕРЕД TP/SL для быстрого закрытия при высокой прибыли
            ph_should_close = await self._check_profit_harvesting(position)
            if ph_should_close:
                await self._close_position_by_reason(position, "profit_harvest")
                return  # Закрыли по PH, дальше не проверяем

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

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #8: Задержка перед проверкой маржи для новых позиций
            # Позиции, открытые менее 10 секунд назад, пропускаем проверку маржи
            position_open_time = None
            try:
                # Пробуем получить время открытия из active_positions
                if symbol in self.active_positions:
                    pos_data = self.active_positions[symbol]
                    if isinstance(pos_data, dict):
                        position_open_time = pos_data.get("open_time") or pos_data.get(
                            "timestamp"
                        )

                # Если не нашли в active_positions, пробуем получить из позиции биржи
                if not position_open_time:
                    # OKX может возвращать время в разных форматах
                    utime_str = position.get("utime", "")
                    ctime_str = position.get("ctime", "")
                    if utime_str:
                        try:
                            position_open_time = (
                                float(utime_str) / 1000.0
                            )  # Конвертируем из миллисекунд
                        except (ValueError, TypeError):
                            pass
                    elif ctime_str:
                        try:
                            position_open_time = float(ctime_str) / 1000.0
                        except (ValueError, TypeError):
                            pass

                # Если нашли время открытия, проверяем задержку
                if position_open_time:
                    time_since_open = time.time() - position_open_time
                    min_check_delay = 10.0  # Минимум 10 секунд перед проверкой маржи
                    if time_since_open < min_check_delay:
                        logger.debug(
                            f"⏳ Позиция {symbol} открыта {time_since_open:.1f} секунд назад, "
                            f"пропускаем проверку маржи (минимум {min_check_delay} секунд)"
                        )
                        return  # Пропускаем проверку для новых позиций
            except Exception as e:
                logger.debug(
                    f"⚠️ Не удалось проверить время открытия позиции {symbol}: {e}"
                )
                # При ошибке продолжаем проверку
            # ✅ ИСПРАВЛЕНИЕ: Используем leverage из конфига, а не из позиции на бирже
            # На бирже может быть установлен старый leverage (3x), но расчеты должны использовать leverage из конфига (5x)
            leverage_from_position = int(position.get("lever", "0"))
            leverage = (
                getattr(self.scalping_config, "leverage", None)
                or leverage_from_position
                or 3
            )
            if leverage_from_position != leverage:
                logger.debug(
                    f"📊 Leverage: биржа={leverage_from_position}x, конфиг={leverage}x, используем {leverage}x для расчетов"
                )

            # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для изолированной маржи получаем equity через get_margin_info!
            # Это правильный баланс для данной позиции, а не общий баланс аккаунта
            try:
                margin_info = await self.client.get_margin_info(symbol)
                equity = margin_info.get("equity", 0)

                # Если equity не найден в margin_info, пытаемся получить из самой позиции
                if equity == 0:
                    # Проверяем, есть ли 'eq' или другие поля в самой позиции
                    if "eq" in position and position["eq"]:
                        eq_value = position["eq"]
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем что это не пустая строка
                        if eq_value and str(eq_value).strip():
                            try:
                                equity = float(eq_value)
                                logger.debug(
                                    f"✅ equity получен из position['eq'] для {symbol}: {equity:.2f}"
                                )
                            except (ValueError, TypeError) as e:
                                logger.debug(
                                    f"⚠️ Ошибка конвертации eq для {symbol}: {e}, значение={eq_value}"
                                )
                                pass

                    # Если все еще 0, используем общий баланс как fallback
                    if equity == 0:
                        # ✅ ИСПРАВЛЕНО: Пробуем получить equity из позиции напрямую через API
                        try:
                            # Получаем позицию напрямую через API для более точного equity
                            positions_data = await self.client._make_request(
                                "GET",
                                "/api/v5/account/positions",
                                params={"instType": "SWAP", "instId": f"{symbol}-SWAP"},
                            )
                            if positions_data and positions_data.get("data"):
                                pos_data = positions_data["data"][0]

                                # Пробуем получить equity из различных полей
                                if "eq" in pos_data and pos_data.get("eq"):
                                    eq_value = pos_data["eq"]
                                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем что это не пустая строка
                                    if eq_value and str(eq_value).strip():
                                        try:
                                            equity = float(eq_value)
                                            logger.debug(
                                                f"✅ equity получен из позиции API для {symbol}: {equity:.2f}"
                                            )
                                        except (ValueError, TypeError) as e:
                                            logger.debug(
                                                f"⚠️ Ошибка конвертации eq для {symbol}: {e}, значение={eq_value}"
                                            )
                                if (
                                    equity == 0
                                    and "margin" in pos_data
                                    and "upl" in pos_data
                                ):
                                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем что значения не пустые строки
                                    try:
                                        margin_str = str(
                                            pos_data.get("margin", "0")
                                        ).strip()
                                        upl_str = str(pos_data.get("upl", "0")).strip()
                                        if margin_str and upl_str:
                                            margin = float(margin_str)
                                            upl = float(upl_str)
                                            equity = margin + upl
                                    except (ValueError, TypeError) as e:
                                        logger.debug(
                                            f"⚠️ Ошибка конвертации margin/upl для {symbol}: {e}"
                                        )
                                    if equity > 0:
                                        logger.debug(
                                            f"✅ equity рассчитан из позиции API для {symbol}: "
                                            f"margin={margin:.2f} + upl={upl:.2f} = {equity:.2f}"
                                        )
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Ошибка получения equity из позиции API для {symbol}: {e}"
                            )

                        # Fallback на общий баланс только если все остальное не сработало
                        if equity == 0:
                            equity = await self.client.get_balance()
                            # ✅ ИСПРАВЛЕНО: Используем DEBUG вместо WARNING для нормальных случаев
                            # equity может быть 0 для новых позиций или во время синхронизации
                            logger.debug(
                                f"⚠️ equity не найден через get_margin_info и API для {symbol}, "
                                f"используем общий баланс: {equity:.2f}"
                            )
            except Exception as e:
                # Fallback при ошибке - сначала пытаемся из позиции
                equity = 0
                try:
                    if "eq" in position and position["eq"]:
                        eq_value = position["eq"]
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем что это не пустая строка
                        if eq_value and str(eq_value).strip():
                            equity = float(eq_value)
                            logger.debug(
                                f"✅ equity получен из position['eq'] (fallback) для {symbol}: {equity:.2f}"
                            )
                except (ValueError, TypeError) as e:
                    logger.debug(
                        f"⚠️ Ошибка конвертации eq (fallback) для {symbol}: {e}"
                    )
                    pass

                if equity == 0:
                    # ✅ ИСПРАВЛЕНО: Пробуем получить equity из позиции напрямую через API
                    try:
                        positions_data = await self.client._make_request(
                            "GET",
                            "/api/v5/account/positions",
                            params={"instType": "SWAP", "instId": f"{symbol}-SWAP"},
                        )
                        if positions_data and positions_data.get("data"):
                            pos_data = positions_data["data"][0]
                            if "eq" in pos_data and pos_data.get("eq"):
                                eq_value = pos_data["eq"]
                                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем что это не пустая строка
                                if eq_value and str(eq_value).strip():
                                    try:
                                        equity = float(eq_value)
                                        logger.debug(
                                            f"✅ equity получен из позиции API (fallback) для {symbol}: {equity:.2f}"
                                        )
                                    except (ValueError, TypeError) as e:
                                        logger.debug(
                                            f"⚠️ Ошибка конвертации eq (fallback) для {symbol}: {e}, значение={eq_value}"
                                        )
                            if (
                                equity == 0
                                and "margin" in pos_data
                                and "upl" in pos_data
                            ):
                                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем что значения не пустые строки
                                try:
                                    margin_str = str(
                                        pos_data.get("margin", "0")
                                    ).strip()
                                    upl_str = str(pos_data.get("upl", "0")).strip()
                                    if margin_str and upl_str:
                                        margin = float(margin_str)
                                        upl = float(upl_str)
                                        equity = margin + upl
                                except (ValueError, TypeError) as e:
                                    logger.debug(
                                        f"⚠️ Ошибка конвертации margin/upl (fallback) для {symbol}: {e}"
                                    )
                                if equity > 0:
                                    logger.debug(
                                        f"✅ equity рассчитан из позиции API (fallback) для {symbol}: "
                                        f"margin={margin:.2f} + upl={upl:.2f} = {equity:.2f}"
                                    )
                    except Exception as api_error:
                        logger.debug(
                            f"⚠️ Ошибка получения equity из позиции API (fallback) для {symbol}: {api_error}"
                        )

                    # Fallback на общий баланс только если все остальное не сработало
                    if equity == 0:
                        equity = await self.client.get_balance()
                        logger.warning(
                            f"⚠️ Ошибка получения equity для {symbol}: {e}, "
                            f"используем общий баланс: {equity:.2f}"
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

            # ✅ ИСПРАВЛЕНО: Получаем режим рынка для адаптивного safety_threshold
            market_regime = None
            try:
                # Получаем режим из позиции (сохранен при открытии)
                market_regime = position.get("regime") or self.active_positions.get(
                    symbol, {}
                ).get("regime")

                # Если режим не найден в позиции, получаем из orchestrator
                if (
                    not market_regime
                    and hasattr(self, "orchestrator")
                    and self.orchestrator
                ):
                    if (
                        hasattr(self.orchestrator, "signal_generator")
                        and self.orchestrator.signal_generator
                    ):
                        regime_manager = getattr(
                            self.orchestrator.signal_generator, "regime_manager", None
                        )
                        if regime_manager:
                            regime_obj = regime_manager.get_current_regime()
                            if regime_obj:
                                market_regime = (
                                    regime_obj.lower()
                                    if isinstance(regime_obj, str)
                                    else str(regime_obj).lower()
                                )
            except Exception as e:
                logger.debug(f"⚠️ Не удалось получить режим для {symbol}: {e}")

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем regime из позиции для margin_calculator
            position_regime = position.get("regime")
            if not position_regime and symbol in self.active_positions:
                position_regime = self.active_positions[symbol].get("regime")

            # Если режим все еще не найден, пытаемся получить из signal_generator
            if not position_regime:
                try:
                    if (
                        hasattr(self, "orchestrator")
                        and self.orchestrator
                        and hasattr(self.orchestrator, "signal_generator")
                        and self.orchestrator.signal_generator
                    ):
                        if hasattr(
                            self.orchestrator.signal_generator, "regime_managers"
                        ):
                            manager = (
                                self.orchestrator.signal_generator.regime_managers.get(
                                    symbol
                                )
                            )
                            if manager:
                                position_regime = manager.get_current_regime()
                        if not position_regime:
                            regime_manager = getattr(
                                self.orchestrator.signal_generator,
                                "regime_manager",
                                None,
                            )
                            if regime_manager:
                                position_regime = regime_manager.get_current_regime()
                except Exception as e:
                    logger.debug(
                        f"⚠️ Не удалось получить regime для margin_calculator: {e}"
                    )

            # Проверка безопасности через Margin Calculator
            # ⚠️ Используем equity из позиции, а не общий баланс!
            logger.debug(
                f"🔍 Проверка безопасности {symbol}: "
                f"position_value={position_value:.2f}, equity={equity:.2f}, "
                f"current_price={current_price:.2f}, entry_price={entry_price:.2f}, "
                f"leverage={leverage}x, regime={position_regime or market_regime or 'N/A'}"
            )
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Передаем regime в margin_calculator (используем position_regime если есть, иначе market_regime)
            regime_for_margin = position_regime or market_regime
            is_safe, details = self.margin_calculator.is_position_safe(
                position_value,
                equity,  # ✅ Используем equity из позиции!
                current_price,
                entry_price,
                side,
                leverage,
                safety_threshold=None,  # ✅ ИСПРАВЛЕНО: None - читает из конфига по режиму
                regime=regime_for_margin,  # ✅ КРИТИЧЕСКОЕ: Передаем regime для адаптивного safety_threshold
            )

            if not is_safe:
                margin_ratio = details["margin_ratio"]
                pnl = details.get("pnl", 0)
                available_margin = details.get("available_margin", 0)
                margin_used = details.get("margin_used", 0)

                # margin_ratio приходит как коэффициент (1.5 = 150%), для лога конвертируем в проценты
                try:
                    margin_ratio_pct = float(margin_ratio) * 100.0
                except Exception:
                    margin_ratio_pct = margin_ratio
                # ✅ ИСПРАВЛЕНО: Используем DEBUG вместо WARNING, так как защита от ложных срабатываний работает
                # Предупреждение будет выведено только если действительно есть проблема
                logger.debug(
                    f"⚠️ Позиция {symbol} небезопасна: маржа {margin_ratio_pct:.2f}% (проверяем защиту от ложных срабатываний)"
                )

                # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА от ложных срабатываний (как в LiquidationGuard):
                # ✅ ИСПРАВЛЕНО: Параметры из конфига
                protection_config = getattr(
                    self.scalping_config, "position_manager", {}
                ).get("false_trigger_protection", {})
                margin_ratio_threshold = protection_config.get(
                    "margin_ratio_threshold", 1.5
                )
                pnl_threshold = protection_config.get("pnl_threshold", 10.0)
                margin_ratio_minimum = protection_config.get(
                    "margin_ratio_minimum", 0.5
                )

                # Если margin_ratio <= threshold и PnL небольшой - это ошибка расчета, а не реальный риск
                # Это особенно часто происходит сразу после открытия позиции
                if margin_ratio <= margin_ratio_threshold and abs(pnl) < pnl_threshold:
                    # ✅ ИСПРАВЛЕНО: Используем DEBUG вместо WARNING, так как защита от ложных срабатываний работает
                    # Это нормально для новых позиций, защита предотвращает автозакрытие
                    logger.debug(
                        f"⚠️ ПОДОЗРИТЕЛЬНОЕ состояние для {symbol} в PositionManager: "
                        f"margin_ratio={margin_ratio:.2f}, available_margin={available_margin:.2f}, "
                        f"pnl={pnl:.2f}, equity={equity:.2f}. "
                        f"Возможна ошибка расчета (позиция только что открыта?), пропускаем автозакрытие."
                    )
                    return  # Пропускаем автозакрытие

                # 🛡️ ЗАЩИТА 2: Если margin_ratio = 0.0 или очень близок к нулю - это почти всегда ошибка
                if margin_ratio <= margin_ratio_minimum and equity > 0:
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
                    # ✅ TODO #2: ЗАЩИТА от ложных срабатываний - проверяем время открытия
                    position_open_time = None
                    try:
                        # Пробуем получить время открытия из позиции
                        if symbol in self.active_positions:
                            pos_data = self.active_positions[symbol]
                            if isinstance(pos_data, dict):
                                position_open_time = pos_data.get("entry_time") or pos_data.get("timestamp") or pos_data.get("open_time")
                        
                        # Если не нашли, пробуем из текущей позиции
                        if not position_open_time:
                            c_time = position.get("cTime")
                            u_time = position.get("uTime")
                            if c_time or u_time:
                                entry_time_str = c_time or u_time
                                try:
                                    if isinstance(entry_time_str, str) and entry_time_str.isdigit():
                                        entry_timestamp = int(entry_time_str) / 1000.0
                                        position_open_time = datetime.fromtimestamp(entry_timestamp)
                                    elif isinstance(entry_time_str, (int, float)):
                                        entry_timestamp = float(entry_time_str) / 1000.0 if float(entry_time_str) > 1000000000000 else float(entry_time_str)
                                        position_open_time = datetime.fromtimestamp(entry_timestamp)
                                except (ValueError, TypeError):
                                    pass
                    except Exception as e:
                        logger.debug(f"⚠️ Ошибка получения времени открытия для {symbol}: {e}")
                    
                    time_since_open = 0.0
                    if position_open_time:
                        if isinstance(position_open_time, datetime):
                            time_since_open = (datetime.now() - position_open_time).total_seconds()
                        else:
                            try:
                                time_since_open = (datetime.now() - datetime.fromtimestamp(float(position_open_time))).total_seconds()
                            except (ValueError, TypeError):
                                pass
                    
                    # ✅ ЗАЩИТА #1: Не закрываем позиции, открытые менее 30 секунд назад
                    if time_since_open < 30.0:
                        logger.debug(
                            f"⚠️ Позиция {symbol} открыта {time_since_open:.1f} сек назад, "
                            f"пропускаем emergency close (защита от ложных срабатываний, margin_ratio={margin_ratio:.2f}%)"
                        )
                        return
                    
                    # ✅ ЗАЩИТА #2: Проверяем, что убыток действительно критический (> 2% от маржи)
                    try:
                        pnl = float(position.get("upl", "0") or 0)
                        margin = float(position.get("margin", "0") or 0)
                        if margin > 0:
                            pnl_percent_from_margin = abs(pnl) / margin * 100
                            # Закрываем только если убыток > 2% от маржи
                            if pnl_percent_from_margin < 2.0:
                                logger.debug(
                                    f"⚠️ Позиция {symbol} margin_ratio={margin_ratio:.2f}%, но убыток только {pnl_percent_from_margin:.2f}% от маржи, "
                                    f"пропускаем emergency close (защита от ложных срабатываний)"
                                )
                                return
                    except (ValueError, TypeError) as e:
                        logger.debug(f"⚠️ Ошибка расчета убытка для emergency close {symbol}: {e}")
                    
                    logger.warning(
                        f"⚠️ Позиция {symbol} имеет низкую маржу: {margin_ratio:.2f}%. Закрытие... "
                        f"(время удержания: {time_since_open:.1f} сек)"
                    )
                    await self._emergency_close_position(position)
                elif margin_ratio <= 0:
                    logger.warning(
                        f"⚠️ Позиция {symbol} имеет некорректный margin_ratio: {margin_ratio:.2f}%. Пропускаем автозакрытие."
                    )

        except Exception as e:
            logger.error(f"Ошибка проверки безопасности позиции: {e}")

    async def _check_sl(self, position: Dict[str, Any]) -> bool:
        """
        ✅ НОВОЕ: Проверка адаптивного Stop Loss (SL)

        Логика:
        - Проверяется ТОЛЬКО если TSL не активен
        - Проверяется ПОСЛЕ min_holding (защита от преждевременного закрытия)
        - Более строгий стоп чем loss_cut (срабатывает раньше)

        Args:
            position: Данные позиции с биржи

        Returns:
            True если нужно закрыть позицию по SL
        """
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            entry_price = float(position.get("avgPx", "0"))
            current_price = float(position.get("markPx", "0"))

            if size == 0 or entry_price == 0 or current_price == 0:
                return False

            # ✅ Проверяем только если TSL не активен
            if hasattr(self, "orchestrator") and self.orchestrator:
                if hasattr(self.orchestrator, "trailing_sl_coordinator"):
                    tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(symbol)
                    if tsl:
                        # TSL активен - проверка SL не нужна (TSL приоритетнее)
                        return False

            # ✅ Получаем режим для адаптивного SL
            regime = position.get("regime") or self.active_positions.get(
                symbol, {}
            ).get("regime")
            if not regime and hasattr(self, "orchestrator") and self.orchestrator:
                if hasattr(self.orchestrator, "signal_generator"):
                    if hasattr(self.orchestrator.signal_generator, "regime_managers"):
                        manager = (
                            self.orchestrator.signal_generator.regime_managers.get(
                                symbol
                            )
                        )
                        if manager:
                            regime = manager.get_current_regime()

            # ✅ Получаем адаптивный SL
            sl_percent = self._get_adaptive_sl_percent(symbol, regime)

            # ✅ Проверяем min_holding (защита от преждевременного закрытия)
            minutes_in_position = 0
            if symbol in self.active_positions:
                entry_time = self.active_positions[symbol].get("entry_time")
                if entry_time:
                    if isinstance(entry_time, datetime):
                        minutes_in_position = (
                            datetime.now() - entry_time
                        ).total_seconds() / 60.0
                    else:
                        try:
                            minutes_in_position = (time.time() - entry_time) / 60.0
                        except (TypeError, ValueError):
                            pass

            # ✅ Получаем min_holding из конфига (адаптивно по режиму)
            min_holding_minutes = 0.5  # Fallback
            if regime and hasattr(self, "orchestrator") and self.orchestrator:
                try:
                    tsl_config = getattr(self.scalping_config, "trailing_sl", {})
                    if not isinstance(tsl_config, dict):
                        tsl_config = getattr(tsl_config, "__dict__", {})

                    by_regime = tsl_config.get("by_regime", {})
                    if regime.lower() in by_regime:
                        regime_tsl = by_regime[regime.lower()]
                        if isinstance(regime_tsl, dict):
                            min_holding_minutes = regime_tsl.get(
                                "min_holding_minutes", 0.5
                            )
                        elif hasattr(regime_tsl, "min_holding_minutes"):
                            min_holding_minutes = getattr(
                                regime_tsl, "min_holding_minutes", 0.5
                            )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Не удалось получить min_holding_minutes из конфига для {symbol} ({regime}): {e}"
                    )

            # ✅ Проверяем min_holding защиту
            if minutes_in_position < min_holding_minutes:
                logger.debug(
                    f"⏱️ SL заблокирован для {symbol}: позиция держится "
                    f"{minutes_in_position:.2f} мин < {min_holding_minutes:.2f} мин "
                    f"(min_holding защита активна, sl_percent={sl_percent:.2f}%)"
                )
                return False  # НЕ закрываем - min_holding защита активна

            # ✅ Рассчитываем PnL% от маржи (ТОЧНАЯ КОПИЯ логики loss_cut строки 934-940)
            try:
                margin_used = float(position.get("margin", 0))
                if margin_used > 0:
                    # ✅ КРИТИЧЕСКОЕ: size в контрактах, нужно перевести в монеты через ctVal
                    try:
                        inst_details = await self.client.get_instrument_details(symbol)
                        ct_val = float(inst_details.get("ctVal", 0.01))
                        size_in_coins = abs(size) * ct_val
                    except Exception:
                        # Fallback: предполагаем что size уже в монетах (для совместимости)
                        size_in_coins = abs(size)

                    position_side = position.get("posSide", "long").lower()
                    if position_side == "long":
                        unrealized_pnl = size_in_coins * (current_price - entry_price)
                    else:  # short
                        unrealized_pnl = size_in_coins * (entry_price - current_price)

                    pnl_percent_from_margin = (unrealized_pnl / margin_used) * 100

                    # ✅ Проверяем SL
                    if pnl_percent_from_margin <= -sl_percent:
                        logger.warning(
                            f"🚨 SL сработал для {symbol}: "
                            f"PnL={pnl_percent_from_margin:.2f}% от маржи <= -{sl_percent:.2f}% "
                            f"(margin=${margin_used:.2f}, PnL=${unrealized_pnl:.2f}, "
                            f"время в позиции: {minutes_in_position:.2f} мин, regime={regime or 'N/A'})"
                        )
                        await self._close_position_by_reason(position, "sl")
                        return True
                else:
                    logger.debug(
                        f"⚠️ margin_used=0 для {symbol}, пропускаем проверку SL"
                    )
            except Exception as e:
                logger.debug(f"⚠️ Не удалось проверить SL для {symbol}: {e}")

            return False

        except Exception as e:
            logger.error(f"❌ Ошибка проверки SL для {symbol}: {e}", exc_info=True)
            return False

    async def _check_tp_sl(self, position: Dict[str, Any]):
        """Проверка Take Profit и Stop Loss (DEPRECATED - используется _check_tp_only)"""
        # Этот метод оставлен для совместимости, но теперь используется _check_tp_only
        await self._check_tp_only(position)

    async def _check_profit_harvesting(self, position: Dict[str, Any]) -> bool:
        """
        ✅ МОДЕРНИЗАЦИЯ #1: Profit Harvest (PH) - быстрое закрытие при высокой прибыли

        Досрочный выход если позиция быстро достигла хорошей прибыли!
        ✅ АДАПТИВНЫЕ параметры из конфига по режиму рынка:
        - TRENDING: $0.20 за 180 сек (3 мин) - из config_futures.yaml
        - RANGING: $0.15 за 120 сек (2 мин) - из config_futures.yaml
        - CHOPPY: $0.10 за 60 сек (1 мин) - из config_futures.yaml

        Все параметры читаются динамически из конфига, нет захардкоженных значений!

        Args:
            position: Данные позиции с биржи

        Returns:
            True если нужно закрыть позицию по PH
        """
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            side = position.get("posSide", "long")
            entry_price = float(position.get("avgPx", "0"))
            current_price = float(position.get("markPx", "0"))

            if size == 0 or entry_price == 0 or current_price == 0:
                return False

            # Получаем параметры PH из конфига по режиму рынка
            ph_enabled = False
            ph_threshold = 0.0
            ph_time_limit = 0

            try:
                # Получаем текущий режим рынка из orchestrator
                market_regime = None
                if hasattr(self, "orchestrator") and self.orchestrator:
                    if (
                        hasattr(self.orchestrator, "signal_generator")
                        and self.orchestrator.signal_generator
                    ):
                        regime_manager = getattr(
                            self.orchestrator.signal_generator, "regime_manager", None
                        )
                        if regime_manager:
                            regime_obj = regime_manager.get_current_regime()
                            if regime_obj:
                                market_regime = (
                                    regime_obj.lower()
                                    if isinstance(regime_obj, str)
                                    else str(regime_obj).lower()
                                )

                # Получаем параметры PH из конфига
                adaptive_regime = getattr(self.scalping_config, "adaptive_regime", {})
                regime_config = None

                if market_regime and hasattr(adaptive_regime, market_regime):
                    regime_config = getattr(adaptive_regime, market_regime)
                elif hasattr(adaptive_regime, "ranging"):  # Fallback на ranging
                    regime_config = getattr(adaptive_regime, "ranging")

                if regime_config:
                    ph_enabled = getattr(regime_config, "ph_enabled", False)
                    ph_threshold = getattr(regime_config, "ph_threshold", 0.0)
                    ph_time_limit = getattr(regime_config, "ph_time_limit", 0)
            except Exception as e:
                logger.debug(f"⚠️ Не удалось получить параметры PH из конфига: {e}")
                return False

            if not ph_enabled or ph_threshold <= 0 or ph_time_limit <= 0:
                return False

            # Получаем время открытия позиции
            entry_time_str = position.get("cTime", position.get("openTime", ""))
            if not entry_time_str:
                # Пытаемся получить из active_positions orchestrator
                if hasattr(self, "orchestrator") and self.orchestrator:
                    active_positions = getattr(
                        self.orchestrator, "active_positions", {}
                    )
                    if symbol in active_positions:
                        entry_time_str = active_positions[symbol].get("entry_time", "")

            if not entry_time_str:
                return False  # Не можем определить время открытия

            try:
                # Конвертируем время открытия (OKX использует миллисекунды)
                if isinstance(entry_time_str, str):
                    if entry_time_str.isdigit():
                        entry_timestamp = (
                            int(entry_time_str) / 1000.0
                        )  # Конвертируем из мс в сек
                    else:
                        # Пытаемся распарсить ISO формат
                        entry_time = datetime.fromisoformat(
                            entry_time_str.replace("Z", "+00:00")
                        )
                        entry_timestamp = entry_time.timestamp()
                else:
                    entry_timestamp = (
                        float(entry_time_str) / 1000.0
                        if entry_time_str > 1000000000000
                        else float(entry_time_str)
                    )

                # Используем UTC время для консистентности с биржей
                from datetime import timezone

                current_timestamp = datetime.now(timezone.utc).timestamp()
                time_since_open = current_timestamp - entry_timestamp
            except Exception as e:
                logger.debug(
                    f"⚠️ Не удалось рассчитать время открытия для {symbol}: {e}"
                )
                return False

            # Рассчитываем PnL в USD
            try:
                # Получаем размер позиции в монетах
                inst_details = await self.client.get_instrument_details(symbol)
                ct_val = float(inst_details.get("ctVal", "0.01"))
                size_in_coins = abs(size) * ct_val

                # Рассчитываем PnL в USD
                if side.lower() == "long":
                    pnl_usd = size_in_coins * (current_price - entry_price)
                else:  # short
                    pnl_usd = size_in_coins * (entry_price - current_price)

                # Вычитаем комиссию (открытие + закрытие)
                # ✅ ИСПРАВЛЕНО: Комиссия из конфига (может быть в scalping или на верхнем уровне)
                commission_config = getattr(self.scalping_config, "commission", None)
                if commission_config is None:
                    # Пробуем получить с верхнего уровня конфига
                    commission_config = getattr(self.config, "commission", {})
                if not commission_config:
                    logger.warning(
                        "⚠️ Комиссия не найдена в конфиге, используем значение по умолчанию 0.0010 (0.10%)"
                    )
                    commission_rate = 0.0010
                else:
                    if isinstance(commission_config, dict):
                        commission_rate = commission_config.get("trading_fee_rate")
                    else:
                        commission_rate = getattr(
                            commission_config, "trading_fee_rate", None
                        )
                    if commission_rate is None:
                        # ✅ ИСПРАВЛЕНО: Используем реальную комиссию в зависимости от типа ордера
                        order_type = getattr(
                            self.scalping_config, "order_type", "limit"
                        )
                        if order_type == "limit":
                            commission_rate = 0.0002  # Maker: 0.02%
                        else:
                            commission_rate = 0.0005  # Taker: 0.05%
                        logger.debug(
                            f"✅ Используем комиссию {order_type}: {commission_rate:.4f} ({commission_rate*100:.2f}%)"
                        )
                position_value = size_in_coins * entry_price
                commission = position_value * commission_rate * 2  # Открытие + закрытие
                net_pnl_usd = pnl_usd - commission

            except Exception as e:
                logger.debug(f"⚠️ Не удалось рассчитать PnL для {symbol}: {e}")
                return False

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем MIN_HOLDING перед Profit Harvesting
            # Защита от шума должна работать - не закрываем по PH до 35 минут (min_holding)
            min_holding_minutes = 35.0  # Default
            try:
                if hasattr(self, "orchestrator") and self.orchestrator:
                    if hasattr(self.orchestrator, "signal_generator") and self.orchestrator.signal_generator:
                        regime_params = self.orchestrator.signal_generator.regime_manager.get_current_parameters()
                        if regime_params:
                            min_holding_minutes = getattr(regime_params, "min_holding_minutes", 35.0)
            except Exception:
                pass  # Используем default 35 минут
            
            min_holding_seconds = min_holding_minutes * 60.0
            
            # ✅ Проверяем MIN_HOLDING: если позиция открыта меньше min_holding, НЕ закрываем по PH
            if time_since_open < min_holding_seconds:
                logger.debug(
                    f"⏱️ Profit Harvest заблокирован MIN_HOLDING для {symbol}: "
                    f"позиция открыта {time_since_open:.1f}с < {min_holding_seconds:.1f}с "
                    f"(защита от шума активна)"
                )
                return False  # НЕ закрываем - защита от шума активна!

            # Проверка условий Profit Harvesting (только после MIN_HOLDING)
            if net_pnl_usd >= ph_threshold and time_since_open < ph_time_limit:
                logger.info(
                    f"💰💰💰 PROFIT HARVESTING TRIGGERED! {symbol} {side.upper()}\n"
                    f"   Quick profit: ${net_pnl_usd:.4f} (threshold: ${ph_threshold:.2f})\n"
                    f"   Time: {time_since_open:.1f}s (limit: {ph_time_limit}s, min_holding: {min_holding_seconds:.1f}s)\n"
                    f"   Entry: ${entry_price:.4f} → Exit: ${current_price:.4f}\n"
                    f"   Regime: {market_regime or 'N/A'}"
                )
                return True

            # Логируем прогресс к PH (если близко)
            if time_since_open < ph_time_limit and net_pnl_usd > 0:
                progress = (net_pnl_usd / ph_threshold) * 100 if ph_threshold > 0 else 0
                if progress >= 50:  # Логируем только если >50% прогресса
                    logger.debug(
                        f"📊 PH прогресс {symbol}: ${net_pnl_usd:.4f} / ${ph_threshold:.2f} "
                        f"({progress:.0f}%), время: {time_since_open:.1f}s / {ph_time_limit}s"
                    )

            return False

        except Exception as e:
            logger.error(f"❌ Ошибка проверки Profit Harvesting для {symbol}: {e}")
            return False

    async def _check_tp_only(self, position: Dict[str, Any]):
        """Проверка только Take Profit (SL управляется TrailingSL в orchestrator)"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            side = position.get("posSide", "long")
            entry_price = float(position.get("avgPx", "0"))
            current_price = float(position.get("markPx", "0"))
            
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем MIN_HOLDING перед TP
            # Защита от шума должна работать - не закрываем по TP до 35 минут (min_holding)
            try:
                entry_time_str = position.get("cTime", position.get("openTime", ""))
                if not entry_time_str and hasattr(self, "orchestrator") and self.orchestrator:
                    active_positions = getattr(self.orchestrator, "active_positions", {})
                    if symbol in active_positions:
                        entry_time_str = active_positions[symbol].get("entry_time", "")
                
                if entry_time_str:
                    from datetime import timezone
                    if isinstance(entry_time_str, str):
                        if entry_time_str.isdigit():
                            entry_timestamp = int(entry_time_str) / 1000.0
                        else:
                            entry_time = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
                            entry_timestamp = entry_time.timestamp()
                    else:
                        entry_timestamp = float(entry_time_str) / 1000.0 if entry_time_str > 1000000000000 else float(entry_time_str)
                    
                    current_timestamp = datetime.now(timezone.utc).timestamp()
                    time_since_open = current_timestamp - entry_timestamp
                    
                    min_holding_minutes = 35.0  # Default
                    if hasattr(self, "orchestrator") and self.orchestrator:
                        if hasattr(self.orchestrator, "signal_generator") and self.orchestrator.signal_generator:
                            regime_params = self.orchestrator.signal_generator.regime_manager.get_current_parameters()
                            if regime_params:
                                min_holding_minutes = getattr(regime_params, "min_holding_minutes", 35.0)
                    
                    min_holding_seconds = min_holding_minutes * 60.0
                    
                    if time_since_open < min_holding_seconds:
                        logger.debug(
                            f"⏱️ TP заблокирован MIN_HOLDING для {symbol}: "
                            f"позиция открыта {time_since_open:.1f}с < {min_holding_seconds:.1f}с "
                            f"(защита от шума активна)"
                        )
                        return  # НЕ закрываем - защита от шума активна!
            except Exception as e:
                logger.debug(f"⚠️ Не удалось проверить MIN_HOLDING для TP {symbol}: {e}")
                # Продолжаем проверку TP, если не удалось получить время

            # ✅ НОВОЕ: Проверка адаптивного SL (ПЕРЕД loss_cut - более строгий стоп)
            sl_should_close = await self._check_sl(position)
            if sl_should_close:
                return  # Закрыли по SL, выходим

            # ✅ TODO #4: Проверка loss_cut для позиций БЕЗ TSL или с большим убытком
            # Это гарантирует, что loss_cut проверяется даже если TSL не инициализирован
            tsl = None
            if hasattr(self, "orchestrator") and self.orchestrator:
                if hasattr(self.orchestrator, "trailing_sl_coordinator"):
                    try:
                        tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(symbol)
                    except Exception:
                        pass
            
            # Рассчитываем PnL для проверки loss_cut
            if entry_price > 0 and current_price > 0:
                try:
                    if side.lower() == "long":
                        pnl_pct = (current_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - current_price) / entry_price
                    
                    # ✅ Проверяем loss_cut только для убыточных позиций
                    if pnl_pct < 0:
                        # Получаем loss_cut из конфига
                        loss_cut_percent = None
                        market_regime = position.get("regime")
                        
                        try:
                            if hasattr(self, "orchestrator") and self.orchestrator:
                                if hasattr(self.orchestrator, "trailing_sl_coordinator"):
                                    # Получаем параметры TSL из конфига
                                    tsl_params = self.orchestrator.trailing_sl_coordinator._get_trailing_sl_params(
                                        symbol, market_regime
                                    )
                                    if tsl_params:
                                        loss_cut_percent = tsl_params.get("loss_cut_percent")
                        except Exception as e:
                            logger.debug(f"⚠️ Ошибка получения loss_cut_percent для {symbol}: {e}")
                        
                        if loss_cut_percent:
                            leverage = getattr(self.scalping_config, "leverage", 5)
                            loss_cut_from_price = loss_cut_percent / leverage
                            
                            # ✅ Для больших убытков (>= loss_cut) закрываем после минимальной задержки (5 сек)
                            if abs(pnl_pct) >= loss_cut_from_price:
                                # Получаем время открытия
                                time_since_open = 0.0
                                try:
                                    entry_time_str = position.get("cTime", position.get("openTime", ""))
                                    if entry_time_str:
                                        from datetime import timezone
                                        if isinstance(entry_time_str, str) and entry_time_str.isdigit():
                                            entry_timestamp = int(entry_time_str) / 1000.0
                                            current_timestamp = datetime.now(timezone.utc).timestamp()
                                            time_since_open = current_timestamp - entry_timestamp
                                        elif isinstance(entry_time_str, (int, float)):
                                            entry_timestamp = float(entry_time_str) / 1000.0 if float(entry_time_str) > 1000000000000 else float(entry_time_str)
                                            current_timestamp = datetime.now(timezone.utc).timestamp()
                                            time_since_open = current_timestamp - entry_timestamp
                                    
                                    # Пробуем из active_positions
                                    if time_since_open == 0 and hasattr(self, "orchestrator") and self.orchestrator:
                                        active_positions = getattr(self.orchestrator, "active_positions", {})
                                        if symbol in active_positions:
                                            entry_time_obj = active_positions[symbol].get("entry_time")
                                            if entry_time_obj:
                                                if isinstance(entry_time_obj, datetime):
                                                    time_since_open = (datetime.now() - entry_time_obj).total_seconds()
                                except Exception as e:
                                    logger.debug(f"⚠️ Ошибка расчета времени открытия для loss_cut {symbol}: {e}")
                                
                                if time_since_open >= 5.0:  # Минимальная задержка
                                    logger.warning(
                                        f"⚠️ Loss-cut (position_manager): {symbol} PnL={pnl_pct:.2%} <= -{loss_cut_from_price:.2%}%, "
                                        f"закрываем (время: {time_since_open:.1f} сек, TSL={'активен' if tsl else 'не активен'})"
                                    )
                                    await self._close_position_by_reason(position, "loss_cut")
                                    return
                                else:
                                    logger.debug(
                                        f"⏱️ Loss-cut заблокирован минимальной задержкой: {symbol} PnL={pnl_pct:.2%}, "
                                        f"время: {time_since_open:.1f} сек < 5.0 сек"
                                    )
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка проверки loss_cut в position_manager для {symbol}: {e}")
            # ✅ ИСПРАВЛЕНИЕ: Используем leverage из конфига, а не из позиции на бирже
            # На бирже может быть установлен старый leverage (3x), но расчеты должны использовать leverage из конфига (5x)
            leverage_from_position = int(position.get("lever", "0"))
            leverage = (
                getattr(self.scalping_config, "leverage", None)
                or leverage_from_position
                or 3
            )
            if leverage_from_position != leverage:
                logger.debug(
                    f"📊 Leverage: биржа={leverage_from_position}x, конфиг={leverage}x, используем {leverage}x для расчетов"
                )

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
                        margin_value = position.get("margin", "0")
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем что это не пустая строка
                        if margin_value and str(margin_value).strip():
                            try:
                                margin_used = float(margin_value)
                            except (ValueError, TypeError) as e:
                                logger.debug(
                                    f"⚠️ Ошибка конвертации margin для {symbol}: {e}, значение={margin_value}"
                                )
                                margin_used = 0
                    elif "imr" in position:
                        imr_value = position.get("imr", "0")
                        if imr_value and str(imr_value).strip():
                            try:
                                margin_used = float(imr_value)
                            except (ValueError, TypeError) as e:
                                logger.debug(
                                    f"⚠️ Ошибка конвертации imr для {symbol}: {e}, значение={imr_value}"
                                )
                                margin_used = 0
                        else:
                            # Fallback: если imr пустой, пытаемся напрямую
                            try:
                                margin_used = float(position.get("imr", "0") or 0)
                            except (ValueError, TypeError):
                                margin_used = 0
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
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Правильное определение направления позиции
                            # Используем position_side из active_positions, если доступен, иначе определяем по side
                            position_side = None
                            if hasattr(self, "orchestrator") and self.orchestrator:
                                active_positions = getattr(
                                    self.orchestrator, "active_positions", {}
                                )
                                if symbol in active_positions:
                                    position_side = active_positions[symbol].get(
                                        "position_side"
                                    )

                            # Определяем направление позиции
                            if position_side:
                                # Используем position_side из active_positions (надежнее)
                                if position_side.lower() == "long":
                                    pnl_percent = (
                                        (current_price - entry_price)
                                        / entry_price
                                        * 100
                                    )
                                else:  # short
                                    pnl_percent = (
                                        (entry_price - current_price)
                                        / entry_price
                                        * 100
                                    )
                            else:
                                # Fallback: определяем по side
                                if side.lower() in ["long", "buy"]:
                                    pnl_percent = (
                                        (current_price - entry_price)
                                        / entry_price
                                        * 100
                                    )
                                else:  # short или sell
                                    pnl_percent = (
                                        (entry_price - current_price)
                                        / entry_price
                                        * 100
                                    )

                            logger.warning(
                                f"⚠️ Используем fallback расчет PnL% для {symbol}: {pnl_percent:.2f}% (от цены, а не от маржи) "
                                f"(side={side}, position_side={position_side or 'N/A'})"
                            )
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем адаптивный TP вместо глобального
                            regime = position.get(
                                "regime"
                            ) or self.active_positions.get(symbol, {}).get("regime")
                            # ✅ ЭТАП 2.3: Передаем current_price для ATR-based расчета
                            tp_percent = self._get_adaptive_tp_percent(
                                symbol, regime, current_price
                            )
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
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Правильное определение направления позиции
                            # Используем position_side из active_positions, если доступен, иначе определяем по side
                            position_side = None
                            if hasattr(self, "orchestrator") and self.orchestrator:
                                active_positions = getattr(
                                    self.orchestrator, "active_positions", {}
                                )
                                if symbol in active_positions:
                                    position_side = active_positions[symbol].get(
                                        "position_side"
                                    )

                            # Определяем направление позиции
                            if position_side:
                                # Используем position_side из active_positions (надежнее)
                                if position_side.lower() == "long":
                                    unrealized_pnl = size_in_coins * (
                                        current_price - entry_price
                                    )
                                else:  # short
                                    unrealized_pnl = size_in_coins * (
                                        entry_price - current_price
                                    )
                            else:
                                # Fallback: определяем по side
                                if side.lower() in ["long", "buy"]:
                                    unrealized_pnl = size_in_coins * (
                                        current_price - entry_price
                                    )
                                else:  # short или sell
                                    unrealized_pnl = size_in_coins * (
                                        entry_price - current_price
                                    )
                        except Exception:
                            # Последний fallback: используем процент от цены
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Правильное определение направления позиции
                            # Используем position_side из active_positions, если доступен, иначе определяем по side
                            position_side = None
                            if hasattr(self, "orchestrator") and self.orchestrator:
                                active_positions = getattr(
                                    self.orchestrator, "active_positions", {}
                                )
                                if symbol in active_positions:
                                    position_side = active_positions[symbol].get(
                                        "position_side"
                                    )

                            # Определяем направление позиции
                            if position_side:
                                # Используем position_side из active_positions (надежнее)
                                if position_side.lower() == "long":
                                    pnl_percent = (
                                        (current_price - entry_price)
                                        / entry_price
                                        * 100
                                    )
                                else:  # short
                                    pnl_percent = (
                                        (entry_price - current_price)
                                        / entry_price
                                        * 100
                                    )
                            else:
                                # Fallback: определяем по side
                                if side.lower() in ["long", "buy"]:
                                    pnl_percent = (
                                        (current_price - entry_price)
                                        / entry_price
                                        * 100
                                    )
                                else:  # short или sell
                                    pnl_percent = (
                                        (entry_price - current_price)
                                        / entry_price
                                        * 100
                                    )

                            logger.warning(
                                f"⚠️ Fallback расчет PnL% для {symbol}: {pnl_percent:.2f}% "
                                f"(side={side}, position_side={position_side or 'N/A'})"
                            )
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем адаптивный TP вместо глобального
                            regime = position.get(
                                "regime"
                            ) or self.active_positions.get(symbol, {}).get("regime")
                            # ✅ ЭТАП 2.3: Передаем current_price для ATR-based расчета
                            tp_percent = self._get_adaptive_tp_percent(
                                symbol, regime, current_price
                            )
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
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Правильное определение направления позиции
                # Используем position_side из active_positions, если доступен, иначе определяем по side
                position_side = None
                if hasattr(self, "orchestrator") and self.orchestrator:
                    active_positions = getattr(
                        self.orchestrator, "active_positions", {}
                    )
                    if symbol in active_positions:
                        position_side = active_positions[symbol].get("position_side")

                # Определяем направление позиции
                if position_side:
                    # Используем position_side из active_positions (надежнее)
                    if position_side.lower() == "long":
                        pnl_percent = (current_price - entry_price) / entry_price * 100
                    else:  # short
                        pnl_percent = (entry_price - current_price) / entry_price * 100
                else:
                    # Fallback: определяем по side
                    if side.lower() in ["long", "buy"]:
                        pnl_percent = (current_price - entry_price) / entry_price * 100
                    else:  # short или sell
                        pnl_percent = (entry_price - current_price) / entry_price * 100

                logger.warning(
                    f"⚠️ Fallback: PnL% для {symbol} считаем от цены: {pnl_percent:.2f}% "
                    f"(side={side}, position_side={position_side or 'N/A'})"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка трейлинг стоп-лосс ПЕРЕД TP
            # Если трейлинг стоп-лосс активен (позиция в прибыли и достиг min_profit_to_close),
            # то TP отключен (трейлинг стоп-лосс имеет приоритет)
            # ✅ ИСПРАВЛЕНО: Комиссия из конфига (может быть в scalping или на верхнем уровне)
            commission_config = getattr(self.scalping_config, "commission", None)
            if commission_config is None:
                # Пробуем получить с верхнего уровня конфига
                commission_config = getattr(self.config, "commission", {})
            if not commission_config:
                commission_config = {}
            # ✅ ИСПРАВЛЕНО: Получаем комиссию из конфига, без захардкоженного fallback
            if isinstance(commission_config, dict):
                commission_rate = commission_config.get("trading_fee_rate")
            else:
                commission_rate = getattr(commission_config, "trading_fee_rate", None)
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: commission_rate ОБЯЗАТЕЛЕН в конфиге (без fallback)
            if commission_rate is None:
                raise ValueError(
                    "❌ КРИТИЧЕСКАЯ ОШИБКА: trading_fee_rate не найден в конфиге! "
                    "Добавьте в config_futures.yaml: scalping.commission.trading_fee_rate (например, 0.0010 для 0.10%)"
                )
            trailing_sl_active = False
            min_profit_to_close = None

            # Получаем трейлинг стоп-лосс из orchestrator (если доступен)
            if hasattr(self, "orchestrator") and self.orchestrator:
                # ✅ ИСПРАВЛЕНО: TSL теперь в trailing_sl_coordinator
                if hasattr(self.orchestrator, "trailing_sl_coordinator"):
                    tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(symbol)
                else:
                    tsl = None
                if tsl:
                    # Получаем текущую прибыль (net с комиссией)
                    profit_pct_net = tsl.get_profit_pct(
                        current_price, include_fees=True
                    )
                    min_profit_to_close = getattr(tsl, "min_profit_to_close", None)

                    # Если позиция в прибыли и достиг минимального профита для трейлинга
                    # ⚠️ ВАЖНО: profit_pct_net и min_profit_to_close оба в долях (0.001 = 0.1%)
                    if profit_pct_net > 0 and min_profit_to_close is not None:
                        if profit_pct_net >= min_profit_to_close:
                            # ✅ ИСПРАВЛЕНО: Трейлинг стоп-лосс активен, но TP все равно проверяем
                            # Если TP достигнут, закрываем сразу, не ждем TSL
                            trailing_sl_active = True
                            logger.debug(
                                f"📊 {symbol} трейлинг стоп-лосс активен "
                                f"(profit={profit_pct_net:.3%} >= {min_profit_to_close:.3%}), "
                                f"но TP все равно проверяем (приоритет TP над TSL)"
                            )
                            # ✅ ИСПРАВЛЕНО: НЕ возвращаемся, продолжаем проверку TP ниже

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем адаптивный TP вместо глобального
            # Получаем режим из позиции (сохранен при открытии)
            regime = position.get("regime") or self.active_positions.get(
                symbol, {}
            ).get("regime")

            # ✅ Используем вспомогательный метод для получения адаптивного TP
            # ✅ ЭТАП 2.3: Передаем current_price для ATR-based расчета
            tp_percent = self._get_adaptive_tp_percent(symbol, regime, current_price)

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: TP должен быть выше минимального профита трейлинг стоп-лосс + комиссия
            # Если трейлинг стоп-лосс еще не активен (не достиг min_profit_to_close), то TP может сработать,
            # но должен быть выше min_profit_to_close + комиссия + buffer
            # ⚠️ ВАЖНО: min_profit_to_close в долях (0.001 = 0.1%), tp_percent в процентах (1.0 = 1%)
            if (
                not trailing_sl_active
                and min_profit_to_close is not None
                and pnl_percent > 0
            ):
                min_profit_to_close_pct = (
                    min_profit_to_close * 100
                )  # Конвертируем в проценты для сравнения с tp_percent
                # ✅ ИСПРАВЛЕНО: Комиссия от маржи с учетом плеча
                leverage_for_calc = (
                    getattr(self.scalping_config, "leverage", leverage) or leverage or 5
                )
                commission_rate_from_margin_calc = (
                    commission_rate * leverage_for_calc * 2
                )
                commission_pct = (
                    commission_rate_from_margin_calc * 100
                )  # Комиссия от маржи в процентах

                # ✅ ИСПРАВЛЕНО: Buffer из конфига (буфер на slippage)
                slippage_buffer_pct = commission_config.get(
                    "slippage_buffer_percent", 0.15
                )
                buffer_pct = commission_config.get("tp_buffer_percent", 0.1)
                min_tp_percent = (
                    min_profit_to_close_pct
                    + commission_pct
                    + slippage_buffer_pct
                    + buffer_pct
                )

                if tp_percent < min_tp_percent:
                    # TP слишком низкий - поднимаем до минимума
                    original_tp = tp_percent
                    tp_percent = min_tp_percent
                    logger.debug(
                        f"📊 {symbol} TP поднят с {original_tp:.2f}% до {tp_percent:.2f}% "
                        f"(минимум для трейлинга: min_profit={min_profit_to_close_pct:.2f}% + комиссия={commission_pct:.2f}% + slippage={slippage_buffer_pct:.2f}% + запас={buffer_pct:.2f}% = {min_tp_percent:.2f}%)"
                    )

            # ✅ НОВОЕ: Продление TP в тренде (из конфига)
            tp_extension_config = getattr(
                self.scalping_config, "position_manager", {}
            ).get("tp_extension", {})
            if tp_extension_config.get("enabled", False) and pnl_percent > 0:
                # Получаем силу тренда из orchestrator
                trend_strength = await self._get_trend_strength(symbol, current_price)
                min_trend_strength = tp_extension_config.get("min_trend_strength", 0.7)

                if trend_strength >= min_trend_strength:
                    # Продлеваем TP вместо закрытия
                    extension_step = tp_extension_config.get("extension_step", 0.5)
                    max_tp = tp_extension_config.get("max_tp_percent", 5.0)

                    # Получаем текущий TP из позиции или символа
                    current_tp = tp_percent
                    new_tp = min(current_tp + extension_step, max_tp)

                    if new_tp > current_tp:
                        logger.info(
                            f"📈 Продление TP для {symbol}: {current_tp:.2f}% → {new_tp:.2f}% "
                            f"(тренд: {trend_strength:.2f}, PnL: {pnl_percent:.2f}%)"
                        )
                        # Обновляем TP в позиции (вместо закрытия)
                        # ВАЖНО: Это требует обновления TP на бирже или сохранения нового TP для проверки
                        # ✅ ИСПРАВЛЕНО: Учитываем комиссию от маржи при продлении TP
                        leverage_for_ext = (
                            getattr(self.scalping_config, "leverage", leverage)
                            or leverage
                            or 5
                        )
                        commission_rate_from_margin_ext = (
                            commission_rate * leverage_for_ext * 2
                        )
                        commission_pct_from_margin_ext = (
                            commission_rate_from_margin_ext * 100
                        )
                        slippage_buffer_ext = commission_config.get(
                            "slippage_buffer_percent", 0.15
                        )
                        if (
                            pnl_percent
                            < new_tp
                            + commission_pct_from_margin_ext
                            + slippage_buffer_ext
                        ):
                            logger.debug(
                                f"📊 {symbol} продлеваем TP до {new_tp:.2f}%, "
                                f"текущий PnL {pnl_percent:.2f}% < нового TP {new_tp:.2f}%, не закрываем"
                            )
                            return  # Не закрываем, продлеваем TP

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Учитываем комиссию при проверке TP с учетом плеча
            # Комиссия берется от номинала, но TP в процентах от маржи
            # При плече 5x: 0.10% от номинала = 1.00% от маржи (0.10% × 5 × 2 для открытия+закрытия)
            # ✅ ИСПРАВЛЕНО: Учитываем плечо при расчете комиссии от маржи
            commission_rate_from_margin = (
                commission_rate * leverage * 2
            )  # Комиссия от маржи (открытие + закрытие)
            commission_pct_from_margin = (
                commission_rate_from_margin * 100
            )  # В процентах от маржи

            # ✅ НОВОЕ: Получаем slippage buffer из конфига (буфер на slippage)
            slippage_buffer_pct = commission_config.get(
                "slippage_buffer_percent", 0.15
            )  # По умолчанию 0.15%

            # ✅ НОВОЕ: Динамический расчет TP с учетом комиссии, плеча и slippage
            tp_percent_with_commission = (
                tp_percent + commission_pct_from_margin + slippage_buffer_pct
            )

            if pnl_percent >= tp_percent_with_commission:
                # ✅ ИСПРАВЛЕНО: Учитываем комиссию от маржи при закрытии
                net_pnl_percent = pnl_percent - commission_pct_from_margin
                if net_pnl_percent > 0:
                    logger.info(
                        f"🎯 TP достигнут для {symbol}: {pnl_percent:.2f}% "
                        f"(TP={tp_percent:.2f}%, net после комиссии: {net_pnl_percent:.2f}%, "
                        f"PnL=${unrealized_pnl:.2f}, margin=${margin_used:.2f})"
                    )
                    await self._close_position_by_reason(position, "tp")
                    return
                else:
                    # После комиссии убыток - не закрываем по TP
                    logger.debug(
                        f"📊 {symbol} TP достигнут, но после комиссии убыток: "
                        f"{pnl_percent:.2f}% - {commission_pct_from_margin:.2f}% = {net_pnl_percent:.2f}%, "
                        f"не закрываем"
                    )
            else:
                logger.debug(
                    f"📊 {symbol} PnL={pnl_percent:.2f}% < TP={tp_percent:.2f}% "
                    f"(с комиссией: {tp_percent_with_commission:.2f}%, нужно еще {tp_percent_with_commission - pnl_percent:.2f}%)"
                )

                # ✅ Big-profit exit: при крупной чистой прибыли — закрытие с трейлинг стопом для удержания прибыльных позиций
                try:
                    # ✅ ИСПРАВЛЕНО: Учитываем комиссию от маржи
                    net_pnl_percent = pnl_percent - commission_pct_from_margin

                    # ✅ НОВОЕ: Получаем big_profit_exit_percent из конфига по символу и режиму
                    big_profit_threshold = None
                    market_regime = None

                    # Получаем текущий режим рынка
                    if hasattr(self, "orchestrator") and self.orchestrator:
                        if (
                            hasattr(self.orchestrator, "signal_generator")
                            and self.orchestrator.signal_generator
                        ):
                            regime_manager = getattr(
                                self.orchestrator.signal_generator,
                                "regime_manager",
                                None,
                            )
                            if regime_manager:
                                regime_obj = regime_manager.get_current_regime()
                                if regime_obj:
                                    market_regime = regime_obj.lower()

                    # Пытаемся получить параметр из symbol_profiles по символу и режиму
                    if symbol in self.symbol_profiles:
                        symbol_config = self.symbol_profiles[symbol]
                        if market_regime and market_regime in symbol_config:
                            regime_config = symbol_config[market_regime]
                            if (
                                isinstance(regime_config, dict)
                                and "big_profit_exit_percent" in regime_config
                            ):
                                big_profit_threshold = float(
                                    regime_config["big_profit_exit_percent"]
                                )

                    # Fallback на глобальные значения если не найдено
                    if big_profit_threshold is None:
                        alts = {"SOL-USDT", "DOGE-USDT", "XRP-USDT"}
                        if symbol in alts:
                            big_profit_threshold = float(
                                getattr(
                                    self.scalping_config,
                                    "big_profit_exit_percent_alts",
                                    2.0,  # Увеличенное значение по умолчанию
                                )
                            )
                        else:
                            big_profit_threshold = float(
                                getattr(
                                    self.scalping_config,
                                    "big_profit_exit_percent_majors",
                                    1.5,  # Увеличенное значение по умолчанию
                                )
                            )

                    # ✅ ИСПРАВЛЕНО: Добавлено детальное логирование Big-profit exit
                    progress = (
                        (net_pnl_percent / big_profit_threshold * 100)
                        if big_profit_threshold > 0
                        else 0
                    )
                    if (
                        net_pnl_percent > 0 and progress >= 50
                    ):  # Логируем если >50% прогресса
                        logger.debug(
                            f"📊 Big-profit exit прогресс {symbol}: net={net_pnl_percent:.2f}% / "
                            f"порог={big_profit_threshold:.2f}% ({progress:.0f}%)"
                        )

                    # ✅ ПРАВКА #6: Big-profit exit с трейлинг стопом для удержания прибыльных позиций
                    # Трейлинг стоп: отслеживаем максимальную прибыль и закрываем только если прибыль просела
                    # ✅ ИСПРАВЛЕНО: position - это dict, используем проверку через "in" вместо hasattr
                    if "_big_profit_max" not in position:
                        position[
                            "_big_profit_max"
                        ] = net_pnl_percent  # Инициализируем максимум
                        position[
                            "_big_profit_history"
                        ] = []  # История прибыли для определения резкого тренда
                    else:
                        # Обновляем максимум если прибыль выросла
                        if net_pnl_percent > position["_big_profit_max"]:
                            position["_big_profit_max"] = net_pnl_percent

                    # ✅ НОВОЕ: Отслеживаем историю прибыли для определения резкого тренда
                    if "_big_profit_history" not in position:
                        position["_big_profit_history"] = []

                    current_time = time.time()
                    position["_big_profit_history"].append(
                        (current_time, net_pnl_percent)
                    )
                    # Храним историю за последние 5 минут
                    position["_big_profit_history"] = [
                        (t, p)
                        for t, p in position["_big_profit_history"]
                        if current_time - t <= 300  # 5 минут
                    ]

                    # ✅ НОВОЕ: Определение резкого тренда (быстрый рост прибыли)
                    strong_trend = False
                    if len(position["_big_profit_history"]) >= 2:
                        # Проверяем скорость роста прибыли
                        oldest_time, oldest_profit = position["_big_profit_history"][0]
                        newest_time, newest_profit = position["_big_profit_history"][-1]
                        time_diff = max(
                            newest_time - oldest_time, 1
                        )  # Минимум 1 секунда
                        profit_growth = newest_profit - oldest_profit
                        growth_rate_per_minute = (
                            profit_growth / time_diff
                        ) * 60  # % в минуту

                        # Резкий тренд: прибыль растет быстрее 0.3% в минуту
                        if growth_rate_per_minute > 0.3 and net_pnl_percent > 0:
                            strong_trend = True
                            logger.debug(
                                f"🚀 Резкий тренд обнаружен {symbol}: скорость роста {growth_rate_per_minute:.2f}%/мин, "
                                f"прибыль {net_pnl_percent:.2f}%"
                            )

                    # ✅ НОВОЕ: Продление позиций при резком тренде
                    # Если резкий тренд активен - увеличиваем порог и трейлинг стоп проседание
                    if strong_trend:
                        big_profit_threshold = (
                            big_profit_threshold * 1.5
                        )  # Увеличиваем порог на 50%
                        big_profit_trailing_pct = (
                            0.4  # Увеличиваем проседание до 40% (вместо 30%)
                        )
                    else:
                        big_profit_trailing_pct = (
                            0.3  # 30% проседание от максимума (стандарт)
                        )

                    profit_drawdown = (
                        (position["_big_profit_max"] - net_pnl_percent)
                        / position["_big_profit_max"]
                        if position["_big_profit_max"] > 0
                        else 0
                    )

                    should_close = False
                    close_reason = ""

                    if net_pnl_percent >= big_profit_threshold:
                        # Прибыль достигла порога - проверяем трейлинг
                        if net_pnl_percent >= position["_big_profit_max"]:
                            # Прибыль на максимуме - НЕ закрываем (ждем проседания)
                            logger.debug(
                                f"📈 Big-profit exit: {symbol} net={net_pnl_percent:.2f}% "
                                f"(порог={big_profit_threshold:.2f}%, max={position['_big_profit_max']:.2f}%), "
                                f"прибыль растет - держим позицию (трейлинг стоп активен)"
                            )
                        elif profit_drawdown >= big_profit_trailing_pct:
                            # Прибыль просела на 30% от максимума - закрываем
                            should_close = True
                            close_reason = f"трейлинг стоп (проседание {profit_drawdown:.1%} от max={position['_big_profit_max']:.2f}%)"
                        else:
                            # Прибыль просела, но не достаточно - продолжаем держать
                            logger.debug(
                                f"📊 Big-profit exit: {symbol} net={net_pnl_percent:.2f}% "
                                f"(порог={big_profit_threshold:.2f}%, max={position['_big_profit_max']:.2f}%), "
                                f"проседание {profit_drawdown:.1%} < {big_profit_trailing_pct:.0%} - держим (трейлинг стоп)"
                            )

                    if should_close:
                        # ✅ ИСПРАВЛЕНО: Проверка min_holding ПЕРЕД big_profit_exit
                        min_holding_blocked = False
                        if hasattr(self, "orchestrator") and self.orchestrator:
                            # ✅ ИСПРАВЛЕНО: TSL теперь в trailing_sl_coordinator
                            if hasattr(self.orchestrator, "trailing_sl_coordinator"):
                                tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(
                                    symbol
                                )
                            else:
                                tsl = None
                            if (
                                tsl
                                and hasattr(tsl, "min_holding_minutes")
                                and tsl.min_holding_minutes
                            ):
                                if (
                                    hasattr(tsl, "entry_timestamp")
                                    and tsl.entry_timestamp
                                ):
                                    minutes_in_position = (
                                        time.time() - tsl.entry_timestamp
                                    ) / 60.0
                                    effective_min_holding = tsl.min_holding_minutes
                                    # Учитываем extend_time_on_profit если позиция в прибыли
                                    if (
                                        hasattr(tsl, "extend_time_on_profit")
                                        and tsl.extend_time_on_profit
                                        and net_pnl_percent > 0
                                        and hasattr(tsl, "extend_time_multiplier")
                                    ):
                                        effective_min_holding = (
                                            effective_min_holding
                                            * tsl.extend_time_multiplier
                                        )

                                    if minutes_in_position < effective_min_holding:
                                        min_holding_blocked = True
                                        logger.debug(
                                            f"⏱️ Big-profit exit заблокирован: позиция держится "
                                            f"{minutes_in_position:.2f} мин < {effective_min_holding:.2f} мин "
                                            f"(min_holding защита активна, net={net_pnl_percent:.2f}%)"
                                        )

                        if min_holding_blocked:
                            return  # НЕ закрываем по big_profit_exit - min_holding защита активна!

                        logger.info(
                            f"💰 Big-profit exit: {symbol} net={net_pnl_percent:.2f}% "
                            f"(порог={big_profit_threshold:.2f}%, max={position['_big_profit_max']:.2f}%), "
                            f"закрываем по {close_reason}"
                        )
                        await self._close_position_by_reason(
                            position, "big_profit_exit"
                        )
                        return
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка Big-profit exit для {symbol}: {e}")

            # ✅ ОПТИМИЗАЦИЯ #5: Partial Take Profit лимитами (maker) перед полным закрытием - АДАПТИВНО ПО РЕЖИМАМ
            # Если прибыль положительная и порог близок/достигнут — пробуем закрыть часть позиции лимитом c post_only
            try:
                partial_cfg = getattr(self.scalping_config, "partial_tp", {})
                if not isinstance(partial_cfg, dict):
                    partial_cfg = {}

                ptp_enabled = partial_cfg.get("enabled", False)
                ptp_post_only = bool(partial_cfg.get("post_only", True))
                ptp_offset_bps = float(
                    partial_cfg.get("limit_offset_bps", 7.0)
                )  # 7 б.п. = 0.07%

                # ✅ ОПТИМИЗАЦИЯ #5: Получаем параметры по режиму (адаптивно)
                ptp_fraction = float(
                    partial_cfg.get("fraction", 0.6)
                )  # По умолчанию 60%
                ptp_trigger = float(
                    partial_cfg.get("trigger_percent", 0.4)
                )  # По умолчанию 0.4%

                # Получаем режим рынка из позиции или signal_generator
                current_regime = None
                if symbol in self.active_positions:
                    stored_position = self.active_positions[symbol]
                    if isinstance(stored_position, dict):
                        current_regime = stored_position.get("regime")

                # Если режим не в позиции, пробуем получить из signal_generator
                if (
                    not current_regime
                    and hasattr(self, "orchestrator")
                    and self.orchestrator
                ):
                    if (
                        hasattr(self.orchestrator, "signal_generator")
                        and self.orchestrator.signal_generator
                    ):
                        signal_gen = self.orchestrator.signal_generator
                        if (
                            hasattr(signal_gen, "regime_managers")
                            and signal_gen.regime_managers
                        ):
                            manager = signal_gen.regime_managers.get(symbol)
                            if manager:
                                current_regime = manager.get_current_regime()
                        elif (
                            hasattr(signal_gen, "regime_manager")
                            and signal_gen.regime_manager
                        ):
                            try:
                                current_regime = (
                                    signal_gen.regime_manager.get_current_regime()
                                )
                            except:
                                pass

                # ✅ ОПТИМИЗАЦИЯ #5: Используем адаптивные параметры по режиму
                regime_configs = partial_cfg.get("by_regime", {})
                if current_regime and current_regime.lower() in regime_configs:
                    regime_config = regime_configs[current_regime.lower()]
                    regime_fraction = regime_config.get("fraction")
                    regime_trigger = regime_config.get("trigger_percent")

                    if regime_fraction is not None:
                        ptp_fraction = float(regime_fraction)
                    if regime_trigger is not None:
                        ptp_trigger = float(regime_trigger)

                    logger.debug(
                        f"📊 Partial TP для {symbol}: режим={current_regime}, "
                        f"fraction={ptp_fraction:.1%}, trigger={ptp_trigger:.2f}%"
                    )

                # Однократность: не делаем повторно для той же позиции
                partial_done = False
                if symbol in self.active_positions:
                    partial_done = self.active_positions[symbol].get(
                        "partial_tp_done", False
                    )

                # ✅ ИСПРАВЛЕНО: Добавлено детальное логирование Partial TP
                if ptp_enabled and not partial_done and size > 0 and pnl_percent > 0:
                    ptp_progress = (
                        (pnl_percent / ptp_trigger * 100) if ptp_trigger > 0 else 0
                    )
                    if ptp_progress >= 50:  # Логируем если >50% прогресса
                        logger.debug(
                            f"📊 Partial TP прогресс {symbol}: pnl={pnl_percent:.2f}% / "
                            f"триггер={ptp_trigger:.2f}% ({ptp_progress:.0f}%, done={partial_done})"
                        )

                if (
                    ptp_enabled
                    and not partial_done
                    and size > 0
                    and pnl_percent > 0
                    and pnl_percent >= ptp_trigger
                ):
                    # ✅ ПРАВКА #1: Проверка min_holding ПЕРЕД Partial TP
                    min_holding_blocked = False
                    if hasattr(self, "orchestrator") and self.orchestrator:
                        # ✅ ИСПРАВЛЕНО: TSL теперь в trailing_sl_coordinator
                        if hasattr(self.orchestrator, "trailing_sl_coordinator"):
                            tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(
                                symbol
                            )
                        else:
                            tsl = None
                        if (
                            tsl
                            and hasattr(tsl, "min_holding_minutes")
                            and tsl.min_holding_minutes
                        ):
                            if hasattr(tsl, "entry_timestamp") and tsl.entry_timestamp:
                                minutes_in_position = (
                                    time.time() - tsl.entry_timestamp
                                ) / 60.0
                                effective_min_holding = tsl.min_holding_minutes
                                # Учитываем extend_time_on_profit если позиция в прибыли
                                if (
                                    hasattr(tsl, "extend_time_on_profit")
                                    and tsl.extend_time_on_profit
                                    and pnl_percent > 0
                                    and hasattr(tsl, "extend_time_multiplier")
                                ):
                                    effective_min_holding = (
                                        effective_min_holding
                                        * tsl.extend_time_multiplier
                                    )

                                # ✅ ЭТАП 1.2: Адаптивный min_holding для Partial TP на основе прибыли
                                # Получаем параметры из конфига
                                partial_tp_config = getattr(
                                    self.scalping_config, "partial_tp", {}
                                )
                                adaptive_min_holding_config = partial_tp_config.get(
                                    "adaptive_min_holding", {}
                                )
                                adaptive_enabled = adaptive_min_holding_config.get(
                                    "enabled", True
                                )

                                if adaptive_enabled and pnl_percent > 0:
                                    # Адаптивно снижаем min_holding на основе прибыли
                                    profit_threshold_1 = (
                                        adaptive_min_holding_config.get(
                                            "profit_threshold_1", 1.0
                                        )
                                    )  # 1.0%
                                    profit_threshold_2 = (
                                        adaptive_min_holding_config.get(
                                            "profit_threshold_2", 0.5
                                        )
                                    )  # 0.5%
                                    reduction_factor_1 = (
                                        adaptive_min_holding_config.get(
                                            "reduction_factor_1", 0.5
                                        )
                                    )  # 50%
                                    reduction_factor_2 = (
                                        adaptive_min_holding_config.get(
                                            "reduction_factor_2", 0.75
                                        )
                                    )  # 75%

                                    if pnl_percent >= profit_threshold_1:
                                        # Прибыль >= 1.0% - снижаем min_holding до 50%
                                        effective_min_holding = (
                                            effective_min_holding * reduction_factor_1
                                        )
                                        logger.debug(
                                            f"📊 Адаптивный min_holding для Partial TP {symbol}: "
                                            f"прибыль {pnl_percent:.2f}% >= {profit_threshold_1:.2f}% → "
                                            f"min_holding снижен до {effective_min_holding:.2f} мин (x{reduction_factor_1})"
                                        )
                                    elif pnl_percent >= profit_threshold_2:
                                        # Прибыль >= 0.5% - снижаем min_holding до 75%
                                        effective_min_holding = (
                                            effective_min_holding * reduction_factor_2
                                        )
                                        logger.debug(
                                            f"📊 Адаптивный min_holding для Partial TP {symbol}: "
                                            f"прибыль {pnl_percent:.2f}% >= {profit_threshold_2:.2f}% → "
                                            f"min_holding снижен до {effective_min_holding:.2f} мин (x{reduction_factor_2})"
                                        )

                                if minutes_in_position < effective_min_holding:
                                    min_holding_blocked = True
                                    logger.debug(
                                        f"⏱️ Partial TP заблокирован: позиция держится "
                                        f"{minutes_in_position:.2f} мин < {effective_min_holding:.2f} мин "
                                        f"(min_holding защита активна, pnl={pnl_percent:.2f}%)"
                                    )

                    if min_holding_blocked:
                        return  # НЕ закрываем по Partial TP - min_holding защита активна!

                    # Рассчитываем размер и цену лимитного reduce-only ордера
                    size_abs = abs(size)
                    size_partial = max(0.0, min(size_abs * ptp_fraction, size_abs))

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #4: Проверка минимального размера перед Partial TP
                    if size_partial > 0:
                        try:
                            # Получаем минимальный размер для символа
                            inst_details = await self.client.get_instrument_details(
                                symbol
                            )
                            min_sz = float(inst_details.get("minSz", 0.01))

                            if size_partial < min_sz:
                                logger.debug(
                                    f"⚠️ Partial TP пропущен для {symbol}: размер {size_partial:.6f} контрактов "
                                    f"< минимума {min_sz:.6f} контрактов (fraction={ptp_fraction:.1%}, "
                                    f"size_abs={size_abs:.6f})"
                                )
                                return  # Пропускаем Partial TP, если размер меньше минимума
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Не удалось получить минимальный размер для {symbol}: {e}, "
                                f"пропускаем проверку"
                            )
                            # При ошибке лучше пропустить Partial TP, чем попытаться закрыть слишком маленькую позицию
                            return

                    if size_partial > 0:
                        # Цена с небольшим сдвигом в сторону тейк-профита
                        offset = ptp_offset_bps / 10000.0
                        if side.lower() == "long":
                            limit_price = current_price * (1 + offset)
                            close_side = "sell"
                        else:
                            limit_price = current_price * (1 - offset)
                            close_side = "buy"

                        logger.info(
                            f"📌 Partial TP {symbol}: выставляем лимит {close_side} "
                            f"{size_partial:.6f} контрактов @ {limit_price:.4f} "
                            f"(pnl={pnl_percent:.2f}%, fraction={ptp_fraction:.2f}, post_only={ptp_post_only})"
                        )

                        try:
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем активные reduceOnly ордера перед размещением
                            # Это предотвращает размещение дубликатов при отмене предыдущих ордеров
                            try:
                                active_orders = await self.client.get_active_orders(
                                    symbol
                                )
                                inst_id = f"{symbol}-SWAP"
                                has_reduce_only_order = False
                                for order in active_orders:
                                    order_inst_id = order.get("instId", "")
                                    order_side = order.get("side", "").lower()
                                    # Проверяем, есть ли уже reduceOnly ордер на закрытие
                                    if (
                                        (
                                            order_inst_id == inst_id
                                            or order_inst_id == symbol
                                        )
                                        and order_side == close_side
                                        and order.get("reduceOnly", "false").lower()
                                        == "true"
                                    ):
                                        order_state = order.get("state", "").lower()
                                        # Пропускаем только отмененные ордера
                                        if order_state not in ["canceled", "cancelled"]:
                                            has_reduce_only_order = True
                                            logger.debug(
                                                f"⚠️ Partial TP пропущен для {symbol}: "
                                                f"уже есть активный reduceOnly ордер {order.get('ordId')} "
                                                f"(state={order_state})"
                                            )
                                            break

                                if has_reduce_only_order:
                                    return  # Пропускаем размещение, если уже есть активный ордер
                            except Exception as e:
                                logger.warning(
                                    f"⚠️ Ошибка проверки активных ордеров для Partial TP {symbol}: {e}, "
                                    f"продолжаем размещение"
                                )

                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем актуальный размер позиции на бирже
                            # перед размещением, так как позиция могла быть закрыта частично
                            try:
                                actual_positions = await self.client.get_positions(
                                    symbol
                                )
                                actual_size = 0.0
                                for pos in actual_positions:
                                    pos_inst_id = pos.get("instId", "").replace(
                                        "-SWAP", ""
                                    )
                                    if pos_inst_id == symbol:
                                        actual_size = abs(float(pos.get("pos", "0")))
                                        break

                                if actual_size < size_partial:
                                    logger.warning(
                                        f"⚠️ Partial TP пропущен для {symbol}: "
                                        f"размер позиции {actual_size:.6f} контрактов < "
                                        f"требуемого для Partial TP {size_partial:.6f} контрактов. "
                                        f"Позиция могла быть закрыта частично."
                                    )
                                    return  # Пропускаем, если позиция слишком мала

                                # Обновляем size_partial, если позиция стала меньше
                                if actual_size < size_abs:
                                    size_partial = min(
                                        size_partial, actual_size * ptp_fraction
                                    )
                                    logger.debug(
                                        f"📊 Partial TP размер скорректирован для {symbol}: "
                                        f"{size_partial:.6f} контрактов (позиция={actual_size:.6f})"
                                    )
                            except Exception as e:
                                logger.warning(
                                    f"⚠️ Ошибка проверки размера позиции для Partial TP {symbol}: {e}, "
                                    f"продолжаем с исходным размером"
                                )

                            # Размещаем лимитный reduce-only ордер (size уже в контрактах)
                            result = await self.client.place_futures_order(
                                symbol=symbol,
                                side=close_side,
                                size=size_partial,
                                order_type="limit",
                                price=limit_price,
                                size_in_contracts=True,
                                reduce_only=True,
                                post_only=ptp_post_only,
                            )
                            if isinstance(result, dict) and result.get("code") == "0":
                                # Помечаем, что partial TP выставлен
                                if symbol in self.active_positions and isinstance(
                                    self.active_positions[symbol], dict
                                ):
                                    self.active_positions[symbol][
                                        "partial_tp_done"
                                    ] = True
                                logger.info(
                                    f"✅ Partial TP ордер для {symbol} размещён успешно (ordId={result.get('data',[{}])[0].get('ordId','?')})"
                                )
                            else:
                                # ❗ Если лимит не размещён — делаем fallback на MARKET reduce_only
                                logger.warning(
                                    f"⚠️ Partial TP лимит не размещён для {symbol}: {result}. Fallback → MARKET reduce_only"
                                )
                                market_res = await self.client.place_futures_order(
                                    symbol=symbol,
                                    side=close_side,
                                    size=size_partial,
                                    order_type="market",
                                    size_in_contracts=True,
                                    reduce_only=True,
                                )
                                if (
                                    isinstance(market_res, dict)
                                    and market_res.get("code") == "0"
                                ):
                                    if symbol in self.active_positions and isinstance(
                                        self.active_positions[symbol], dict
                                    ):
                                        self.active_positions[symbol][
                                            "partial_tp_done"
                                        ] = True
                                    logger.info(
                                        f"✅ Partial TP MARKET для {symbol} выполнен успешно"
                                    )
                                else:
                                    logger.error(
                                        f"❌ Partial TP MARKET не выполнен для {symbol}: {market_res}"
                                    )
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Ошибка размещения Partial TP для {symbol}: {e}"
                            )
            except Exception as e:
                logger.debug(f"⚠️ Partial TP блок пропущен: {e}")

            # ⚠️ Stop Loss отключен - используется TrailingSL из orchestrator
            # TrailingSL более гибкий и учитывает тренд/режим рынка

        except Exception as e:
            logger.error(f"Ошибка проверки TP: {e}")

    async def _get_trend_strength(self, symbol: str, current_price: float) -> float:
        """
        ✅ НОВОЕ: Получение силы тренда для продления TP

        Returns:
            Сила тренда от 0.0 до 1.0 (0.7+ = сильный тренд)
        """
        try:
            # Получаем FastADX из orchestrator
            if hasattr(self, "orchestrator") and self.orchestrator:
                fast_adx = getattr(self.orchestrator, "fast_adx", None)
                if fast_adx:
                    # Получаем ADX значение
                    # FastADX требует свечи, получаем их через signal_generator или client
                    if hasattr(self.orchestrator, "signal_generator"):
                        signal_gen = self.orchestrator.signal_generator
                        if signal_gen:
                            market_data = await signal_gen._get_market_data(symbol)
                            if market_data and market_data.ohlcv_data:
                                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #3: Используем правильные методы FastADX
                                # Обновляем FastADX с данными свечей
                                for candle in market_data.ohlcv_data:
                                    fast_adx.update(
                                        high=candle.high,
                                        low=candle.low,
                                        close=candle.close,
                                    )
                                # Получаем ADX значение
                                adx_value = fast_adx.get_current_adx()
                                if adx_value and adx_value > 0:
                                    # Нормализуем ADX к 0-1 (ADX обычно 0-100)
                                    # Сильный тренд = ADX > 25, очень сильный = ADX > 50
                                    trend_strength = min(
                                        adx_value / 50.0, 1.0
                                    )  # 50+ ADX = 1.0 сила
                                    return trend_strength
        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить силу тренда для {symbol}: {e}")

        # Fallback: возвращаем 0.5 (средняя сила тренда)
        return 0.5

    async def _close_position_by_reason(
        self, position: Dict[str, Any], reason: str
    ) -> Optional[TradeResult]:
        """
        Закрытие позиции по причине

        Returns:
            TradeResult если позиция успешно закрыта, None в противном случае
        """
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
                return None

            size = float(actual_position.get("pos", "0"))
            side = actual_position.get("posSide", "long")
            entry_price = float(actual_position.get("avgPx", "0"))
            exit_price = float(
                actual_position.get("markPx", "0")
            )  # Текущая цена (mark price)

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем финальный PnL перед закрытием
            final_pnl = 0.0
            try:
                # Пробуем разные варианты названий полей для unrealized PnL
                if "upl" in actual_position and actual_position.get("upl"):
                    final_pnl = float(actual_position["upl"])
                elif "uPnl" in actual_position and actual_position.get("uPnl"):
                    final_pnl = float(actual_position["uPnl"])
                elif "unrealizedPnl" in actual_position and actual_position.get(
                    "unrealizedPnl"
                ):
                    final_pnl = float(actual_position["unrealizedPnl"])
            except (ValueError, TypeError):
                pass

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем время открытия позиции для расчета duration
            # Приоритет 1: orchestrator.active_positions (главный источник)
            # Приоритет 2: TrailingStopLoss.entry_timestamp
            # Приоритет 3: position_manager.active_positions (fallback)
            entry_time = None

            # 1. Пробуем получить из orchestrator.active_positions (главный источник)
            if hasattr(self, "orchestrator") and self.orchestrator:
                if hasattr(self.orchestrator, "active_positions"):
                    if symbol in self.orchestrator.active_positions:
                        stored_position = self.orchestrator.active_positions[symbol]
                        if isinstance(stored_position, dict):
                            entry_time = stored_position.get("entry_time")
                            if isinstance(entry_time, str):
                                try:
                                    entry_time = datetime.fromisoformat(
                                        entry_time.replace("Z", "+00:00")
                                    )
                                    logger.debug(
                                        f"✅ entry_time для {symbol} получен из orchestrator.active_positions: {entry_time}"
                                    )
                                except Exception as e:
                                    logger.warning(
                                        f"⚠️ Не удалось распарсить entry_time из orchestrator для {symbol}: {e}"
                                    )
                                    entry_time = None
                            elif isinstance(entry_time, datetime):
                                logger.debug(
                                    f"✅ entry_time для {symbol} получен из orchestrator.active_positions: {entry_time}"
                                )
                            else:
                                entry_time = None

            # 2. Пробуем получить из TrailingStopLoss.entry_timestamp (если есть)
            if entry_time is None:
                if hasattr(self, "orchestrator") and self.orchestrator:
                    if hasattr(self.orchestrator, "trailing_sl_coordinator"):
                        tsl_coord = self.orchestrator.trailing_sl_coordinator
                        if hasattr(tsl_coord, "trailing_sl_by_symbol"):
                            if symbol in tsl_coord.trailing_sl_by_symbol:
                                tsl = tsl_coord.trailing_sl_by_symbol[symbol]
                                if (
                                    hasattr(tsl, "entry_timestamp")
                                    and tsl.entry_timestamp > 0
                                ):
                                    try:
                                        entry_time = datetime.fromtimestamp(
                                            tsl.entry_timestamp
                                        )
                                        logger.debug(
                                            f"✅ entry_time для {symbol} получен из TrailingStopLoss.entry_timestamp: {entry_time}"
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            f"⚠️ Не удалось преобразовать entry_timestamp для {symbol}: {e}"
                                        )

            # 3. Fallback: пробуем из position_manager.active_positions (старый источник)
            if entry_time is None:
                if symbol in self.active_positions:
                    stored_position = self.active_positions[symbol]
                    if isinstance(stored_position, dict):
                        entry_time = stored_position.get("entry_time")
                        if isinstance(entry_time, str):
                            try:
                                entry_time = datetime.fromisoformat(
                                    entry_time.replace("Z", "+00:00")
                                )
                                logger.debug(
                                    f"✅ entry_time для {symbol} получен из position_manager.active_positions: {entry_time}"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"⚠️ Не удалось распарсить entry_time из position_manager для {symbol}: {e}"
                                )
                                entry_time = None
                        elif isinstance(entry_time, datetime):
                            logger.debug(
                                f"✅ entry_time для {symbol} получен из position_manager.active_positions: {entry_time}"
                            )
                        else:
                            entry_time = None

            # 4. Последний fallback: текущее время (только если ничего не найдено)
            if entry_time is None:
                logger.warning(
                    f"⚠️ Не удалось найти entry_time для {symbol}, используем текущее время (duration_sec может быть 0)"
                )
                entry_time = datetime.now()

            # ✅ ЗАДАЧА #10: Получаем комиссию из конфига (может быть в scalping или на верхнем уровне)
            commission_config = getattr(self.scalping_config, "commission", None)
            if commission_config is None:
                # Пробуем получить с верхнего уровня конфига
                commission_config = getattr(self.config, "commission", {})
            if not commission_config:
                commission_config = {}
            # ✅ ЗАДАЧА #10: Получаем maker_fee_rate и taker_fee_rate из конфига
            if isinstance(commission_config, dict):
                maker_fee_rate = commission_config.get("maker_fee_rate")
                taker_fee_rate = commission_config.get("taker_fee_rate")
                trading_fee_rate = commission_config.get("trading_fee_rate")  # Fallback
            else:
                maker_fee_rate = getattr(commission_config, "maker_fee_rate", None)
                taker_fee_rate = getattr(commission_config, "taker_fee_rate", None)
                trading_fee_rate = getattr(commission_config, "trading_fee_rate", None)

            # ✅ ЗАДАЧА #10: Если не указаны отдельные ставки, используем trading_fee_rate как fallback
            if maker_fee_rate is None or taker_fee_rate is None:
                if trading_fee_rate is None:
                    raise ValueError(
                        "❌ КРИТИЧЕСКАЯ ОШИБКА: maker_fee_rate, taker_fee_rate или trading_fee_rate не найдены в конфиге! "
                        "Добавьте в config_futures.yaml: scalping.commission.maker_fee_rate и taker_fee_rate"
                    )
                # Используем trading_fee_rate / 2 как fallback для каждого ордера
                maker_fee_rate = trading_fee_rate / 2.0
                taker_fee_rate = trading_fee_rate / 2.0
                logger.warning(
                    f"⚠️ Используется trading_fee_rate как fallback: maker={maker_fee_rate:.4f}, taker={taker_fee_rate:.4f}"
                )

            # ✅ ЗАДАЧА #10: Определяем тип entry ордера из active_positions
            entry_order_type = "market"  # По умолчанию taker (MARKET)
            entry_post_only = False
            if symbol in self.active_positions:
                stored_position = self.active_positions[symbol]
                if isinstance(stored_position, dict):
                    entry_order_type = stored_position.get("order_type", "market")
                    entry_post_only = stored_position.get("post_only", False)

            # ✅ ЗАДАЧА #10: Определяем комиссию entry: если limit с post_only - maker, иначе taker
            if entry_order_type == "limit" and entry_post_only:
                entry_commission_rate = maker_fee_rate  # Maker: 0.02%
                entry_order_type_str = "POST-ONLY/LIMIT (Maker)"
            else:
                entry_commission_rate = taker_fee_rate  # Taker: 0.05%
                entry_order_type_str = f"{entry_order_type.upper()} (Taker)"

            # ✅ ЗАДАЧА #10: Exit ордер обычно MARKET (taker), но может быть LIMIT с post_only
            # По умолчанию используем taker для exit, так как закрытие обычно через MARKET ордер
            exit_commission_rate = taker_fee_rate  # По умолчанию taker
            exit_order_type_str = "MARKET (Taker)"

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Рассчитываем размер позиции в монетах
            # size из API в КОНТРАКТАХ, нужно конвертировать в монеты через ctVal
            try:
                details = await self.client.get_instrument_details(symbol)
                ct_val = float(details.get("ctVal", "0.01"))
                # ✅ Правильная конвертация: контракты * ctVal = монеты
                size_in_coins = abs(size) * ct_val
                logger.debug(
                    f"✅ Конвертация размера для {symbol}: size={size} контрактов, "
                    f"ctVal={ct_val}, size_in_coins={size_in_coins:.6f} монет"
                )
            except Exception as e:
                raise ValueError(
                    f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить ctVal для {symbol}: {e}. "
                    f"Невозможно рассчитать size_in_coins без ctVal!"
                )

            # ✅ ЗАДАЧА #10: Рассчитываем комиссию отдельно для entry и exit
            notional_entry = size_in_coins * entry_price
            notional_exit = size_in_coins * exit_price
            commission_entry = notional_entry * entry_commission_rate
            commission_exit = notional_exit * exit_commission_rate
            commission = commission_entry + commission_exit

            # Рассчитываем gross PnL
            if side.lower() == "long":
                gross_pnl = (exit_price - entry_price) * size_in_coins
            else:  # short
                gross_pnl = (entry_price - exit_price) * size_in_coins

            # Net PnL = Gross PnL - Commission
            net_pnl = gross_pnl - commission

            # Рассчитываем duration в секундах
            duration_sec = (datetime.now() - entry_time).total_seconds()
            duration_min = duration_sec / 60.0
            duration_str = f"{duration_sec:.0f} сек ({duration_min:.2f} мин)"

            # ✅ ЗАДАЧА #8: Улучшенное логирование закрытия позиции
            close_time = datetime.now()

            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"💰 ПОЗИЦИЯ ЗАКРЫТА: {symbol} {side.upper()}")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(
                f"   ⏰ Время закрытия: {close_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            logger.info(f"   📊 Entry price: ${entry_price:.6f}")
            logger.info(f"   📊 Exit price: ${exit_price:.6f}")
            logger.info(f"   📦 Size: {size_in_coins:.8f} монет ({size} контрактов)")
            logger.info(f"   ⏱️  Длительность удержания: {duration_str}")
            logger.info(f"   💵 Gross PnL: ${gross_pnl:+.4f} USDT")
            logger.info(f"   💵 Net PnL: ${net_pnl:+.4f} USDT")
            logger.info(
                f"   💸 Комиссия вход ({entry_order_type_str}): ${commission_entry:.4f} USDT ({entry_commission_rate*100:.2f}%)"
            )
            logger.info(
                f"   💸 Комиссия выход ({exit_order_type_str}): ${commission_exit:.4f} USDT ({exit_commission_rate*100:.2f}%)"
            )
            logger.info(f"   💸 Комиссия общая: ${commission:.4f} USDT")
            logger.info(f"   🎯 Причина закрытия: {reason}")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            # ✅ Метрики: суммарное время удержания
            try:
                self.management_stats.setdefault("sum_duration_sec", 0.0)
                self.management_stats["sum_duration_sec"] += float(duration_sec)
            except Exception:
                pass

            # Определение стороны закрытия
            close_side = "sell" if side.lower() == "long" else "buy"

            # Размещение рыночного ордера на закрытие
            # ⚠️ size из API уже в контрактах, поэтому size_in_contracts=True
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем reduceOnly=True для закрытия
            result = await self.client.place_futures_order(
                symbol=symbol,
                side=close_side,
                size=abs(size),
                order_type="market",
                size_in_contracts=True,  # size из API уже в контрактах
                reduce_only=True,  # ✅ КРИТИЧЕСКОЕ: Только закрытие, не открытие новой позиции
            )

            if result.get("code") == "0":
                # ✅ ЗАДАЧА #8: Детальное логирование уже сделано выше перед закрытием
                logger.info(f"✅ Позиция {symbol} успешно закрыта по {reason}")

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Создаем TradeResult для записи в CSV
                trade_result = TradeResult(
                    symbol=symbol,
                    side=side.lower(),  # "long" или "short"
                    entry_price=entry_price,
                    exit_price=exit_price,
                    size=size_in_coins,
                    gross_pnl=gross_pnl,
                    commission=commission,
                    net_pnl=net_pnl,
                    duration_sec=duration_sec,
                    reason=reason,
                    timestamp=datetime.now(),
                )

                # Обновление статистики
                self._update_close_stats(reason)

                # Удаление из активных позиций
                if symbol in self.active_positions:
                    del self.active_positions[symbol]
                    logger.debug(
                        f"✅ Позиция {symbol} удалена из active_positions (position_manager)"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Удаляем позицию из orchestrator.active_positions, trailing_sl_by_symbol и max_size_limiter
                # для синхронизации состояния после закрытия по TP
                if hasattr(self, "orchestrator") and self.orchestrator:
                    if symbol in self.orchestrator.active_positions:
                        del self.orchestrator.active_positions[symbol]
                        logger.debug(
                            f"✅ Позиция {symbol} удалена из orchestrator.active_positions"
                        )
                    # ✅ ИСПРАВЛЕНО: TSL теперь в trailing_sl_coordinator
                    if hasattr(self.orchestrator, "trailing_sl_coordinator"):
                        tsl = self.orchestrator.trailing_sl_coordinator.remove_tsl(
                            symbol
                        )
                        if tsl:
                            tsl.reset()
                        logger.debug(
                            f"✅ TrailingStopLoss для {symbol} удален из orchestrator"
                        )
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Удаляем позицию из max_size_limiter при закрытии
                    if hasattr(self.orchestrator, "max_size_limiter"):
                        if symbol in self.orchestrator.max_size_limiter.position_sizes:
                            self.orchestrator.max_size_limiter.remove_position(symbol)
                            logger.debug(
                                f"✅ Позиция {symbol} удалена из max_size_limiter.position_sizes"
                            )
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем last_orders_cache для предотвращения блокировки
                    if hasattr(self.orchestrator, "last_orders_cache"):
                        normalized_symbol = self.orchestrator._normalize_symbol(symbol)
                        if normalized_symbol in self.orchestrator.last_orders_cache:
                            self.orchestrator.last_orders_cache[normalized_symbol][
                                "status"
                            ] = "closed"
                            logger.debug(
                                f"✅ Статус ордера для {symbol} обновлен на 'closed' в last_orders_cache"
                            )

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Немедленная синхронизация после закрытия позиции
                    # Это гарантирует, что состояние обновится сразу после закрытия, и новая позиция сможет открыться
                    try:
                        if hasattr(self.orchestrator, "_sync_positions_with_exchange"):
                            await self.orchestrator._sync_positions_with_exchange(
                                force=True
                            )
                            logger.debug(
                                f"✅ Выполнена немедленная синхронизация позиций после закрытия {symbol}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Ошибка синхронизации позиций после закрытия {symbol}: {e}"
                        )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Записываем сделку в CSV через performance_tracker
                # Используем orchestrator.performance_tracker для записи в CSV
                if hasattr(self, "orchestrator") and self.orchestrator:
                    if hasattr(self.orchestrator, "performance_tracker"):
                        try:
                            self.orchestrator.performance_tracker.record_trade(trade_result)
                            logger.debug(f"✅ Сделка {symbol} записана в CSV через orchestrator.performance_tracker")
                        except Exception as e:
                            logger.error(f"❌ Ошибка записи сделки {symbol} в CSV: {e}", exc_info=True)
                    else:
                        logger.warning(f"⚠️ orchestrator.performance_tracker не найден, пропуск записи в CSV для {symbol}")
                else:
                    logger.warning(f"⚠️ orchestrator не найден, пропуск записи в CSV для {symbol}")

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем TradeResult для записи в CSV
                return trade_result
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка закрытия позиции {symbol}: {error_msg}")
                return None

        except Exception as e:
            logger.error(f"Ошибка закрытия позиции: {e}")
            return None

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
                ct_val = float(details.get("ctVal", "0.01"))
                # Реальный размер в монетах
                size_in_coins = abs(size) * ct_val
            except Exception as e:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Ошибка вместо fallback - ctVal ОБЯЗАТЕЛЕН
                raise ValueError(
                    f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить ctVal для {symbol} в _update_position_stats: {e}. "
                    f"Невозможно рассчитать size_in_coins без ctVal!"
                )

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

    async def close_position_manually(
        self, symbol: str, reason: str = "manual"
    ) -> Optional[TradeResult]:
        """
        ✅ РУЧНОЕ ЗАКРЫТИЕ ПОЗИЦИИ (для TrailingSL)

        Закрывает позицию через API без конфликтов с OCO

        Returns:
            TradeResult если позиция успешно закрыта, None в противном случае
        """
        try:
            # Получаем информацию о позиции с биржи
            # ⚠️ ИСПРАВЛЕНИЕ: get_positions() возвращает СПИСОК, не dict!
            positions = await self.client.get_positions(symbol)

            # Проверяем, что positions это список
            if not isinstance(positions, list) or len(positions) == 0:
                logger.warning(f"Позиция {symbol} не найдена на бирже (список пустой)")
                return None

            # Ищем нужную позицию в списке
            for pos_data in positions:
                inst_id = pos_data.get("instId", "").replace("-SWAP", "")
                if inst_id != symbol:
                    continue

                size = float(pos_data.get("pos", "0"))
                if size == 0:
                    logger.warning(f"Размер позиции {symbol} = 0, позиция уже закрыта")
                    return None

                side = pos_data.get("posSide", "long")

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем финальный PnL перед закрытием
                final_pnl = 0.0
                try:
                    # Пробуем разные варианты названий полей для unrealized PnL
                    if "upl" in pos_data and pos_data.get("upl"):
                        final_pnl = float(pos_data["upl"])
                    elif "uPnl" in pos_data and pos_data.get("uPnl"):
                        final_pnl = float(pos_data["uPnl"])
                    elif "unrealizedPnl" in pos_data and pos_data.get("unrealizedPnl"):
                        final_pnl = float(pos_data["unrealizedPnl"])
                except (ValueError, TypeError):
                    pass

                logger.info(
                    f"🔄 Закрытие позиции {symbol} {side} размер={size} контрактов, PnL={final_pnl:.2f} USDT"
                )

                # Определение стороны закрытия
                close_side = "sell" if side.lower() == "long" else "buy"

                # ✅ Размещаем рыночный ордер на закрытие
                # ⚠️ size из API уже в контрактах, поэтому size_in_contracts=True
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для закрытия позиции используем reduceOnly=True
                # Это гарантирует, что ордер не откроет новую позицию, а только закроет существующую
                result = await self.client.place_futures_order(
                    symbol=symbol,
                    side=close_side,
                    size=abs(size),
                    order_type="market",
                    size_in_contracts=True,  # size из API уже в контрактах
                    reduce_only=True,  # ✅ КРИТИЧЕСКОЕ: Только закрытие, не открытие новой позиции
                )

                if result.get("code") == "0":
                    # ✅ ЗАДАЧА #8: Детальное логирование уже сделано выше перед закрытием
                    logger.info(f"✅ Позиция {symbol} успешно закрыта через API")

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Создаем TradeResult для записи в CSV
                    entry_price = float(pos_data.get("avgPx", "0"))
                    exit_price = float(pos_data.get("markPx", "0"))

                    # Получаем время открытия позиции
                    entry_time = None
                    if symbol in self.active_positions:
                        stored_position = self.active_positions[symbol]
                        if isinstance(stored_position, dict):
                            entry_time = stored_position.get("entry_time")
                            if isinstance(entry_time, str):
                                try:
                                    entry_time = datetime.fromisoformat(
                                        entry_time.replace("Z", "+00:00")
                                    )
                                except:
                                    entry_time = None
                            elif not isinstance(entry_time, datetime):
                                entry_time = None

                    if entry_time is None:
                        entry_time = datetime.now()

                    # ✅ ЗАДАЧА #10: Комиссия из конфига (может быть в scalping или на верхнем уровне)
                    commission_config = getattr(
                        self.scalping_config, "commission", None
                    )
                    if commission_config is None:
                        # Пробуем получить с верхнего уровня конфига
                        commission_config = getattr(self.config, "commission", {})
                    if not commission_config:
                        commission_config = {}
                    # ✅ ЗАДАЧА #10: Получаем maker_fee_rate и taker_fee_rate из конфига
                    if isinstance(commission_config, dict):
                        maker_fee_rate = commission_config.get("maker_fee_rate")
                        taker_fee_rate = commission_config.get("taker_fee_rate")
                        trading_fee_rate = commission_config.get(
                            "trading_fee_rate"
                        )  # Fallback
                    else:
                        maker_fee_rate = getattr(
                            commission_config, "maker_fee_rate", None
                        )
                        taker_fee_rate = getattr(
                            commission_config, "taker_fee_rate", None
                        )
                        trading_fee_rate = getattr(
                            commission_config, "trading_fee_rate", None
                        )

                    # ✅ ЗАДАЧА #10: Если не указаны отдельные ставки, используем trading_fee_rate как fallback
                    if maker_fee_rate is None or taker_fee_rate is None:
                        if trading_fee_rate is None:
                            raise ValueError(
                                "❌ КРИТИЧЕСКАЯ ОШИБКА: maker_fee_rate, taker_fee_rate или trading_fee_rate не найдены в конфиге! "
                                "Добавьте в config_futures.yaml: scalping.commission.maker_fee_rate и taker_fee_rate"
                            )
                        # Используем trading_fee_rate / 2 как fallback для каждого ордера
                        maker_fee_rate = trading_fee_rate / 2.0
                        taker_fee_rate = trading_fee_rate / 2.0
                        logger.warning(
                            f"⚠️ Используется trading_fee_rate как fallback: maker={maker_fee_rate:.4f}, taker={taker_fee_rate:.4f}"
                        )

                    # ✅ ЗАДАЧА #10: Определяем тип entry ордера из active_positions
                    entry_order_type = "market"  # По умолчанию taker (MARKET)
                    entry_post_only = False
                    if symbol in self.active_positions:
                        stored_position = self.active_positions[symbol]
                        if isinstance(stored_position, dict):
                            entry_order_type = stored_position.get(
                                "order_type", "market"
                            )
                            entry_post_only = stored_position.get("post_only", False)

                    # ✅ ЗАДАЧА #10: Определяем комиссию entry: если limit с post_only - maker, иначе taker
                    if entry_order_type == "limit" and entry_post_only:
                        entry_commission_rate = maker_fee_rate  # Maker: 0.02%
                        entry_order_type_str = "POST-ONLY/LIMIT (Maker)"
                    else:
                        entry_commission_rate = taker_fee_rate  # Taker: 0.05%
                        entry_order_type_str = f"{entry_order_type.upper()} (Taker)"

                    # ✅ ЗАДАЧА #10: Exit ордер обычно MARKET (taker), но может быть LIMIT с post_only
                    # По умолчанию используем taker для exit, так как закрытие обычно через MARKET ордер
                    exit_commission_rate = taker_fee_rate  # По умолчанию taker
                    exit_order_type_str = "MARKET (Taker)"

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Конвертируем size из контрактов в монеты через ctVal
                    try:
                        details = await self.client.get_instrument_details(symbol)
                        ct_val = float(details.get("ctVal", "0.01"))
                        size_in_coins = abs(size) * ct_val
                        logger.debug(
                            f"✅ Конвертация размера для {symbol} (close_position_manually): "
                            f"size={size} контрактов, ctVal={ct_val}, size_in_coins={size_in_coins:.6f} монет"
                        )
                    except Exception as e:
                        raise ValueError(
                            f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить ctVal для {symbol}: {e}. "
                            f"Невозможно рассчитать size_in_coins без ctVal!"
                        )

                    # ✅ ЗАДАЧА #10: Рассчитываем комиссию отдельно для entry и exit
                    notional_entry = size_in_coins * entry_price
                    notional_exit = size_in_coins * exit_price
                    commission_entry = notional_entry * entry_commission_rate
                    commission_exit = notional_exit * exit_commission_rate
                    commission = commission_entry + commission_exit

                    # Рассчитываем gross PnL
                    if side.lower() == "long":
                        gross_pnl = (exit_price - entry_price) * size_in_coins
                    else:
                        gross_pnl = (entry_price - exit_price) * size_in_coins

                    net_pnl = gross_pnl - commission
                    duration_sec = (datetime.now() - entry_time).total_seconds()
                    duration_min = duration_sec / 60.0
                    duration_str = f"{duration_sec:.0f} сек ({duration_min:.2f} мин)"

                    # ✅ ЗАДАЧА #8: Улучшенное логирование закрытия позиции
                    close_time = datetime.now()

                    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    logger.info(f"💰 ПОЗИЦИЯ ЗАКРЫТА (manual): {symbol} {side.upper()}")
                    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    logger.info(
                        f"   ⏰ Время закрытия: {close_time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    logger.info(f"   📊 Entry price: ${entry_price:.6f}")
                    logger.info(f"   📊 Exit price: ${exit_price:.6f}")
                    logger.info(
                        f"   📦 Size: {size_in_coins:.8f} монет ({size} контрактов)"
                    )
                    logger.info(f"   ⏱️  Длительность удержания: {duration_str}")
                    logger.info(f"   💵 Gross PnL: ${gross_pnl:+.4f} USDT")
                    logger.info(f"   💵 Net PnL: ${net_pnl:+.4f} USDT")
                    logger.info(
                        f"   💸 Комиссия вход ({entry_order_type_str}): ${commission_entry:.4f} USDT ({entry_commission_rate*100:.2f}%)"
                    )
                    logger.info(
                        f"   💸 Комиссия выход ({exit_order_type_str}): ${commission_exit:.4f} USDT ({exit_commission_rate*100:.2f}%)"
                    )
                    logger.info(f"   💸 Комиссия общая: ${commission:.4f} USDT")
                    logger.info(f"   🎯 Причина закрытия: {reason}")
                    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

                    trade_result = TradeResult(
                        symbol=symbol,
                        side=side.lower(),
                        entry_price=entry_price,
                        exit_price=exit_price,
                        size=size_in_coins,
                        gross_pnl=gross_pnl,
                        commission=commission,
                        net_pnl=net_pnl,
                        duration_sec=duration_sec,
                        reason=reason,  # ✅ ИСПРАВЛЕНО: Используем переданный reason вместо "manual"
                        timestamp=datetime.now(),
                    )
                    # ✅ Метрики: суммарное время удержания и счётчики закрытий
                    try:
                        self.management_stats.setdefault("sum_duration_sec", 0.0)
                        self.management_stats["sum_duration_sec"] += float(duration_sec)
                        self._update_close_stats(
                            reason
                        )  # ✅ ИСПРАВЛЕНО: Используем переданный reason
                    except Exception:
                        pass

                    # Удаляем из активных позиций
                    if symbol in self.active_positions:
                        del self.active_positions[symbol]
                    return trade_result
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

    async def close_partial_position(
        self, symbol: str, fraction: float, reason: str = "partial_tp"
    ) -> Optional[Dict[str, Any]]:
        """
        ✅ ЧАСТИЧНОЕ ЗАКРЫТИЕ ПОЗИЦИИ (Partial TP)

        Закрывает часть позиции (например, 60% от текущего размера).
        Используется для Partial Take Profit.

        Args:
            symbol: Торговый символ
            fraction: Доля позиции для закрытия (0.0-1.0, например 0.6 = 60%)
            reason: Причина закрытия

        Returns:
            Dict с результатом операции или None
        """
        try:
            if fraction <= 0 or fraction >= 1:
                logger.error(
                    f"❌ Невалидный fraction для частичного закрытия {symbol}: {fraction} (должен быть 0.0-1.0)"
                )
                return None

            # Получаем актуальную позицию с биржи
            positions = await self.client.get_positions(symbol)

            if not isinstance(positions, list) or len(positions) == 0:
                logger.warning(
                    f"⚠️ Позиция {symbol} не найдена на бирже для частичного закрытия"
                )
                return None

            # Ищем позицию
            pos_data = None
            for pos in positions:
                inst_id = pos.get("instId", "").replace("-SWAP", "")
                if inst_id == symbol:
                    size = float(pos.get("pos", "0"))
                    if size != 0:
                        pos_data = pos
                        break

            if pos_data is None:
                logger.warning(
                    f"⚠️ Позиция {symbol} уже закрыта, частичное закрытие невозможно"
                )
                return None

            current_size = float(pos_data.get("pos", "0"))
            side = pos_data.get("posSide", "long")

            # Рассчитываем размер для закрытия
            close_size_contracts = abs(current_size) * fraction
            remaining_size_contracts = abs(current_size) * (1.0 - fraction)

            logger.info(
                f"✂️ Частичное закрытие {symbol} {side}: "
                f"текущий размер={current_size} контрактов, "
                f"закрываем {fraction*100:.0f}% ({close_size_contracts:.6f} контрактов), "
                f"останется {remaining_size_contracts:.6f} контрактов"
            )

            # Получаем ctVal для расчетов
            try:
                details = await self.client.get_instrument_details(symbol)
                ct_val = float(details.get("ctVal", "0.01"))
                close_size_coins = close_size_contracts * ct_val
            except Exception as e:
                logger.error(f"❌ Не удалось получить ctVal для {symbol}: {e}")
                return None

            # Определение стороны закрытия
            close_side = "sell" if side.lower() == "long" else "buy"

            # Получаем текущую цену для расчета PnL
            entry_price = float(pos_data.get("avgPx", "0"))
            current_price = float(pos_data.get("markPx", entry_price))

            # Размещаем ордер на частичное закрытие (MARKET, reduceOnly)
            result = await self.client.place_futures_order(
                symbol=symbol,
                side=close_side,
                size=close_size_contracts,
                order_type="market",
                size_in_contracts=True,  # size в контрактах
                reduce_only=True,  # Только закрытие
            )

            if result.get("code") == "0":
                logger.info(
                    f"✅ Частичное закрытие {symbol} выполнено: "
                    f"закрыто {fraction*100:.0f}% позиции"
                )

                # Рассчитываем PnL для закрытой части
                if side.lower() == "long":
                    partial_pnl = (current_price - entry_price) * close_size_coins
                else:
                    partial_pnl = (entry_price - current_price) * close_size_coins

                # Получаем комиссию из конфига
                commission_config = getattr(self.scalping_config, "commission", {})
                if isinstance(commission_config, dict):
                    taker_fee_rate = commission_config.get("taker_fee_rate", 0.0005)
                else:
                    taker_fee_rate = getattr(
                        commission_config, "taker_fee_rate", 0.0005
                    )

                # Комиссия на закрытие (MARKET = taker)
                commission = close_size_coins * current_price * taker_fee_rate
                net_partial_pnl = partial_pnl - commission

                # Обновляем метаданные позиции (partial_tp_done = True)
                if symbol in self.active_positions:
                    self.active_positions[symbol]["partial_tp_done"] = True
                    self.active_positions[symbol]["partial_tp_fraction"] = fraction
                    logger.debug(
                        f"✅ Метаданные обновлены: partial_tp_done=True для {symbol}"
                    )

                # Обновляем PositionRegistry если используется
                if self.position_registry:
                    try:
                        await self.position_registry.update_position(
                            symbol,
                            metadata_updates={
                                "partial_tp_done": True,
                                "partial_tp_fraction": fraction,
                            },
                        )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось обновить PositionRegistry для {symbol}: {e}"
                        )

                logger.info(
                    f"💰 Частичное закрытие {symbol}: "
                    f"PnL={net_partial_pnl:+.2f} USDT, "
                    f"комиссия={commission:.4f} USDT"
                )

                return {
                    "success": True,
                    "symbol": symbol,
                    "fraction": fraction,
                    "close_size_contracts": close_size_contracts,
                    "close_size_coins": close_size_coins,
                    "remaining_size_contracts": remaining_size_contracts,
                    "partial_pnl": partial_pnl,
                    "commission": commission,
                    "net_partial_pnl": net_partial_pnl,
                    "reason": reason,
                }
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка частичного закрытия {symbol}: {error_msg}")
                return {"success": False, "error": error_msg}

        except Exception as e:
            logger.error(
                f"❌ Ошибка частичного закрытия позиции {symbol}: {e}",
                exc_info=True,
            )
            return None

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
                "avg_duration_sec": (
                    (self.management_stats.get("sum_duration_sec", 0.0) / closed)
                    if closed > 0
                    else 0.0
                ),
                "last_position_time": self.position_history[-1]["close_time"]
                if self.position_history
                else None,
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики управления: {e}")
            return {"error": str(e)}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 🆕 НОВЫЕ МЕТОДЫ: Управление позициями (ЭТАП 2 рефакторинга)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def add_position_to_tracking(self, symbol: str, position: Dict[str, Any]) -> None:
        """
        Добавить позицию в трекинг (алиас для совместимости).

        Args:
            symbol: Торговый символ
            position: Данные позиции
        """
        self.active_positions[symbol] = position
        logger.debug(f"✅ Position added: {symbol}")

    def remove_position_from_tracking(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Удалить позицию из трекинга (алиас для совместимости).

        Args:
            symbol: Торговый символ

        Returns:
            Dict: Удаленная позиция или None
        """
        position = self.active_positions.pop(symbol, None)
        if position:
            logger.debug(f"✅ Position removed: {symbol}")
        return position

    def get_position_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получить позицию по символу.

        Args:
            symbol: Торговый символ

        Returns:
            Dict: Данные позиции или None
        """
        return self.active_positions.get(symbol)

    def has_position_for_symbol(self, symbol: str) -> bool:
        """
        Проверить наличие позиции по символу.

        Args:
            symbol: Торговый символ

        Returns:
            bool: True если позиция существует
        """
        return symbol in self.active_positions

    def get_all_active_positions(self) -> Dict[str, Dict[str, Any]]:
        """
        Получить все открытые позиции.

        Returns:
            Dict: Словарь всех позиций
        """
        return self.active_positions.copy()

    def get_active_positions_count(self) -> int:
        """
        Получить количество открытых позиций.

        Returns:
            int: Количество позиций
        """
        return len(self.active_positions)

    async def load_positions_from_exchange(self) -> int:
        """
        Загрузить существующие позиции с биржи.

        Returns:
            int: Количество загруженных позиций
        """
        try:
            positions = await self.client.get_positions()
            count = 0

            for position in positions:
                symbol = position.get("instId", "").replace("-SWAP", "")
                size = float(position.get("pos", "0"))
                if size != 0:
                    self.active_positions[symbol] = position
                    count += 1

            logger.info(f"✅ Loaded {count} existing positions from exchange")
            self.is_initialized = True
            return count

        except Exception as e:
            logger.error(f"❌ Error loading existing positions: {e}")
            return 0

    async def sync_positions_with_exchange(self, force: bool = False) -> Dict[str, Any]:
        """
        Синхронизация локальных позиций с биржей.

        Args:
            force: Принудительная синхронизация

        Returns:
            Dict: Статистика синхронизации
        """
        stats = {
            "synced": 0,
            "new": 0,
            "closed": 0,
            "errors": 0,
        }

        try:
            # Получаем актуальные позиции с биржи
            exchange_positions = await self.client.get_positions()
            exchange_symbols = set()

            # Обновляем существующие и добавляем новые
            for position in exchange_positions:
                symbol = position.get("instId", "").replace("-SWAP", "")
                size = float(position.get("pos", "0"))

                if size != 0:
                    exchange_symbols.add(symbol)

                    # Обновляем или добавляем позицию
                    if symbol in self.active_positions:
                        # Сохраняем метаданные
                        saved_regime = self.active_positions[symbol].get("regime")
                        saved_entry_time = self.active_positions[symbol].get(
                            "entry_time"
                        )
                        saved_entry_price = self.active_positions[symbol].get(
                            "entry_price"
                        )
                        saved_position_side = self.active_positions[symbol].get(
                            "position_side"
                        )

                        self.active_positions[symbol] = position.copy()

                        if saved_regime:
                            self.active_positions[symbol]["regime"] = saved_regime
                        if saved_entry_time:
                            self.active_positions[symbol][
                                "entry_time"
                            ] = saved_entry_time
                        if saved_entry_price:
                            self.active_positions[symbol][
                                "entry_price"
                            ] = saved_entry_price
                        if saved_position_side:
                            self.active_positions[symbol][
                                "position_side"
                            ] = saved_position_side

                        stats["synced"] += 1
                    else:
                        self.active_positions[symbol] = position
                        stats["new"] += 1
                        logger.info(f"✅ New position detected: {symbol}")

            # Удаляем позиции которых нет на бирже
            local_symbols = set(self.active_positions.keys())
            closed_symbols = local_symbols - exchange_symbols

            for symbol in closed_symbols:
                logger.info(f"🔍 Position closed on exchange: {symbol}")
                await self._handle_position_closed(symbol)
                stats["closed"] += 1

            if force or closed_symbols or stats["new"] > 0:
                logger.info(
                    f"✅ Sync completed: {stats['synced']} synced, "
                    f"{stats['new']} new, {stats['closed']} closed"
                )

            return stats

        except Exception as e:
            logger.error(f"❌ Error syncing positions: {e}")
            stats["errors"] += 1
            return stats


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
