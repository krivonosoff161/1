"""
ExitAnalyzer - Централизованное управление закрытием позиций.

Анализирует позиции и принимает решения о закрытии/продлении для каждого режима.
Использует все ресурсы бота: ADX, Order Flow, MTF, индикаторы.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from ..core.data_registry import DataRegistry
from ..core.position_registry import PositionMetadata, PositionRegistry


class ExitAnalyzer:
    """
    Анализатор закрытия позиций.

    Для каждого режима (trending, ranging, choppy) анализирует позицию и принимает решения:
    - extend_tp: Продлить TP при сильном тренде
    - close: Закрыть позицию
    - protect: Защитить прибыль (trailing stop)
    """

    def __init__(
        self,
        position_registry: PositionRegistry,
        data_registry: DataRegistry,
        exit_decision_logger=None,
        orchestrator=None,  # Orchestrator для доступа к ADX, Order Flow, MTF
        config_manager=None,  # ConfigManager для получения параметров
        signal_generator=None,  # SignalGenerator для получения режима и индикаторов
        signal_locks_ref: Optional[
            Dict[str, asyncio.Lock]
        ] = None,  # ✅ FIX: Race condition
    ):
        """
        Инициализация ExitAnalyzer.

        Args:
            position_registry: Реестр позиций
            data_registry: Реестр данных
            exit_decision_logger: Логгер решений (опционально)
            orchestrator: Orchestrator для доступа к модулям (опционально)
            config_manager: ConfigManager для получения параметров (опционально)
            signal_generator: SignalGenerator для получения режима (опционально)
            signal_locks_ref: Ссылка на словарь блокировок по символам (опционально)
        """
        self.position_registry = position_registry
        self.data_registry = data_registry
        self.exit_decision_logger = exit_decision_logger
        self.orchestrator = orchestrator
        self.config_manager = config_manager
        self.signal_generator = signal_generator

        # ✅ FIX: Используем существующие locks для предотвращения race condition
        self._signal_locks_ref = signal_locks_ref or {}

        # Получаем доступ к модулям через orchestrator
        self.fast_adx = None
        self.order_flow = None
        self.mtf_filter = None
        self.scalping_config = None

        if orchestrator:
            self.fast_adx = getattr(orchestrator, "fast_adx", None)
            self.order_flow = getattr(orchestrator, "order_flow", None)
            if signal_generator:
                # MTF фильтр может быть в signal_generator
                if hasattr(signal_generator, "mtf_filter"):
                    self.mtf_filter = signal_generator.mtf_filter
                elif (
                    hasattr(signal_generator, "filter_manager")
                    and signal_generator.filter_manager
                ):
                    self.mtf_filter = getattr(
                        signal_generator.filter_manager, "mtf_filter", None
                    )

            # Получаем scalping_config из orchestrator
            if hasattr(orchestrator, "scalping_config"):
                self.scalping_config = orchestrator.scalping_config

        logger.info("✅ ExitAnalyzer инициализирован")

    def set_exit_decision_logger(self, exit_decision_logger):
        """Установить ExitDecisionLogger"""
        self.exit_decision_logger = exit_decision_logger
        logger.debug("✅ ExitAnalyzer: ExitDecisionLogger установлен")

    async def analyze_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Проанализировать позицию и принять решение.

        Args:
            symbol: Торговый символ

        Returns:
            Решение о закрытии/продлении или None
        """
        import time

        analysis_start = time.perf_counter()

        # ✅ FIX: Получаем или создаём lock для символа (предотвращение race condition)
        if symbol not in self._signal_locks_ref:
            self._signal_locks_ref[symbol] = asyncio.Lock()

        async with self._signal_locks_ref[symbol]:
            return await self._analyze_position_impl(symbol, analysis_start)

    async def _analyze_position_impl(
        self, symbol: str, analysis_start: float
    ) -> Optional[Dict[str, Any]]:
        """Внутренняя реализация analyze_position под lock."""
        import time

        try:
            # Получаем позицию и метаданные
            position = await self.position_registry.get_position(symbol)
            metadata = await self.position_registry.get_metadata(symbol)

            if not position:
                analysis_time = (time.perf_counter() - analysis_start) * 1000  # мс
                logger.debug(
                    f"ℹ️ ExitAnalyzer: Позиция {symbol} не найдена (за {analysis_time:.2f}ms)"
                )
                return None

            # ✅ DEBUG-лог начала анализа
            logger.debug(f"📊 ExitAnalyzer: Начало анализа позиции {symbol}")

            # Получаем режим рынка
            # ✅ ИСПРАВЛЕНИЕ: Всегда берем актуальный режим из signal_generator, а не из metadata
            # (metadata содержит режим на момент открытия позиции, который может устареть)
            regime = None
            regime_source = None

            # ✅ ПРИОРИТЕТ: Сначала пытаемся получить актуальный режим из signal_generator
            if self.signal_generator:
                try:
                    if (
                        hasattr(self.signal_generator, "regime_managers")
                        and symbol in self.signal_generator.regime_managers
                    ):
                        regime_manager = self.signal_generator.regime_managers[symbol]
                        regime_obj = regime_manager.get_current_regime()
                        if regime_obj:
                            regime = (
                                regime_obj.value.lower()
                                if hasattr(regime_obj, "value")
                                else str(regime_obj).lower()
                            )
                            regime_source = "signal_generator.regime_managers"
                    elif (
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
                            regime_source = "signal_generator.regime_manager"
                except Exception as e:
                    logger.debug(
                        f"⚠️ ExitAnalyzer: Не удалось получить режим из signal_generator: {e}"
                    )

            # Fallback: если не получили из signal_generator, пробуем из DataRegistry
            if not regime:
                regime_data = await self.data_registry.get_regime(symbol)
                if regime_data:
                    if hasattr(regime_data, "regime"):
                        regime = regime_data.regime
                        regime_source = "data_registry"
                    elif isinstance(regime_data, dict):
                        regime = regime_data.get("regime")
                        regime_source = "data_registry_dict"

            # Fallback: если не получили из DataRegistry, пробуем из metadata (старый режим)
            if not regime:
                if metadata and hasattr(metadata, "regime"):
                    regime = metadata.regime
                    regime_source = "metadata"
                elif isinstance(position, dict):
                    regime = position.get("regime")
                    regime_source = "position_dict"

            # Fallback: если ничего не нашли, используем ranging
            if not regime:
                regime = "ranging"
                regime_source = "fallback"

            # ✅ ЛОГИРОВАНИЕ источника режима (INFO для видимости)
            logger.info(
                f"🔍 ExitAnalyzer {symbol}: режим={regime}, источник={regime_source}, "
                f"metadata.regime={getattr(metadata, 'regime', None) if metadata else None}, "
                f"position.regime={position.get('regime') if isinstance(position, dict) else None}"
            )

            # Получаем рыночные данные
            market_data = await self.data_registry.get_market_data(symbol)
            current_price = await self.data_registry.get_price(symbol)

            if not current_price:
                analysis_time = (time.perf_counter() - analysis_start) * 1000  # мс
                logger.warning(
                    f"⚠️ ExitAnalyzer: Нет цены для {symbol} (за {analysis_time:.2f}ms)"
                )
                return None

            # Анализируем в зависимости от режима
            decision = None
            if regime == "trending":
                decision = await self._generate_exit_for_trending(
                    symbol, position, metadata, market_data, current_price
                )
            elif regime == "ranging":
                decision = await self._generate_exit_for_ranging(
                    symbol, position, metadata, market_data, current_price
                )
            elif regime == "choppy":
                decision = await self._generate_exit_for_choppy(
                    symbol, position, metadata, market_data, current_price
                )
            else:
                # Fallback на ranging
                decision = await self._generate_exit_for_ranging(
                    symbol, position, metadata, market_data, current_price
                )

            # ✅ INFO-логи для отслеживания решений
            analysis_time = (time.perf_counter() - analysis_start) * 1000  # мс
            if decision:
                action = decision.get("action", "unknown")
                reason = decision.get("reason", "unknown")
                pnl_pct = decision.get("pnl_pct", 0.0)
                logger.info(
                    f"📊 ExitAnalyzer: Решение для {symbol} (режим={regime}): "
                    f"action={action}, reason={reason}, PnL={pnl_pct:.2f}% (за {analysis_time:.2f}ms)"
                )
            else:
                # Логируем, что решение не принято (hold)
                analysis_time = (time.perf_counter() - analysis_start) * 1000  # мс
                logger.debug(
                    f"📊 ExitAnalyzer: Для {symbol} (режим={regime}) решение не принято за {analysis_time:.2f}ms - удерживаем позицию"
                )

            # Логируем решение в exit_decision_logger (если есть)
            if decision and self.exit_decision_logger:
                try:
                    if hasattr(self.exit_decision_logger, "log_decision"):
                        self.exit_decision_logger.log_decision(
                            symbol, decision, position
                        )
                except Exception as e:
                    logger.debug(f"⚠️ ExitAnalyzer: Ошибка логирования решения: {e}")

            return decision

        except Exception as e:
            analysis_time = (time.perf_counter() - analysis_start) * 1000  # мс
            logger.error(
                f"❌ ExitAnalyzer: Ошибка анализа позиции {symbol} (за {analysis_time:.2f}ms): {e}",
                exc_info=True,
            )
            return None

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    def _calculate_pnl_percent(
        self,
        entry_price: float,
        current_price: float,
        position_side: str,
        include_fees: bool = True,
        entry_time: Optional[datetime] = None,
        position: Optional[Any] = None,
        metadata: Optional[Any] = None,
    ) -> float:
        """
        Расчет PnL% с учетом комиссии.

        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для фьючерсов считаем PnL% от МАРЖИ, а не от цены!
        Биржа показывает PnL% от маржи (с учетом плеча), поэтому наш расчет должен совпадать.

        Args:
            entry_price: Цена входа
            current_price: Текущая цена
            position_side: Направление позиции ("long" или "short")
            include_fees: Учитывать комиссию
            entry_time: Время открытия позиции (опционально, для проверки первых 10 секунд)
            position: Данные позиции (для получения margin и unrealizedPnl)
            metadata: Метаданные позиции (для получения margin и unrealizedPnl)

        Returns:
            PnL% от маржи (с комиссией если include_fees=True и прошло >10 секунд)
        """
        if entry_price == 0:
            return 0.0

        # ✅ ПРИОРИТЕТ 1: Пытаемся получить PnL% от маржи (как на бирже)
        margin_used = None
        unrealized_pnl = None

        # Пробуем получить из position
        if position and isinstance(position, dict):
            try:
                margin_str = position.get("margin") or position.get("imr") or "0"
                if margin_str and str(margin_str).strip() and str(margin_str) != "0":
                    margin_used = float(margin_str)
                upl_str = position.get("upl") or position.get("unrealizedPnl") or "0"
                if upl_str and str(upl_str).strip() and str(upl_str) != "0":
                    unrealized_pnl = float(upl_str)
            except (ValueError, TypeError) as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения margin/upl из position: {e}"
                )

        # Пробуем получить из metadata
        if (margin_used is None or margin_used == 0) and metadata:
            try:
                if hasattr(metadata, "margin") and metadata.margin:
                    margin_used = float(metadata.margin)
                elif hasattr(metadata, "margin_used") and metadata.margin_used:
                    margin_used = float(metadata.margin_used)
                if hasattr(metadata, "unrealized_pnl") and metadata.unrealized_pnl:
                    unrealized_pnl = float(metadata.unrealized_pnl)
            except (ValueError, TypeError) as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения margin/upl из metadata: {e}"
                )

        # Если получили margin и unrealizedPnl - считаем от маржи (как на бирже)
        if margin_used and margin_used > 0 and unrealized_pnl is not None:
            gross_pnl_pct = (unrealized_pnl / margin_used) * 100  # В процентах

            # Учитываем комиссию если нужно
            if include_fees:
                seconds_since_open = 0.0
                if entry_time:
                    try:
                        if isinstance(entry_time, str):
                            entry_time = datetime.fromisoformat(
                                entry_time.replace("Z", "+00:00")
                            )
                        # ✅ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time в UTC
                        if isinstance(entry_time, datetime):
                            if entry_time.tzinfo is None:
                                entry_time = entry_time.replace(tzinfo=timezone.utc)
                            elif entry_time.tzinfo != timezone.utc:
                                entry_time = entry_time.astimezone(timezone.utc)
                        seconds_since_open = (
                            datetime.now(timezone.utc) - entry_time
                        ).total_seconds()
                    except Exception:
                        pass

                if seconds_since_open < 10.0:
                    # В первые 10 секунд не учитываем комиссию
                    logger.debug(
                        f"⏱️ ExitAnalyzer: Позиция открыта {seconds_since_open:.1f} сек назад, "
                        f"комиссия не учитывается (PnL% от маржи={gross_pnl_pct:.4f}%)"
                    )
                    return gross_pnl_pct
                else:
                    # После 10 секунд учитываем комиссию
                    trading_fee_rate = 0.0010  # 0.1% по умолчанию
                    if self.scalping_config:
                        commission_config = getattr(
                            self.scalping_config, "commission", {}
                        )
                        if isinstance(commission_config, dict):
                            trading_fee_rate = commission_config.get(
                                "trading_fee_rate", 0.0010
                            )
                        elif hasattr(commission_config, "trading_fee_rate"):
                            trading_fee_rate = getattr(
                                commission_config, "trading_fee_rate", 0.0010
                            )

                    # Комиссия в процентах от маржи (на круг)
                    commission_pct = trading_fee_rate * 100  # 0.1% = 0.1
                    net_pnl_pct = gross_pnl_pct - commission_pct
                    logger.debug(
                        f"💰 ExitAnalyzer: PnL% от маржи={gross_pnl_pct:.4f}%, "
                        f"комиссия={commission_pct:.4f}%, Net PnL%={net_pnl_pct:.4f}%"
                    )
                    return net_pnl_pct
            else:
                return gross_pnl_pct

        # ✅ FALLBACK: Если не получили margin, считаем от цены (старый метод)
        # Это менее точно, но лучше чем ничего
        logger.debug(
            f"⚠️ ExitAnalyzer: margin/unrealizedPnl не найдены, используем расчет от цены (менее точно)"
        )

        # Базовая прибыль без комиссии (от цены)
        if position_side.lower() == "long":
            gross_profit_pct = (current_price - entry_price) / entry_price * 100
        else:  # short
            gross_profit_pct = (entry_price - current_price) / entry_price * 100

        # Учитываем комиссию если нужно
        if include_fees:
            seconds_since_open = 0.0
            if entry_time:
                try:
                    if isinstance(entry_time, str):
                        entry_time = datetime.fromisoformat(
                            entry_time.replace("Z", "+00:00")
                        )
                    # ✅ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time в UTC
                    if isinstance(entry_time, datetime):
                        if entry_time.tzinfo is None:
                            entry_time = entry_time.replace(tzinfo=timezone.utc)
                        elif entry_time.tzinfo != timezone.utc:
                            entry_time = entry_time.astimezone(timezone.utc)
                    seconds_since_open = (
                        datetime.now(timezone.utc) - entry_time
                    ).total_seconds()
                except Exception:
                    pass

            if seconds_since_open < 10.0:
                logger.debug(
                    f"⏱️ ExitAnalyzer: Позиция открыта {seconds_since_open:.1f} сек назад, "
                    f"комиссия не учитывается (PnL% от цены={gross_profit_pct:.4f}%)"
                )
                return gross_profit_pct
            else:
                trading_fee_rate = 0.0010  # 0.1% по умолчанию
                if self.scalping_config:
                    commission_config = getattr(self.scalping_config, "commission", {})
                    if isinstance(commission_config, dict):
                        trading_fee_rate = commission_config.get(
                            "trading_fee_rate", 0.0010
                        )
                    elif hasattr(commission_config, "trading_fee_rate"):
                        trading_fee_rate = getattr(
                            commission_config, "trading_fee_rate", 0.0010
                        )

                commission_pct = trading_fee_rate * 100
                net_profit_pct = gross_profit_pct - commission_pct
                return net_profit_pct
        else:
            return gross_profit_pct

    def _get_tp_percent(self, symbol: str, regime: str) -> float:
        """
        Получение TP% из конфига по символу и режиму.

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending, ranging, choppy)

        Returns:
            TP% для использования
        """
        tp_percent = 2.4  # Fallback значение

        if self.config_manager:
            try:
                # Пробуем получить TP из symbol_profiles
                symbol_profiles = getattr(self.config_manager, "symbol_profiles", {})
                if symbol in symbol_profiles:
                    symbol_config = symbol_profiles[symbol]
                    if isinstance(symbol_config, dict) and regime in symbol_config:
                        regime_config = symbol_config[regime]
                        if (
                            isinstance(regime_config, dict)
                            and "tp_percent" in regime_config
                        ):
                            return float(regime_config["tp_percent"])

                # Fallback на by_regime
                by_regime = self.config_manager.to_dict(
                    getattr(self.scalping_config, "by_regime", {})
                    if self.scalping_config
                    else {}
                )
                if regime in by_regime:
                    regime_config = by_regime[regime]
                    if (
                        isinstance(regime_config, dict)
                        and "tp_percent" in regime_config
                    ):
                        return float(regime_config["tp_percent"])

                # Fallback на глобальный TP
                if self.scalping_config:
                    tp_percent = getattr(self.scalping_config, "tp_percent", 2.4)
            except Exception as e:
                logger.debug(f"⚠️ ExitAnalyzer: Ошибка получения TP% для {symbol}: {e}")

        return tp_percent

    def _get_big_profit_exit_percent(self, symbol: str) -> float:
        """
        Получение big_profit_exit% из конфига по символу.

        Args:
            symbol: Торговый символ

        Returns:
            big_profit_exit% для использования
        """
        majors = {"BTC-USDT", "ETH-USDT"}
        alts = {"SOL-USDT", "DOGE-USDT", "XRP-USDT"}

        if symbol in majors:
            default_value = 1.5
            config_key = "big_profit_exit_percent_majors"
        elif symbol in alts:
            default_value = 2.0
            config_key = "big_profit_exit_percent_alts"
        else:
            default_value = 1.5  # Fallback
            config_key = "big_profit_exit_percent_majors"

        if self.scalping_config:
            return float(getattr(self.scalping_config, config_key, default_value))

        return default_value

    def _get_time_in_position_minutes(
        self, metadata: Any, position: Any
    ) -> Optional[float]:
        """
        Получение времени в позиции в минутах.

        Args:
            metadata: Метаданные позиции
            position: Данные позиции

        Returns:
            Время в позиции в минутах или None если не удалось определить
        """
        try:
            entry_time = None

            # Приоритет 1: metadata.entry_time
            if metadata and hasattr(metadata, "entry_time") and metadata.entry_time:
                entry_time = metadata.entry_time
                logger.debug(
                    f"✅ ExitAnalyzer: entry_time получен из metadata.entry_time: {entry_time}"
                )
            elif isinstance(metadata, dict) and metadata.get("entry_time"):
                entry_time = metadata.get("entry_time")
                logger.debug(
                    f"✅ ExitAnalyzer: entry_time получен из metadata dict: {entry_time}"
                )

            # Приоритет 2: position.cTime или openTime
            if not entry_time and isinstance(position, dict):
                entry_time = position.get("cTime") or position.get("openTime")
                if entry_time:
                    logger.debug(
                        f"✅ ExitAnalyzer: entry_time получен из position: {entry_time}"
                    )

            if not entry_time:
                logger.debug(
                    f"⚠️ ExitAnalyzer: entry_time не найден (metadata={metadata is not None}, "
                    f"position={isinstance(position, dict)}, "
                    f"metadata.entry_time={getattr(metadata, 'entry_time', None) if metadata else None})"
                )
                return None

            # Конвертируем в datetime если нужно
            if isinstance(entry_time, datetime):
                # ✅ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time в UTC
                if entry_time.tzinfo is None:
                    # Если без timezone, предполагаем что это UTC и добавляем timezone
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                elif entry_time.tzinfo != timezone.utc:
                    # Если в другом timezone, конвертируем в UTC
                    entry_time = entry_time.astimezone(timezone.utc)
                entry_timestamp = entry_time.timestamp()
            elif isinstance(entry_time, str):
                if entry_time.isdigit():
                    # Timestamp в миллисекундах
                    entry_timestamp = int(entry_time) / 1000.0
                else:
                    # ISO формат строки
                    entry_time_obj = datetime.fromisoformat(
                        entry_time.replace("Z", "+00:00")
                    )
                    # Убеждаемся, что в UTC
                    if entry_time_obj.tzinfo is None:
                        entry_time_obj = entry_time_obj.replace(tzinfo=timezone.utc)
                    elif entry_time_obj.tzinfo != timezone.utc:
                        entry_time_obj = entry_time_obj.astimezone(timezone.utc)
                    entry_timestamp = entry_time_obj.timestamp()
            elif isinstance(entry_time, (int, float)):
                # Timestamp (в миллисекундах если > 1000000000000, иначе в секундах)
                entry_timestamp = (
                    float(entry_time) / 1000.0
                    if entry_time > 1000000000000
                    else float(entry_time)
                )
            else:
                return None

            current_timestamp = datetime.now(timezone.utc).timestamp()
            time_since_open = current_timestamp - entry_timestamp

            # ✅ ЗАЩИТА: Если время отрицательное или слишком большое - ошибка расчета
            if time_since_open < 0:
                logger.warning(
                    f"⚠️ ExitAnalyzer: Отрицательное время в позиции: {time_since_open:.1f} сек "
                    f"(entry_timestamp={entry_timestamp}, current_timestamp={current_timestamp})"
                )
                return None

            if time_since_open > 86400 * 7:  # Больше 7 дней - подозрительно
                logger.warning(
                    f"⚠️ ExitAnalyzer: Подозрительно большое время в позиции: {time_since_open/86400:.1f} дней"
                )
                return None

            minutes = time_since_open / 60.0
            return minutes

        except Exception as e:
            logger.debug(
                f"⚠️ ExitAnalyzer: Ошибка расчета времени в позиции: {e}", exc_info=True
            )
            return None

    def _get_max_holding_minutes(self, regime: str) -> float:
        """
        Получение max_holding_minutes из конфига по режиму.

        Args:
            regime: Режим рынка (trending, ranging, choppy)

        Returns:
            max_holding_minutes или 120.0 по умолчанию
        """
        max_holding_minutes = 120.0  # Default 2 часа

        if self.scalping_config:
            try:
                adaptive_regime = getattr(self.scalping_config, "adaptive_regime", {})
                regime_config = None

                if isinstance(adaptive_regime, dict):
                    if regime and regime in adaptive_regime:
                        regime_config = adaptive_regime.get(regime, {})
                    elif "ranging" in adaptive_regime:
                        regime_config = adaptive_regime.get("ranging", {})
                else:
                    if regime and hasattr(adaptive_regime, regime):
                        regime_config = getattr(adaptive_regime, regime)
                    elif hasattr(adaptive_regime, "ranging"):
                        regime_config = getattr(adaptive_regime, "ranging")

                if regime_config:
                    if isinstance(regime_config, dict):
                        max_holding_minutes = float(
                            regime_config.get("max_holding_minutes", 120.0)
                        )
                    else:
                        max_holding_minutes = float(
                            getattr(regime_config, "max_holding_minutes", 120.0)
                        )
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения max_holding_minutes: {e}"
                )

        return max_holding_minutes

    def _get_partial_tp_params(self, regime: str) -> Dict[str, Any]:
        """
        Получение параметров partial_tp из конфига по режиму.

        Args:
            regime: Режим рынка (trending, ranging, choppy)

        Returns:
            Параметры partial_tp {enabled: bool, fraction: float, trigger_percent: float}
        """
        params = {
            "enabled": False,
            "fraction": 0.6,
            "trigger_percent": 0.4,
        }

        if self.scalping_config:
            try:
                partial_tp_config = getattr(self.scalping_config, "partial_tp", {})
                if isinstance(partial_tp_config, dict):
                    params["enabled"] = partial_tp_config.get("enabled", False)
                    params["fraction"] = partial_tp_config.get("fraction", 0.6)
                    params["trigger_percent"] = partial_tp_config.get(
                        "trigger_percent", 0.4
                    )

                    # Пробуем получить параметры по режиму
                    by_regime = partial_tp_config.get("by_regime", {})
                    if regime in by_regime:
                        regime_config = by_regime[regime]
                        if isinstance(regime_config, dict):
                            params["fraction"] = regime_config.get(
                                "fraction", params["fraction"]
                            )
                            params["trigger_percent"] = regime_config.get(
                                "trigger_percent", params["trigger_percent"]
                            )
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения partial_tp параметров: {e}"
                )

        return params

    async def _analyze_trend_strength(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Анализ силы тренда через ADX.

        Args:
            symbol: Торговый символ

        Returns:
            {adx: float, plus_di: float, minus_di: float, trend_strength: float (0-1)} или None
        """
        if not self.fast_adx:
            return None

        try:
            # Получаем ADX значения для символа
            adx_data = self.fast_adx.get_adx(symbol)
            if not adx_data:
                return None

            adx_value = adx_data.get("adx", 0)
            plus_di = adx_data.get("plus_di", 0)
            minus_di = adx_data.get("minus_di", 0)

            # Рассчитываем силу тренда (0-1)
            # ADX > 25 = сильный тренд (нормализуем до 1.0)
            # ADX 20-25 = средний тренд (нормализуем до 0.7)
            # ADX < 20 = слабый тренд (нормализуем до 0.3)
            if adx_value >= 25:
                trend_strength = 1.0
            elif adx_value >= 20:
                trend_strength = 0.7
            else:
                trend_strength = 0.3

            return {
                "adx": adx_value,
                "plus_di": plus_di,
                "minus_di": minus_di,
                "trend_strength": trend_strength,
            }
        except Exception as e:
            logger.debug(f"⚠️ ExitAnalyzer: Ошибка анализа тренда для {symbol}: {e}")
            return None

    async def _check_reversal_signals(self, symbol: str, position_side: str) -> bool:
        """
        Проверка признаков разворота через Order Flow и MTF.

        Args:
            symbol: Торговый символ
            position_side: Направление позиции ("long" или "short")

        Returns:
            True если обнаружен разворот, False если нет
        """
        reversal_detected = False

        # Проверка Order Flow разворота
        if self.order_flow:
            try:
                current_delta = self.order_flow.get_delta()
                avg_delta = self.order_flow.get_avg_delta(periods=10)
                reversal_threshold = 0.15  # 15% изменение delta

                if position_side.lower() == "long":
                    # Для LONG: разворот = delta был положительным и стал отрицательным
                    if (
                        current_delta < -reversal_threshold
                        and avg_delta > reversal_threshold
                    ):
                        reversal_detected = True
                        logger.debug(
                            f"🔄 ExitAnalyzer: Order Flow разворот обнаружен для {symbol} LONG: "
                            f"delta {avg_delta:.3f} → {current_delta:.3f}"
                        )
                elif position_side.lower() == "short":
                    # Для SHORT: разворот = delta был отрицательным и стал положительным
                    if (
                        current_delta > reversal_threshold
                        and avg_delta < -reversal_threshold
                    ):
                        reversal_detected = True
                        logger.debug(
                            f"🔄 ExitAnalyzer: Order Flow разворот обнаружен для {symbol} SHORT: "
                            f"delta {avg_delta:.3f} → {current_delta:.3f}"
                        )
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка проверки Order Flow разворота для {symbol}: {e}"
                )

        # Проверка MTF разворота
        if self.mtf_filter and not reversal_detected:
            try:
                # MTF фильтр может показывать разворот тренда на более высоком таймфрейме
                # Пока упрощенная проверка - можно расширить позже
                pass  # TODO: Реализовать проверку MTF разворота
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка проверки MTF разворота для {symbol}: {e}"
                )

        return reversal_detected

    async def _get_entry_price_and_side(
        self, symbol: str, position: Any, metadata: Any
    ) -> tuple[Optional[float], Optional[str]]:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получение entry_price из множественных источников.

        Приоритет:
        1. metadata.entry_price
        2. position.avgPx (данные с биржи)
        3. PositionRegistry metadata

        Args:
            symbol: Торговый символ
            position: Данные позиции (dict или PositionMetadata)
            metadata: Метаданные позиции

        Returns:
            (entry_price, position_side) или (None, None) если не найдено
        """
        position_side = None
        entry_price = None

        # Приоритет 1: metadata.entry_price
        if metadata and hasattr(metadata, "entry_price") and metadata.entry_price:
            try:
                entry_price = float(metadata.entry_price)
                position_side = getattr(metadata, "position_side", None)
            except (TypeError, ValueError):
                pass

        # Приоритет 2: position.avgPx (данные с биржи)
        if (not entry_price or entry_price == 0) and isinstance(position, dict):
            try:
                avg_px = position.get("avgPx") or position.get("entry_price") or 0
                if avg_px:
                    entry_price = float(avg_px)
                    # Получаем position_side из position если еще не получен
                    if not position_side:
                        pos_side_raw = position.get("posSide", "").lower()
                        if pos_side_raw in ["long", "short"]:
                            position_side = pos_side_raw
                        else:
                            position_side = position.get("position_side")
            except (TypeError, ValueError):
                pass

        # Приоритет 3: Попытка получить из PositionRegistry напрямую
        if (not entry_price or entry_price == 0) and self.position_registry:
            try:
                registry_metadata = await self.position_registry.get_metadata(symbol)
                if registry_metadata:
                    if registry_metadata.entry_price:
                        entry_price = float(registry_metadata.entry_price)
                    if not position_side and registry_metadata.position_side:
                        position_side = registry_metadata.position_side
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Не удалось получить entry_price из PositionRegistry для {symbol}: {e}"
                )

        # Fallback для position_side
        original_position_side = position_side
        if not position_side:
            if (
                metadata
                and hasattr(metadata, "position_side")
                and metadata.position_side
            ):
                position_side = metadata.position_side
            elif isinstance(position, dict):
                pos_side_raw = position.get("posSide", "").lower()
                if pos_side_raw in ["long", "short"]:
                    position_side = pos_side_raw
                else:
                    position_side = position.get("position_side", "long")
                    # ✅ ИСПРАВЛЕНО: Нормализуем position_side перед сравнением
                    if isinstance(position_side, str):
                        position_side = position_side.lower()
                    if position_side == "long":
                        logger.warning(
                            f"⚠️ FALLBACK position_side: Используется 'long' для {symbol} "
                            f"(posSide={pos_side_raw}, position.position_side={position.get('position_side')})"
                        )
            else:
                position_side = "long"  # Последний fallback
                logger.warning(
                    f"⚠️ FALLBACK position_side: Используется 'long' для {symbol} "
                    f"(metadata={metadata is not None}, position={isinstance(position, dict)})"
                )

        return entry_price if entry_price and entry_price > 0 else None, position_side

    async def _check_adaptive_min_holding_for_partial_tp(
        self, symbol: str, metadata: Any, pnl_percent: float, regime: str
    ) -> tuple[bool, str]:
        """
        ✅ Проверка adaptive_min_holding для Partial TP.

        Проверяет, можно ли выполнить частичное закрытие на основе:
        - Времени удержания позиции
        - Адаптивного min_holding на основе прибыли

        Args:
            symbol: Торговый символ
            metadata: Метаданные позиции (PositionMetadata)
            pnl_percent: Текущая прибыль в процентах
            regime: Режим рынка

        Returns:
            (can_close: bool, info: str) - можно ли закрывать и информационное сообщение
        """
        try:
            # Получаем entry_time из метаданных
            entry_time = None
            if metadata and hasattr(metadata, "entry_time"):
                entry_time = metadata.entry_time
                # ✅ ИСПРАВЛЕНИЕ: Нормализуем timezone сразу при получении из metadata
                if isinstance(entry_time, datetime):
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=timezone.utc)
                    elif entry_time.tzinfo != timezone.utc:
                        entry_time = entry_time.astimezone(timezone.utc)
            elif isinstance(metadata, dict):
                entry_time_str = metadata.get("entry_time")
                if entry_time_str:
                    if isinstance(entry_time_str, str):
                        try:
                            entry_time = datetime.fromisoformat(
                                entry_time_str.replace("Z", "+00:00")
                            )
                            # ✅ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time в UTC
                            if entry_time.tzinfo is None:
                                entry_time = entry_time.replace(tzinfo=timezone.utc)
                            elif entry_time.tzinfo != timezone.utc:
                                entry_time = entry_time.astimezone(timezone.utc)
                        except:
                            pass
                    elif isinstance(entry_time_str, datetime):
                        entry_time = entry_time_str
                        # ✅ ИСПРАВЛЕНИЕ: Нормализуем timezone сразу
                        if entry_time.tzinfo is None:
                            entry_time = entry_time.replace(tzinfo=timezone.utc)
                        elif entry_time.tzinfo != timezone.utc:
                            entry_time = entry_time.astimezone(timezone.utc)

            if not entry_time:
                # Если entry_time не найден, разрешаем partial_tp (без проверки времени)
                return True, "entry_time не найден, пропускаем проверку min_holding"

            # ✅ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time в UTC (offset-aware) - финальная проверка
            if isinstance(entry_time, datetime):
                if entry_time.tzinfo is None:
                    # Если entry_time без timezone, добавляем UTC
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                elif entry_time.tzinfo != timezone.utc:
                    # Если entry_time в другом timezone, конвертируем в UTC
                    entry_time = entry_time.astimezone(timezone.utc)

            # Рассчитываем время удержания в минутах
            duration_minutes = (
                datetime.now(timezone.utc) - entry_time
            ).total_seconds() / 60.0

            # Получаем базовый min_holding из конфига по режиму
            min_holding_minutes = None
            if self.config_manager:
                try:
                    regime_params = self.config_manager.get_regime_params(regime)
                    if regime_params and isinstance(regime_params, dict):
                        min_holding_minutes = regime_params.get("min_holding_minutes")
                        if min_holding_minutes is None:
                            # Пробуем получить из scalping_config
                            if self.scalping_config:
                                by_regime = getattr(
                                    self.scalping_config, "by_regime", {}
                                )
                                if regime in by_regime:
                                    regime_config = by_regime[regime]
                                    if isinstance(regime_config, dict):
                                        min_holding_minutes = regime_config.get(
                                            "min_holding_minutes"
                                        )
                except Exception as e:
                    logger.debug(
                        f"⚠️ ExitAnalyzer: Ошибка получения min_holding_minutes для {symbol}: {e}"
                    )

            if min_holding_minutes is None:
                # Если min_holding не указан, разрешаем partial_tp
                return True, "min_holding не указан в конфиге, разрешаем partial_tp"

            # ✅ Получаем параметры adaptive_min_holding из конфига
            adaptive_config = None
            if self.scalping_config:
                try:
                    partial_tp_config = getattr(self.scalping_config, "partial_tp", {})
                    if isinstance(partial_tp_config, dict):
                        adaptive_config = partial_tp_config.get(
                            "adaptive_min_holding", {}
                        )
                        if isinstance(adaptive_config, dict):
                            enabled = adaptive_config.get("enabled", False)
                            if not enabled:
                                # adaptive_min_holding выключен, используем базовый min_holding
                                adaptive_config = None
                except Exception as e:
                    logger.debug(
                        f"⚠️ ExitAnalyzer: Ошибка получения adaptive_min_holding для {symbol}: {e}"
                    )

            # ✅ Применяем adaptive_min_holding на основе прибыли
            actual_min_holding = min_holding_minutes
            if adaptive_config:
                profit_threshold_1 = adaptive_config.get("profit_threshold_1", 1.0)
                profit_threshold_2 = adaptive_config.get("profit_threshold_2", 0.5)
                reduction_factor_1 = adaptive_config.get("reduction_factor_1", 0.5)
                reduction_factor_2 = adaptive_config.get("reduction_factor_2", 0.75)

                if pnl_percent >= profit_threshold_1:
                    # Прибыль >= 1.0% → снижаем min_holding до 50%
                    actual_min_holding = min_holding_minutes * reduction_factor_1
                    logger.debug(
                        f"✅ Adaptive min_holding для {symbol}: прибыль {pnl_percent:.2f}% >= {profit_threshold_1}%, "
                        f"снижаем min_holding с {min_holding_minutes:.1f} до {actual_min_holding:.1f} мин"
                    )
                elif pnl_percent >= profit_threshold_2:
                    # Прибыль >= 0.5% → снижаем min_holding до 75%
                    actual_min_holding = min_holding_minutes * reduction_factor_2
                    logger.debug(
                        f"✅ Adaptive min_holding для {symbol}: прибыль {pnl_percent:.2f}% >= {profit_threshold_2}%, "
                        f"снижаем min_holding с {min_holding_minutes:.1f} до {actual_min_holding:.1f} мин"
                    )

            # Проверяем, прошло ли достаточно времени
            if duration_minutes >= actual_min_holding:
                return (
                    True,
                    f"min_holding пройден: {duration_minutes:.1f} мин >= {actual_min_holding:.1f} мин",
                )
            else:
                return (
                    False,
                    f"min_holding не пройден: {duration_minutes:.1f} мин < {actual_min_holding:.1f} мин",
                )

        except Exception as e:
            logger.error(
                f"❌ ExitAnalyzer: Ошибка проверки adaptive_min_holding для {symbol}: {e}",
                exc_info=True,
            )
            # В случае ошибки разрешаем partial_tp (безопаснее)
            return True, f"ошибка проверки min_holding: {e}, разрешаем partial_tp"

    async def _generate_exit_for_trending(
        self,
        symbol: str,
        position: Any,  # PositionMetadata или dict
        metadata: Any,  # Deprecated, использовать position
        market_data: Optional[Any],
        current_price: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Генерация решения для режима TRENDING.

        Логика:
        - При сильном тренде продлеваем TP
        - При развороте закрываем
        - Защищаем прибыль trailing stop
        - Проверяем TP, big_profit_exit, partial_tp

        Args:
            symbol: Торговый символ
            position: Данные позиции
            metadata: Метаданные позиции
            market_data: Рыночные данные
            current_price: Текущая цена

        Returns:
            Решение {action: str, reason: str, ...} или None
        """
        try:
            # 1. Получаем данные позиции (✅ ИСПОЛЬЗУЕМ ОБЩИЙ МЕТОД)
            entry_price, position_side = await self._get_entry_price_and_side(
                symbol, position, metadata
            )

            if not entry_price or entry_price == 0:
                logger.warning(
                    f"⚠️ ExitAnalyzer TRENDING: Не удалось получить entry_price для {symbol} "
                    f"(metadata={metadata is not None}, position={isinstance(position, dict)})"
                )
                return None

            # Получаем entry_time из metadata для правильного расчета комиссии
            entry_time = None
            if metadata and hasattr(metadata, "entry_time"):
                entry_time = metadata.entry_time
            elif isinstance(metadata, dict):
                entry_time = metadata.get("entry_time")

            # 2. Рассчитываем PnL
            pnl_percent = self._calculate_pnl_percent(
                entry_price,
                current_price,
                position_side,
                include_fees=True,
                entry_time=entry_time,
                position=position,
                metadata=metadata,
            )

            # 3. Проверка TP (Take Profit)
            tp_percent = self._get_tp_percent(symbol, "trending")
            if pnl_percent >= tp_percent:
                # Проверяем силу тренда перед закрытием по TP
                trend_data = await self._analyze_trend_strength(symbol)
                if trend_data and trend_data.get("trend_strength", 0) >= 0.7:
                    # Сильный тренд - продлеваем TP вместо закрытия
                    logger.info(
                        f"📈 ExitAnalyzer TRENDING: TP достигнут ({pnl_percent:.2f}% >= {tp_percent:.2f}%), "
                        f"но тренд сильный (ADX={trend_data.get('adx', 0):.1f}, strength={trend_data.get('trend_strength', 0):.2f}), "
                        f"продлеваем TP для {symbol}"
                    )
                    return {
                        "action": "extend_tp",
                        "reason": "strong_trend_extend_tp",
                        "pnl_pct": pnl_percent,
                        "current_tp": tp_percent,
                        "new_tp": tp_percent * 1.2,  # Продлеваем на 20%
                        "trend_strength": trend_data.get("trend_strength", 0),
                    }
                else:
                    # Слабый тренд - закрываем по TP
                    logger.info(
                        f"🎯 ExitAnalyzer TRENDING: TP достигнут для {symbol}: "
                        f"{pnl_percent:.2f}% >= {tp_percent:.2f}%"
                    )
                    return {
                        "action": "close",
                        "reason": "tp_reached",
                        "pnl_pct": pnl_percent,
                        "tp_percent": tp_percent,
                    }

            # 4. Проверка big_profit_exit
            big_profit_exit_percent = self._get_big_profit_exit_percent(symbol)
            if pnl_percent >= big_profit_exit_percent:
                logger.info(
                    f"💰 ExitAnalyzer TRENDING: Big profit exit достигнут для {symbol}: "
                    f"{pnl_percent:.2f}% >= {big_profit_exit_percent:.2f}%"
                )
                return {
                    "action": "close",
                    "reason": "big_profit_exit",
                    "pnl_pct": pnl_percent,
                    "big_profit_exit_percent": big_profit_exit_percent,
                }

            # 5. Проверка partial_tp с учетом adaptive_min_holding
            partial_tp_params = self._get_partial_tp_params("trending")
            if partial_tp_params.get("enabled", False):
                # ✅ УЛУЧШЕНИЕ #6: Используем оптимизированные триггеры из конфига
                trigger_percent = partial_tp_params.get(
                    "trigger_percent", 0.8
                )  # Обновлено: 0.8% для trending
                if pnl_percent >= trigger_percent:
                    # ✅ Проверяем adaptive_min_holding перед partial_tp
                    (
                        can_partial_close,
                        min_holding_info,
                    ) = await self._check_adaptive_min_holding_for_partial_tp(
                        symbol, metadata, pnl_percent, "trending"
                    )

                    if can_partial_close:
                        fraction = partial_tp_params.get("fraction", 0.6)
                        logger.info(
                            f"📊 ExitAnalyzer TRENDING: Partial TP триггер достигнут для {symbol}: "
                            f"{pnl_percent:.2f}% >= {trigger_percent:.2f}%, закрываем {fraction*100:.0f}% позиции "
                            f"({min_holding_info})"
                        )
                        return {
                            "action": "partial_close",
                            "reason": "partial_tp",
                            "pnl_pct": pnl_percent,
                            "trigger_percent": trigger_percent,
                            "fraction": fraction,
                            "min_holding_info": min_holding_info,
                        }
                    else:
                        logger.debug(
                            f"⏱️ ExitAnalyzer TRENDING: Partial TP триггер достигнут для {symbol}, "
                            f"но min_holding не пройден ({min_holding_info}), ждем..."
                        )
                        # Не закрываем частично, возвращаем hold
                        return {
                            "action": "hold",
                            "reason": "partial_tp_min_holding_wait",
                            "pnl_pct": pnl_percent,
                            "min_holding_info": min_holding_info,
                        }

            # 6. Проверка разворота (Order Flow, MTF)
            reversal_detected = await self._check_reversal_signals(
                symbol, position_side
            )
            if reversal_detected:
                logger.info(
                    f"🔄 ExitAnalyzer TRENDING: Разворот обнаружен для {symbol}, закрываем позицию "
                    f"(profit={pnl_percent:.2f}%)"
                )
                return {
                    "action": "close",
                    "reason": "reversal_detected",
                    "pnl_pct": pnl_percent,
                    "reversal_signal": "order_flow_or_mtf",
                }

            # 7. Если прибыль > 0.5% и тренд сильный - продлеваем TP
            if pnl_percent > 0.5:
                trend_data = await self._analyze_trend_strength(symbol)
                if trend_data and trend_data.get("trend_strength", 0) >= 0.8:
                    logger.debug(
                        f"📈 ExitAnalyzer TRENDING: Прибыль {pnl_percent:.2f}% > 0.5% и сильный тренд "
                        f"(ADX={trend_data.get('adx', 0):.1f}), продлеваем TP для {symbol}"
                    )
                    return {
                        "action": "extend_tp",
                        "reason": "strong_trend_profit",
                        "pnl_pct": pnl_percent,
                        "trend_strength": trend_data.get("trend_strength", 0),
                    }

            # 8. ✅ НОВОЕ: Проверка Max Holding - учитываем время в позиции как фактор анализа
            minutes_in_position = self._get_time_in_position_minutes(metadata, position)
            max_holding_minutes = self._get_max_holding_minutes("trending")

            if (
                minutes_in_position is not None
                and minutes_in_position >= max_holding_minutes
            ):
                # Время превышено - проверяем, есть ли сильные сигналы держать
                trend_data = await self._analyze_trend_strength(symbol)
                trend_strength = (
                    trend_data.get("trend_strength", 0) if trend_data else 0
                )

                # Если сильный тренд (>= 0.7) и прибыль > 0.3% - продлеваем
                if trend_strength >= 0.7 and pnl_percent > 0.3:
                    logger.info(
                        f"⏰ ExitAnalyzer TRENDING: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                        f"но сильный тренд (strength={trend_strength:.2f}) и прибыль {pnl_percent:.2f}% - продлеваем"
                    )
                    return {
                        "action": "extend_tp",
                        "reason": "max_holding_strong_trend",
                        "pnl_pct": pnl_percent,
                        "trend_strength": trend_strength,
                        "minutes_in_position": minutes_in_position,
                    }
                else:
                    # ✅ ИСПРАВЛЕНО: Не закрываем убыточные позиции по max_holding
                    # Позволяем им дойти до SL или восстановиться
                    if pnl_percent < 0:
                        logger.info(
                            f"⏰ ExitAnalyzer TRENDING: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                            f"но позиция в убытке ({pnl_percent:.2f}%) - НЕ закрываем, ждем SL или восстановления"
                        )
                        return {
                            "action": "hold",
                            "reason": "max_holding_exceeded_but_loss_trending",
                            "pnl_pct": pnl_percent,
                            "trend_strength": trend_strength,
                            "minutes_in_position": minutes_in_position,
                        }
                    
                    # Нет сильных сигналов, но позиция в прибыли - закрываем по времени
                    logger.info(
                        f"⏰ ExitAnalyzer TRENDING: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                        f"нет сильных сигналов держать (trend_strength={trend_strength:.2f}, pnl={pnl_percent:.2f}%) - закрываем"
                    )
                    return {
                        "action": "close",
                        "reason": "max_holding_no_signals",
                        "pnl_pct": pnl_percent,
                        "minutes_in_position": minutes_in_position,
                        "max_holding_minutes": max_holding_minutes,
                    }

            # Нет причин для закрытия или продления
            return None

        except Exception as e:
            logger.error(
                f"❌ ExitAnalyzer: Ошибка анализа для {symbol} в режиме TRENDING: {e}",
                exc_info=True,
            )
            return None

    async def _generate_exit_for_ranging(
        self,
        symbol: str,
        position: Any,
        metadata: Any,
        market_data: Optional[Any],
        current_price: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Генерация решения для режима RANGING.

        Логика:
        - Более консервативный подход
        - Закрываем при достижении TP
        - Меньше продлений
        - Проверяем TP, big_profit_exit, partial_tp

        Args:
            symbol: Торговый символ
            position: Данные позиции
            metadata: Метаданные позиции
            market_data: Рыночные данные
            current_price: Текущая цена

        Returns:
            Решение {action: str, reason: str, ...} или None
        """
        try:
            # 1. Получаем данные позиции (✅ ИСПОЛЬЗУЕМ ОБЩИЙ МЕТОД)
            entry_price, position_side = await self._get_entry_price_and_side(
                symbol, position, metadata
            )

            if not entry_price or entry_price == 0:
                logger.warning(
                    f"⚠️ ExitAnalyzer TRENDING: Не удалось получить entry_price для {symbol} "
                    f"(metadata={metadata is not None}, position={isinstance(position, dict)})"
                )
                return None

            # Получаем entry_time из metadata для правильного расчета комиссии
            entry_time = None
            if metadata and hasattr(metadata, "entry_time"):
                entry_time = metadata.entry_time
            elif isinstance(metadata, dict):
                entry_time = metadata.get("entry_time")

            # 2. Рассчитываем PnL
            pnl_percent = self._calculate_pnl_percent(
                entry_price,
                current_price,
                position_side,
                include_fees=True,
                entry_time=entry_time,
                position=position,
                metadata=metadata,
            )

            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для диагностики
            # Рассчитываем gross PnL для сравнения
            if position_side.lower() == "long":
                gross_pnl_pct = (current_price - entry_price) / entry_price * 100
            else:
                gross_pnl_pct = (entry_price - current_price) / entry_price * 100

            # Показываем больше знаков для маленьких значений
            pnl_format = (
                f"{pnl_percent:.4f}" if abs(pnl_percent) < 0.1 else f"{pnl_percent:.2f}"
            )
            gross_format = (
                f"{gross_pnl_pct:.4f}"
                if abs(gross_pnl_pct) < 0.1
                else f"{gross_pnl_pct:.2f}"
            )

            logger.info(
                f"🔍 ExitAnalyzer RANGING {symbol}: entry_price={entry_price:.2f}, "
                f"current_price={current_price:.2f}, side={position_side}, "
                f"Gross PnL%={gross_format}%, Net PnL%={pnl_format}% (с комиссией), entry_time={entry_time}"
            )

            # 3. Проверка TP (Take Profit) - в ranging режиме закрываем сразу
            tp_percent = self._get_tp_percent(symbol, "ranging")
            pnl_format = (
                f"{pnl_percent:.4f}" if abs(pnl_percent) < 0.1 else f"{pnl_percent:.2f}"
            )
            logger.info(
                f"🔍 ExitAnalyzer RANGING {symbol}: TP={tp_percent:.2f}%, "
                f"PnL%={pnl_format}%, достигнут={pnl_percent >= tp_percent}"
            )
            if pnl_percent >= tp_percent:
                logger.info(
                    f"🎯 ExitAnalyzer RANGING: TP достигнут для {symbol}: "
                    f"{pnl_percent:.2f}% >= {tp_percent:.2f}%"
                )
                return {
                    "action": "close",
                    "reason": "tp_reached",
                    "pnl_pct": pnl_percent,
                    "tp_percent": tp_percent,
                }

            # 4. Проверка big_profit_exit
            big_profit_exit_percent = self._get_big_profit_exit_percent(symbol)
            pnl_format = (
                f"{pnl_percent:.4f}" if abs(pnl_percent) < 0.1 else f"{pnl_percent:.2f}"
            )
            logger.info(
                f"🔍 ExitAnalyzer RANGING {symbol}: big_profit_exit={big_profit_exit_percent:.2f}%, "
                f"PnL%={pnl_format}%, достигнут={pnl_percent >= big_profit_exit_percent}"
            )
            if pnl_percent >= big_profit_exit_percent:
                logger.info(
                    f"💰 ExitAnalyzer RANGING: Big profit exit достигнут для {symbol}: "
                    f"{pnl_percent:.2f}% >= {big_profit_exit_percent:.2f}%"
                )
                return {
                    "action": "close",
                    "reason": "big_profit_exit",
                    "pnl_pct": pnl_percent,
                    "big_profit_exit_percent": big_profit_exit_percent,
                }

            # 5. Проверка partial_tp с учетом adaptive_min_holding
            partial_tp_params = self._get_partial_tp_params("ranging")
            logger.info(
                f"🔍 ExitAnalyzer RANGING {symbol}: partial_tp enabled={partial_tp_params.get('enabled', False)}, "
                f"trigger_percent={partial_tp_params.get('trigger_percent', 0.6):.2f}%"
            )
            if partial_tp_params.get("enabled", False):
                trigger_percent = partial_tp_params.get("trigger_percent", 0.6)
                pnl_format = (
                    f"{pnl_percent:.4f}"
                    if abs(pnl_percent) < 0.1
                    else f"{pnl_percent:.2f}"
                )
                logger.info(
                    f"🔍 ExitAnalyzer RANGING {symbol}: partial_tp trigger={trigger_percent:.2f}%, "
                    f"PnL%={pnl_format}%, достигнут={pnl_percent >= trigger_percent}"
                )
                if pnl_percent >= trigger_percent:
                    # ✅ Проверяем adaptive_min_holding перед partial_tp
                    (
                        can_partial_close,
                        min_holding_info,
                    ) = await self._check_adaptive_min_holding_for_partial_tp(
                        symbol, metadata, pnl_percent, "ranging"
                    )

                    if can_partial_close:
                        # ✅ УЛУЧШЕНИЕ #5.2: Адаптивная fraction для Partial TP в зависимости от PnL
                        base_fraction = partial_tp_params.get("fraction", 0.6)
                        if pnl_percent < 1.0:
                            fraction = base_fraction * 0.67  # 40% если PnL < 1.0%
                        elif pnl_percent >= 2.0:
                            fraction = base_fraction * 1.33  # 80% если PnL >= 2.0%
                        else:
                            fraction = base_fraction  # 60% стандарт

                        logger.info(
                            f"📊 ExitAnalyzer RANGING: Partial TP триггер достигнут для {symbol}: "
                            f"{pnl_percent:.2f}% >= {trigger_percent:.2f}%, закрываем {fraction*100:.0f}% позиции "
                            f"({min_holding_info})"
                        )
                        return {
                            "action": "partial_close",
                            "reason": "partial_tp",
                            "pnl_pct": pnl_percent,
                            "trigger_percent": trigger_percent,
                            "fraction": fraction,
                            "min_holding_info": min_holding_info,
                        }
                    else:
                        logger.debug(
                            f"⏱️ ExitAnalyzer RANGING: Partial TP триггер достигнут для {symbol}, "
                            f"но min_holding не пройден ({min_holding_info}), ждем..."
                        )
                        return {
                            "action": "hold",
                            "reason": "partial_tp_min_holding_wait",
                            "pnl_pct": pnl_percent,
                            "min_holding_info": min_holding_info,
                        }

            # 6. Проверка разворота (Order Flow, MTF) - в ranging режиме более строго
            reversal_detected = await self._check_reversal_signals(
                symbol, position_side
            )
            if (
                reversal_detected and pnl_percent > 0.3
            ):  # Закрываем только если есть прибыль
                logger.info(
                    f"🔄 ExitAnalyzer RANGING: Разворот обнаружен для {symbol}, закрываем позицию "
                    f"(profit={pnl_percent:.2f}%)"
                )
                return {
                    "action": "close",
                    "reason": "reversal_detected",
                    "pnl_pct": pnl_percent,
                    "reversal_signal": "order_flow_or_mtf",
                }

            # 7. ✅ НОВОЕ: Проверка Max Holding - учитываем время в позиции как фактор анализа
            logger.debug(
                f"🔍 ExitAnalyzer RANGING {symbol}: Проверка Max Holding - "
                f"metadata={metadata is not None}, position={isinstance(position, dict)}, "
                f"metadata.entry_time={getattr(metadata, 'entry_time', None) if metadata else None}"
            )
            minutes_in_position = self._get_time_in_position_minutes(metadata, position)
            max_holding_minutes = self._get_max_holding_minutes("ranging")
            logger.debug(
                f"🔍 ExitAnalyzer RANGING {symbol}: minutes_in_position={minutes_in_position}, "
                f"max_holding_minutes={max_holding_minutes}"
            )

            # Получаем параметры продления времени
            extend_time_if_profitable = False
            min_profit_for_extension = 0.5
            extension_percent = 100
            try:
                adaptive_regime = getattr(self.scalping_config, "adaptive_regime", {})
                regime_config = None
                if isinstance(adaptive_regime, dict):
                    regime_config = adaptive_regime.get("ranging", {})
                elif hasattr(adaptive_regime, "ranging"):
                    regime_config = getattr(adaptive_regime, "ranging")

                if regime_config:
                    if isinstance(regime_config, dict):
                        extend_time_if_profitable = regime_config.get(
                            "extend_time_if_profitable", False
                        )
                        min_profit_for_extension = regime_config.get(
                            "min_profit_for_extension", 0.5
                        )
                        extension_percent = regime_config.get("extension_percent", 100)
                    else:
                        extend_time_if_profitable = getattr(
                            regime_config, "extend_time_if_profitable", False
                        )
                        min_profit_for_extension = getattr(
                            regime_config, "min_profit_for_extension", 0.5
                        )
                        extension_percent = getattr(
                            regime_config, "extension_percent", 100
                        )
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения extend_time_if_profitable: {e}"
                )

            actual_max_holding = max_holding_minutes
            if extend_time_if_profitable and pnl_percent >= min_profit_for_extension:
                extension_minutes = max_holding_minutes * (extension_percent / 100.0)
                actual_max_holding = max_holding_minutes + extension_minutes

            if (
                minutes_in_position is not None
                and minutes_in_position >= actual_max_holding
            ):
                # ✅ ИСПРАВЛЕНО: Не закрываем убыточные позиции по max_holding
                # Позволяем им дойти до SL или восстановиться
                if pnl_percent < 0:
                    logger.info(
                        f"⏰ ExitAnalyzer RANGING: Время {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин, "
                        f"но позиция в убытке ({pnl_percent:.2f}%) - НЕ закрываем, ждем SL или восстановления"
                    )
                    return {
                        "action": "hold",
                        "reason": "max_holding_exceeded_but_loss",
                        "pnl_pct": pnl_percent,
                        "minutes_in_position": minutes_in_position,
                        "max_holding_minutes": actual_max_holding,
                    }
                
                # Время превышено и позиция в прибыли - закрываем
                logger.info(
                    f"⏰ ExitAnalyzer RANGING: Время {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин "
                    f"(базовое: {max_holding_minutes:.1f} мин), прибыль={pnl_percent:.2f}% - закрываем по времени"
                )
                return {
                    "action": "close",
                    "reason": "max_holding_exceeded",
                    "pnl_pct": pnl_percent,
                    "minutes_in_position": minutes_in_position,
                    "max_holding_minutes": actual_max_holding,
                }
            elif (
                minutes_in_position is not None
                and minutes_in_position >= max_holding_minutes
            ):
                # Базовое время превышено, но есть продление - проверяем прибыль
                if (
                    extend_time_if_profitable
                    and pnl_percent >= min_profit_for_extension
                ):
                    logger.debug(
                        f"⏰ ExitAnalyzer RANGING: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                        f"но прибыль {pnl_percent:.2f}% >= {min_profit_for_extension:.2f}% - продлеваем до {actual_max_holding:.1f} мин"
                    )
                    # Продлеваем, но не закрываем пока
                    return None

            # В ranging режиме не продлеваем TP - более консервативный подход
            time_info = "N/A"
            if minutes_in_position is not None:
                if actual_max_holding is not None:
                    time_info = (
                        f"{minutes_in_position:.1f} мин / {actual_max_holding:.1f} мин"
                    )
                else:
                    time_info = f"{minutes_in_position:.1f} мин"

            logger.info(
                f"🔍 ExitAnalyzer RANGING {symbol}: Нет причин для закрытия - "
                f"TP={tp_percent:.2f}% (не достигнут), big_profit={big_profit_exit_percent:.2f}% (не достигнут), "
                f"partial_tp={partial_tp_params.get('trigger_percent', 0.6):.2f}% (не достигнут), "
                f"текущий PnL%={pnl_percent:.2f}%, время: {time_info}"
            )
            return None

        except Exception as e:
            logger.error(
                f"❌ ExitAnalyzer: Ошибка анализа для {symbol} в режиме RANGING: {e}",
                exc_info=True,
            )
            return None

    async def _generate_exit_for_choppy(
        self,
        symbol: str,
        position: Any,
        metadata: Any,
        market_data: Optional[Any],
        current_price: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Генерация решения для режима CHOPPY.

        Логика:
        - Быстрые закрытия
        - Меньшие TP
        - Защита от флэтов
        - Проверяем TP, big_profit_exit, partial_tp

        Args:
            symbol: Торговый символ
            position: Данные позиции
            metadata: Метаданные позиции
            market_data: Рыночные данные
            current_price: Текущая цена

        Returns:
            Решение {action: str, reason: str, ...} или None
        """
        try:
            # 1. Получаем данные позиции (✅ ИСПОЛЬЗУЕМ ОБЩИЙ МЕТОД)
            entry_price, position_side = await self._get_entry_price_and_side(
                symbol, position, metadata
            )

            if not entry_price or entry_price == 0:
                logger.warning(
                    f"⚠️ ExitAnalyzer TRENDING: Не удалось получить entry_price для {symbol} "
                    f"(metadata={metadata is not None}, position={isinstance(position, dict)})"
                )
                return None

            # Получаем entry_time из metadata для правильного расчета комиссии
            entry_time = None
            if metadata and hasattr(metadata, "entry_time"):
                entry_time = metadata.entry_time
            elif isinstance(metadata, dict):
                entry_time = metadata.get("entry_time")

            # 2. Рассчитываем PnL
            pnl_percent = self._calculate_pnl_percent(
                entry_price,
                current_price,
                position_side,
                include_fees=True,
                entry_time=entry_time,
                position=position,
                metadata=metadata,
            )

            # 3. Проверка TP (Take Profit) - в choppy режиме закрываем сразу (меньший TP)
            tp_percent = self._get_tp_percent(symbol, "choppy")
            if pnl_percent >= tp_percent:
                logger.info(
                    f"🎯 ExitAnalyzer CHOPPY: TP достигнут для {symbol}: "
                    f"{pnl_percent:.2f}% >= {tp_percent:.2f}%"
                )
                return {
                    "action": "close",
                    "reason": "tp_reached",
                    "pnl_pct": pnl_percent,
                    "tp_percent": tp_percent,
                }

            # 4. Проверка big_profit_exit
            big_profit_exit_percent = self._get_big_profit_exit_percent(symbol)
            if pnl_percent >= big_profit_exit_percent:
                logger.info(
                    f"💰 ExitAnalyzer CHOPPY: Big profit exit достигнут для {symbol}: "
                    f"{pnl_percent:.2f}% >= {big_profit_exit_percent:.2f}%"
                )
                return {
                    "action": "close",
                    "reason": "big_profit_exit",
                    "pnl_pct": pnl_percent,
                    "big_profit_exit_percent": big_profit_exit_percent,
                }

            # 5. Проверка partial_tp - в choppy режиме более агрессивно (с учетом adaptive_min_holding)
            # ✅ УЛУЧШЕНИЕ #6: Используем оптимизированные триггеры из конфига
            partial_tp_params = self._get_partial_tp_params("choppy")
            if partial_tp_params.get("enabled", False):
                trigger_percent = partial_tp_params.get(
                    "trigger_percent", 0.6
                )  # Обновлено: 0.6% для choppy
                if pnl_percent >= trigger_percent:
                    # ✅ Проверяем adaptive_min_holding перед partial_tp
                    (
                        can_partial_close,
                        min_holding_info,
                    ) = await self._check_adaptive_min_holding_for_partial_tp(
                        symbol, metadata, pnl_percent, "choppy"
                    )

                    if can_partial_close:
                        # ✅ УЛУЧШЕНИЕ #5.2: Адаптивная fraction для Partial TP в зависимости от PnL
                        base_fraction = partial_tp_params.get("fraction", 0.7)
                        if pnl_percent < 1.0:
                            fraction = base_fraction * 0.67  # ~47% если PnL < 1.0%
                        elif pnl_percent >= 2.0:
                            fraction = base_fraction * 1.33  # ~93% если PnL >= 2.0%
                        else:
                            fraction = base_fraction  # 70% стандарт для choppy

                        logger.info(
                            f"📊 ExitAnalyzer CHOPPY: Partial TP триггер достигнут для {symbol}: "
                            f"{pnl_percent:.2f}% >= {trigger_percent:.2f}%, закрываем {fraction*100:.0f}% позиции "
                            f"({min_holding_info})"
                        )
                        return {
                            "action": "partial_close",
                            "reason": "partial_tp",
                            "pnl_pct": pnl_percent,
                            "trigger_percent": trigger_percent,
                            "fraction": fraction,
                            "min_holding_info": min_holding_info,
                        }
                    else:
                        logger.debug(
                            f"⏱️ ExitAnalyzer CHOPPY: Partial TP триггер достигнут для {symbol}, "
                            f"но min_holding не пройден ({min_holding_info}), ждем..."
                        )
                        return {
                            "action": "hold",
                            "reason": "partial_tp_min_holding_wait",
                            "pnl_pct": pnl_percent,
                            "min_holding_info": min_holding_info,
                        }

            # 6. Проверка разворота (Order Flow, MTF) - в choppy режиме закрываем сразу
            reversal_detected = await self._check_reversal_signals(
                symbol, position_side
            )
            if reversal_detected:
                logger.info(
                    f"🔄 ExitAnalyzer CHOPPY: Разворот обнаружен для {symbol}, закрываем позицию "
                    f"(profit={pnl_percent:.2f}%)"
                )
                return {
                    "action": "close",
                    "reason": "reversal_detected",
                    "pnl_pct": pnl_percent,
                    "reversal_signal": "order_flow_or_mtf",
                }

            # 7. ✅ НОВОЕ: Проверка Max Holding - учитываем время в позиции как фактор анализа
            minutes_in_position = self._get_time_in_position_minutes(metadata, position)
            max_holding_minutes = self._get_max_holding_minutes("choppy")

            if (
                minutes_in_position is not None
                and minutes_in_position >= max_holding_minutes
            ):
                # ✅ ИСПРАВЛЕНО: Не закрываем убыточные позиции по max_holding даже в choppy
                # Позволяем им дойти до SL или восстановиться
                if pnl_percent < 0:
                    logger.info(
                        f"⏰ ExitAnalyzer CHOPPY: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                        f"но позиция в убытке ({pnl_percent:.2f}%) - НЕ закрываем, ждем SL или восстановления"
                    )
                    return {
                        "action": "hold",
                        "reason": "max_holding_exceeded_but_loss_choppy",
                        "pnl_pct": pnl_percent,
                        "minutes_in_position": minutes_in_position,
                        "max_holding_minutes": max_holding_minutes,
                    }
                
                # В choppy режиме закрываем строго по времени, но только если в прибыли
                logger.info(
                    f"⏰ ExitAnalyzer CHOPPY: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                    f"прибыль={pnl_percent:.2f}% - закрываем по времени"
                )
                return {
                    "action": "close",
                    "reason": "max_holding_exceeded_choppy",
                    "pnl_pct": pnl_percent,
                    "minutes_in_position": minutes_in_position,
                    "max_holding_minutes": max_holding_minutes,
                }

            # В choppy режиме не продлеваем TP - быстрые закрытия
            return None

        except Exception as e:
            logger.error(
                f"❌ ExitAnalyzer: Ошибка анализа для {symbol} в режиме CHOPPY: {e}",
                exc_info=True,
            )
            return None

    async def close_position(
        self, symbol: str, reason: str, decision: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Закрыть позицию.

        Args:
            symbol: Торговый символ
            reason: Причина закрытия
            decision: Решение ExitAnalyzer (опционально)

        Returns:
            True если позиция успешно закрыта
        """
        # TODO: Реализовать закрытие позиции через OrderExecutor
        # Пока просто удаляем из реестра
        try:
            await self.position_registry.unregister_position(symbol)
            logger.info(f"✅ ExitAnalyzer: Позиция {symbol} закрыта (reason={reason})")
            return True
        except Exception as e:
            logger.error(f"❌ ExitAnalyzer: Ошибка закрытия позиции {symbol}: {e}")
            return False
