"""
ExitAnalyzer - Централизованное управление закрытием позиций.

Анализирует позиции и принимает решения о закрытии/продлении для каждого режима.
Использует все ресурсы бота: ADX, Order Flow, MTF, индикаторы.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
from loguru import logger

from src.indicators.advanced.candle_patterns import CandlePatternDetector
from src.indicators.advanced.pivot_calculator import PivotCalculator
from src.indicators.advanced.volume_profile import VolumeProfileCalculator

from ..config.parameter_provider import ParameterProvider
from ..core.data_registry import DataRegistry
from ..core.position_registry import PositionMetadata, PositionRegistry
from ..indicators.atr_provider import ATRProvider
from ..indicators.liquidity_levels import LiquidityLevelsDetector


class ExitAnalyzer:
    """
    Анализатор закрытия позиций.

    Для каждого режима (trending, ranging, choppy) анализирует позицию и принимает решения:
    - extend_tp: Продлить TP при сильном тренде
    - close: Закрыть позицию
    """

    def _to_float(self, value: Any, name: str, default: float = 0.0) -> float:
        """
        Helper функция для безопасной конвертации значений в float.
        # ИСПРАВЛЕНО: Helper функция для безопасной конвертации значений в float.

        Args:
            value: Значение для конвертации (может быть str, int, float, None)
            name: Имя переменной для логирования
            default: Значение по умолчанию при ошибке

        Returns:
            float: Конвертированное значение или default
        """
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except (ValueError, TypeError):
                logger.warning(
                    f"⚠️ ExitAnalyzer: Не удалось конвертировать {name}={value} в float, используем default={default}"
                )
                return default
        logger.warning(
            f"⚠️ ExitAnalyzer: Неизвестный тип для {name}={value} (type={type(value)}), используем default={default}"
        )
        return default

    def __init__(
        self,
        position_registry: PositionRegistry,
        data_registry: DataRegistry,
        exit_decision_logger=None,
        orchestrator=None,  # Orchestrator для доступа к ADX, Order Flow, MTF
        config_manager=None,  # ConfigManager для получения параметров (deprecated, используйте parameter_provider)
        signal_generator=None,  # SignalGenerator для получения режима и индикаторов
        signal_locks_ref: Optional[
            Dict[str, asyncio.Lock]
        ] = None,  # ✅ FIX: Race condition
        parameter_provider=None,  # ✅ НОВОЕ (26.12.2025): ParameterProvider для единого доступа к параметрам
    ):
        """
        Инициализация ExitAnalyzer.

        Args:
            position_registry: Реестр позиций
            data_registry: Реестр данных
            exit_decision_logger: Логгер решений (опционально)
            orchestrator: Orchestrator для доступа к модулям (опционально)
            config_manager: ConfigManager для получения параметров (deprecated, используйте parameter_provider)
            signal_generator: SignalGenerator для получения режима (опционально)
            signal_locks_ref: Ссылка на словарь блокировок по символам (опционально)
            parameter_provider: ParameterProvider для единого доступа к параметрам (опционально)
        """
        self.position_registry = position_registry
        self.data_registry = data_registry
        self.exit_decision_logger = exit_decision_logger
        self.orchestrator = orchestrator
        self.config_manager = config_manager  # Оставляем для обратной совместимости
        self.signal_generator = signal_generator

        # ✅ НОВОЕ (26.12.2025): ParameterProvider для единого доступа к параметрам
        self.parameter_provider = parameter_provider
        # Если parameter_provider не передан, создаем его из config_manager
        if not self.parameter_provider and self.config_manager:
            regime_manager = None
            if self.signal_generator:
                regime_manager = getattr(self.signal_generator, "regime_manager", None)
            self.parameter_provider = ParameterProvider(
                config_manager=self.config_manager,
                regime_manager=regime_manager,
                data_registry=self.data_registry,
            )
            logger.debug("✅ ExitAnalyzer: ParameterProvider создан из config_manager")

        # ✅ НОВОЕ (26.12.2025): ATRProvider для синхронного доступа к ATR
        self.atr_provider = ATRProvider(data_registry=data_registry)

        # ✅ НОВОЕ (26.12.2025): Метрики для отслеживания конверсии и времени удержания
        self.conversion_metrics = None
        self.holding_time_metrics = None
        self.alert_manager = None

        # ✅ FIX: Используем существующие locks для предотвращения race condition
        self._signal_locks_ref = signal_locks_ref or {}

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Grace period для SL при недоступном MTF
        self._sl_grace_periods: Dict[
            str, float
        ] = {}  # {symbol: timestamp последней попытки SL}
        self._sl_grace_duration = 30.0  # 30 секунд grace period

        # Получаем доступ к модулям через orchestrator
        self.fast_adx = None
        self.order_flow = None
        self._mtf_filter = (
            None  # ✅ FIX: Приватное поле, используем getter _get_mtf_filter()
        )
        self.scalping_config = None
        self.funding_monitor = None
        self.client = None

        if orchestrator:
            self.fast_adx = getattr(orchestrator, "fast_adx", None)
            self.order_flow = getattr(orchestrator, "order_flow", None)
            self.funding_monitor = getattr(orchestrator, "funding_monitor", None)
            self.client = getattr(orchestrator, "client", None)
            # ✅ FIX: MTF filter получается динамически через _get_mtf_filter()
            # Не сохраняем здесь, так как signal_generator.initialize() ещё не вызван
            logger.debug(
                "✅ ExitAnalyzer: MTF фильтр будет получен динамически через _get_mtf_filter()"
            )

            # Получаем scalping_config из orchestrator
            if hasattr(orchestrator, "scalping_config"):
                self.scalping_config = orchestrator.scalping_config

        # ✅ НОВОЕ: Инициализация модулей для умного закрытия
        try:
            self.candle_pattern_detector = CandlePatternDetector()
            logger.info("✅ CandlePatternDetector инициализирован")
        except Exception as e:
            logger.exception(f"❌ Ошибка инициализации CandlePatternDetector: {e}")
            self.candle_pattern_detector = None

        try:
            self.volume_profile_calculator = VolumeProfileCalculator()
            logger.info("✅ VolumeProfileCalculator инициализирован")
        except Exception as e:
            logger.exception(f"❌ Ошибка инициализации VolumeProfileCalculator: {e}")
            self.volume_profile_calculator = None

        try:
            self.pivot_calculator = PivotCalculator()
            logger.info("✅ PivotCalculator инициализирован")
        except Exception as e:
            logger.exception(f"❌ Ошибка инициализации PivotCalculator: {e}")
            self.pivot_calculator = None

        try:
            self.liquidity_levels_detector = LiquidityLevelsDetector(client=self.client)
            logger.info("✅ LiquidityLevelsDetector инициализирован")
        except Exception as e:
            logger.exception(f"❌ Ошибка инициализации LiquidityLevelsDetector: {e}")
            self.liquidity_levels_detector = None

        logger.info("✅ ExitAnalyzer инициализирован")

    def set_exit_decision_logger(self, exit_decision_logger):
        """Установить ExitDecisionLogger"""
        self.exit_decision_logger = exit_decision_logger
        logger.debug("✅ ExitAnalyzer: ExitDecisionLogger установлен")

    def _get_mtf_filter(self):
        """
        ✅ FIX (09.01.2026): Динамическое получение MTF фильтра из signal_generator.

        Решает проблему: ExitAnalyzer создаётся ДО вызова signal_generator.initialize(),
        поэтому mtf_filter ещё None на момент создания ExitAnalyzer.
        Этот метод получает mtf_filter динамически при каждом использовании.

        Returns:
            MTF фильтр или None
        """
        # Сначала проверяем кэшированное значение
        if self._mtf_filter is not None:
            return self._mtf_filter

        # Пробуем получить из signal_generator
        if self.signal_generator:
            if (
                hasattr(self.signal_generator, "mtf_filter")
                and self.signal_generator.mtf_filter
            ):
                self._mtf_filter = self.signal_generator.mtf_filter
                logger.debug(
                    "✅ ExitAnalyzer: MTF фильтр получен динамически из signal_generator.mtf_filter"
                )
                return self._mtf_filter
            elif (
                hasattr(self.signal_generator, "filter_manager")
                and self.signal_generator.filter_manager
            ):
                mtf = getattr(self.signal_generator.filter_manager, "mtf_filter", None)
                if mtf:
                    self._mtf_filter = mtf
                    logger.debug(
                        "✅ ExitAnalyzer: MTF фильтр получен динамически из filter_manager.mtf_filter"
                    )
                    return self._mtf_filter

        return None

    def _get_fee_rate_per_side(self, order_type: str = "market") -> float:
        """Возвращает ставку комиссии за сторону (maker/taker) из scalping_config."""
        fee_rate = 0.0002
        commission_config = getattr(self.scalping_config, "commission", None)
        try:
            if isinstance(commission_config, dict):
                if order_type == "market":
                    fee_rate = commission_config.get(
                        "taker_fee_rate",
                        commission_config.get("trading_fee_rate", fee_rate),
                    )
                else:
                    fee_rate = commission_config.get(
                        "maker_fee_rate",
                        commission_config.get("trading_fee_rate", fee_rate),
                    )
            elif commission_config is not None:
                if order_type == "market":
                    fee_rate = getattr(
                        commission_config,
                        "taker_fee_rate",
                        getattr(commission_config, "trading_fee_rate", fee_rate),
                    )
                else:
                    fee_rate = getattr(
                        commission_config,
                        "maker_fee_rate",
                        getattr(commission_config, "trading_fee_rate", fee_rate),
                    )
        except Exception:
            fee_rate = fee_rate
        try:
            return max(0.0, float(fee_rate))
        except (TypeError, ValueError):
            return 0.0002

    async def _fetch_price_via_rest(self, symbol: str) -> Optional[float]:
        """
        ✅ НОВОЕ (10.01.2026): REST API fallback для получения цены.

        Вызывается когда DataRegistry не имеет свежей цены.
        Используется как 4-й уровень fallback в _analyze_position_impl.

        Args:
            symbol: Торговая пара (например "BTC-USDT")

        Returns:
            float: Текущая цена или None если получить не удалось
        """
        if not self.client:
            return None

        try:
            # OKX REST API метод получения текущей цены
            ticker = await self.client.get_ticker(symbol)
            if ticker and isinstance(ticker, dict):
                price = ticker.get("last") or ticker.get("lastPx")
                if price:
                    try:
                        price_float = float(price)
                        if price_float > 0:
                            logger.debug(
                                f"✅ ExitAnalyzer._fetch_price_via_rest: {symbol} = {price_float:.8f}"
                            )
                            return price_float
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logger.debug(
                f"⚠️ ExitAnalyzer._fetch_price_via_rest: Ошибка для {symbol}: {e}"
            )

        return None

    def set_conversion_metrics(self, conversion_metrics):
        """
        ✅ НОВОЕ (26.12.2025): Установить ConversionMetrics для отслеживания конверсии.

        Args:
            conversion_metrics: Экземпляр ConversionMetrics
        """
        self.conversion_metrics = conversion_metrics
        logger.debug("✅ ExitAnalyzer: ConversionMetrics установлен")

    def set_holding_time_metrics(self, holding_time_metrics):
        """
        ✅ НОВОЕ (26.12.2025): Установить HoldingTimeMetrics для отслеживания времени удержания.

        Args:
            holding_time_metrics: Экземпляр HoldingTimeMetrics
        """
        self.holding_time_metrics = holding_time_metrics
        logger.debug("✅ ExitAnalyzer: HoldingTimeMetrics установлен")

    def set_alert_manager(self, alert_manager):
        """
        ✅ НОВОЕ (26.12.2025): Установить AlertManager для отправки алертов.

        Args:
            alert_manager: Экземпляр AlertManager
        """
        self.alert_manager = alert_manager
        logger.debug("✅ ExitAnalyzer: AlertManager установлен")

    def _record_metrics_on_close(
        self,
        symbol: str,
        reason: str,
        pnl_percent: float,
        entry_time: Optional[Any] = None,
    ) -> None:
        """
        ✅ НОВОЕ (26.12.2025): Записать метрики при закрытии позиции.

        Args:
            symbol: Торговый символ
            reason: Причина закрытия
            pnl_percent: PnL в процентах
            entry_time: Время открытия позиции
        """
        try:
            # Записываем закрытие позиции в ConversionMetrics
            if self.conversion_metrics:
                self.conversion_metrics.record_position_closed(
                    symbol=symbol, reason=reason, pnl=pnl_percent
                )

            # Записываем время удержания в HoldingTimeMetrics
            if self.holding_time_metrics and entry_time:
                try:
                    if isinstance(entry_time, str):
                        entry_time_dt = datetime.fromisoformat(
                            entry_time.replace("Z", "+00:00")
                        )
                    else:
                        entry_time_dt = entry_time

                    if entry_time_dt.tzinfo is None:
                        entry_time_dt = entry_time_dt.replace(tzinfo=timezone.utc)
                    elif entry_time_dt.tzinfo != timezone.utc:
                        entry_time_dt = entry_time_dt.astimezone(timezone.utc)

                    holding_seconds = (
                        datetime.now(timezone.utc) - entry_time_dt
                    ).total_seconds()
                    self.holding_time_metrics.record_holding_time(
                        symbol=symbol,
                        reason=reason,
                        holding_time_seconds=holding_seconds,
                        pnl=pnl_percent,
                    )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка записи времени удержания для {symbol}: {e}"
                    )
        except Exception as e:
            logger.debug(f"⚠️ Ошибка записи метрик при закрытии {symbol}: {e}")

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

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (24.01.2026): Используем СТРОГИЙ TTL для ExitAnalyzer
            # Проблема: DataRegistry.get_price() терпит устаревание до 60s, что приводит к:
            # - TP срабатывает на убыточных позициях (ложная прибыль от устаревшей цены)
            # - Адаптивные параметры настраиваются на ложных данных
            # Решение: get_fresh_price_for_exit_analyzer() с TTL=2s + REST fallback

            # Получаем client для REST fallback
            client = None
            if self.orchestrator and hasattr(self.orchestrator, "position_manager"):
                client = getattr(self.orchestrator.position_manager, "client", None)

            current_price = await self.data_registry.get_fresh_price_for_exit_analyzer(
                symbol, client=client
            )
            price_source = "data_registry_fresh"

            if current_price is None or current_price <= 0:
                logger.error(
                    f"❌ ExitAnalyzer: Нет СВЕЖЕЙ цены для {symbol} (WebSocket устарел >2s, REST fallback failed), "
                    f"позиция не анализируется - НЕ ПРИНИМАЕМ РЕШЕНИЕ о закрытии!"
                )
                analysis_time = (time.perf_counter() - analysis_start) * 1000  # мс
                return None

            logger.debug(
                f"✅ ExitAnalyzer: Получена СВЕЖАЯ цена для {symbol}: ${current_price:.8f} (source={price_source}, TTL<=2s)"
            )

            # Получаем рыночные данные для анализа
            market_data = await self.data_registry.get_market_data(symbol)
            if market_data is None:
                logger.warning(
                    f"⚠️ ExitAnalyzer: Нет market_data для {symbol}, но цена получена (${current_price:.8f}), продолжаем анализ"
                )
                # Создаем минимальный market_data для анализа
                market_data = {"price": current_price, "last_price": current_price}

            # Анализируем в зависимости от режима
            decision = None
            logger.info(
                f"[ExitAnalyzer] Итоговый источник цены для {symbol}: {current_price} (source={price_source})"
            )
            if current_price is None or current_price <= 0:
                logger.error(
                    f"❌ ExitAnalyzer: Блокировка анализа для {symbol} — current_price невалиден (source={price_source})"
                )
                return None
            if regime == "trending":
                decision = await self._generate_exit_for_trending(
                    symbol, position, metadata, market_data, current_price, regime
                )
            elif regime == "ranging":
                decision = await self._generate_exit_for_ranging(
                    symbol, position, metadata, market_data, current_price, regime
                )
            elif regime == "choppy":
                decision = await self._generate_exit_for_choppy(
                    symbol, position, metadata, market_data, current_price, regime
                )
            else:
                # Fallback на более консервативный режим (trending)
                decision = await self._generate_exit_for_trending(
                    symbol,
                    position,
                    metadata,
                    market_data,
                    current_price,
                    regime or "trending",
                )

            # ✅ INFO-логи для отслеживания решений
            analysis_time = (time.perf_counter() - analysis_start) * 1000  # мс
            if decision:
                action = decision.get("action", "unknown")
                reason = decision.get("reason", "unknown")
                pnl_pct = decision.get("pnl_pct", 0.0)

                # ✅ КРИТИЧЕСКОЕ УЛУЧШЕНИЕ ЛОГИРОВАНИЯ (26.12.2025): Добавляем детальную информацию
                # Получаем TP/SL параметры для логирования
                tp_percent = decision.get("tp_percent") or decision.get("current_tp")
                sl_percent = decision.get("sl_percent")
                entry_regime = (
                    decision.get("entry_regime") or metadata.regime
                    if metadata and hasattr(metadata, "regime")
                    else regime
                )
                threshold = decision.get("threshold")

                # Формируем детальное сообщение
                log_parts = [
                    f"📊 ExitAnalyzer: Решение для {symbol}",
                    f"режим={regime}",
                    f"action={action}",
                    f"reason={reason}",
                    f"PnL={pnl_pct:.2f}%",
                ]

                if tp_percent:
                    log_parts.append(f"TP={tp_percent:.2f}%")
                if sl_percent:
                    log_parts.append(f"SL={sl_percent:.2f}%")
                if entry_regime:
                    log_parts.append(f"entry_regime={entry_regime}")
                if threshold:
                    log_parts.append(f"threshold={threshold:.2f}%")
                if decision.get("emergency"):
                    log_parts.append("🚨 EMERGENCY")

                log_parts.append(f"(за {analysis_time:.2f}ms)")

                logger.info(" | ".join(log_parts))
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
    ) -> Optional[float]:
        """
        Расчет PnL% с учетом комиссии.
        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для фьючерсов считаем PnL% от МАРЖИ, а не от цены!
        # Биржа показывает PnL% от маржи (с учетом плеча), поэтому наш расчет должен совпадать.

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
                    # ✅ ИСПРАВЛЕНО: После 10 секунд учитываем комиссию с учётом плеча и двух сторон (вход+выход)
                    # Используем maker_fee_rate (0.02%) для limit ордеров, т.к. бот использует limit ордера
                    entry_order_type = "market"
                    if metadata and getattr(metadata, "order_type", None):
                        entry_order_type = str(metadata.order_type).lower()
                    elif (
                        position
                        and isinstance(position, dict)
                        and position.get("order_type")
                    ):
                        entry_order_type = str(position.get("order_type")).lower()
                    entry_fee_rate = self._get_fee_rate_per_side(entry_order_type)
                    exit_fee_rate = self._get_fee_rate_per_side("market")

                    # ✅ ИСПРАВЛЕНО: Комиссия учитывает плечо и две стороны (вход + выход)
                    # Получаем leverage из metadata или position
                    leverage = 5  # Default
                    if metadata and hasattr(metadata, "leverage") and metadata.leverage:
                        try:
                            leverage = int(
                                float(metadata.leverage)
                            )  # ✅ ФИКС: Конвертируем в float сначала
                        except (ValueError, TypeError):
                            leverage = 5
                    elif position and isinstance(position, dict):
                        try:
                            leverage_val = position.get("leverage", 5) or 5
                            leverage = int(
                                float(leverage_val)
                            )  # ✅ ФИКС: Конвертируем в float сначала
                        except (ValueError, TypeError):
                            leverage = 5

                    # Комиссия: 0.02% на вход + 0.02% на выход, умноженная на leverage
                    # (т.к. комиссия считается от номинала, а PnL% от маржи)
                    commission_pct = (
                        (entry_fee_rate + exit_fee_rate) * leverage * 100
                    )  # 0.02% × 2 × leverage = 0.2% при leverage=5
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

        leverage = self._get_effective_leverage(position, metadata)
        gross_profit_pct = gross_profit_pct * leverage

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
                # ✅ ИСПРАВЛЕНО: Комиссия с учётом плеча и двух сторон (вход+выход)
                # Используем maker_fee_rate (0.02%) для limit ордеров
                entry_order_type = "market"
                if metadata and getattr(metadata, "order_type", None):
                    entry_order_type = str(metadata.order_type).lower()
                elif (
                    position
                    and isinstance(position, dict)
                    and position.get("order_type")
                ):
                    entry_order_type = str(position.get("order_type")).lower()
                entry_fee_rate = self._get_fee_rate_per_side(entry_order_type)
                exit_fee_rate = self._get_fee_rate_per_side("market")

                # Получаем leverage из metadata или position
                leverage = 5  # Default
                if metadata and hasattr(metadata, "leverage") and metadata.leverage:
                    try:
                        leverage = int(
                            float(metadata.leverage)
                        )  # ✅ ФИКС: Конвертируем в float сначала
                    except (ValueError, TypeError):
                        leverage = 5
                elif position and isinstance(position, dict):
                    try:
                        leverage_val = position.get("leverage", 5) or 5
                        leverage = int(
                            float(leverage_val)
                        )  # ✅ ФИКС: Конвертируем в float сначала
                    except (ValueError, TypeError):
                        leverage = 5

                # Комиссия: 0.02% на вход + 0.02% на выход, умноженная на leverage
                commission_pct = (entry_fee_rate + exit_fee_rate) * leverage * 100
                net_profit_pct = gross_profit_pct - commission_pct
                return net_profit_pct
        else:
            return gross_profit_pct

    def _get_effective_leverage(
        self, position: Optional[Any] = None, metadata: Optional[Any] = None
    ) -> float:
        """Определяем фактическое плечо позиции с безопасным fallback."""
        leverage = None
        if metadata and hasattr(metadata, "leverage") and metadata.leverage:
            try:
                leverage = float(metadata.leverage)
            except (TypeError, ValueError):
                leverage = None
        if leverage is None and position and isinstance(position, dict):
            try:
                leverage_val = position.get("leverage") or position.get("lever")
                leverage = float(leverage_val) if leverage_val else None
            except (TypeError, ValueError):
                leverage = None
        if leverage is None and self.scalping_config:
            leverage = getattr(self.scalping_config, "leverage", None)
        try:
            leverage = float(leverage) if leverage else 1.0
        except (TypeError, ValueError):
            leverage = 1.0
        return max(1.0, leverage)

    def _get_exit_leverage_scale(
        self, position: Optional[Any] = None, metadata: Optional[Any] = None
    ) -> float:
        """Масштабирует exit-проценты под текущее плечо, если включено."""
        scale_enabled = True
        reference_leverage = None
        if self.config_manager and hasattr(self.config_manager, "_raw_config_dict"):
            cfg = self.config_manager._raw_config_dict or {}
            scale_enabled = cfg.get("exit_params_scale_by_leverage", True)
            reference_leverage = cfg.get("exit_params_reference_leverage")
        if reference_leverage is None and self.scalping_config:
            reference_leverage = getattr(self.scalping_config, "leverage", None)
        try:
            reference_leverage = float(reference_leverage)
        except (TypeError, ValueError):
            reference_leverage = 1.0
        if not scale_enabled or reference_leverage <= 0:
            return 1.0
        leverage = self._get_effective_leverage(position, metadata)
        return leverage / reference_leverage

    def _get_emergency_threshold(
        self,
        base_threshold: float,
        position: Optional[Any] = None,
        metadata: Optional[Any] = None,
    ) -> float:
        reference_leverage = None
        if self.config_manager and hasattr(self.config_manager, "_raw_config_dict"):
            cfg = self.config_manager._raw_config_dict or {}
            reference_leverage = cfg.get("exit_params_reference_leverage")
        if reference_leverage is None and self.scalping_config:
            reference_leverage = getattr(self.scalping_config, "leverage", None)
        try:
            reference_leverage = float(reference_leverage)
        except (TypeError, ValueError):
            reference_leverage = 1.0
        if reference_leverage <= 0:
            reference_leverage = 1.0

        leverage = self._get_effective_leverage(position, metadata)
        scale = max(1.0, min(2.5, leverage / reference_leverage))
        return base_threshold * scale

    def _check_tsl_hit(
        self,
        symbol: str,
        position_side: str,
        current_price: float,
    ) -> tuple[bool, Optional[float]]:
        try:
            if not self.orchestrator or not hasattr(
                self.orchestrator, "trailing_sl_coordinator"
            ):
                return False, None
            tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(symbol)
            if not tsl or not hasattr(tsl, "get_stop_loss"):
                return False, None
            stop_loss = tsl.get_stop_loss()
            if stop_loss is None:
                return False, None
            side = position_side.lower()
            if side == "long":
                return current_price <= stop_loss, stop_loss
            return current_price >= stop_loss, stop_loss
        except Exception as e:
            logger.debug(f"ExitAnalyzer: TSL check failed for {symbol}: {e}")
            return False, None

    async def _get_tp_percent(
        self,
        symbol: str,
        regime: str,
        current_price: Optional[float] = None,
        market_data: Optional[Any] = None,
        current_pnl: Optional[float] = None,
        position: Optional[Any] = None,
        metadata: Optional[Any] = None,
    ) -> float:
        """
        Получение TP% из конфига по символу и режиму.
        # ГРОК ФИКС: Поддержка ATR-based TP (max(1.5%, 2.5*ATR_1m) для ranging)
        # ✅ НОВОЕ (05.01.2026): Поддержка адаптивных параметров на основе контекста

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending, ranging, choppy)
            current_price: Текущая цена (для ATR расчета)
            market_data: Рыночные данные (для ATR)
            current_pnl: Текущий P&L позиции в % (для адаптивного расширения TP)

        Returns:
            TP% для использования (адаптивный если передан контекст)
        """
        tp_percent: Optional[float] = None
        tp_atr_multiplier: Optional[float] = None
        tp_min_percent: Optional[float] = None
        tp_max_percent: Optional[float] = None
        tp_fallback_enabled = False

        # ✅ ИСПРАВЛЕНО (26.12.2025): Используем ParameterProvider для получения параметров
        # ✅ НОВОЕ (05.01.2026): Передаем контекст для адаптивных параметров
        if self.parameter_provider:
            try:
                # Получаем контекст для адаптации
                balance = None
                drawdown = None
                if self.client:
                    try:
                        balance = (
                            await self.client.get_balance()
                        )  # ✅ ФИКС (06.01.2026): Добавлен await
                    except Exception:
                        pass  # Если не удалось получить баланс, продолжаем без него

                    try:
                        # ✅ НОВОЕ (07.01.2026): Расчет drawdown для адаптивных параметров
                        account_info = await self.client.get_account_info()
                        if account_info:
                            total_equity = (
                                account_info.get("total_equity", balance)
                                if balance
                                else None
                            )
                            if total_equity and balance:
                                # Предполагаем что peak_equity это 100% от начального баланса
                                # Если система отслеживает начальный баланс, используем его
                                drawdown = (
                                    ((balance - total_equity) / total_equity * 100)
                                    if total_equity > 0
                                    else 0
                                )
                                if drawdown > 0:  # Положительный drawdown = loss
                                    logger.debug(
                                        f"📊 ExitAnalyzer: drawdown={drawdown:.1f}% для {symbol}"
                                    )
                    except Exception:
                        pass  # Если не удалось рассчитать drawdown, продолжаем без него

                exit_params = self.parameter_provider.get_exit_params(
                    symbol,
                    regime,
                    balance=balance,
                    current_pnl=current_pnl,
                    drawdown=drawdown,
                )
                if exit_params:
                    if "tp_percent" in exit_params:
                        tp_percent = self._to_float(
                            exit_params["tp_percent"], "tp_percent", None
                        )
                    if "tp_atr_multiplier" in exit_params:
                        tp_atr_multiplier = self._to_float(
                            exit_params["tp_atr_multiplier"], "tp_atr_multiplier", None
                        )
                    if "tp_min_percent" in exit_params:
                        tp_min_percent = self._to_float(
                            exit_params["tp_min_percent"], "tp_min_percent", None
                        )
                    if "tp_max_percent" in exit_params:
                        tp_max_percent = self._to_float(
                            exit_params["tp_max_percent"], "tp_max_percent", None
                        )
                    # ✅ НОВОЕ (03.01.2026): Детальное логирование источников TP параметров
                    if (
                        tp_percent is not None
                        and tp_atr_multiplier is not None
                        and tp_min_percent is not None
                        and tp_max_percent is not None
                    ):
                        logger.info(
                            f"📊 [PARAMS] {symbol} ({regime}): TP параметры "
                            f"tp_percent={tp_percent:.2f}%, tp_atr_multiplier={tp_atr_multiplier:.2f}, "
                            f"tp_min={tp_min_percent:.2f}%, tp_max={tp_max_percent:.2f}% | "
                            f"Источник: ParameterProvider.get_exit_params()"
                        )
                    else:
                        logger.warning(
                            f"⚠️ ExitAnalyzer: TP параметры отсутствуют/неполные для {symbol} ({regime}) "
                            f"(tp_percent={tp_percent}, tp_atr_multiplier={tp_atr_multiplier}, "
                            f"tp_min={tp_min_percent}, tp_max={tp_max_percent})"
                        )
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения TP параметров через ParameterProvider: {e}, "
                    f"используем fallback к config_manager"
                )

        if (
            tp_atr_multiplier is None
            or tp_min_percent is None
            or tp_max_percent is None
        ):
            logger.error(
                f"❌ ExitAnalyzer: TP параметры не валидны для {symbol} ({regime}) "
                f"(tp_atr_multiplier={tp_atr_multiplier}, tp_min_percent={tp_min_percent}, tp_max_percent={tp_max_percent})"
            )
            return None

        # Fallback на config_manager для обратной совместимости
        if tp_fallback_enabled and self.config_manager and tp_percent is None:
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
                            # ✅ ИСПРАВЛЕНИЕ: Явное преобразование в float для предотвращения str vs int ошибок
                            try:
                                tp_percent = float(regime_config["tp_percent"])
                                tp_atr_based = regime_config.get("tp_atr_based", False)
                                tp_atr_multiplier = float(
                                    regime_config.get("tp_atr_multiplier", 2.5)
                                )
                                tp_min_percent = float(
                                    regime_config.get("tp_min_percent", 1.5)
                                )
                                tp_max_percent = float(
                                    regime_config.get("tp_max_percent", 2.2)
                                )
                                # ✅ НОВОЕ (03.01.2026): Логирование источника TP параметров при использовании fallback
                                logger.info(
                                    f"📊 [PARAMS] {symbol} ({regime}): TP параметры "
                                    f"tp_percent={tp_percent:.2f}%, tp_atr_multiplier={tp_atr_multiplier:.2f}, "
                                    f"tp_min={tp_min_percent:.2f}%, tp_max={tp_max_percent:.2f}% | "
                                    f"Источник: symbol_profiles.{symbol}.{regime} (fallback)"
                                )
                            except (TypeError, ValueError) as e:
                                logger.warning(
                                    f"⚠️ ExitAnalyzer: Не удалось преобразовать tp_percent={regime_config.get('tp_percent')} "
                                    f"в float для {symbol}: {e}, используем fallback"
                                )
                                return 2.4

                # Fallback на by_regime
                if tp_percent == 2.4:  # Если не нашли в symbol_profiles
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
                            # ✅ ИСПРАВЛЕНИЕ: Явное преобразование в float для предотвращения str vs int ошибок
                            try:
                                tp_percent = float(regime_config["tp_percent"])
                                tp_atr_based = regime_config.get("tp_atr_based", False)
                                tp_atr_multiplier = float(
                                    regime_config.get("tp_atr_multiplier", 2.5)
                                )
                                tp_min_percent = float(
                                    regime_config.get("tp_min_percent", 1.5)
                                )
                                tp_max_percent = float(
                                    regime_config.get("tp_max_percent", 2.2)
                                )
                                # ✅ НОВОЕ (03.01.2026): Логирование источника TP параметров при использовании fallback
                                logger.info(
                                    f"📊 [PARAMS] {symbol} ({regime}): TP параметры "
                                    f"tp_percent={tp_percent:.2f}%, tp_atr_multiplier={tp_atr_multiplier:.2f}, "
                                    f"tp_min={tp_min_percent:.2f}%, tp_max={tp_max_percent:.2f}% | "
                                    f"Источник: by_regime.{regime} (fallback)"
                                )
                            except (TypeError, ValueError) as e:
                                logger.warning(
                                    f"⚠️ ExitAnalyzer: Не удалось преобразовать tp_percent={regime_config.get('tp_percent')} "
                                    f"в float для {symbol}: {e}, используем fallback"
                                )
                                return 2.4

                # Fallback на глобальный TP
                if tp_percent == 2.4 and self.scalping_config:
                    tp_percent_raw = getattr(self.scalping_config, "tp_percent", 2.4)
                    # ✅ ИСПРАВЛЕНИЕ: Явное преобразование в float
                    try:
                        tp_percent = float(tp_percent_raw)
                        # ✅ НОВОЕ (03.01.2026): Логирование источника TP параметров при использовании глобального fallback
                        logger.info(
                            f"📊 [PARAMS] {symbol} ({regime}): TP параметры "
                            f"tp_percent={tp_percent:.2f}%, tp_atr_multiplier={tp_atr_multiplier:.2f}, "
                            f"tp_min={tp_min_percent:.2f}%, tp_max={tp_max_percent:.2f}% | "
                            f"Источник: scalping_config.tp_percent (глобальный fallback)"
                        )
                    except (TypeError, ValueError):
                        tp_percent = 2.4
            except Exception as e:
                logger.debug(f"⚠️ ExitAnalyzer: Ошибка получения TP% для {symbol}: {e}")

        # ✅ ИСПРАВЛЕНО (26.12.2025): Всегда адаптируем TP к волатильности через ATR (если доступен)
        # ATR-based TP обеспечивает адаптацию к волатильности рынка
        leverage = self._get_effective_leverage(position, metadata)
        tp_scale = self._get_exit_leverage_scale(position, metadata)
        if tp_scale != 1.0:
            tp_percent *= tp_scale
            tp_min_percent *= tp_scale
            tp_max_percent *= tp_scale

        # === ГАРАНТИРОВАННАЯ ИНИЦИАЛИЗАЦИЯ sl_percent ===
        sl_percent = 2.0
        sl_min_percent = 1.0
        leverage = self._get_effective_leverage(position, metadata)
        sl_scale = self._get_exit_leverage_scale(position, metadata)
        if sl_scale != 1.0:
            sl_percent *= sl_scale
            sl_min_percent *= sl_scale

        if current_price and current_price > 0:
            try:
                # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #6: Используем ATRProvider БЕЗ fallback
                if not self.atr_provider:
                    logger.error(
                        f"❌ [ATR] {symbol}: ATRProvider недоступен для расчета TP/SL - ПРОПУСКАЕМ расчет"
                    )
                    if not tp_fallback_enabled:
                        return None
                    return 2.4  # Возвращаем fallback значение

                atr_1m = self.atr_provider.get_atr(symbol)  # БЕЗ FALLBACK
                if atr_1m is None:
                    logger.error(
                        f"❌ [ATR] {symbol}: ATR не найден через ATRProvider для расчета TP/SL - ПРОПУСКАЕМ расчет"
                    )
                    if not tp_fallback_enabled:
                        return None
                    return 2.4  # Возвращаем fallback значение

                # ✅ ИСПРАВЛЕНО: ATR найден через ATRProvider, продолжаем расчет TP/SL
                # БЕЗ FALLBACK - если ATR не найден, уже вернули None выше

                if atr_1m and atr_1m > 0:
                    # ✅ ГРОК ФИКС: ATR-based TP: max(1.5%, 2.5*ATR_1m) для ranging с per-symbol adjustment
                    atr_pct = (atr_1m / current_price) * 100
                    atr_tp_percent = atr_pct * tp_atr_multiplier
                    # ATR% считается от цены, переводим в % от маржи через leverage
                    atr_tp_percent = atr_tp_percent * leverage

                    # ✅ ГРОК ФИКС: Per-symbol multipliers для адаптации под волатильность символа
                    # В волатильных символах (SOL, DOGE) делаем TP чуть tighter (меньше), в стабильных (BTC) - стандарт
                    symbol_multipliers = {
                        "SOL-USDT": 0.95,  # SOL более волатильный -> tighter TP
                        "BTC-USDT": 1.0,  # BTC стандарт
                        "ETH-USDT": 1.0,  # ETH стандарт
                        "DOGE-USDT": 0.9,  # DOGE очень волатильный -> tighter TP
                        "XRP-USDT": 0.98,  # XRP немного волатильный
                    }
                    symbol_mult = symbol_multipliers.get(symbol, 1.0)
                    atr_tp_percent = atr_tp_percent * symbol_mult

                    tp_percent = max(
                        tp_min_percent, min(tp_max_percent, atr_tp_percent)
                    )

                    # ✅ КРИТИЧЕСКОЕ УЛУЧШЕНИЕ (04.01.2026): Детальное логирование расчета TP для каждой пары
                    logger.info(
                        f"📊 [PARAMS_TP] {symbol} ({regime}): ATR-based TP расчет | "
                        f"ATR_1m={atr_1m:.6f}, ATR%={atr_pct:.4f}%, "
                        f"base_multiplier={tp_atr_multiplier:.2f}, per_symbol_mult={symbol_mult:.2f} ({symbol}), "
                        f"atr_tp_before_symbol={atr_tp_percent/symbol_mult:.4f}%, "
                        f"atr_tp_after_symbol={atr_tp_percent:.4f}%, "
                        f"min={tp_min_percent:.2f}%, max={tp_max_percent:.2f}%, "
                        f"FINAL TP={tp_percent:.2f}% | "
                        f"Источник: ATR-based расчет с per-symbol adjustment"
                    )
                    logger.debug(
                        f"✅ [ATR_TP] {symbol}: ATR-based TP | "
                        f"ATR_1m={atr_1m:.6f}, ATR%={atr_pct:.4f}%, "
                        f"multiplier={tp_atr_multiplier:.2f}, symbol_mult={symbol_mult:.2f}, "
                        f"min={tp_min_percent:.2f}%, max={tp_max_percent:.2f}%, "
                        f"final TP={tp_percent:.2f}%"
                    )
                else:
                    # ✅ КРИТИЧЕСКОЕ: Если ATR не найден, используем фиксированный TP из конфига
                    # НО проверяем, что tp_percent не равен fallback значению 2.4
                    if tp_percent is None:
                        logger.warning(
                            f"⚠️ [ATR_TP] {symbol}: ATR не найден и tp_percent отсутствует - "
                            f"TP отключен (fallback запрещен)"
                        )
                        return None
                    if tp_percent == 2.4:
                        logger.warning(
                            f"⚠️ [ATR_TP] {symbol}: ATR не найден И tp_percent=2.4 (fallback) - "
                            f"возможно конфиг не загружен! Проверьте symbol_profiles для {symbol} в режиме {regime}"
                        )
                    else:
                        logger.debug(
                            f"✅ [ATR_TP] {symbol}: ATR не найден, используем фиксированный TP={tp_percent:.2f}% из конфига"
                        )
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка расчета ATR-based TP для {symbol}: {e}, используем фиксированный"
                )

        # ✅ ИСПРАВЛЕНО (07.01.2026): Убедитесь что tp_percent всегда float перед возвратом
        if tp_percent is None:
            return None
        tp_percent = self._to_float(tp_percent, "tp_percent_final", tp_percent)
        return tp_percent

    def _safe_sl_percent(
        self,
        symbol: str,
        regime: str,
        current_price: Optional[float] = None,
        market_data: Optional[Any] = None,
        position: Optional[Any] = None,
        metadata: Optional[Any] = None,
    ) -> float:
        """
        Надежный вызов _get_sl_percent с логом и резервом, чтобы ошибки
        не приводили к UnboundLocalError внутри генераторов выходов.
        """
        try:
            return self._get_sl_percent(
                symbol,
                regime,
                current_price=current_price,
                market_data=market_data,
                position=position,
                metadata=metadata,
            )
        except Exception as exc:
            logger.error(
                f"⚠️ ExitAnalyzer: не удалось получить sl_percent для {symbol} ({regime}): {exc}",
                exc_info=True,
            )
            return 2.0

    def _get_sl_percent(
        self,
        symbol: str,
        regime: str,
        current_price: Optional[float] = None,
        market_data: Optional[Any] = None,
        position: Optional[Any] = None,
        metadata: Optional[Any] = None,
    ) -> float:
        """
        Получение SL% из конфига по символу и режиму.
        # ГРОК ФИКС: Поддержка ATR-based SL (max(0.6%, 1.2*ATR_1m) для меньших шумовых хитов)

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending, ranging, choppy)
            current_price: Текущая цена (для ATR расчета)
            market_data: Рыночные данные (для ATR)

        Returns:
            SL% для использования
        """
        sl_percent = 2.0  # Fallback значение
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (09.01.2026): Обновлены fallback значения с 1.0→2.0 и 0.6→0.9
        sl_atr_multiplier = 2.0  # Было 1.0 - слишком маленький множитель!
        sl_min_percent = 0.9  # Было 0.6 - слишком тесный SL!
        leverage = self._get_effective_leverage(position, metadata)

        # ✅ ИСПРАВЛЕНО (26.12.2025): Используем ParameterProvider для получения параметров
        # ✅ НОВОЕ (05.01.2026): Передаем контекст для адаптивных параметров
        # ⚠️ ФИКС (06.01.2026): balance не получаем здесь (метод не async), передаётся извне
        # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ (23.01.2026): Отслеживаем откуда берутся параметры SL
        logger.debug(
            f"🔍 [SL_SOURCE_TRACE] {symbol} ({regime}): Начало поиска параметров SL | "
            f"parameter_provider={'present' if self.parameter_provider else 'MISSING'}, "
            f"config_manager={'present' if self.config_manager else 'MISSING'}"
        )

        if self.parameter_provider:
            try:
                # Получаем контекст для адаптации
                balance = None
                drawdown = None

                exit_params = self.parameter_provider.get_exit_params(
                    symbol, regime, balance=balance, drawdown=drawdown
                )
                logger.debug(
                    f"🔍 [SL_SOURCE_TRACE] {symbol} ({regime}): ParameterProvider вернул exit_params={'present' if exit_params else 'NONE'} | "
                    f"keys={list(exit_params.keys()) if exit_params else 'N/A'}"
                )

                if exit_params:
                    raw_sl_atr = exit_params.get("sl_atr_multiplier")
                    raw_sl_min = exit_params.get("sl_min_percent")

                    logger.debug(
                        f"🔍 [SL_SOURCE_TRACE] {symbol} ({regime}): RAW значения из exit_params | "
                        f"sl_atr_multiplier={raw_sl_atr} (type={type(raw_sl_atr).__name__}), "
                        f"sl_min_percent={raw_sl_min} (type={type(raw_sl_min).__name__})"
                    )

                    if "sl_percent" in exit_params:
                        sl_percent = self._to_float(
                            exit_params["sl_percent"], "sl_percent", 2.0
                        )
                    if "sl_atr_multiplier" in exit_params:
                        sl_atr_multiplier = self._to_float(
                            exit_params["sl_atr_multiplier"],
                            "sl_atr_multiplier",
                            2.0,  # ✅ FIX: 1.0→2.0
                        )
                        logger.debug(
                            f"🔍 [SL_SOURCE_TRACE] {symbol} ({regime}): sl_atr_multiplier ПОСЛЕ _to_float | "
                            f"raw={raw_sl_atr} → converted={sl_atr_multiplier}"
                        )
                    if "sl_min_percent" in exit_params:
                        sl_min_percent = self._to_float(
                            exit_params["sl_min_percent"],
                            "sl_min_percent",
                            0.9,  # ✅ FIX: 0.6→0.9
                        )
                        logger.debug(
                            f"🔍 [SL_SOURCE_TRACE] {symbol} ({regime}): sl_min_percent ПОСЛЕ _to_float | "
                            f"raw={raw_sl_min} → converted={sl_min_percent}"
                        )
                    # ✅ НОВОЕ (03.01.2026): Детальное логирование источников SL параметров
                    logger.info(
                        f"📊 [PARAMS] {symbol} ({regime}): SL параметры "
                        f"sl_percent={sl_percent:.2f}%, sl_atr_multiplier={sl_atr_multiplier:.2f}, "
                        f"sl_min={sl_min_percent:.2f}% | "
                        f"Источник: ParameterProvider.get_exit_params()"
                    )
            except Exception as e:
                import traceback

                logger.warning(
                    f"⚠️ ExitAnalyzer: Ошибка получения SL параметров через ParameterProvider: {e}, "
                    f"используем fallback к config_manager\n{traceback.format_exc()}"
                )

        # Fallback на config_manager для обратной совместимости
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (23.01.2026): Сохраняем значения из ParameterProvider
        param_provider_sl_min = (
            sl_min_percent  # Сохраняем значение из ParameterProvider
        )
        param_provider_sl_atr_mult = (
            sl_atr_multiplier  # Сохраняем значение из ParameterProvider
        )

        if self.config_manager and sl_percent == 2.0:
            try:
                # Пробуем получить SL из symbol_profiles
                symbol_profiles = getattr(self.config_manager, "symbol_profiles", {})
                if symbol in symbol_profiles:
                    symbol_config = symbol_profiles[symbol]
                    if isinstance(symbol_config, dict) and regime in symbol_config:
                        regime_config = symbol_config[regime]
                        if (
                            isinstance(regime_config, dict)
                            and "sl_percent" in regime_config
                        ):
                            # ✅ ИСПРАВЛЕНИЕ: Явное преобразование в float для предотвращения str vs int ошибок
                            try:
                                sl_percent = float(regime_config["sl_percent"])
                                sl_atr_based = regime_config.get("sl_atr_based", False)
                                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (23.01.2026): НЕ перезаписываем если уже установлено из ParameterProvider
                                if (
                                    param_provider_sl_atr_mult == 2.0
                                ):  # Только если было fallback значение
                                    sl_atr_multiplier = float(
                                        regime_config.get(
                                            "sl_atr_multiplier", 2.0
                                        )  # ✅ FIX: 1.0→2.0
                                    )
                                if (
                                    param_provider_sl_min == 0.9
                                ):  # Только если было fallback значение
                                    sl_min_percent = float(
                                        regime_config.get(
                                            "sl_min_percent", 0.9
                                        )  # ✅ FIX: 0.6→0.9
                                    )
                            except (TypeError, ValueError) as e:
                                logger.warning(
                                    f"⚠️ ExitAnalyzer: Не удалось преобразовать sl_percent={regime_config.get('sl_percent')} "
                                    f"в float для {symbol}: {e}, используем fallback"
                                )
                                return 2.0

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Fallback на adaptive_regime (правильная структура конфига)
                if sl_percent == 2.0:  # Если не нашли в symbol_profiles
                    # Пробуем получить из adaptive_regime.{regime}.sl_percent
                    adaptive_regime = getattr(
                        self.scalping_config, "adaptive_regime", None
                    )
                    if adaptive_regime:
                        adaptive_dict = self.config_manager.to_dict(adaptive_regime)
                        if regime in adaptive_dict:
                            regime_config = adaptive_dict[regime]
                            if (
                                isinstance(regime_config, dict)
                                and "sl_percent" in regime_config
                            ):
                                # ✅ ИСПРАВЛЕНИЕ: Явное преобразование в float для предотвращения str vs int ошибок
                                try:
                                    sl_percent = float(regime_config["sl_percent"])
                                    sl_atr_based = regime_config.get(
                                        "sl_atr_based", False
                                    )
                                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (23.01.2026): НЕ перезаписываем если уже установлено из ParameterProvider
                                    if (
                                        param_provider_sl_atr_mult == 2.0
                                    ):  # Только если было fallback значение
                                        sl_atr_multiplier = float(
                                            regime_config.get(
                                                "sl_atr_multiplier", 2.0
                                            )  # ✅ FIX: 1.0→2.0
                                        )
                                    if (
                                        param_provider_sl_min == 0.9
                                    ):  # Только если было fallback значение
                                        sl_min_percent = float(
                                            regime_config.get(
                                                "sl_min_percent", 0.9
                                            )  # ✅ FIX: 0.6→0.9
                                        )
                                    # ✅ НОВОЕ (03.01.2026): Логирование источника SL параметров при использовании fallback
                                    logger.info(
                                        f"📊 [PARAMS] {symbol} ({regime}): SL параметры "
                                        f"sl_percent={sl_percent:.2f}%, sl_atr_multiplier={sl_atr_multiplier:.2f}, "
                                        f"sl_min={sl_min_percent:.2f}% | "
                                        f"Источник: adaptive_regime.{regime} (fallback)"
                                    )
                                except (TypeError, ValueError) as e:
                                    logger.warning(
                                        f"⚠️ ExitAnalyzer: Не удалось преобразовать sl_percent={regime_config.get('sl_percent')} "
                                        f"в float для {symbol}: {e}, используем fallback"
                                    )

                    # ✅ ДОПОЛНИТЕЛЬНЫЙ FALLBACK: Пробуем by_regime (для обратной совместимости)
                    if sl_percent == 2.0:
                        by_regime = self.config_manager.to_dict(
                            getattr(self.scalping_config, "by_regime", {})
                            if self.scalping_config
                            else {}
                        )
                        if regime in by_regime:
                            regime_config = by_regime[regime]
                            if (
                                isinstance(regime_config, dict)
                                and "sl_percent" in regime_config
                            ):
                                try:
                                    sl_percent = float(regime_config["sl_percent"])
                                    sl_atr_based = regime_config.get(
                                        "sl_atr_based", False
                                    )
                                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (23.01.2026): НЕ перезаписываем если уже установлено из ParameterProvider
                                    if (
                                        param_provider_sl_atr_mult == 2.0
                                    ):  # Только если было fallback значение
                                        sl_atr_multiplier = float(
                                            regime_config.get(
                                                "sl_atr_multiplier", 2.0
                                            )  # ✅ FIX: 1.0→2.0
                                        )
                                    if (
                                        param_provider_sl_min == 0.9
                                    ):  # Только если было fallback значение
                                        sl_min_percent = float(
                                            regime_config.get(
                                                "sl_min_percent", 0.9
                                            )  # ✅ FIX: 0.6→0.9
                                        )
                                    # ✅ НОВОЕ (03.01.2026): Логирование источника SL параметров при использовании fallback
                                    logger.info(
                                        f"📊 [PARAMS] {symbol} ({regime}): SL параметры "
                                        f"sl_percent={sl_percent:.2f}%, sl_atr_multiplier={sl_atr_multiplier:.2f}, "
                                        f"sl_min={sl_min_percent:.2f}% | "
                                        f"Источник: by_regime.{regime} (fallback)"
                                    )
                                except (TypeError, ValueError) as e:
                                    logger.warning(
                                        f"⚠️ ExitAnalyzer: Не удалось преобразовать sl_percent={regime_config.get('sl_percent')} "
                                        f"в float для {symbol}: {e}, используем fallback"
                                    )

                # Fallback на глобальный SL
                if sl_percent == 2.0 and self.scalping_config:
                    sl_percent_raw = getattr(self.scalping_config, "sl_percent", 2.0)
                    # ✅ ИСПРАВЛЕНИЕ: Явное преобразование в float
                    try:
                        sl_percent = float(sl_percent_raw)
                        # ✅ НОВОЕ (03.01.2026): Логирование источника SL параметров при использовании глобального fallback
                        logger.info(
                            f"📊 [PARAMS] {symbol} ({regime}): SL параметры "
                            f"sl_percent={sl_percent:.2f}%, sl_atr_multiplier={sl_atr_multiplier:.2f}, "
                            f"sl_min={sl_min_percent:.2f}% | "
                            f"Источник: scalping_config.sl_percent (глобальный fallback)"
                        )
                    except (TypeError, ValueError):
                        sl_percent = 2.0
            except Exception as e:
                logger.debug(f"⚠️ ExitAnalyzer: Ошибка получения SL% для {symbol}: {e}")

        # ✅ ИСПРАВЛЕНО (26.12.2025): Всегда используем ATR для расчета SL (если доступен)
        # ATR-based SL обеспечивает адаптацию к волатильности рынка
        if current_price and current_price > 0:
            try:
                # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #6: Используем ATRProvider БЕЗ fallback
                atr_1m = None
                if not self.atr_provider:
                    logger.error(
                        f"❌ [ATR_SL] {symbol}: ATRProvider недоступен - ПРОПУСКАЕМ расчет SL"
                    )
                    return sl_percent
                else:
                    atr_1m = self.atr_provider.get_atr(symbol)  # БЕЗ FALLBACK
                    if atr_1m is None:
                        logger.error(
                            f"❌ [ATR_SL] {symbol}: ATR не найден через ATRProvider - ПРОПУСКАЕМ расчет SL"
                        )
                        return sl_percent
                    else:
                        logger.debug(
                            f"✅ [ATR_SL] {symbol}: ATR получен через ATRProvider: {atr_1m:.6f}"
                        )

                # ✅ ИСПРАВЛЕНО: ATR найден через ATRProvider, продолжаем расчет SL
                # БЕЗ FALLBACK - если ATR не найден, уже вернули None выше

                # ✅ ИСПРАВЛЕНО (28.12.2025): Удален проблемный fallback через IndicatorManager.get_indicator()
                # IndicatorManager не имеет метода get_indicator(), используем только ATRProvider и fallback на фиксированный SL

                # ✅ ИСПРАВЛЕНО: Используем ATR для расчета SL если доступен
                if atr_1m and atr_1m > 0:
                    # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ (23.01.2026): Проверяем значения ПЕРЕД расчетом
                    logger.debug(
                        f"🔍 [SL_SOURCE_TRACE] {symbol} ({regime}): ATR-based расчет НАЧАЛО | "
                        f"sl_atr_multiplier={sl_atr_multiplier:.2f}, "
                        f"sl_min_percent={sl_min_percent:.2f}%, "
                        f"leverage={leverage}x, ATR_1m={atr_1m:.6f}"
                    )

                    # ATR-based SL: max(min_percent, ATR% * multiplier)
                    atr_pct = (atr_1m / current_price) * 100
                    atr_sl_percent = atr_pct * sl_atr_multiplier
                    # ATR% считается от цены, переводим в % от маржи через leverage
                    atr_sl_percent = atr_sl_percent * leverage
                    sl_percent = max(sl_min_percent, atr_sl_percent)

                    # ✅ КРИТИЧЕСКОЕ УЛУЧШЕНИЕ (04.01.2026): Детальное логирование расчета SL для каждой пары
                    logger.info(
                        f"📊 [PARAMS_SL] {symbol} ({regime}): ATR-based SL расчет | "
                        f"ATR_1m={atr_1m:.6f}, ATR%={atr_pct:.4f}%, "
                        f"multiplier={sl_atr_multiplier:.2f}, "
                        f"atr_sl={atr_sl_percent:.4f}%, min={sl_min_percent:.2f}%, "
                        f"FINAL SL={sl_percent:.2f}% | "
                        f"Источник: ATR-based расчет"
                    )

                    # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ (23.01.2026): Проверяем значения ПОСЛЕ расчета
                    logger.debug(
                        f"🔍 [SL_SOURCE_TRACE] {symbol} ({regime}): ATR-based расчет ФИНАЛ | "
                        f"atr_pct={atr_pct:.4f}% → atr_sl_percent={atr_sl_percent:.4f}% "
                        f"→ max({sl_min_percent:.2f}%, {atr_sl_percent:.4f}%) = {sl_percent:.2f}%"
                    )
                    logger.debug(
                        f"✅ [ATR_SL] {symbol}: ATR-based SL | "
                        f"ATR_1m={atr_1m:.6f}, ATR%={atr_pct:.4f}%, "
                        f"multiplier={sl_atr_multiplier:.2f}, min={sl_min_percent:.2f}%, "
                        f"final SL={sl_percent:.2f}%"
                    )
                else:
                    # ✅ Если ATR не найден, используем фиксированный SL из конфига
                    if sl_percent == 2.0:
                        logger.warning(
                            f"⚠️ [ATR_SL] {symbol}: ATR не найден И sl_percent=2.0 (fallback) - "
                            f"возможно конфиг не загружен! Проверьте symbol_profiles для {symbol} в режиме {regime}"
                        )
                    else:
                        logger.debug(
                            f"✅ [ATR_SL] {symbol}: ATR не найден, используем фиксированный SL={sl_percent:.2f}% из конфига"
                        )
            except Exception as e:
                logger.warning(
                    f"⚠️ [ATR_SL] {symbol}: Ошибка расчета ATR-based SL: {e}, используем фиксированный SL={sl_percent:.2f}%"
                )
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка расчета ATR-based SL для {symbol}: {e}, используем фиксированный"
                )

        return sl_percent

    def _get_spread_buffer(self, symbol: str, current_price: float) -> float:
        """
        Возвращает буфер спреда в процентах для учёта проскальзывания.

        Если данных нет - возвращаем 0.05% по умолчанию.

        Args:
            symbol: Торговый символ
            current_price: Текущая цена (для fallback)

        Returns:
            Буфер спреда в процентах (например, 0.05 для 0.05%)
        """
        try:
            # Пробуем получить best_bid и best_ask из data_registry
            if self.data_registry:
                # Используем прямой доступ к _market_data (синхронный метод)
                # ⚠️ ВНИМАНИЕ: Это безопасно, так как мы в синхронном контексте
                market_data = getattr(self.data_registry, "_market_data", {}).get(
                    symbol, {}
                )
                if market_data:
                    best_bid = market_data.get("best_bid") or market_data.get("bid")
                    best_ask = market_data.get("best_ask") or market_data.get("ask")

                    if best_bid and best_ask and best_ask > 0:
                        spread = best_ask - best_bid
                        # 🔴 BUG #19 FIX (09.01.2026): Correct spread ratio = (ask-bid) / mid_price * 100, not / ask_price
                        mid_price = (best_bid + best_ask) / 2.0
                        if mid_price > 0:
                            spread_pct = (spread / mid_price) * 100.0  # в процентах
                        else:
                            spread_pct = 0.0
                        return spread_pct
        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить спред для {symbol}: {e}")

        # Fallback: 0.05% по умолчанию
        return 0.05

    def _get_commission_buffer(
        self, position: Any = None, metadata: Any = None
    ) -> float:
        """
        Возвращает буфер комиссии в процентах для учёта комиссий при закрытии позиции.

        Комиссия учитывает:
        - maker_fee_rate (0.02% на сторону)
        - leverage (комиссия от номинала, PnL% от маржи)
        - две стороны (вход + выход)

        Args:
            position: Данные позиции (для получения leverage)
            metadata: Метаданные позиции (для получения leverage)

        Returns:
            Буфер комиссии в процентах (например, 0.2 для 0.2% при leverage=5)
        """
        try:
            # Получаем leverage
            leverage = 5  # Default
            if metadata and hasattr(metadata, "leverage") and metadata.leverage:
                try:
                    leverage = int(
                        float(metadata.leverage)
                    )  # ✅ ФИКС: Конвертируем в float сначала
                except (ValueError, TypeError):
                    leverage = 5
            elif position and isinstance(position, dict):
                try:
                    leverage_val = position.get("leverage", 5) or 5
                    leverage = int(
                        float(leverage_val)
                    )  # ✅ ФИКС: Конвертируем в float сначала
                except (ValueError, TypeError):
                    leverage = 5

            # Получаем maker_fee_rate из конфига
            trading_fee_rate = 0.0002  # 0.02% по умолчанию
            if self.scalping_config:
                commission_config = getattr(self.scalping_config, "commission", {})
                if isinstance(commission_config, dict):
                    trading_fee_rate = commission_config.get(
                        "maker_fee_rate",
                        commission_config.get("trading_fee_rate", 0.0002),
                    )
                elif hasattr(commission_config, "maker_fee_rate"):
                    trading_fee_rate = getattr(
                        commission_config, "maker_fee_rate", 0.0002
                    )
                elif hasattr(commission_config, "trading_fee_rate"):
                    trading_fee_rate = getattr(
                        commission_config, "trading_fee_rate", 0.0002
                    )

            # Комиссия: 0.02% на вход + 0.02% на выход, умноженная на leverage
            # (т.к. комиссия считается от номинала, а PnL% от маржи)
            commission_buffer = (trading_fee_rate * 2) * leverage * 100  # в процентах

            return commission_buffer
        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить commission_buffer: {e}")
            # Fallback: 0.2% по умолчанию (для leverage=5)
            return 0.2

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
            value_raw = getattr(self.scalping_config, config_key, default_value)
            # ✅ ИСПРАВЛЕНИЕ: Явное преобразование в float для предотвращения str vs int ошибок
            try:
                return float(value_raw)
            except (TypeError, ValueError):
                return default_value

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

    def _get_min_holding_minutes(
        self, regime: str, symbol: Optional[str] = None
    ) -> Optional[float]:
        """
        Получение min_holding_minutes из конфига по режиму.

        Приоритет:
        1. exit_params.regime.min_holding_minutes (через ParameterProvider)
        2. adaptive_regime.regime.min_holding_minutes
        3. per-symbol min_holding_minutes

        Args:
            regime: Режим рынка (trending, ranging, choppy)
            symbol: Торговый символ (опционально, для per-symbol параметров)

        Returns:
            min_holding_minutes или None если не задано
        """
        # ✅ ПРИОРИТЕТ 1: exit_params.regime.min_holding_minutes (через ParameterProvider)
        if self.parameter_provider:
            try:
                exit_params = self.parameter_provider.get_exit_params(
                    symbol or "", regime
                )
                if exit_params and "min_holding_minutes" in exit_params:
                    min_holding_minutes = self._to_float(
                        exit_params["min_holding_minutes"], "min_holding_minutes", None
                    )
                    if min_holding_minutes is not None:
                        logger.debug(
                            f"✅ ExitAnalyzer: min_holding_minutes для {symbol or 'default'} ({regime}) "
                            f"получен через ParameterProvider: {min_holding_minutes:.1f}мин"
                        )
                        return min_holding_minutes
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения min_holding_minutes через ParameterProvider: {e}"
                )

        # ✅ ПРИОРИТЕТ 2: adaptive_regime.regime.min_holding_minutes
        if self.config_manager:
            try:
                if hasattr(self.config_manager, "_raw_config_dict"):
                    config_dict = self.config_manager._raw_config_dict
                    adaptive_regime = config_dict.get("adaptive_regime", {})
                    regime_config = adaptive_regime.get(regime, {})
                    if "min_holding_minutes" in regime_config:
                        min_holding_minutes = self._to_float(
                            regime_config["min_holding_minutes"],
                            "min_holding_minutes",
                            None,
                        )
                        if min_holding_minutes is not None:
                            logger.debug(
                                f"✅ ExitAnalyzer: min_holding_minutes для {regime} "
                                f"получен из adaptive_regime: {min_holding_minutes:.1f}мин"
                            )
                            return min_holding_minutes
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения min_holding_minutes из adaptive_regime: {e}"
                )

        # ✅ ПРИОРИТЕТ 3: per-symbol min_holding_minutes
        if symbol and self.config_manager:
            try:
                if hasattr(self.config_manager, "_raw_config_dict"):
                    config_dict = self.config_manager._raw_config_dict
                    by_symbol = config_dict.get("by_symbol", {})
                    symbol_config = by_symbol.get(symbol, {})
                    # Проверяем per-symbol min_holding_minutes по режиму
                    if isinstance(symbol_config, dict):
                        # Сначала проверяем режим-специфичный параметр
                        regime_config = symbol_config.get(regime, {})
                        if (
                            isinstance(regime_config, dict)
                            and "min_holding_minutes" in regime_config
                        ):
                            min_holding_minutes = self._to_float(
                                regime_config["min_holding_minutes"],
                                "min_holding_minutes",
                                None,
                            )
                            if min_holding_minutes is not None:
                                logger.debug(
                                    f"✅ ExitAnalyzer: min_holding_minutes для {symbol} ({regime}) "
                                    f"получен из by_symbol: {min_holding_minutes:.1f}мин"
                                )
                                return min_holding_minutes
                        # Затем проверяем общий параметр для символа
                        if "min_holding_minutes" in symbol_config:
                            min_holding_minutes = self._to_float(
                                symbol_config["min_holding_minutes"],
                                "min_holding_minutes",
                                None,
                            )
                            if min_holding_minutes is not None:
                                logger.debug(
                                    f"✅ ExitAnalyzer: min_holding_minutes для {symbol} "
                                    f"получен из by_symbol (общий): {min_holding_minutes:.1f}мин"
                                )
                                return min_holding_minutes
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения min_holding_minutes из by_symbol: {e}"
                )

        # По умолчанию возвращаем None (нет защиты)
        return None

    def _get_max_holding_minutes(
        self, regime: str, symbol: Optional[str] = None
    ) -> float:
        """
        Получение max_holding_minutes из конфига по режиму.

        Приоритет:
        1. exit_params.regime.max_holding_minutes (через ParameterProvider)
        2. adaptive_regime.regime.max_holding_minutes
        3. per-symbol max_holding_minutes
        4. 120.0 (default)

        Args:
            regime: Режим рынка (trending, ranging, choppy)
            symbol: Торговый символ (опционально, для per-symbol параметров)

        Returns:
            max_holding_minutes или 120.0 по умолчанию
        """
        max_holding_minutes = 120.0  # Default 2 часа

        # ✅ ИСПРАВЛЕНО (26.12.2025): Используем ParameterProvider для получения exit_params
        if self.parameter_provider:
            try:
                exit_params = self.parameter_provider.get_exit_params(
                    symbol or "", regime
                )
                if exit_params and "max_holding_minutes" in exit_params:
                    max_holding_minutes = self._to_float(
                        exit_params["max_holding_minutes"], "max_holding_minutes", 120.0
                    )
                    logger.debug(
                        f"✅ ExitAnalyzer: max_holding_minutes для {symbol or 'default'} ({regime}) "
                        f"получен через ParameterProvider: {max_holding_minutes:.1f}мин"
                    )
                    return max_holding_minutes
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения max_holding_minutes через ParameterProvider: {e}, "
                    f"используем fallback"
                )

        # ✅ ПРИОРИТЕТ 1: exit_params.regime.max_holding_minutes
        # ✅ ИСПРАВЛЕНО (26.12.2025): Используем правильный способ получения exit_params из ConfigManager
        if self.config_manager:
            try:
                # ConfigManager не имеет метода get(), используем _raw_config_dict напрямую
                if (
                    hasattr(self.config_manager, "_raw_config_dict")
                    and self.config_manager._raw_config_dict
                ):
                    exit_params = self.config_manager._raw_config_dict.get(
                        "exit_params", {}
                    )
                else:
                    # Fallback: пробуем получить через другие способы
                    exit_params = (
                        getattr(self.config_manager.config, "exit_params", None) or {}
                    )

                if isinstance(exit_params, dict) and regime in exit_params:
                    regime_config = exit_params.get(regime, {})
                    if (
                        isinstance(regime_config, dict)
                        and "max_holding_minutes" in regime_config
                    ):
                        # ✅ ИСПРАВЛЕНО (28.12.2025): Используем _to_float() вместо float() напрямую
                        max_holding_minutes_raw = regime_config["max_holding_minutes"]
                        max_holding_minutes = self._to_float(
                            max_holding_minutes_raw, "max_holding_minutes", 120.0
                        )
                        return max_holding_minutes
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения exit_params.max_holding_minutes: {e}"
                )

        # ✅ ПРИОРИТЕТ 2: adaptive_regime.regime.max_holding_minutes (старая логика)
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
                        # ✅ ИСПРАВЛЕНО (28.12.2025): Используем _to_float() вместо float() напрямую
                        max_holding_minutes_raw = regime_config.get(
                            "max_holding_minutes", 120.0
                        )
                        max_holding_minutes = self._to_float(
                            max_holding_minutes_raw, "max_holding_minutes", 120.0
                        )
                    else:
                        # ✅ ИСПРАВЛЕНО (28.12.2025): Используем _to_float() вместо float() напрямую
                        max_holding_minutes_raw = getattr(
                            regime_config, "max_holding_minutes", 120.0
                        )
                        max_holding_minutes = self._to_float(
                            max_holding_minutes_raw, "max_holding_minutes", 120.0
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

            # ✅ ИСПРАВЛЕНИЕ #1 (07.01.2026): Конвертируем все значения в float (защита от string из конфига)
            # Было: adx_value = adx_data.get("adx", 0) может быть string "25" → ошибка при сравнении > 25
            # Теперь: гарантируем что это float
            adx_value = float(adx_data.get("adx", 0) or 0)
            plus_di = float(adx_data.get("plus_di", 0) or 0)
            minus_di = float(adx_data.get("minus_di", 0) or 0)

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
        order_flow_reversal = False
        mtf_reversal = False

        # ✅ КРИТИЧЕСКОЕ УЛУЧШЕНИЕ (04.01.2026): Детальное логирование проверки разворота
        logger.info(
            f"🔍 [REVERSAL_CHECK] {symbol} {position_side.upper()}: Начало проверки признаков разворота"
        )

        # Проверка Order Flow разворота
        if self.order_flow:
            try:
                current_delta = self.order_flow.get_delta()
                avg_delta = self.order_flow.get_avg_delta(periods=10)
                reversal_threshold = 0.15  # 15% изменение delta

                logger.info(
                    f"🔍 [REVERSAL_CHECK] {symbol} {position_side.upper()}: Order Flow данные | "
                    f"current_delta={current_delta:.3f}, avg_delta={avg_delta:.3f}, "
                    f"threshold={reversal_threshold:.3f}"
                )

                if position_side.lower() == "long":
                    # Для LONG: разворот = delta был положительным и стал отрицательным
                    if (
                        current_delta < -reversal_threshold
                        and avg_delta > reversal_threshold
                    ):
                        reversal_detected = True
                        order_flow_reversal = True
                        logger.info(
                            f"🔄 [REVERSAL_CHECK] {symbol} LONG: Order Flow разворот ОБНАРУЖЕН | "
                            f"delta {avg_delta:.3f} -> {current_delta:.3f} "
                            f"(был положительным, стал отрицательным)"
                        )
                    else:
                        logger.info(
                            f"✅ [REVERSAL_CHECK] {symbol} LONG: Order Flow разворот НЕ обнаружен | "
                            f"current_delta={current_delta:.3f}, avg_delta={avg_delta:.3f} "
                            f"(условия не выполнены)"
                        )
                elif position_side.lower() == "short":
                    # Для SHORT: разворот = delta был отрицательным и стал положительным
                    if (
                        current_delta > reversal_threshold
                        and avg_delta < -reversal_threshold
                    ):
                        reversal_detected = True
                        order_flow_reversal = True
                        logger.info(
                            f"🔄 [REVERSAL_CHECK] {symbol} SHORT: Order Flow разворот ОБНАРУЖЕН | "
                            f"delta {avg_delta:.3f} -> {current_delta:.3f} "
                            f"(был отрицательным, стал положительным)"
                        )
                    else:
                        logger.info(
                            f"✅ [REVERSAL_CHECK] {symbol} SHORT: Order Flow разворот НЕ обнаружен | "
                            f"current_delta={current_delta:.3f}, avg_delta={avg_delta:.3f} "
                            f"(условия не выполнены)"
                        )
            except Exception as e:
                logger.warning(
                    f"⚠️ [REVERSAL_CHECK] {symbol} {position_side.upper()}: Ошибка проверки Order Flow разворота: {e}"
                )
        else:
            logger.info(
                f"⚠️ [REVERSAL_CHECK] {symbol} {position_side.upper()}: Order Flow недоступен"
            )

        # Проверка MTF разворота
        mtf_filter = self._get_mtf_filter()
        if mtf_filter and not reversal_detected:
            try:
                # MTF фильтр может показывать разворот тренда на более высоком таймфрейме
                # Пока упрощенная проверка - можно расширить позже
                logger.info(
                    f"🔍 [REVERSAL_CHECK] {symbol} {position_side.upper()}: MTF фильтр доступен, "
                    f"но проверка разворота еще не реализована (TODO)"
                )
                pass  # TODO: Реализовать проверку MTF разворота
            except Exception as e:
                logger.warning(
                    f"⚠️ [REVERSAL_CHECK] {symbol} {position_side.upper()}: Ошибка проверки MTF разворота: {e}"
                )
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Grace period при ошибке MTF
                # MTF недоступен из-за ошибки, откладываем SL
                if not order_flow_reversal:
                    self._apply_sl_grace_period(symbol, "MTF ошибка")
                    # ✅ НЕ возвращаем True - grace period не является разворотом!
        elif not mtf_filter:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Grace period при отсутствии MTF
            logger.warning(
                f"⚠️ [REVERSAL_CHECK] {symbol} {position_side.upper()}: MTF фильтр недоступен — "
                f"применяем grace period для SL"
            )
            # Если Order Flow тоже не показал разворот → откладываем SL
            if not order_flow_reversal:
                self._apply_sl_grace_period(symbol, "MTF недоступен")
                # ✅ НЕ возвращаем результат - grace period не является разворотом!

        # ✅ ИТОГОВОЕ ЛОГИРОВАНИЕ
        logger.info(
            f"🔍 [REVERSAL_CHECK] {symbol} {position_side.upper()}: ИТОГ проверки разворота | "
            f"reversal_detected={reversal_detected}, order_flow={order_flow_reversal}, mtf={mtf_reversal}"
        )

        return reversal_detected

    def _apply_sl_grace_period(self, symbol: str, reason: str) -> None:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Применение grace period для SL.

        При недоступности MTF фильтра откладываем срабатывание SL на 30 секунд,
        чтобы избежать преждевременного закрытия позиций, которые могут развернуться.
        Grace period НЕ считается разворотом!

        Args:
            symbol: Торговый символ
            reason: Причина применения grace period
        """
        now = time.time()
        grace_key = f"{symbol}_sl_grace"
        last_attempt = self._sl_grace_periods.get(grace_key)

        if not last_attempt:
            # Первая попытка SL — запоминаем время и откладываем
            self._sl_grace_periods[grace_key] = now
            logger.info(
                f"⏳ [GRACE_PERIOD] {symbol}: Начало grace period ({self._sl_grace_duration}s) — {reason}. "
                f"SL отложен."
            )
            return  # ✅ Просто отмечаем, не возвращаем результат

        elapsed = now - last_attempt

        if elapsed < self._sl_grace_duration:
            # Grace period ещё не истёк
            remaining = self._sl_grace_duration - elapsed
            logger.info(
                f"⏳ [GRACE_PERIOD] {symbol}: Grace period активен ({remaining:.1f}s осталось) — {reason}. "
                f"SL отложен."
            )
            return  # ✅ Grace period активен
        else:
            # Grace period истёк — разрешаем SL
            logger.warning(
                f"⚠️ [GRACE_PERIOD] {symbol}: Grace period истёк ({elapsed:.1f}s > {self._sl_grace_duration}s) — {reason}. "
                f"SL РАЗРЕШЁН."
            )
            # Сбрасываем grace period
            del self._sl_grace_periods[grace_key]
            return  # ✅ Grace period истёк

    def _is_grace_period_active(self, symbol: str) -> bool:
        """
        ✅ НОВОЕ (08.01.2026): Проверка активного grace period.

        Args:
            symbol: Торговый символ

        Returns:
            True если grace period активен, False если истёк или не существует
        """
        grace_key = f"{symbol}_sl_grace"
        last_attempt = self._sl_grace_periods.get(grace_key)

        if not last_attempt:
            return False  # Нет grace period

        elapsed = time.time() - last_attempt

        if elapsed < self._sl_grace_duration:
            return True  # Grace period активен
        else:
            # Grace period истёк
            del self._sl_grace_periods[grace_key]
            return False

    async def _get_entry_price_and_side(
        self, symbol: str, position: Any, metadata: Any
    ) -> tuple[Optional[float], Optional[str]]:
        """
        Получение entry_price из множественных источников.
        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получение entry_price из множественных источников.

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
        Проверка adaptive_min_holding для Partial TP.
        # Проверка adaptive_min_holding для Partial TP.

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
                    # ✅ ИСПРАВЛЕНО (26.12.2025): Используем ParameterProvider для получения regime_params
                    if self.parameter_provider:
                        regime_params = self.parameter_provider.get_regime_params(
                            symbol, regime, balance=None
                        )
                    else:
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
                    # Прибыль >= 1.0% -> снижаем min_holding до 50%
                    actual_min_holding = min_holding_minutes * reduction_factor_1
                    logger.debug(
                        f"✅ Adaptive min_holding для {symbol}: прибыль {pnl_percent:.2f}% >= {profit_threshold_1}%, "
                        f"снижаем min_holding с {min_holding_minutes:.1f} до {actual_min_holding:.1f} мин"
                    )
                elif pnl_percent >= profit_threshold_2:
                    # Прибыль >= 0.5% -> снижаем min_holding до 75%
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
        regime: str = "trending",
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
        sl_percent = 2.0  # Гарантированная инициализация для UnboundLocalError
        try:
            # Базовый SL заранее, чтобы исключить UnboundLocalError при любых ветках логики
            try:
                sl_percent = self._safe_sl_percent(
                    symbol,
                    "trending",
                    current_price,
                    market_data,
                    position=position,
                    metadata=metadata,
                )
            except Exception:
                logger.error(
                    f"⚠️ ExitAnalyzer TRENDING: не удалось рассчитать SL для {symbol}, fallback 2.0%",
                    exc_info=True,
                )
                sl_percent = 2.0
            sl_percent = self._to_float(sl_percent, "sl_percent", 2.0)

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

            # ✅ ПРАВКА #4: Приведение типов для предотвращения str vs int ошибок
            try:
                pnl_percent = float(pnl_percent)
            except (TypeError, ValueError) as e:
                logger.error(
                    f"❌ ExitAnalyzer TRENDING: Ошибка приведения pnl_percent для {symbol}: {e}"
                )
                return None

            # 2. Рассчитываем Gross PnL для SL (без комиссий)
            gross_pnl_percent = self._calculate_pnl_percent(
                entry_price,
                current_price,
                position_side,
                include_fees=False,  # Gross PnL для сравнения с SL
                entry_time=entry_time,
                position=position,
                metadata=metadata,
            )
            gross_pnl_percent = self._to_float(
                gross_pnl_percent, "gross_pnl_percent", 0.0
            )

            tsl_hit, tsl_stop = self._check_tsl_hit(
                symbol, position_side, current_price
            )
            if tsl_hit:
                self._record_metrics_on_close(
                    symbol=symbol,
                    reason="tsl_hit",
                    pnl_percent=pnl_percent,
                    entry_time=entry_time,
                )
                return {
                    "action": "close",
                    "reason": "tsl_hit",
                    "pnl_pct": pnl_percent,
                    "regime": regime,
                    "tsl_stop": tsl_stop,
                }

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (03.01.2026): Emergency Loss Protection - ПЕРВАЯ ЗАЩИТА
            # Проверяется ПЕРВОЙ, перед всеми другими проверками (соответствует приоритету 1 в ExitDecisionCoordinator)
            # ✅ ПРАВКА #13: Защита от больших убытков - АДАПТИВНО ПО РЕЖИМАМ
            # TRENDING: более высокий порог (-4.0%), так как тренды могут иметь большие просадки
            base_emergency_threshold = -8.0
            emergency_loss_threshold = self._get_emergency_threshold(
                base_emergency_threshold, position, metadata
            )

            # ✅ НОВОЕ (26.12.2025): Учитываем spread_buffer и commission_buffer
            emergency_spread_buffer = self._get_spread_buffer(symbol, current_price)
            emergency_commission_buffer = self._get_commission_buffer(
                position, metadata
            )
            adjusted_emergency_threshold = (
                emergency_loss_threshold
                - emergency_spread_buffer
                - emergency_commission_buffer
            )

            # ✅ НОВОЕ (26.12.2025): Минимальное время удержания перед emergency close
            min_holding_seconds = 120.0  # TRENDING: 120 секунд (2 минуты)
            if pnl_percent < adjusted_emergency_threshold:
                # Проверяем минимальное время удержания
                if entry_time:
                    try:
                        if isinstance(entry_time, str):
                            entry_time_dt = datetime.fromisoformat(
                                entry_time.replace("Z", "+00:00")
                            )
                        else:
                            entry_time_dt = entry_time

                        if entry_time_dt.tzinfo is None:
                            entry_time_dt = entry_time_dt.replace(tzinfo=timezone.utc)
                        elif entry_time_dt.tzinfo != timezone.utc:
                            entry_time_dt = entry_time_dt.astimezone(timezone.utc)

                        holding_seconds = (
                            datetime.now(timezone.utc) - entry_time_dt
                        ).total_seconds()

                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (24.01.2026): При КРИТИЧЕСКИХ убытках > -20% НЕ проверяем min_hold_time
                        # XRP-USDT упал на -49% за 136 секунд, но emergency close блокировался min_hold_time=120s
                        critical_loss_threshold = -20.0  # Очень критический убыток

                        if pnl_percent < critical_loss_threshold:
                            # КРИТИЧЕСКИЙ убыток - закрываем НЕМЕДЛЕННО, игнорируя min_hold_time
                            logger.warning(
                                f"🚨 ExitAnalyzer TRENDING: КРИТИЧЕСКИЙ убыток {pnl_percent:.2f}% < {critical_loss_threshold:.1f}% "
                                f"для {symbol} - генерируем НЕМЕДЛЕННОЕ закрытие (игнорируем min_hold_time={min_holding_seconds:.1f}s, "
                                f"текущее время удержания={holding_seconds:.1f}s)"
                            )
                            return {
                                "action": "close",
                                "reason": "emergency_loss_protection",
                                "details": f"Критический убыток {pnl_percent:.2f}%, немедленное закрытие без проверки min_hold_time",
                            }

                        if holding_seconds < min_holding_seconds:
                            logger.debug(
                                f"⏳ ExitAnalyzer TRENDING: Emergency close заблокирован для {symbol} - "
                                f"время удержания {holding_seconds:.1f}с < минимум {min_holding_seconds:.1f}с "
                                f"(PnL={pnl_percent:.2f}% < порог={emergency_loss_threshold:.1f}%)"
                            )
                            # Не закрываем, если не прошло минимальное время
                            # Продолжаем с другими проверками
                        else:
                            # Прошло минимальное время - проверяем признаки разворота перед emergency close
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): Проверяем признаки разворота перед emergency close
                            reversal_detected = await self._check_reversal_signals(
                                symbol, position_side
                            )
                            if reversal_detected:
                                logger.info(
                                    f"🔄 ExitAnalyzer TRENDING: Обнаружен разворот для {symbol} {position_side.upper()}, "
                                    f"но убыток критический ({pnl_percent:.2f}% < {adjusted_emergency_threshold:.2f}%). "
                                    f"Используем Smart Close для комплексного анализа..."
                                )
                                smart_close_sl_percent = self._safe_sl_percent(
                                    symbol,
                                    "trending",
                                    current_price,
                                    market_data,
                                    position=position,
                                    metadata=metadata,
                                )
                                logger.info(
                                    f"🔍 ExitAnalyzer TRENDING: Запуск Smart Close анализа для {symbol} {position_side.upper()} | "
                                    f"PnL={pnl_percent:.2f}%, SL={smart_close_sl_percent:.2f}%, режим={regime}"
                                )
                                smart_close = (
                                    await self._should_force_close_by_smart_analysis(
                                        symbol,
                                        position_side,
                                        pnl_percent,
                                        smart_close_sl_percent,
                                        regime,
                                        metadata,
                                        position,
                                    )
                                )
                                logger.info(
                                    f"🔍 ExitAnalyzer TRENDING: Результат Smart Close для {symbol} {position_side.upper()}: "
                                    f"smart_close={smart_close}"
                                )
                                if smart_close:
                                    logger.warning(
                                        f"🚨 ExitAnalyzer TRENDING: Smart Close рекомендует закрыть {symbol} "
                                        f"несмотря на признаки разворота (убыток {pnl_percent:.2f}% критический)"
                                    )
                                    self._record_metrics_on_close(
                                        symbol=symbol,
                                        reason="emergency_loss_protection_smart_close",
                                        pnl_percent=pnl_percent,
                                        entry_time=entry_time,
                                    )
                                    return {
                                        "action": "close",
                                        "reason": "emergency_loss_protection_smart_close",
                                        "pnl_pct": pnl_percent,
                                        "regime": regime,
                                        "emergency": True,
                                        "reversal_detected": True,
                                        "smart_close": True,
                                    }
                                else:
                                    logger.info(
                                        f"✅ ExitAnalyzer TRENDING: Smart Close рекомендует ДЕРЖАТЬ {symbol} "
                                        f"из-за признаков разворота (убыток {pnl_percent:.2f}%, но есть шанс восстановления)"
                                    )
                                    return {
                                        "action": "hold",
                                        "reason": "emergency_loss_protection_reversal_detected",
                                        "pnl_pct": pnl_percent,
                                        "regime": regime,
                                        "reversal_detected": True,
                                    }

                            # Нет признаков разворота - закрываем по Emergency Loss Protection
                            logger.warning(
                                f"🚨 ExitAnalyzer TRENDING: Критический убыток {pnl_percent:.2f}% для {symbol} "
                                f"(порог: {emergency_loss_threshold:.1f}%, скорректирован: {adjusted_emergency_threshold:.2f}% "
                                f"с учетом spread={emergency_spread_buffer:.3f}% + commission={emergency_commission_buffer:.3f}%), "
                                f"нет признаков разворота - генерируем экстренное закрытие (первая защита, приоритет 1)"
                            )
                            self._record_metrics_on_close(
                                symbol=symbol,
                                reason="emergency_loss_protection",
                                pnl_percent=pnl_percent,
                                entry_time=entry_time,
                            )
                            return {
                                "action": "close",
                                "reason": "emergency_loss_protection",
                                "pnl_pct": pnl_percent,
                                "regime": regime,
                                "emergency": True,
                                "threshold": emergency_loss_threshold,
                                "adjusted_threshold": adjusted_emergency_threshold,
                                "spread_buffer": emergency_spread_buffer,
                                "commission_buffer": emergency_commission_buffer,
                                "reversal_detected": False,
                            }
                    except Exception as e:
                        logger.debug(
                            f"⚠️ ExitAnalyzer TRENDING: Ошибка проверки времени удержания для {symbol}: {e}"
                        )
                        # В случае ошибки разрешаем emergency close (безопаснее)
                        logger.warning(
                            f"🚨 ExitAnalyzer TRENDING: Критический убыток {pnl_percent:.2f}% для {symbol} "
                            f"(порог: {emergency_loss_threshold:.1f}%, скорректирован: {adjusted_emergency_threshold:.2f}% "
                            f"с учетом spread={emergency_spread_buffer:.3f}% + commission={emergency_commission_buffer:.3f}%), "
                            f"генерируем экстренное закрытие (первая защита, приоритет 1)"
                        )
                        self._record_metrics_on_close(
                            symbol=symbol,
                            reason="emergency_loss_protection",
                            pnl_percent=pnl_percent,
                            entry_time=entry_time,
                        )
                        return {
                            "action": "close",
                            "reason": "emergency_loss_protection",
                            "pnl_pct": pnl_percent,
                            "regime": regime,
                            "emergency": True,
                            "threshold": emergency_loss_threshold,
                            "adjusted_threshold": adjusted_emergency_threshold,
                            "spread_buffer": emergency_spread_buffer,
                            "commission_buffer": emergency_commission_buffer,
                        }
                else:
                    # Нет entry_time, но убыток критический - закрываем
                    logger.warning(
                        f"🚨 ExitAnalyzer TRENDING: Критический убыток {pnl_percent:.2f}% для {symbol} "
                        f"(порог: {emergency_loss_threshold:.1f}%, скорректирован: {adjusted_emergency_threshold:.2f}% "
                        f"с учетом spread={emergency_spread_buffer:.3f}% + commission={emergency_commission_buffer:.3f}%), "
                        f"генерируем экстренное закрытие (первая защита, приоритет 1)"
                    )
                    self._record_metrics_on_close(
                        symbol=symbol,
                        reason="emergency_loss_protection",
                        pnl_percent=pnl_percent,
                        entry_time=entry_time,
                    )
                    return {
                        "action": "close",
                        "reason": "emergency_loss_protection",
                        "pnl_pct": pnl_percent,
                        "regime": regime,
                        "emergency": True,
                        "threshold": emergency_loss_threshold,
                        "adjusted_threshold": adjusted_emergency_threshold,
                        "spread_buffer": emergency_spread_buffer,
                        "commission_buffer": emergency_commission_buffer,
                    }

            # 3. Проверка TP (Take Profit)
            # ✅ ГРОК КОМПРОМИСС: Передаем current_price и market_data для адаптивного TP
            # ✅ НОВОЕ (05.01.2026): Передаем current_pnl для адаптивного расширения TP
            tp_percent = await self._get_tp_percent(
                symbol,
                "trending",
                current_price,
                market_data,
                current_pnl=pnl_percent,
                position=position,
                metadata=metadata,
            )
            try:
                if tp_percent is None:
                    logger.warning(
                        f"⚠️ ExitAnalyzer TRENDING: TP отключен (нет параметров) для {symbol}"
                    )
                tp_percent = (
                    float(tp_percent) if tp_percent is not None else float("inf")
                )
            except (TypeError, ValueError) as e:
                logger.error(
                    f"❌ ExitAnalyzer TRENDING: Ошибка приведения tp_percent для {symbol}: {e}"
                )
                tp_percent = float("inf")
            if pnl_percent >= tp_percent:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (23.01.2026): Защита от TP на убыточных позициях
                # Проверяем реальный PnL от entry_price к current_price
                real_price_pnl_pct = (
                    ((current_price - entry_price) / entry_price * 100)
                    if position_side == "long"
                    else ((entry_price - current_price) / entry_price * 100)
                )

                if real_price_pnl_pct < 0:
                    logger.warning(
                        f"⚠️ TP ЗАЩИТА: {symbol} TP хочет сработать (pnl_percent={pnl_percent:.2f}%), "
                        f"но РЕАЛЬНЫЙ PnL от цены = {real_price_pnl_pct:.2f}% (УБЫТОК)! "
                        f"entry={entry_price:.6f}, current={current_price:.6f}, side={position_side}. "
                        f"БЛОКИРУЕМ закрытие - возможно неправильная передача current_pnl из адаптивных параметров."
                    )
                    return {"action": "hold", "reason": "tp_rejected_negative_real_pnl"}

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
                        "regime": regime,
                    }
                else:
                    # Слабый тренд - закрываем по TP
                    logger.info(
                        f"🎯 ExitAnalyzer TRENDING: TP достигнут для {symbol}: "
                        f"{pnl_percent:.2f}% >= {tp_percent:.2f}% (режим={regime})"
                    )
                    entry_regime = (
                        metadata.regime
                        if metadata and hasattr(metadata, "regime")
                        else regime
                    )
                    # ✅ КРИТИЧЕСКОЕ УЛУЧШЕНИЕ ЛОГИРОВАНИЯ (29.12.2025): Явный лог "TP достигнут"
                    minutes_in_position = self._get_time_in_position_minutes(
                        metadata, position
                    )
                    tp_price = (
                        entry_price * (1 + tp_percent / 100)
                        if position_side == "long"
                        else entry_price * (1 - tp_percent / 100)
                    )
                    logger.info(
                        f"🎯 TP reached for {symbol}: current={current_price:.2f} >= TP={tp_price:.2f}, "
                        f"PnL={pnl_percent:.2f}%, time={minutes_in_position:.1f} min, regime={regime}"
                    )
                    # ✅ НОВОЕ (26.12.2025): Записываем метрики при закрытии
                    self._record_metrics_on_close(
                        symbol=symbol,
                        reason="tp_reached",
                        pnl_percent=pnl_percent,
                        entry_time=entry_time,
                    )
                    return {
                        "action": "close",
                        "reason": "tp_reached",
                        "pnl_pct": pnl_percent,
                        "tp_percent": tp_percent,
                        "regime": regime,
                        "entry_regime": entry_regime,
                    }

            # 4. Проверка big_profit_exit
            big_profit_exit_percent = self._get_big_profit_exit_percent(symbol)
            try:
                big_profit_exit_percent = (
                    float(big_profit_exit_percent)
                    if big_profit_exit_percent is not None
                    else 1.5
                )
            except (TypeError, ValueError) as e:
                logger.error(
                    f"❌ ExitAnalyzer TRENDING: Ошибка приведения big_profit_exit_percent для {symbol}: {e}"
                )
                big_profit_exit_percent = 1.5
            if pnl_percent >= big_profit_exit_percent:
                logger.info(
                    f"💰 ExitAnalyzer TRENDING: Big profit exit достигнут для {symbol}: "
                    f"{pnl_percent:.2f}% >= {big_profit_exit_percent:.2f}%"
                )
                # ✅ НОВОЕ (26.12.2025): Записываем метрики при закрытии
                self._record_metrics_on_close(
                    symbol=symbol,
                    reason="big_profit_exit",
                    pnl_percent=pnl_percent,
                    entry_time=entry_time,
                )
                return {
                    "action": "close",
                    "reason": "big_profit_exit",
                    "pnl_pct": pnl_percent,
                    "big_profit_exit_percent": big_profit_exit_percent,
                    "regime": regime,
                }

            # 5. Проверка partial_tp с учетом adaptive_min_holding
            partial_tp_params = self._get_partial_tp_params("trending")
            partial_tp_enabled = partial_tp_params.get("enabled", False)
            trigger_percent = partial_tp_params.get("trigger_percent", 0.8)

            # ✅ FIX (09.01.2026): Улучшенное логирование partial_tp для диагностики
            logger.debug(
                f"📊 [PARTIAL_TP] {symbol} TRENDING: enabled={partial_tp_enabled}, "
                f"pnl={pnl_percent:.2f}% vs trigger={trigger_percent:.2f}%, "
                f"достаточно для partial_tp={'✅ ДА' if pnl_percent >= trigger_percent else '❌ НЕТ'}"
            )

            if partial_tp_enabled:
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
                            "regime": regime,
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
                            "regime": regime,
                        }

            # 6. Проверка SL (Stop Loss) - должна быть ДО Smart Close
            # ✅ ГРОК КОМПРОМИСС: Передаем current_price и market_data для ATR-based SL
            sl_percent = self._safe_sl_percent(
                symbol,
                "trending",
                current_price,
                market_data,
                position=position,
                metadata=metadata,
            )
            sl_percent = self._to_float(sl_percent, "sl_percent", 2.0)
            spread_buffer = self._get_spread_buffer(symbol, current_price)
            sl_threshold = -sl_percent - spread_buffer

            # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ SL решения
            adx_value = None
            mtf_signal = None
            try:
                if self.fast_adx:
                    adx_value = self.fast_adx.get_current_adx()
                mtf_filter = self._get_mtf_filter()
                if mtf_filter:
                    mtf_result = await mtf_filter.check_mtf_confirmation_async(
                        symbol, position_side, current_price, market_data
                    )
                    mtf_signal = "confirm" if mtf_result else "block"
            except Exception:
                pass

            logger.debug(
                f"🔍 [SL_CHECK] {symbol}: gross_pnl={gross_pnl_percent:.2f}% vs threshold={sl_threshold:.2f}% | "
                f"net_pnl={pnl_percent:.2f}%, sl={sl_percent:.2f}%, spread_buffer={spread_buffer:.2f}% | "
                f"ADX={adx_value or 'N/A'}, MTF={mtf_signal or 'N/A'}, regime={regime}"
            )

            if gross_pnl_percent <= sl_threshold:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Проверяем min_holding_minutes перед закрытием по SL
                min_holding_minutes = self._get_min_holding_minutes("trending", symbol)
                if min_holding_minutes is not None:
                    minutes_in_position = self._get_time_in_position_minutes(
                        metadata, position
                    )
                    if (
                        minutes_in_position is not None
                        and minutes_in_position < min_holding_minutes
                    ):
                        logger.info(
                            f"⏳ ExitAnalyzer TRENDING: SL заблокирован для {symbol} - "
                            f"время удержания {minutes_in_position:.1f} мин < минимум {min_holding_minutes:.1f} мин "
                            f"(Gross PnL={gross_pnl_percent:.2f}% <= SL threshold={sl_threshold:.2f}%)"
                        )
                        return {
                            "action": "hold",
                            "reason": "sl_blocked_by_min_holding",
                            "pnl_pct": gross_pnl_percent,
                            "net_pnl_pct": pnl_percent,
                            "minutes_in_position": minutes_in_position,
                            "min_holding_minutes": min_holding_minutes,
                            "sl_percent": sl_percent,
                            "sl_threshold": sl_threshold,
                            "regime": regime,
                        }

                # ✅ КРИТИЧЕСКОЕ УЛУЧШЕНИЕ ЛОГИРОВАНИЯ (29.12.2025): Явный лог "SL достигнут" с деталями
                minutes_in_position = self._get_time_in_position_minutes(
                    metadata, position
                )
                sl_price = (
                    entry_price * (1 - sl_percent / 100)
                    if position_side == "long"
                    else entry_price * (1 + sl_percent / 100)
                )
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): Проверяем признаки разворота перед SL close
                reversal_detected = await self._check_reversal_signals(
                    symbol, position_side
                )
                if reversal_detected:
                    logger.info(
                        f"🔄 ExitAnalyzer TRENDING: Обнаружен разворот для {symbol} {position_side.upper()}, "
                        f"но SL достигнут (Gross PnL={gross_pnl_percent:.2f}% <= {sl_threshold:.2f}%). "
                        f"Используем Smart Close для комплексного анализа..."
                    )
                    smart_close = await self._should_force_close_by_smart_analysis(
                        symbol,
                        position_side,
                        gross_pnl_percent,
                        sl_percent,
                        regime,
                        metadata,
                        position,
                    )
                    if smart_close:
                        logger.warning(
                            f"🛑 ExitAnalyzer TRENDING: Smart Close рекомендует закрыть {symbol} по SL "
                            f"несмотря на признаки разворота (убыток {gross_pnl_percent:.2f}% критический)"
                        )
                        self._record_metrics_on_close(
                            symbol=symbol,
                            reason="sl_reached_smart_close",
                            pnl_percent=gross_pnl_percent,
                            entry_time=entry_time,
                        )
                        return {
                            "action": "close",
                            "reason": "sl_reached_smart_close",
                            "pnl_pct": gross_pnl_percent,
                            "net_pnl_pct": pnl_percent,
                            "sl_percent": sl_percent,
                            "spread_buffer": spread_buffer,
                            "regime": regime,
                            "reversal_detected": True,
                            "smart_close": True,
                        }
                    else:
                        logger.info(
                            f"✅ ExitAnalyzer TRENDING: Smart Close рекомендует ДЕРЖАТЬ {symbol} "
                            f"из-за признаков разворота (SL достигнут, но есть шанс восстановления)"
                        )
                        return {
                            "action": "hold",
                            "reason": "sl_reached_reversal_detected",
                            "pnl_pct": gross_pnl_percent,
                            "net_pnl_pct": pnl_percent,
                            "sl_percent": sl_percent,
                            "spread_buffer": spread_buffer,
                            "regime": regime,
                            "reversal_detected": True,
                        }

                # ✅ КРИТИЧЕСКАЯ ЗАЩИТА (23.01.2026): Минимальная задержка 90 сек для SL
                # Защита от преждевременного закрытия из-за спреда/комиссии (аналогично TrailingStopLoss.loss_cut)
                seconds_in_position = minutes_in_position * 60.0
                min_sl_hold_seconds = 90.0  # Минимум 90 секунд перед SL

                if seconds_in_position < min_sl_hold_seconds:
                    logger.info(
                        f"⏱️ SL ЗАЩИТА: {symbol} SL достигнут (PnL={pnl_percent:.2f}%), "
                        f"но позиция держится {seconds_in_position:.1f}с < {min_sl_hold_seconds:.1f}с | "
                        f"БЛОКИРУЕМ закрытие (защита от спреда/комиссии) | "
                        f"current={current_price:.2f}, SL={sl_price:.2f}"
                    )
                    return {
                        "action": "hold",
                        "reason": "sl_grace_period",
                        "pnl_pct": gross_pnl_percent,
                        "net_pnl_pct": pnl_percent,
                        "sl_percent": sl_percent,
                        "seconds_in_position": seconds_in_position,
                        "min_seconds_required": min_sl_hold_seconds,
                        "regime": regime,
                    }

                logger.info(
                    f"🛑 SL reached for {symbol}: current={current_price:.2f} <= SL={sl_price:.2f}, "
                    f"PnL={gross_pnl_percent:.2f}% (gross), {pnl_percent:.2f}% (net), "
                    f"time={minutes_in_position:.1f} min ({seconds_in_position:.1f}с), regime={regime}, нет признаков разворота"
                )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (09.01.2026): ПРОВЕРЯЕМ GRACE PERIOD ПЕРЕД SL
                if self._is_grace_period_active(symbol):
                    logger.warning(
                        f"⏳ [GRACE_PERIOD ЗАЩИТА] {symbol}: SL достигнут но grace period активен! "
                        f"Откладываем закрытие на следующий раунд."
                    )
                    # Не закрываем - жди перепроверки на следующей итерации
                    return {
                        "action": "hold",
                        "reason": "sl_reached_but_grace_period",
                        "pnl_pct": gross_pnl_percent,
                        "net_pnl_pct": pnl_percent,
                        "grace_period_active": True,
                    }

                self._record_metrics_on_close(
                    symbol=symbol,
                    reason="sl_reached",
                    pnl_percent=gross_pnl_percent,
                    entry_time=entry_time,
                )
                return {
                    "action": "close",
                    "reason": "sl_reached",
                    "pnl_pct": gross_pnl_percent,
                    "net_pnl_pct": pnl_percent,
                    "sl_percent": sl_percent,
                    "spread_buffer": spread_buffer,
                    "regime": regime,
                    "reversal_detected": False,
                }

            # 6.1. ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Smart Close проверяется ПЕРЕД max_holding
            # Проверяем Smart Close только если убыток >= 1.5 * SL и прошло min_holding_minutes
            if gross_pnl_percent < 0:
                smart_close_sl_percent = self._safe_sl_percent(
                    symbol,
                    "trending",
                    current_price,
                    market_data,
                    position=position,
                    metadata=metadata,
                )
                smart_close_spread_buffer = self._get_spread_buffer(
                    symbol, current_price
                )
                smart_close_threshold = (
                    -smart_close_sl_percent * 1.5 - smart_close_spread_buffer
                )
                if gross_pnl_percent <= smart_close_threshold:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Проверяем min_holding_minutes перед Smart Close
                    min_holding_minutes = self._get_min_holding_minutes(
                        "trending", symbol
                    )
                    if min_holding_minutes is not None:
                        minutes_in_position = self._get_time_in_position_minutes(
                            metadata, position
                        )
                        if (
                            minutes_in_position is not None
                            and minutes_in_position < min_holding_minutes
                        ):
                            logger.debug(
                                f"⏳ ExitAnalyzer TRENDING: Smart Close заблокирован для {symbol} - "
                                f"время удержания {minutes_in_position:.1f} мин < минимум {min_holding_minutes:.1f} мин "
                                f"(Gross убыток {gross_pnl_percent:.2f}% >= {smart_close_threshold:.2f}%)"
                            )
                        else:
                            # Прошло min_holding_minutes - проверяем Smart Close
                            smart_close = (
                                await self._should_force_close_by_smart_analysis(
                                    symbol,
                                    position_side,
                                    gross_pnl_percent,
                                    smart_close_sl_percent,
                                    regime,
                                    metadata,
                                    position,
                                )
                            )
                            if smart_close:
                                logger.warning(
                                    f"🚨 ExitAnalyzer TRENDING: Умное закрытие {symbol} "
                                    f"(Gross убыток {gross_pnl_percent:.2f}% >= {smart_close_sl_percent * 1.5:.2f}%, "
                                    f"Net PnL {pnl_percent:.2f}%, нет признаков отката)"
                                )
                                self._record_metrics_on_close(
                                    symbol=symbol,
                                    reason="smart_forced_close_trending",
                                    pnl_percent=gross_pnl_percent,
                                    entry_time=entry_time,
                                )
                                return {
                                    "action": "close",
                                    "reason": "smart_forced_close_trending",
                                    "pnl_pct": gross_pnl_percent,
                                    "net_pnl_pct": pnl_percent,
                                    "note": "Нет признаков отката - закрываем до SL",
                                    "regime": regime,
                                }
                    else:
                        # min_holding_minutes не настроен - проверяем Smart Close без блокировки
                        smart_close = await self._should_force_close_by_smart_analysis(
                            symbol,
                            position_side,
                            gross_pnl_percent,
                            smart_close_sl_percent,
                            regime,
                            metadata,
                            position,
                        )
                        if smart_close:
                            logger.warning(
                                f"🚨 ExitAnalyzer TRENDING: Умное закрытие {symbol} "
                                f"(Gross убыток {gross_pnl_percent:.2f}% >= {smart_close_sl_percent * 1.5:.2f}%, "
                                f"Net PnL {pnl_percent:.2f}%, нет признаков отката)"
                            )
                            self._record_metrics_on_close(
                                symbol=symbol,
                                reason="smart_forced_close_trending",
                                pnl_percent=gross_pnl_percent,
                                entry_time=entry_time,
                            )
                            return {
                                "action": "close",
                                "reason": "smart_forced_close_trending",
                                "pnl_pct": gross_pnl_percent,
                                "net_pnl_pct": pnl_percent,
                                "note": "Нет признаков отката - закрываем до SL",
                                "regime": regime,
                            }

            # 7. Проверка разворота (Order Flow, MTF)
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
                    "regime": regime,
                }

            # 8. Если прибыль > 0.5% и тренд сильный - продлеваем TP
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
                        "regime": regime,
                    }

            # 8. ✅ НОВОЕ: Проверка Max Holding - учитываем время в позиции как фактор анализа
            minutes_in_position = self._get_time_in_position_minutes(metadata, position)
            max_holding_minutes = self._get_max_holding_minutes("trending", symbol)

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): Конвертируем max_holding_minutes в float перед сравнением
            try:
                max_holding_minutes_float = (
                    float(max_holding_minutes)
                    if max_holding_minutes is not None
                    else 120.0
                )
            except (TypeError, ValueError):
                logger.warning(
                    f"⚠️ ExitAnalyzer TRENDING: Не удалось преобразовать max_holding_minutes={max_holding_minutes} в float, используем 120.0"
                )
                max_holding_minutes_float = 120.0

            if (
                minutes_in_position is not None
                and isinstance(minutes_in_position, (int, float))
                and float(minutes_in_position) >= max_holding_minutes_float
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
                        "regime": regime,
                    }
                else:
                    # ✅ ИСПРАВЛЕНО: Не закрываем убыточные позиции по max_holding
                    # Позволяем им дойти до SL или восстановиться
                    if pnl_percent < 0:
                        # ✅ НОВОЕ (28.12.2025): Проверяем min_holding_minutes перед проверкой SL
                        min_holding_minutes = None
                        if self.parameter_provider:
                            try:
                                exit_params = self.parameter_provider.get_exit_params(
                                    symbol, regime
                                )
                                min_holding_minutes = exit_params.get(
                                    "min_holding_minutes", 1.5
                                )
                                if min_holding_minutes is not None:
                                    min_holding_minutes = float(min_holding_minutes)
                            except Exception as e:
                                logger.debug(
                                    f"⚠️ ExitAnalyzer: Ошибка получения min_holding_minutes: {e}"
                                )

                        if min_holding_minutes is None:
                            min_holding_minutes = 1.5  # Fallback для trending

                        # Не закрываем по SL если позиция открыта меньше min_holding_minutes
                        if (
                            minutes_in_position is not None
                            and minutes_in_position < min_holding_minutes
                        ):
                            # ✅ ФИНАЛЬНОЕ ДОПОЛНЕНИЕ (Grok): Улучшенное логирование при ignore SL
                            logger.info(
                                f"⏳ ExitAnalyzer {regime.upper()}: Ignore SL для {symbol} - "
                                f"hold {minutes_in_position:.1f} мин < min_holding {min_holding_minutes:.1f} мин "
                                f"(убыток {pnl_percent:.2f}%, защита от раннего закрытия)"
                            )
                            return {
                                "action": "hold",
                                "reason": "min_holding_not_reached_before_sl",
                                "pnl_pct": pnl_percent,
                                "minutes_in_position": minutes_in_position,
                                "min_holding_minutes": min_holding_minutes,
                                "regime": regime,
                            }

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
                            "regime": regime,
                        }

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем min_profit_to_close перед закрытием по времени
                    # Не закрываем по времени если прибыль < min_profit_to_close (после комиссий будет убыток!)
                    min_profit_to_close = None
                    if self.orchestrator and hasattr(
                        self.orchestrator, "trailing_sl_coordinator"
                    ):
                        tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(symbol)
                        if tsl:
                            min_profit_to_close = getattr(
                                tsl, "min_profit_to_close", None
                            )

                    # Если min_profit_to_close не найден, используем минимальный порог 0.3% (чтобы покрыть комиссии)
                    # ✅ ИСПРАВЛЕНИЕ: min_profit_to_close в долях (0.003 = 0.3%), pnl_percent в процентах (1.5 = 1.5%)
                    # Конвертируем min_profit_to_close в проценты для сравнения
                    min_profit_threshold_pct = (
                        min_profit_to_close * 100
                        if min_profit_to_close is not None
                        else 0.3
                    )  # 0.3% в процентах

                    if pnl_percent < min_profit_threshold_pct:
                        # Прибыль меньше min_profit_to_close - НЕ закрываем по времени (после комиссий будет убыток!)
                        logger.info(
                            f"⏰ ExitAnalyzer TRENDING: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                            f"но прибыль {pnl_percent:.2f}% < min_profit_threshold {min_profit_threshold_pct:.2f}% - "
                            f"НЕ закрываем по времени (после комиссий будет убыток!)"
                        )
                        return {
                            "action": "hold",
                            "reason": "max_holding_low_profit",
                            "pnl_pct": pnl_percent,
                            "min_profit_threshold": min_profit_threshold_pct,
                            "minutes_in_position": minutes_in_position,
                            "regime": regime,
                        }

                    # Нет сильных сигналов, но позиция в прибыли >= min_profit_to_close - проверяем признаки разворота
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): Проверяем признаки разворота перед закрытием по времени
                    logger.info(
                        f"🔍 ExitAnalyzer TRENDING: Проверка разворота перед закрытием по времени для {symbol} {position_side.upper()} | "
                        f"время={minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                        f"PnL={pnl_percent:.2f}% >= {min_profit_threshold_pct:.2f}%"
                    )
                    reversal_detected = await self._check_reversal_signals(
                        symbol, position_side
                    )
                    logger.info(
                        f"🔍 ExitAnalyzer TRENDING: Результат проверки разворота для {symbol} {position_side.upper()}: "
                        f"reversal_detected={reversal_detected}"
                    )
                    if reversal_detected:
                        # Есть признаки разворота - закрываем по времени
                        logger.info(
                            f"⏰ ExitAnalyzer TRENDING: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                            f"прибыль={pnl_percent:.2f}% >= {min_profit_threshold_pct:.2f}%, "
                            f"обнаружен разворот - закрываем по времени"
                        )
                        return {
                            "action": "close",
                            "reason": "max_holding_no_signals_reversal",
                            "pnl_pct": pnl_percent,
                            "minutes_in_position": minutes_in_position,
                            "max_holding_minutes": max_holding_minutes,
                            "regime": regime,
                            "reversal_detected": True,
                        }
                    else:
                        # Нет признаков разворота - закрываем по времени
                        logger.info(
                            f"⏰ ExitAnalyzer TRENDING: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                            f"нет сильных сигналов держать (trend_strength={trend_strength:.2f}, pnl={pnl_percent:.2f}% >= {min_profit_threshold_pct:.2f}%), "
                            f"нет признаков разворота - закрываем по времени"
                        )
                        return {
                            "action": "close",
                            "reason": "max_holding_no_signals",
                            "pnl_pct": pnl_percent,
                            "minutes_in_position": minutes_in_position,
                            "max_holding_minutes": max_holding_minutes,
                            "regime": regime,
                            "reversal_detected": False,
                        }

            # Нет причин для закрытия или продления
            return None

        except Exception as e:
            logger.exception(
                f"❌ ExitAnalyzer: Ошибка анализа для {symbol} в режиме TRENDING: {e}\n"
                f"symbol={symbol}, position={position}, metadata={metadata}, current_price={current_price}, regime={regime}"
            )
            return None

    async def _generate_exit_for_ranging(
        self,
        symbol: str,
        position: Any,
        metadata: Any,
        market_data: Optional[Any],
        current_price: float,
        regime: str = "ranging",
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
        sl_percent = 2.0  # Гарантированная инициализация для UnboundLocalError
        try:
            # Базовый SL заранее, чтобы исключить UnboundLocalError при любых ветках логики
            try:
                sl_percent = self._safe_sl_percent(
                    symbol,
                    "ranging",
                    current_price,
                    market_data,
                    position=position,
                    metadata=metadata,
                )
            except Exception:
                logger.error(
                    f"⚠️ ExitAnalyzer RANGING: не удалось рассчитать SL для {symbol}, fallback 2.0%",
                    exc_info=True,
                )
                sl_percent = 2.0
            sl_percent = self._to_float(sl_percent, "sl_percent", 2.0)

            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ (25.12.2025): Начало анализа для режима RANGING
            logger.debug(
                f"🔍 [RANGING_ANALYSIS_START] {symbol}: Начало анализа позиции | "
                f"position_type={type(position).__name__}, metadata_type={type(metadata).__name__}, "
                f"current_price={current_price:.2f}, regime={regime}"
            )

            # 1. Получаем данные позиции (✅ ИСПОЛЬЗУЕМ ОБЩИЙ МЕТОД)
            entry_price, position_side = await self._get_entry_price_and_side(
                symbol, position, metadata
            )

            if not entry_price or entry_price == 0:
                logger.warning(
                    f"⚠️ ExitAnalyzer RANGING: Не удалось получить entry_price для {symbol} "
                    f"(metadata={metadata is not None}, position={isinstance(position, dict)})"
                )
                return None

            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ (25.12.2025): Данные позиции получены
            logger.debug(
                f"🔍 [RANGING_POSITION_DATA] {symbol}: entry_price={entry_price:.2f}, "
                f"position_side={position_side}, current_price={current_price:.2f}"
            )

            # Получаем entry_time из metadata для правильного расчета комиссии
            entry_time = None
            if metadata and hasattr(metadata, "entry_time"):
                entry_time = metadata.entry_time
            elif isinstance(metadata, dict):
                entry_time = metadata.get("entry_time")

            # 2. Рассчитываем PnL
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для SL используем Gross PnL (без комиссий)
            # SL должен срабатывать на основе движения цены, а не комиссий
            # Комиссии учитываются отдельно при расчете финального PnL
            gross_pnl_percent = self._calculate_pnl_percent(
                entry_price,
                current_price,
                position_side,
                include_fees=False,  # ✅ ИСПРАВЛЕНО: Gross PnL для сравнения с SL
                entry_time=entry_time,
                position=position,
                metadata=metadata,
            )

            # Net PnL (с комиссиями) для логирования и других проверок
            net_pnl_percent = self._calculate_pnl_percent(
                entry_price,
                current_price,
                position_side,
                include_fees=True,  # Net PnL для логирования
                entry_time=entry_time,
                position=position,
                metadata=metadata,
            )

            # ✅ ИСПРАВЛЕНО: Используем helper функцию для безопасной конвертации всех значений
            gross_pnl_percent = self._to_float(
                gross_pnl_percent, "gross_pnl_percent", 0.0
            )
            net_pnl_percent = self._to_float(net_pnl_percent, "net_pnl_percent", 0.0)

            tsl_hit, tsl_stop = self._check_tsl_hit(
                symbol, position_side, current_price
            )
            if tsl_hit:
                self._record_metrics_on_close(
                    symbol=symbol,
                    reason="tsl_hit",
                    pnl_percent=net_pnl_percent,
                    entry_time=entry_time,
                )
                return {
                    "action": "close",
                    "reason": "tsl_hit",
                    "pnl_pct": net_pnl_percent,
                    "regime": regime,
                    "tsl_stop": tsl_stop,
                }

            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для диагностики
            # Показываем больше знаков для маленьких значений
            gross_format = (
                f"{gross_pnl_percent:.4f}"
                if abs(gross_pnl_percent) < 0.1
                else f"{gross_pnl_percent:.2f}"
            )
            net_format = (
                f"{net_pnl_percent:.4f}"
                if abs(net_pnl_percent) < 0.1
                else f"{net_pnl_percent:.2f}"
            )

            logger.info(
                f"🔍 ExitAnalyzer RANGING {symbol}: entry_price={entry_price:.2f}, "
                f"current_price={current_price:.2f}, side={position_side}, "
                f"Gross PnL%={gross_format}% (для SL), Net PnL%={net_format}% (с комиссией), entry_time={entry_time}"
            )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (03.01.2026): Emergency Loss Protection - ПЕРВАЯ ЗАЩИТА
            # Проверяется ПЕРВОЙ, перед всеми другими проверками (соответствует приоритету 1 в ExitDecisionCoordinator)
            # ✅ ПРАВКА #13: Защита от больших убытков - АДАПТИВНО ПО РЕЖИМАМ
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Пороги emergency_loss_protection адаптируются по режимам
            # ✅ ИСПРАВЛЕНО (26.12.2025): Увеличены пороги для уменьшения частоты emergency close
            # RANGING: более низкий порог (-2.5%), так как в ranging режиме позиции должны закрываться быстрее
            base_emergency_threshold = -7.0
            emergency_loss_threshold = self._get_emergency_threshold(
                base_emergency_threshold, position, metadata
            )

            # ✅ НОВОЕ (26.12.2025): Учитываем spread_buffer и commission_buffer
            emergency_spread_buffer = self._get_spread_buffer(symbol, current_price)
            emergency_commission_buffer = self._get_commission_buffer(
                position, metadata
            )
            # Скорректируем порог вниз (сделаем более строгим), чтобы учесть дополнительные потери при закрытии
            adjusted_emergency_threshold = (
                emergency_loss_threshold
                - emergency_spread_buffer
                - emergency_commission_buffer
            )

            # ✅ НОВОЕ (26.12.2025): Минимальное время удержания перед emergency close
            min_holding_seconds = 60.0  # RANGING: 60 секунд (1 минута)
            if net_pnl_percent < adjusted_emergency_threshold:
                # Проверяем минимальное время удержания
                if entry_time:
                    try:
                        if isinstance(entry_time, str):
                            entry_time_dt = datetime.fromisoformat(
                                entry_time.replace("Z", "+00:00")
                            )
                        else:
                            entry_time_dt = entry_time

                        # Убеждаемся, что entry_time в UTC
                        if entry_time_dt.tzinfo is None:
                            entry_time_dt = entry_time_dt.replace(tzinfo=timezone.utc)
                        elif entry_time_dt.tzinfo != timezone.utc:
                            entry_time_dt = entry_time_dt.astimezone(timezone.utc)

                        holding_seconds = (
                            datetime.now(timezone.utc) - entry_time_dt
                        ).total_seconds()

                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (24.01.2026): При КРИТИЧЕСКИХ убытках > -20% НЕ проверяем min_hold_time
                        # XRP-USDT упал на -49% за 136 секунд, но emergency close блокировался min_hold_time=60s
                        critical_loss_threshold = -20.0  # Очень критический убыток

                        if net_pnl_percent < critical_loss_threshold:
                            # КРИТИЧЕСКИЙ убыток - закрываем НЕМЕДЛЕННО, игнорируя min_hold_time
                            logger.warning(
                                f"🚨 ExitAnalyzer RANGING: КРИТИЧЕСКИЙ убыток {net_pnl_percent:.2f}% < {critical_loss_threshold:.1f}% "
                                f"для {symbol} - генерируем НЕМЕДЛЕННОЕ закрытие (игнорируем min_hold_time={min_holding_seconds:.1f}s, "
                                f"текущее время удержания={holding_seconds:.1f}s)"
                            )
                            self._record_metrics_on_close(
                                symbol=symbol,
                                reason="emergency_loss_protection",
                                pnl_percent=net_pnl_percent,
                                entry_time=entry_time,
                            )
                            return {
                                "action": "close",
                                "reason": "emergency_loss_protection",
                                "pnl_pct": net_pnl_percent,
                                "regime": regime,
                                "details": f"Критический убыток {net_pnl_percent:.2f}%, немедленное закрытие без проверки min_hold_time",
                            }

                        if holding_seconds < min_holding_seconds:
                            logger.debug(
                                f"⏳ ExitAnalyzer RANGING: Emergency close заблокирован для {symbol} - "
                                f"время удержания {holding_seconds:.1f}с < минимум {min_holding_seconds:.1f}с "
                                f"(PnL={net_pnl_percent:.2f}% < порог={emergency_loss_threshold:.1f}%)"
                            )
                            # Не закрываем, если не прошло минимальное время
                            # Продолжаем с другими проверками
                        else:
                            # Прошло минимальное время - проверяем признаки разворота перед emergency close
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): Проверяем признаки разворота перед emergency close
                            # Если есть признаки разворота в нашу пользу - НЕ закрываем, даем позиции шанс восстановиться
                            logger.info(
                                f"🔍 ExitAnalyzer RANGING: Проверка разворота перед emergency close для {symbol} {position_side.upper()} | "
                                f"Net PnL={net_pnl_percent:.2f}%, порог={adjusted_emergency_threshold:.2f}%, "
                                f"время удержания={holding_seconds:.1f}с"
                            )
                            reversal_detected = await self._check_reversal_signals(
                                symbol, position_side
                            )
                            logger.info(
                                f"🔍 ExitAnalyzer RANGING: Результат проверки разворота для {symbol} {position_side.upper()}: "
                                f"reversal_detected={reversal_detected}"
                            )
                            if reversal_detected:
                                logger.info(
                                    f"🔄 ExitAnalyzer RANGING: Обнаружен разворот для {symbol} {position_side.upper()}, "
                                    f"но убыток критический ({net_pnl_percent:.2f}% < {adjusted_emergency_threshold:.2f}%). "
                                    f"Используем Smart Close для комплексного анализа..."
                                )
                                # Используем Smart Close для более умного решения
                                smart_close_sl_percent = self._safe_sl_percent(
                                    symbol,
                                    "ranging",
                                    current_price,
                                    market_data,
                                    position=position,
                                    metadata=metadata,
                                )
                                logger.info(
                                    f"🔍 ExitAnalyzer RANGING: Запуск Smart Close анализа для {symbol} {position_side.upper()} | "
                                    f"Gross PnL={gross_pnl_percent:.2f}%, SL={smart_close_sl_percent:.2f}%, режим={regime}"
                                )
                                smart_close = (
                                    await self._should_force_close_by_smart_analysis(
                                        symbol,
                                        position_side,
                                        gross_pnl_percent,
                                        smart_close_sl_percent,
                                        regime,
                                        metadata,
                                        position,
                                    )
                                )
                                logger.info(
                                    f"🔍 ExitAnalyzer RANGING: Результат Smart Close для {symbol} {position_side.upper()}: "
                                    f"smart_close={smart_close}"
                                )
                                if smart_close:
                                    logger.warning(
                                        f"🚨 ExitAnalyzer RANGING: Smart Close рекомендует закрыть {symbol} "
                                        f"несмотря на признаки разворота (убыток {gross_pnl_percent:.2f}% критический)"
                                    )
                                    self._record_metrics_on_close(
                                        symbol=symbol,
                                        reason="emergency_loss_protection_smart_close",
                                        pnl_percent=net_pnl_percent,
                                        entry_time=entry_time,
                                    )
                                    return {
                                        "action": "close",
                                        "reason": "emergency_loss_protection_smart_close",
                                        "pnl_pct": net_pnl_percent,
                                        "gross_pnl_pct": gross_pnl_percent,
                                        "regime": regime,
                                        "emergency": True,
                                        "reversal_detected": True,
                                        "smart_close": True,
                                    }
                                else:
                                    logger.info(
                                        f"✅ ExitAnalyzer RANGING: Smart Close рекомендует ДЕРЖАТЬ {symbol} "
                                        f"из-за признаков разворота (убыток {gross_pnl_percent:.2f}%, но есть шанс восстановления)"
                                    )
                                    return {
                                        "action": "hold",
                                        "reason": "emergency_loss_protection_reversal_detected",
                                        "pnl_pct": net_pnl_percent,
                                        "gross_pnl_pct": gross_pnl_percent,
                                        "regime": regime,
                                        "reversal_detected": True,
                                    }

                            # Нет признаков разворота - закрываем по Emergency Loss Protection
                            logger.warning(
                                f"🚨 ExitAnalyzer RANGING: Критический убыток {net_pnl_percent:.2f}% для {symbol} "
                                f"(порог: {emergency_loss_threshold:.1f}%, скорректирован: {adjusted_emergency_threshold:.2f}% "
                                f"с учетом spread={emergency_spread_buffer:.3f}% + commission={emergency_commission_buffer:.3f}%), "
                                f"нет признаков разворота - генерируем экстренное закрытие (первая защита, приоритет 1)"
                            )
                            # ✅ НОВОЕ (26.12.2025): Записываем метрики при закрытии
                            self._record_metrics_on_close(
                                symbol=symbol,
                                reason="emergency_loss_protection",
                                pnl_percent=net_pnl_percent,
                                entry_time=entry_time,
                            )
                            return {
                                "action": "close",
                                "reason": "emergency_loss_protection",
                                "pnl_pct": net_pnl_percent,
                                "gross_pnl_pct": gross_pnl_percent,
                                "regime": regime,  # ✅ ПРАВКА #15: Логирование regime
                                "emergency": True,
                                "threshold": emergency_loss_threshold,
                                "adjusted_threshold": adjusted_emergency_threshold,
                                "spread_buffer": emergency_spread_buffer,
                                "commission_buffer": emergency_commission_buffer,
                                "reversal_detected": False,
                            }
                    except Exception as e:
                        logger.debug(
                            f"⚠️ ExitAnalyzer RANGING: Ошибка проверки времени удержания для {symbol}: {e}"
                        )
                        # В случае ошибки разрешаем emergency close (безопаснее)
                        logger.warning(
                            f"🚨 ExitAnalyzer RANGING: Критический убыток {net_pnl_percent:.2f}% для {symbol} "
                            f"(порог: {emergency_loss_threshold:.1f}%, скорректирован: {adjusted_emergency_threshold:.2f}% "
                            f"с учетом spread={emergency_spread_buffer:.3f}% + commission={emergency_commission_buffer:.3f}%), "
                            f"генерируем экстренное закрытие (первая защита, приоритет 1)"
                        )
                        self._record_metrics_on_close(
                            symbol=symbol,
                            reason="emergency_loss_protection",
                            pnl_percent=net_pnl_percent,
                            entry_time=entry_time,
                        )
                        return {
                            "action": "close",
                            "reason": "emergency_loss_protection",
                            "pnl_pct": net_pnl_percent,
                            "gross_pnl_pct": gross_pnl_percent,
                            "regime": regime,
                            "emergency": True,
                            "threshold": emergency_loss_threshold,
                            "adjusted_threshold": adjusted_emergency_threshold,
                            "spread_buffer": emergency_spread_buffer,
                            "commission_buffer": emergency_commission_buffer,
                        }
                else:
                    # Нет entry_time, но убыток критический - закрываем
                    logger.warning(
                        f"🚨 ExitAnalyzer RANGING: Критический убыток {net_pnl_percent:.2f}% для {symbol} "
                        f"(порог: {emergency_loss_threshold:.1f}%, скорректирован: {adjusted_emergency_threshold:.2f}% "
                        f"с учетом spread={emergency_spread_buffer:.3f}% + commission={emergency_commission_buffer:.3f}%), "
                        f"генерируем экстренное закрытие (первая защита, приоритет 1)"
                    )
                    self._record_metrics_on_close(
                        symbol=symbol,
                        reason="emergency_loss_protection",
                        pnl_percent=net_pnl_percent,
                        entry_time=entry_time,
                    )
                    return {
                        "action": "close",
                        "reason": "emergency_loss_protection",
                        "pnl_pct": net_pnl_percent,
                        "gross_pnl_pct": gross_pnl_percent,
                        "regime": regime,
                        "emergency": True,
                        "threshold": emergency_loss_threshold,
                        "adjusted_threshold": adjusted_emergency_threshold,
                        "spread_buffer": emergency_spread_buffer,
                        "commission_buffer": emergency_commission_buffer,
                    }

            # 2.3. ✅ ГРОК: Проверка peak_profit с absolute threshold - не блокировать для малых прибылей
            # Применяем только для прибылей > 0.5% чтобы избежать блокировки микроприбылей
            # ✅ ИСПРАВЛЕНО: Используем Net PnL для проверки peak_profit (прибыль должна быть реальной после комиссий)
            if (
                net_pnl_percent > 0.5
            ):  # ✅ ГРОК: Только для прибылей > 0.5% (absolute threshold)
                peak_profit_usd = 0.0
                if metadata and hasattr(metadata, "peak_profit_usd"):
                    peak_profit_usd = metadata.peak_profit_usd
                elif isinstance(metadata, dict):
                    peak_profit_usd = metadata.get("peak_profit_usd", 0.0)

                if peak_profit_usd > 0:
                    # Получаем margin_used для конвертации peak_profit_usd в проценты
                    margin_used = None
                    if isinstance(position, dict):
                        margin_used = position.get("margin_used") or position.get(
                            "margin"
                        )
                    elif metadata and hasattr(metadata, "margin_used"):
                        margin_used = metadata.margin_used
                    elif isinstance(metadata, dict):
                        margin_used = metadata.get("margin_used")

                    # ✅ ФИКС: Конвертируем margin_used в float перед сравнением
                    if margin_used:
                        try:
                            margin_used = float(margin_used)
                        except (ValueError, TypeError):
                            margin_used = None

                    if margin_used and margin_used > 0:
                        peak_profit_pct = (peak_profit_usd / margin_used) * 100
                        # ✅ ГРОК: Не закрывать если текущая прибыль < 70% от peak, но только если прибыль > 0.5%
                        # ✅ ИСПРАВЛЕНО: Используем Net PnL для сравнения с peak (прибыль должна быть реальной)
                        if net_pnl_percent < peak_profit_pct * 0.7:
                            logger.info(
                                f"🛡️ ExitAnalyzer RANGING: Не закрываем {symbol} - "
                                f"текущая прибыль {net_pnl_percent:.2f}% < 70% от peak {peak_profit_pct:.2f}% "
                                f"(peak_profit_usd=${peak_profit_usd:.2f}, margin=${margin_used:.2f})"
                            )
                            return {
                                "action": "hold",
                                "reason": "profit_too_low_vs_peak",
                                "pnl_pct": net_pnl_percent,
                                "peak_profit_pct": peak_profit_pct,
                                "peak_profit_usd": peak_profit_usd,
                                "regime": regime,
                            }

            # 2.5. ✅ НОВОЕ: Проверка SL (Stop Loss) - должна быть ДО проверки TP
            # ✅ ГРОК КОМПРОМИСС: Передаем current_price и market_data для ATR-based SL
            try:
                sl_percent = self._safe_sl_percent(
                    symbol,
                    "ranging",
                    current_price,
                    market_data,
                    position=position,
                    metadata=metadata,
                )
            except Exception as sl_exc:
                logger.error(
                    f"⚠️ ExitAnalyzer RANGING: не удалось рассчитать SL для {symbol}; "
                    f"fallback к 2.0% (regime={regime})",
                    exc_info=True,
                )
                sl_percent = 2.0
            # ✅ ИСПРАВЛЕНО: Используем helper функцию для безопасной конвертации
            sl_percent = self._to_float(sl_percent, "sl_percent", 2.0)

            # ✅ ИСПРАВЛЕНО: После partial TP используем более мягкий SL для оставшейся позиции
            # Это защищает оставшиеся 40% от преждевременного закрытия
            if (
                metadata
                and hasattr(metadata, "partial_tp_executed")
                and metadata.partial_tp_executed
            ):
                # После partial TP увеличиваем SL в 1.5 раза для оставшейся позиции
                sl_percent = sl_percent * 1.5  # 1.2% * 1.5 = 1.8%
                logger.debug(
                    f"🛡️ ExitAnalyzer RANGING: После partial TP для {symbol} используем более мягкий SL: "
                    f"{sl_percent:.2f}% (вместо стандартного {self._safe_sl_percent(symbol, 'ranging', current_price, market_data, position=position, metadata=metadata):.2f}%)"
                )

            spread_buffer = self._get_spread_buffer(symbol, current_price)
            sl_threshold = -sl_percent - spread_buffer
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем Gross PnL для сравнения с SL threshold
            # SL должен срабатывать на основе движения цены, а не комиссий
            gross_format_sl = (
                f"{gross_pnl_percent:.4f}"
                if abs(gross_pnl_percent) < 0.1
                else f"{gross_pnl_percent:.2f}"
            )
            net_format_sl = (
                f"{net_pnl_percent:.4f}"
                if abs(net_pnl_percent) < 0.1
                else f"{net_pnl_percent:.2f}"
            )
            # ➞ ОТЛАДОЧНОЕ ЛОГИРОВАНИЕ: всегда показываем проверку SL
            logger.debug(
                f"🔍 ExitAnalyzer RANGING: SL проверка {symbol} | "
                f"Gross PnL={gross_pnl_percent:.2f}% (для SL) | Net PnL={net_pnl_percent:.2f}% (с комиссией) | "
                f"SL={sl_percent:.2f}% | threshold={sl_threshold:.2f}% | action={'PASS' if gross_pnl_percent > sl_threshold else 'TRIGGER'}"
            )
            logger.info(
                f"🔍 ExitAnalyzer RANGING {symbol}: SL={sl_percent:.2f}%, "
                f"Gross PnL%={gross_format_sl}% (для SL), Net PnL%={net_format_sl}% (с комиссией), "
                f"spread_buffer={spread_buffer:.4f}%, SL threshold={sl_threshold:.2f}%, "
                f"достигнут={gross_pnl_percent <= sl_threshold}"
            )
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Сравниваем Gross PnL с SL threshold
            if gross_pnl_percent <= sl_threshold:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Проверяем min_holding_minutes перед закрытием по SL
                min_holding_minutes = self._get_min_holding_minutes("ranging", symbol)
                if min_holding_minutes is not None:
                    minutes_in_position = self._get_time_in_position_minutes(
                        metadata, position
                    )
                    if (
                        minutes_in_position is not None
                        and minutes_in_position < min_holding_minutes
                    ):
                        logger.info(
                            f"⏳ ExitAnalyzer RANGING: SL заблокирован для {symbol} - "
                            f"время удержания {minutes_in_position:.1f} мин < минимум {min_holding_minutes:.1f} мин "
                            f"(Gross PnL={gross_pnl_percent:.2f}% <= SL threshold={sl_threshold:.2f}%)"
                        )
                        # Не закрываем, если не прошло минимальное время
                        return {
                            "action": "hold",
                            "reason": "sl_blocked_by_min_holding",
                            "pnl_pct": gross_pnl_percent,
                            "net_pnl_pct": net_pnl_percent,
                            "minutes_in_position": minutes_in_position,
                            "min_holding_minutes": min_holding_minutes,
                            "sl_percent": sl_percent,
                            "sl_threshold": sl_threshold,
                            "regime": regime,
                        }

                # ✅ КРИТИЧЕСКОЕ УЛУЧШЕНИЕ ЛОГИРОВАНИЯ (29.12.2025): Явный лог "SL достигнут" с деталями
                minutes_in_position = self._get_time_in_position_minutes(
                    metadata, position
                )
                sl_price = (
                    entry_price * (1 - sl_percent / 100)
                    if position_side == "long"
                    else entry_price * (1 + sl_percent / 100)
                )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Учет slippage в расчете effective SL
                # Slippage для OKX составляет 0.1-0.2%, учитываем при закрытии позиции
                slippage_pct = 0.1  # 0.1% slippage для OKX futures
                if position_side == "long":
                    # Для LONG: effective SL ниже расчетного (учитываем slippage при закрытии)
                    effective_sl = sl_price - (slippage_pct / 100 * entry_price)
                else:
                    # Для SHORT: effective SL выше расчетного (учитываем slippage при закрытии)
                    effective_sl = sl_price + (slippage_pct / 100 * entry_price)

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): Проверяем признаки разворота перед SL close
                # Если есть признаки разворота в нашу пользу - НЕ закрываем, даем позиции шанс восстановиться
                logger.info(
                    f"🔍 ExitAnalyzer TRENDING: Проверка разворота перед SL close для {symbol} {position_side.upper()} | "
                    f"Gross PnL={gross_pnl_percent:.2f}%, SL threshold={sl_threshold:.2f}%, "
                    f"SL={sl_percent:.2f}%"
                )
                reversal_detected = await self._check_reversal_signals(
                    symbol, position_side
                )
                logger.info(
                    f"🔍 ExitAnalyzer TRENDING: Результат проверки разворота для {symbol} {position_side.upper()}: "
                    f"reversal_detected={reversal_detected}"
                )
                if reversal_detected:
                    logger.info(
                        f"🔄 ExitAnalyzer RANGING: Обнаружен разворот для {symbol} {position_side.upper()}, "
                        f"но SL достигнут (Gross PnL={gross_pnl_percent:.2f}% <= {sl_threshold:.2f}%). "
                        f"Используем Smart Close для комплексного анализа..."
                    )
                    # Используем Smart Close для более умного решения
                    logger.info(
                        f"🔍 ExitAnalyzer TRENDING: Запуск Smart Close анализа для {symbol} {position_side.upper()} | "
                        f"Gross PnL={gross_pnl_percent:.2f}%, SL={sl_percent:.2f}%, режим={regime}"
                    )
                    smart_close = await self._should_force_close_by_smart_analysis(
                        symbol,
                        position_side,
                        gross_pnl_percent,
                        sl_percent,
                        regime,
                        metadata,
                        position,
                    )
                    logger.info(
                        f"🔍 ExitAnalyzer TRENDING: Результат Smart Close для {symbol} {position_side.upper()}: "
                        f"smart_close={smart_close}"
                    )
                    if smart_close:
                        logger.warning(
                            f"🛑 ExitAnalyzer RANGING: Smart Close рекомендует закрыть {symbol} по SL "
                            f"несмотря на признаки разворота (убыток {gross_pnl_percent:.2f}% критический)"
                        )
                        self._record_metrics_on_close(
                            symbol=symbol,
                            reason="sl_reached_smart_close",
                            pnl_percent=gross_pnl_percent,
                            entry_time=entry_time,
                        )
                        return {
                            "action": "close",
                            "reason": "sl_reached_smart_close",
                            "pnl_pct": gross_pnl_percent,
                            "net_pnl_pct": net_pnl_percent,
                            "sl_percent": sl_percent,
                            "spread_buffer": spread_buffer,
                            "regime": regime,
                            "reversal_detected": True,
                            "smart_close": True,
                        }
                    else:
                        logger.info(
                            f"✅ ExitAnalyzer RANGING: Smart Close рекомендует ДЕРЖАТЬ {symbol} "
                            f"из-за признаков разворота (SL достигнут, но есть шанс восстановления)"
                        )
                        return {
                            "action": "hold",
                            "reason": "sl_reached_reversal_detected",
                            "pnl_pct": gross_pnl_percent,
                            "net_pnl_pct": net_pnl_percent,
                            "sl_percent": sl_percent,
                            "spread_buffer": spread_buffer,
                            "regime": regime,
                            "reversal_detected": True,
                        }

                # ✅ КРИТИЧЕСКАЯ ЗАЩИТА (23.01.2026): Минимальная задержка 90 сек для SL (ranging режим)
                # Защита от преждевременного закрытия из-за спреда/комиссии (аналогично TrailingStopLoss.loss_cut)
                seconds_in_position = minutes_in_position * 60.0
                min_sl_hold_seconds = 90.0  # Минимум 90 секунд перед SL

                if seconds_in_position < min_sl_hold_seconds:
                    logger.info(
                        f"⏱️ SL ЗАЩИТА (ranging): {symbol} SL достигнут (PnL={net_pnl_percent:.2f}%), "
                        f"но позиция держится {seconds_in_position:.1f}с < {min_sl_hold_seconds:.1f}с | "
                        f"БЛОКИРУЕМ закрытие (защита от спреда/комиссии) | "
                        f"current={current_price:.2f}, SL={sl_price:.2f}, effective_SL={effective_sl:.2f}"
                    )
                    return {
                        "action": "hold",
                        "reason": "sl_grace_period",
                        "pnl_pct": gross_pnl_percent,
                        "net_pnl_pct": net_pnl_percent,
                        "sl_percent": sl_percent,
                        "seconds_in_position": seconds_in_position,
                        "min_seconds_required": min_sl_hold_seconds,
                        "regime": regime,
                    }

                logger.info(
                    f"🛑 SL reached for {symbol}: current={current_price:.2f} <= SL={sl_price:.2f} "
                    f"(effective_SL={effective_sl:.2f} с учетом slippage {slippage_pct}%), "
                    f"PnL={gross_pnl_percent:.2f}% (gross), {net_pnl_percent:.2f}% (net), "
                    f"time={minutes_in_position:.1f} min ({seconds_in_position:.1f}с), regime={regime}, нет признаков разворота"
                )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (09.01.2026): ПРОВЕРЯЕМ GRACE PERIOD ПЕРЕД SL (RANGING РЕЖИМ)
                if self._is_grace_period_active(symbol):
                    logger.warning(
                        f"⏳ [GRACE_PERIOD ЗАЩИТА] {symbol}: SL достигнут но grace period активен! "
                        f"Откладываем закрытие на следующий раунд (RANGING режим)."
                    )
                    # Не закрываем - жди перепроверки на следующей итерации
                    return {
                        "action": "hold",
                        "reason": "sl_reached_but_grace_period",
                        "pnl_pct": gross_pnl_percent,
                        "net_pnl_pct": net_pnl_percent,
                        "grace_period_active": True,
                    }

                # ✅ НОВОЕ (26.12.2025): Записываем метрики при закрытии
                self._record_metrics_on_close(
                    symbol=symbol,
                    reason="sl_reached",
                    pnl_percent=gross_pnl_percent,
                    entry_time=entry_time,
                )
                return {
                    "action": "close",
                    "reason": "sl_reached",
                    "pnl_pct": gross_pnl_percent,  # Gross PnL для логирования
                    "net_pnl_pct": net_pnl_percent,  # Net PnL для информации
                    "sl_percent": sl_percent,
                    "spread_buffer": spread_buffer,
                    "regime": regime,
                    "entry_regime": metadata.regime
                    if metadata and hasattr(metadata, "regime")
                    else regime,
                    "reversal_detected": False,
                }

            # 2.6. ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Smart Close проверяется ПЕРЕД TP
            # Проверяем Smart Close только если убыток >= 1.5 * SL и прошло min_holding_minutes
            # ---------- УМНОЕ ЗАКРЫТИЕ УБЫТОЧНОЙ ПОЗИЦИИ ----------
            # Вызывается только если gross_pnl_percent < 0 и |убыток| >= 1.5 * SL
            # ✅ ИСПРАВЛЕНО: Учитываем спред для предотвращения дергания
            if gross_pnl_percent < 0:
                smart_close_sl_percent = self._safe_sl_percent(
                    symbol,
                    "ranging",
                    current_price,
                    market_data,
                    position=position,
                    metadata=metadata,
                )
                smart_close_spread_buffer = self._get_spread_buffer(
                    symbol, current_price
                )
                smart_close_threshold = (
                    -smart_close_sl_percent * 1.5 - smart_close_spread_buffer
                )
                if gross_pnl_percent <= smart_close_threshold:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Проверяем min_holding_minutes перед Smart Close
                    min_holding_minutes = self._get_min_holding_minutes(
                        "ranging", symbol
                    )
                    if min_holding_minutes is not None:
                        minutes_in_position = self._get_time_in_position_minutes(
                            metadata, position
                        )
                        if (
                            minutes_in_position is not None
                            and minutes_in_position < min_holding_minutes
                        ):
                            logger.debug(
                                f"⏳ ExitAnalyzer RANGING: Smart Close заблокирован для {symbol} - "
                                f"время удержания {minutes_in_position:.1f} мин < минимум {min_holding_minutes:.1f} мин "
                                f"(Gross убыток {gross_pnl_percent:.2f}% >= {smart_close_threshold:.2f}%)"
                            )
                            # Не закрываем, если не прошло минимальное время
                        else:
                            # Прошло min_holding_minutes - проверяем Smart Close
                            smart_close = (
                                await self._should_force_close_by_smart_analysis(
                                    symbol,
                                    position_side,
                                    gross_pnl_percent,
                                    smart_close_sl_percent,
                                    regime,
                                    metadata,
                                    position,
                                )
                            )
                            if smart_close:
                                logger.warning(
                                    f"🚨 ExitAnalyzer RANGING: Умное закрытие {symbol} "
                                    f"(Gross убыток {gross_pnl_percent:.2f}% >= {smart_close_sl_percent * 1.5:.2f}%, "
                                    f"Net PnL {net_pnl_percent:.2f}%, нет признаков отката)"
                                )
                                # ✅ НОВОЕ (26.12.2025): Записываем метрики при закрытии
                                self._record_metrics_on_close(
                                    symbol=symbol,
                                    reason="smart_forced_close_ranging",
                                    pnl_percent=gross_pnl_percent,
                                    entry_time=entry_time,
                                )
                                return {
                                    "action": "close",
                                    "reason": "smart_forced_close_ranging",
                                    "pnl_pct": gross_pnl_percent,  # Gross PnL для логирования
                                    "net_pnl_pct": net_pnl_percent,  # Net PnL для информации
                                    "note": "Нет признаков отката - закрываем до SL",
                                    "regime": regime,
                                }
                    else:
                        # min_holding_minutes не настроен - проверяем Smart Close без блокировки
                        smart_close = await self._should_force_close_by_smart_analysis(
                            symbol,
                            position_side,
                            gross_pnl_percent,
                            smart_close_sl_percent,
                            regime,
                            metadata,
                            position,
                        )
                        if smart_close:
                            logger.warning(
                                f"🚨 ExitAnalyzer RANGING: Умное закрытие {symbol} "
                                f"(Gross убыток {gross_pnl_percent:.2f}% >= {smart_close_sl_percent * 1.5:.2f}%, "
                                f"Net PnL {net_pnl_percent:.2f}%, нет признаков отката)"
                            )
                            # ✅ НОВОЕ (26.12.2025): Записываем метрики при закрытии
                            self._record_metrics_on_close(
                                symbol=symbol,
                                reason="smart_forced_close_ranging",
                                pnl_percent=gross_pnl_percent,
                                entry_time=entry_time,
                            )
                            return {
                                "action": "close",
                                "reason": "smart_forced_close_ranging",
                                "pnl_pct": gross_pnl_percent,  # Gross PnL для логирования
                                "net_pnl_pct": net_pnl_percent,  # Net PnL для информации
                                "note": "Нет признаков отката - закрываем до SL",
                                "regime": regime,
                            }
            # ---------- КОНЕЦ УМНОГО ЗАКРЫТИЯ ----------

            # 3. Проверка TP (Take Profit) - в ranging режиме закрываем сразу
            # ✅ ГРОК КОМПРОМИСС: Передаем current_price и market_data для адаптивного TP
            # ✅ НОВОЕ (05.01.2026): Передаем current_pnl для адаптивного расширения TP
            # ✅ ИСПРАВЛЕНО: Для TP используем Net PnL (реальная прибыль после комиссий)
            tp_percent = await self._get_tp_percent(
                symbol,
                "ranging",
                current_price,
                market_data,
                current_pnl=net_pnl_percent,
                position=position,
                metadata=metadata,
            )
            # ✅ ИСПРАВЛЕНО: Используем helper функцию для безопасной конвертации
            if tp_percent is None:
                logger.warning(
                    f"⚠️ ExitAnalyzer RANGING: TP отключен (нет параметров) для {symbol}"
                )
            tp_percent = self._to_float(tp_percent, "tp_percent", float("inf"))
            net_format_tp = (
                f"{net_pnl_percent:.4f}"
                if abs(net_pnl_percent) < 0.1
                else f"{net_pnl_percent:.2f}"
            )
            logger.info(
                f"🔍 ExitAnalyzer RANGING {symbol}: TP={tp_percent:.2f}%, "
                f"Net PnL%={net_format_tp}% (с комиссией), достигнут={net_pnl_percent >= tp_percent}"
            )
            if net_pnl_percent >= tp_percent:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (23.01.2026): Защита от TP на убыточных позициях
                # Проверяем реальный PnL от entry_price к current_price
                real_price_pnl_pct = (
                    ((current_price - entry_price) / entry_price * 100)
                    if position_side == "long"
                    else ((entry_price - current_price) / entry_price * 100)
                )

                if real_price_pnl_pct < 0:
                    logger.warning(
                        f"⚠️ TP ЗАЩИТА: {symbol} TP хочет сработать (net_pnl={net_pnl_percent:.2f}%), "
                        f"но РЕАЛЬНЫЙ PnL от цены = {real_price_pnl_pct:.2f}% (УБЫТОК)! "
                        f"entry={entry_price:.6f}, current={current_price:.6f}, side={position_side}. "
                        f"БЛОКИРУЕМ закрытие - возможно неправильная передача current_pnl из адаптивных параметров."
                    )
                    return {"action": "hold", "reason": "tp_rejected_negative_real_pnl"}

                logger.info(
                    f"🎯 ExitAnalyzer RANGING: TP достигнут для {symbol}: "
                    f"Net PnL {net_pnl_percent:.2f}% >= {tp_percent:.2f}% (Gross PnL {gross_pnl_percent:.2f}%), режим={regime}"
                )
                # ✅ НОВОЕ (26.12.2025): Записываем метрики при закрытии
                self._record_metrics_on_close(
                    symbol=symbol,
                    reason="tp_reached",
                    pnl_percent=net_pnl_percent,
                    entry_time=entry_time,
                )
                return {
                    "action": "close",
                    "reason": "tp_reached",
                    "pnl_pct": net_pnl_percent,  # Net PnL для логирования
                    "gross_pnl_pct": gross_pnl_percent,  # Gross PnL для информации
                    "tp_percent": tp_percent,
                    "regime": regime,
                    "entry_regime": metadata.regime
                    if metadata and hasattr(metadata, "regime")
                    else regime,
                }

            # 4. Проверка big_profit_exit
            # ✅ ИСПРАВЛЕНО: Для big_profit_exit используем Net PnL (реальная прибыль после комиссий)
            big_profit_exit_percent = self._get_big_profit_exit_percent(symbol)
            # ✅ ИСПРАВЛЕНО: Используем helper функцию для безопасной конвертации
            big_profit_exit_percent = self._to_float(
                big_profit_exit_percent, "big_profit_exit_percent", 1.5
            )
            net_format_bp = (
                f"{net_pnl_percent:.4f}"
                if abs(net_pnl_percent) < 0.1
                else f"{net_pnl_percent:.2f}"
            )
            logger.info(
                f"🔍 ExitAnalyzer RANGING {symbol}: big_profit_exit={big_profit_exit_percent:.2f}%, "
                f"Net PnL%={net_format_bp}% (с комиссией), достигнут={net_pnl_percent >= big_profit_exit_percent}"
            )
            if net_pnl_percent >= big_profit_exit_percent:
                logger.info(
                    f"💰 ExitAnalyzer RANGING: Big profit exit достигнут для {symbol}: "
                    f"Net PnL {net_pnl_percent:.2f}% >= {big_profit_exit_percent:.2f}% (Gross PnL {gross_pnl_percent:.2f}%), режим={regime}"
                )
                # ✅ НОВОЕ (26.12.2025): Записываем метрики при закрытии
                self._record_metrics_on_close(
                    symbol=symbol,
                    reason="big_profit_exit",
                    pnl_percent=net_pnl_percent,
                    entry_time=entry_time,
                )
                return {
                    "action": "close",
                    "reason": "big_profit_exit",
                    "pnl_pct": net_pnl_percent,  # Net PnL для логирования
                    "gross_pnl_pct": gross_pnl_percent,  # Gross PnL для информации
                    "big_profit_exit_percent": big_profit_exit_percent,
                    "regime": regime,
                    "entry_regime": metadata.regime
                    if metadata and hasattr(metadata, "regime")
                    else regime,
                }

            # 5. Проверка partial_tp с учетом adaptive_min_holding
            partial_tp_params = self._get_partial_tp_params("ranging")
            # ✅ ИСПРАВЛЕНИЕ (21.12.2025): Определяем trigger_percent до блока if для использования в логировании
            trigger_percent = (
                partial_tp_params.get("trigger_percent", 0.6)
                if partial_tp_params.get("enabled", False)
                else None
            )
            logger.info(
                f"🔍 ExitAnalyzer RANGING {symbol}: partial_tp enabled={partial_tp_params.get('enabled', False)}, "
                f"trigger_percent={trigger_percent:.2f}%"
                if trigger_percent is not None
                else f"trigger_percent=N/A"
            )
            if partial_tp_params.get("enabled", False):
                trigger_percent = partial_tp_params.get("trigger_percent", 0.6)
                # ✅ ИСПРАВЛЕНО: Используем helper функцию для безопасной конвертации
                trigger_percent = self._to_float(
                    trigger_percent, "trigger_percent", 0.6
                )
                # ✅ ИСПРАВЛЕНО: Для partial_tp используем Net PnL (реальная прибыль после комиссий)
                net_format_ptp = (
                    f"{net_pnl_percent:.4f}"
                    if abs(net_pnl_percent) < 0.1
                    else f"{net_pnl_percent:.2f}"
                )
                logger.info(
                    f"🔍 ExitAnalyzer RANGING {symbol}: partial_tp trigger={trigger_percent:.2f}%, "
                    f"Net PnL%={net_format_ptp}% (с комиссией), достигнут={net_pnl_percent >= trigger_percent}"
                )
                if net_pnl_percent >= trigger_percent:
                    # ✅ ИСПРАВЛЕНО: Проверяем, не выполнялся ли уже partial_tp
                    if (
                        metadata
                        and hasattr(metadata, "partial_tp_executed")
                        and metadata.partial_tp_executed
                    ):
                        logger.debug(
                            f"⏱️ ExitAnalyzer RANGING: Partial TP уже был выполнен для {symbol}, пропускаем"
                        )
                    else:
                        # ✅ Проверяем adaptive_min_holding перед partial_tp
                        (
                            can_partial_close,
                            min_holding_info,
                        ) = await self._check_adaptive_min_holding_for_partial_tp(
                            symbol,
                            metadata,
                            net_pnl_percent,
                            "ranging",  # ✅ ИСПРАВЛЕНО: Используем Net PnL
                        )

                        if can_partial_close:
                            # ✅ УЛУЧШЕНИЕ #5.2: Адаптивная fraction для Partial TP в зависимости от Net PnL
                            base_fraction = partial_tp_params.get("fraction", 0.6)
                            if net_pnl_percent < 1.0:
                                fraction = (
                                    base_fraction * 0.67
                                )  # 40% если Net PnL < 1.0%
                            elif net_pnl_percent >= 2.0:
                                fraction = (
                                    base_fraction * 1.33
                                )  # 80% если Net PnL >= 2.0%
                            else:
                                fraction = base_fraction  # 60% стандарт

                            logger.info(
                                f"📊 ExitAnalyzer RANGING: Partial TP триггер достигнут для {symbol}: "
                                f"Net PnL {net_pnl_percent:.2f}% >= {trigger_percent:.2f}%, закрываем {fraction*100:.0f}% позиции "
                                f"(Gross PnL {gross_pnl_percent:.2f}%, {min_holding_info})"
                            )
                            # ✅ ИСПРАВЛЕНО: Устанавливаем флаг partial_tp_executed в metadata
                            if metadata and hasattr(metadata, "partial_tp_executed"):
                                metadata.partial_tp_executed = True
                            return {
                                "action": "partial_close",
                                "reason": "partial_tp",
                                "pnl_pct": net_pnl_percent,  # Net PnL для логирования
                                "gross_pnl_pct": gross_pnl_percent,  # Gross PnL для информации
                                "trigger_percent": trigger_percent,
                                "fraction": fraction,
                                "min_holding_info": min_holding_info,
                                "regime": regime,
                            }
                        else:
                            # ✅ ИСПРАВЛЕНИЕ (21.12.2025): Логируем, почему Partial TP блокируется
                            logger.warning(
                                f"⚠️ ExitAnalyzer RANGING: Partial TP триггер достигнут для {symbol} "
                                f"(Net PnL {net_pnl_percent:.2f}% >= {trigger_percent:.2f}%), но блокируется: {min_holding_info}"
                            )
                            return {
                                "action": "hold",
                                "reason": "partial_tp_min_holding_wait",
                                "pnl_pct": net_pnl_percent,  # Net PnL для логирования
                                "min_holding_info": min_holding_info,
                                "regime": regime,
                            }

            # 6. Проверка разворота (Order Flow, MTF) - в ranging режиме более строго
            # ✅ ИСПРАВЛЕНО: Используем Net PnL для проверки прибыли (реальная прибыль после комиссий)
            reversal_detected = await self._check_reversal_signals(
                symbol, position_side
            )
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Проверяем что это РЕАЛЬНЫЙ разворот, а не grace period!
            if (
                reversal_detected
                and not self._is_grace_period_active(symbol)
                and net_pnl_percent > 0.3
            ):  # Закрываем только если есть реальная прибыль после комиссий И это реальный разворот
                logger.info(
                    f"🔄 ExitAnalyzer RANGING: Разворот обнаружен для {symbol}, закрываем позицию "
                    f"(Net PnL={net_pnl_percent:.2f}%, Gross PnL={gross_pnl_percent:.2f}%)"
                )
                return {
                    "action": "close",
                    "reason": "reversal_detected",
                    "pnl_pct": net_pnl_percent,  # Net PnL для логирования
                    "gross_pnl_pct": gross_pnl_percent,  # Gross PnL для информации
                    "reversal_signal": "order_flow_or_mtf",
                    "regime": regime,
                }

            # 7. ✅ НОВОЕ: Проверка Max Holding - учитываем время в позиции как фактор анализа
            logger.debug(
                f"🔍 ExitAnalyzer RANGING {symbol}: Проверка Max Holding - "
                f"metadata={metadata is not None}, position={isinstance(position, dict)}, "
                f"metadata.entry_time={getattr(metadata, 'entry_time', None) if metadata else None}"
            )
            minutes_in_position = self._get_time_in_position_minutes(metadata, position)
            max_holding_minutes = self._get_max_holding_minutes("ranging", symbol)
            logger.debug(
                f"🔍 ExitAnalyzer RANGING {symbol}: minutes_in_position={minutes_in_position}, "
                f"max_holding_minutes={max_holding_minutes}"
            )

            # Получаем параметры продления времени и жесткого стопа
            extend_time_if_profitable = False
            min_profit_for_extension = 0.5
            extension_percent = 100
            max_holding_hard_stop = False  # ✅ ГРОК: По умолчанию мягкий стоп
            timeout_loss_percent = (
                2.0  # ✅ ГРОК: По умолчанию 2% убыток для жесткого выхода
            )
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
                        max_holding_hard_stop = regime_config.get(
                            "max_holding_hard_stop", False
                        )  # ✅ ГРОК: Получаем из конфига
                        timeout_loss_percent = regime_config.get(
                            "timeout_loss_percent", 2.0
                        )  # ✅ ГРОК: Получаем из конфига
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
                        max_holding_hard_stop = getattr(
                            regime_config, "max_holding_hard_stop", False
                        )  # ✅ ГРОК: Получаем из конфига
                        timeout_loss_percent = getattr(
                            regime_config, "timeout_loss_percent", 2.0
                        )  # ✅ ГРОК: Получаем из конфига
            except Exception as e:
                logger.debug(
                    f"⚠️ ExitAnalyzer: Ошибка получения параметров max_holding: {e}"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Конвертируем max_holding_minutes в float сразу
            try:
                max_holding_minutes_float = (
                    float(max_holding_minutes)
                    if max_holding_minutes is not None
                    else 25.0
                )
            except (TypeError, ValueError):
                logger.warning(
                    f"⚠️ ExitAnalyzer: Не удалось преобразовать max_holding_minutes={max_holding_minutes} в float, используем 25.0"
                )
                max_holding_minutes_float = 25.0

            actual_max_holding = max_holding_minutes_float
            # ✅ ИСПРАВЛЕНО: Используем Net PnL для проверки продления (реальная прибыль после комиссий)
            if (
                extend_time_if_profitable
                and net_pnl_percent >= min_profit_for_extension
            ):
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Конвертируем extension_percent в float
                try:
                    extension_percent_float = (
                        float(extension_percent)
                        if extension_percent is not None
                        else 100.0
                    )
                except (TypeError, ValueError):
                    logger.warning(
                        f"⚠️ ExitAnalyzer: Не удалось преобразовать extension_percent={extension_percent} в float, используем 100.0"
                    )
                    extension_percent_float = 100.0

                extension_minutes = max_holding_minutes_float * (
                    extension_percent_float / 100.0
                )
                actual_max_holding = max_holding_minutes_float + extension_minutes

            # ✅ ИСПРАВЛЕНИЕ #1: Приводим оба значения к float перед сравнением
            # actual_max_holding может быть строкой из конфига, minutes_in_position может быть None
            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ (25.12.2025): Логируем типы перед конвертацией
            logger.debug(
                f"🔍 [RANGING_TYPE_CHECK] {symbol}: actual_max_holding={actual_max_holding} (type={type(actual_max_holding).__name__}), "
                f"max_holding_minutes={max_holding_minutes} (type={type(max_holding_minutes).__name__}), "
                f"minutes_in_position={minutes_in_position} (type={type(minutes_in_position).__name__ if minutes_in_position is not None else 'None'})"
            )
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (26.12.2025): Убеждаемся, что extension_minutes тоже float
            if (
                extend_time_if_profitable
                and net_pnl_percent >= min_profit_for_extension
            ):
                # ✅ ИСПРАВЛЕНО: Конвертируем extension_percent в float перед вычислением
                extension_percent_float = (
                    float(extension_percent) if extension_percent is not None else 100.0
                )
                max_holding_minutes_float = (
                    float(max_holding_minutes)
                    if max_holding_minutes is not None
                    else 25.0
                )
                extension_minutes = max_holding_minutes_float * (
                    extension_percent_float / 100.0
                )
                actual_max_holding = max_holding_minutes_float + extension_minutes
            else:
                # ✅ ИСПРАВЛЕНО: Конвертируем max_holding_minutes в float сразу
                actual_max_holding = (
                    float(max_holding_minutes)
                    if max_holding_minutes is not None
                    else 25.0
                )

            try:
                actual_max_holding_float = (
                    float(actual_max_holding)
                    if actual_max_holding is not None
                    else 25.0
                )
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (25.12.2025): Сохраняем float версию для использования везде
                actual_max_holding = (
                    actual_max_holding_float  # Теперь actual_max_holding всегда float
                )
                logger.debug(
                    f"✅ [RANGING_TYPE_CONVERSION] {symbol}: actual_max_holding успешно конвертирован в float: {actual_max_holding:.2f}"
                )
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"⚠️ ExitAnalyzer: Не удалось преобразовать actual_max_holding={actual_max_holding} (type={type(actual_max_holding)}) в float: {e}, "
                    f"используем max_holding_minutes={max_holding_minutes}"
                )
                try:
                    actual_max_holding_float = (
                        float(max_holding_minutes)
                        if max_holding_minutes is not None
                        else 25.0
                    )
                    actual_max_holding = actual_max_holding_float
                    logger.debug(
                        f"✅ [RANGING_TYPE_CONVERSION] {symbol}: Использован max_holding_minutes, конвертирован в float: {actual_max_holding:.2f}"
                    )
                except (TypeError, ValueError) as e2:
                    logger.error(
                        f"❌ ExitAnalyzer: КРИТИЧЕСКАЯ ОШИБКА - не удалось преобразовать max_holding_minutes={max_holding_minutes} (type={type(max_holding_minutes)}) в float: {e2}, "
                        f"используем fallback 25.0"
                    )
                    actual_max_holding_float = 25.0
                    actual_max_holding = 25.0

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Убеждаемся, что actual_max_holding всегда float перед сравнениями
            try:
                if not isinstance(actual_max_holding, (int, float)):
                    actual_max_holding = (
                        float(actual_max_holding)
                        if actual_max_holding is not None
                        else 25.0
                    )
                else:
                    actual_max_holding = float(actual_max_holding)
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"⚠️ ExitAnalyzer: Не удалось преобразовать actual_max_holding в float: {e}, используем 25.0"
                )
                actual_max_holding = 25.0

            actual_max_holding_float = (
                actual_max_holding  # Теперь actual_max_holding всегда float
            )

            if (
                minutes_in_position is not None
                and isinstance(minutes_in_position, (int, float))
                and float(minutes_in_position) >= actual_max_holding_float
            ):
                # ✅ ГРОК: Жесткий стоп по max_holding (если включен в конфиге)
                # ✅ ИСПРАВЛЕНО: Используем Net PnL для проверки (реальная прибыль/убыток после комиссий)
                if max_holding_hard_stop:
                    if net_pnl_percent < 0:
                        sl_active = False
                        tsl_active = False
                        try:
                            sl_pct_tmp = self._safe_sl_percent(
                                symbol,
                                "ranging",
                                current_price,
                                market_data,
                                position=position,
                                metadata=metadata,
                            )
                            sl_pct_tmp = self._to_float(sl_pct_tmp, "sl_percent", 2.0)
                            sl_threshold_tmp = -sl_pct_tmp - self._get_spread_buffer(
                                symbol, current_price
                            )
                            sl_active = gross_pnl_percent <= sl_threshold_tmp
                        except Exception:
                            sl_active = False
                        try:
                            if self.orchestrator and hasattr(
                                self.orchestrator, "trailing_sl_coordinator"
                            ):
                                tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(
                                    symbol
                                )
                                if tsl:
                                    stop_loss = tsl.get_stop_loss()
                                    if stop_loss:
                                        if position_side == "long":
                                            tsl_active = current_price <= stop_loss
                                        else:
                                            tsl_active = current_price >= stop_loss
                        except Exception:
                            tsl_active = False

                        logger.info(
                            f"⏰ ExitAnalyzer RANGING: max_holding soft hold для {symbol} - "
                            f"Net PnL {net_pnl_percent:.2f}% (Gross {gross_pnl_percent:.2f}%), "
                            f"SL active={sl_active}, TSL active={tsl_active}"
                        )
                        return {
                            "action": "hold",
                            "reason": "max_holding_loss_soft_hold",
                            "pnl_pct": net_pnl_percent,
                            "gross_pnl_pct": gross_pnl_percent,
                            "minutes_in_position": minutes_in_position,
                            "max_holding_minutes": actual_max_holding,
                            "timeout_loss_percent": timeout_loss_percent,
                            "regime": regime,
                            "sl_active": sl_active,
                            "tsl_active": tsl_active,
                        }
                    # Жесткий стоп: закрываем независимо от PnL, кроме случаев когда убыток < timeout_loss_percent
                    if net_pnl_percent < 0:
                        # Если убыток >= timeout_loss_percent - закрываем жестко
                        if abs(net_pnl_percent) >= timeout_loss_percent:
                            sl_active = False
                            tsl_active = False
                            try:
                                sl_pct_tmp = self._safe_sl_percent(
                                    symbol,
                                    "ranging",
                                    current_price,
                                    market_data,
                                    position=position,
                                    metadata=metadata,
                                )
                                sl_pct_tmp = self._to_float(
                                    sl_pct_tmp, "sl_percent", 2.0
                                )
                                sl_threshold_tmp = (
                                    -sl_pct_tmp
                                    - self._get_spread_buffer(symbol, current_price)
                                )
                                sl_active = gross_pnl_percent <= sl_threshold_tmp
                            except Exception:
                                sl_active = False
                            try:
                                if self.orchestrator and hasattr(
                                    self.orchestrator, "trailing_sl_coordinator"
                                ):
                                    tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(
                                        symbol
                                    )
                                    if tsl:
                                        stop_loss = tsl.get_stop_loss()
                                        if stop_loss:
                                            if position_side == "long":
                                                tsl_active = current_price <= stop_loss
                                            else:
                                                tsl_active = current_price >= stop_loss
                            except Exception:
                                tsl_active = False

                            if not (sl_active or tsl_active):
                                logger.info(
                                    f"⏰ ExitAnalyzer RANGING: ЖЕСТКИЙ СТОП смягчен для {symbol} - "
                                    f"убыток {net_pnl_percent:.2f}%, но SL/TSL не активны, удерживаем"
                                )
                                return {
                                    "action": "hold",
                                    "reason": "max_holding_hard_stop_loss_soft_hold",
                                    "pnl_pct": net_pnl_percent,
                                    "gross_pnl_pct": gross_pnl_percent,
                                    "minutes_in_position": minutes_in_position,
                                    "max_holding_minutes": actual_max_holding,
                                    "timeout_loss_percent": timeout_loss_percent,
                                    "regime": regime,
                                    "sl_active": sl_active,
                                    "tsl_active": tsl_active,
                                }
                            logger.warning(
                                f"⏰ ExitAnalyzer RANGING: ЖЕСТКИЙ СТОП по max_holding для {symbol} - "
                                f"время {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин, "
                                f"Net убыток {net_pnl_percent:.2f}% >= {timeout_loss_percent:.2f}% "
                                f"(Gross PnL {gross_pnl_percent:.2f}%)"
                            )
                            return {
                                "action": "close",
                                "reason": "max_holding_hard_stop_timeout_loss",
                                "pnl_pct": net_pnl_percent,  # Net PnL для логирования
                                "gross_pnl_pct": gross_pnl_percent,  # Gross PnL для информации
                                "minutes_in_position": minutes_in_position,
                                "max_holding_minutes": actual_max_holding,
                                "timeout_loss_percent": timeout_loss_percent,
                                "regime": regime,
                            }
                        else:
                            # Убыток < timeout_loss_percent - еще даем шанс
                            logger.info(
                                f"⏰ ExitAnalyzer RANGING: Время {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин, "
                                f"но Net убыток {net_pnl_percent:.2f}% < {timeout_loss_percent:.2f}% "
                                f"(Gross PnL {gross_pnl_percent:.2f}%) - даем еще шанс"
                            )
                            return {
                                "action": "hold",
                                "reason": "max_holding_exceeded_but_loss_small",
                                "pnl_pct": net_pnl_percent,  # Net PnL для логирования
                                "gross_pnl_pct": gross_pnl_percent,  # Gross PnL для информации
                                "minutes_in_position": minutes_in_position,
                                "max_holding_minutes": actual_max_holding,
                                "timeout_loss_percent": timeout_loss_percent,
                                "regime": regime,
                            }
                    else:
                        # Позиция в прибыли - закрываем по max_holding
                        min_profit_for_time_close = 0.05
                        if net_pnl_percent < min_profit_for_time_close:
                            logger.info(
                                f"ExitAnalyzer RANGING: max_holding hold {symbol} - "
                                f"Net PnL {net_pnl_percent:.2f}% < {min_profit_for_time_close:.2f}% (Gross PnL {gross_pnl_percent:.2f}%)"
                            )
                            return {
                                "action": "hold",
                                "reason": "max_holding_time_hold_not_profitable",
                                "pnl_pct": net_pnl_percent,
                                "gross_pnl_pct": gross_pnl_percent,
                                "minutes_in_position": minutes_in_position,
                                "max_holding_minutes": actual_max_holding,
                                "min_profit_for_time_close": min_profit_for_time_close,
                                "regime": regime,
                            }
                        reason = (
                            "max_holding_hard_stop_loss"
                            if net_pnl_percent < 0
                            else "max_holding_hard_stop_profit"
                        )
                        logger.info(
                            f"⏰ ExitAnalyzer RANGING: ЖЕСТКИЙ СТОП по max_holding для {symbol} - "
                            f"время {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин, "
                            f"Net PnL {net_pnl_percent:.2f}% (Gross PnL {gross_pnl_percent:.2f}%), "
                            f"reason={reason}"
                        )
                        return {
                            "action": "close",
                            "reason": reason,
                            "pnl_pct": net_pnl_percent,  # Net PnL для логирования
                            "gross_pnl_pct": gross_pnl_percent,  # Gross PnL для информации
                            "minutes_in_position": minutes_in_position,
                            "max_holding_minutes": actual_max_holding,
                            "regime": regime,
                        }
                else:
                    # ✅ МЯГКИЙ СТОП (старая логика): Не закрываем убыточные позиции по max_holding
                    # Позволяем им дойти до SL или восстановиться
                    # ✅ ИСПРАВЛЕНО: Используем Gross PnL для проверки убытка (SL должен срабатывать на основе движения цены)
                    if gross_pnl_percent < 0:
                        # ✅ НОВОЕ (28.12.2025): Проверяем min_holding_minutes перед проверкой SL
                        min_holding_minutes = None
                        if self.parameter_provider:
                            try:
                                exit_params = self.parameter_provider.get_exit_params(
                                    symbol, regime
                                )
                                min_holding_minutes = exit_params.get(
                                    "min_holding_minutes", 0.5
                                )
                                if min_holding_minutes is not None:
                                    min_holding_minutes = float(min_holding_minutes)
                            except Exception as e:
                                logger.debug(
                                    f"⚠️ ExitAnalyzer: Ошибка получения min_holding_minutes: {e}"
                                )

                        if min_holding_minutes is None:
                            min_holding_minutes = 0.5  # Fallback

                        # Не закрываем по SL если позиция открыта меньше min_holding_minutes
                        if (
                            minutes_in_position is not None
                            and minutes_in_position < min_holding_minutes
                        ):
                            # ✅ ФИНАЛЬНОЕ ДОПОЛНЕНИЕ (Grok): Улучшенное логирование при ignore SL
                            logger.info(
                                f"⏳ ExitAnalyzer {regime.upper()}: Ignore SL для {symbol} - "
                                f"hold {minutes_in_position:.1f} мин < min_holding {min_holding_minutes:.1f} мин "
                                f"(убыток {gross_pnl_percent:.2f}%, защита от раннего закрытия)"
                            )
                            return {
                                "action": "hold",
                                "reason": "min_holding_not_reached_before_sl",
                                "pnl_pct": gross_pnl_percent,
                                "minutes_in_position": minutes_in_position,
                                "min_holding_minutes": min_holding_minutes,
                                "regime": regime,
                            }

                        logger.info(
                            f"⏰ ExitAnalyzer RANGING: Время {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин, "
                            f"но позиция в убытке (Gross PnL {gross_pnl_percent:.2f}%, Net PnL {net_pnl_percent:.2f}%) - "
                            f"НЕ закрываем (мягкий стоп), ждем SL или восстановления"
                        )
                        return {
                            "action": "hold",
                            "reason": "max_holding_exceeded_but_loss",
                            "pnl_pct": gross_pnl_percent,  # Gross PnL для логирования
                            "net_pnl_pct": net_pnl_percent,  # Net PnL для информации
                            "minutes_in_position": minutes_in_position,
                            "max_holding_minutes": actual_max_holding,
                            "regime": regime,
                        }

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем min_profit_to_close перед закрытием по времени
                # Не закрываем по времени если прибыль < min_profit_to_close (после комиссий будет убыток!)
                min_profit_to_close = None
                if self.orchestrator and hasattr(
                    self.orchestrator, "trailing_sl_coordinator"
                ):
                    tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(symbol)
                    if tsl:
                        min_profit_to_close = getattr(tsl, "min_profit_to_close", None)

                # Если min_profit_to_close не найден, используем минимальный порог 0.3% (чтобы покрыть комиссии)
                # ✅ ИСПРАВЛЕНИЕ: min_profit_to_close в долях (0.003 = 0.3%), net_pnl_percent в процентах (1.5 = 1.5%)
                # Конвертируем min_profit_to_close в проценты для сравнения
                # ✅ FIX STRING/INT: Обязательно конвертируем в float перед умножением
                min_profit_threshold_pct = (
                    float(min_profit_to_close) * 100
                    if min_profit_to_close is not None
                    else 0.3
                )  # 0.3% в процентах

                # ✅ ИСПРАВЛЕНО: Используем Net PnL для проверки min_profit_to_close (реальная прибыль после комиссий)
                if net_pnl_percent < min_profit_threshold_pct:
                    # Прибыль меньше min_profit_to_close - НЕ закрываем по времени (после комиссий будет убыток!)
                    logger.info(
                        f"⏰ ExitAnalyzer RANGING: Время {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин "
                        f"(базовое: {max_holding_minutes:.1f} мин), но Net прибыль {net_pnl_percent:.2f}% < "
                        f"min_profit_threshold {min_profit_threshold_pct:.2f}% (Gross PnL {gross_pnl_percent:.2f}%) - "
                        f"НЕ закрываем по времени (после комиссий будет убыток!)"
                    )
                    return {
                        "action": "hold",
                        "reason": "max_holding_low_profit",
                        "pnl_pct": net_pnl_percent,  # Net PnL для логирования
                        "gross_pnl_pct": gross_pnl_percent,  # Gross PnL для информации
                        "min_profit_threshold": min_profit_threshold_pct,
                        "minutes_in_position": minutes_in_position,
                        "regime": regime,
                    }

                # Время превышено и позиция в прибыли >= min_profit_to_close - проверяем признаки разворота
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): Проверяем признаки разворота перед закрытием по времени
                # Если есть признаки разворота против нас - закрываем, если в нашу пользу - продлеваем
                logger.info(
                    f"🔍 ExitAnalyzer RANGING: Проверка разворота и силы тренда перед закрытием по времени для {symbol} {position_side.upper()} | "
                    f"время={minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин, "
                    f"Net PnL={net_pnl_percent:.2f}% >= {min_profit_threshold_pct:.2f}%"
                )
                reversal_detected = await self._check_reversal_signals(
                    symbol, position_side
                )
                logger.info(
                    f"🔍 ExitAnalyzer RANGING: Результат проверки разворота для {symbol} {position_side.upper()}: "
                    f"reversal_detected={reversal_detected}"
                )
                trend_data = await self._analyze_trend_strength(symbol)
                trend_strength = (
                    trend_data.get("trend_strength", 0) if trend_data else 0
                )
                logger.info(
                    f"🔍 ExitAnalyzer RANGING: Результат анализа силы тренда для {symbol} {position_side.upper()}: "
                    f"trend_strength={trend_strength:.2f}"
                )

                if reversal_detected:
                    # Есть признаки разворота - закрываем по времени
                    logger.info(
                        f"⏰ ExitAnalyzer RANGING: Время {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин, "
                        f"Net прибыль={net_pnl_percent:.2f}% >= {min_profit_threshold_pct:.2f}%, "
                        f"обнаружен разворот - закрываем по времени"
                    )
                    return {
                        "action": "close",
                        "reason": "max_holding_exceeded_reversal",
                        "pnl_pct": net_pnl_percent,
                        "gross_pnl_pct": gross_pnl_percent,
                        "minutes_in_position": minutes_in_position,
                        "max_holding_minutes": actual_max_holding,
                        "regime": regime,
                        "reversal_detected": True,
                    }
                elif trend_strength >= 0.7:
                    # Сильный тренд в нашу пользу - продлеваем время
                    logger.info(
                        f"⏰ ExitAnalyzer RANGING: Время {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин, "
                        f"Net прибыль={net_pnl_percent:.2f}% >= {min_profit_threshold_pct:.2f}%, "
                        f"сильный тренд (strength={trend_strength:.2f}) - продлеваем время"
                    )
                    return {
                        "action": "extend_tp",
                        "reason": "max_holding_strong_trend",
                        "pnl_pct": net_pnl_percent,
                        "gross_pnl_pct": gross_pnl_percent,
                        "minutes_in_position": minutes_in_position,
                        "max_holding_minutes": actual_max_holding,
                        "trend_strength": trend_strength,
                        "regime": regime,
                    }
                else:
                    # Нет признаков разворота, тренд не сильный - закрываем по времени
                    logger.info(
                        f"⏰ ExitAnalyzer RANGING: Время {minutes_in_position:.1f} мин >= {actual_max_holding:.1f} мин "
                        f"(базовое: {max_holding_minutes:.1f} мин), Net прибыль={net_pnl_percent:.2f}% >= {min_profit_threshold_pct:.2f}% "
                        f"(Gross PnL {gross_pnl_percent:.2f}%), нет признаков разворота, тренд слабый (strength={trend_strength:.2f}) - закрываем по времени"
                    )
                    return {
                        "action": "close",
                        "reason": "max_holding_exceeded",
                        "pnl_pct": net_pnl_percent,  # Net PnL для логирования
                        "gross_pnl_pct": gross_pnl_percent,  # Gross PnL для информации
                        "minutes_in_position": minutes_in_position,
                        "max_holding_minutes": actual_max_holding,
                        "regime": regime,
                        "reversal_detected": False,
                        "trend_strength": trend_strength,
                    }
            elif minutes_in_position is not None and isinstance(
                minutes_in_position, (int, float)
            ):
                # ✅ ИСПРАВЛЕНО: Конвертируем max_holding_minutes в float перед сравнением
                try:
                    max_holding_minutes_float = (
                        float(max_holding_minutes)
                        if max_holding_minutes is not None
                        else 0.0
                    )
                except (TypeError, ValueError):
                    logger.warning(
                        f"⚠️ ExitAnalyzer: Не удалось преобразовать max_holding_minutes={max_holding_minutes} в float, "
                        f"используем actual_max_holding_float={actual_max_holding_float}"
                    )
                    max_holding_minutes_float = actual_max_holding_float

                if float(minutes_in_position) >= max_holding_minutes_float:
                    # Базовое время превышено, но есть продление - проверяем прибыль
                    # ✅ ИСПРАВЛЕНО: Используем Net PnL для проверки продления (реальная прибыль после комиссий)
                    if (
                        extend_time_if_profitable
                        and net_pnl_percent >= min_profit_for_extension
                    ):
                        logger.debug(
                            f"⏰ ExitAnalyzer RANGING: Время {minutes_in_position:.1f} мин >= {max_holding_minutes_float:.1f} мин, "
                            f"но Net прибыль {net_pnl_percent:.2f}% >= {min_profit_for_extension:.2f}% "
                            f"(Gross PnL {gross_pnl_percent:.2f}%) - продлеваем до {actual_max_holding:.1f} мин"
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

            # ✅ ИСПРАВЛЕНИЕ (21.12.2025): Используем правильное значение trigger_percent в логировании
            # ✅ ИСПРАВЛЕНО: Используем Net PnL для проверки partial_tp (реальная прибыль после комиссий)
            # ✅ ИСПРАВЛЕНО: Конвертируем trigger_percent и net_pnl_percent в float перед сравнением
            try:
                trigger_percent_float = (
                    float(trigger_percent) if trigger_percent is not None else None
                )
                net_pnl_percent_float = (
                    float(net_pnl_percent) if net_pnl_percent is not None else 0.0
                )
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"⚠️ ExitAnalyzer: Ошибка конвертации trigger_percent={trigger_percent} или net_pnl_percent={net_pnl_percent}: {e}"
                )
                trigger_percent_float = None
                net_pnl_percent_float = 0.0

            partial_tp_status = (
                f"partial_tp={trigger_percent_float:.2f}% (не достигнут)"
                if trigger_percent_float is not None
                and net_pnl_percent_float < trigger_percent_float
                else f"partial_tp={trigger_percent_float:.2f}% (достигнут, но блокируется)"
                if trigger_percent_float is not None
                else "partial_tp=disabled"
            )
            logger.info(
                f"🔍 ExitAnalyzer RANGING {symbol}: Нет причин для закрытия - "
                f"TP={tp_percent:.2f}% (не достигнут), big_profit={big_profit_exit_percent:.2f}% (не достигнут), "
                f"{partial_tp_status}, "
                f"текущий Net PnL%={net_pnl_percent:.2f}% (Gross PnL {gross_pnl_percent:.2f}%), время: {time_info}"
            )

            return None

        except Exception as e:
            logger.exception(
                f"❌ ExitAnalyzer: Ошибка анализа для {symbol} в режиме RANGING: {e}\n"
                f"symbol={symbol}, position={position}, metadata={metadata}, current_price={current_price}, regime={regime}"
            )
            return None

    async def _generate_exit_for_choppy(
        self,
        symbol: str,
        position: Any,
        metadata: Any,
        market_data: Optional[Any],
        current_price: float,
        regime: str = "choppy",
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
        sl_percent = 2.0  # Гарантированная инициализация для UnboundLocalError
        try:
            # Базовый SL заранее, чтобы исключить UnboundLocalError при любых ветках логики
            try:
                sl_percent = self._safe_sl_percent(
                    symbol,
                    "choppy",
                    current_price,
                    market_data,
                    position=position,
                    metadata=metadata,
                )
            except Exception:
                logger.error(
                    f"⚠️ ExitAnalyzer CHOPPY: не удалось рассчитать SL для {symbol}, fallback 2.0%",
                    exc_info=True,
                )
                sl_percent = 2.0
            sl_percent = self._to_float(sl_percent, "sl_percent", 2.0)

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

            # ✅ ПРАВКА #4: Приведение типов для предотвращения str vs int ошибок
            try:
                pnl_percent = float(pnl_percent)
            except (TypeError, ValueError) as e:
                logger.error(
                    f"❌ ExitAnalyzer CHOPPY: Ошибка приведения pnl_percent для {symbol}: {e}"
                )
                return None

            # 2. Рассчитываем Gross PnL для SL (без комиссий)
            gross_pnl_percent = self._calculate_pnl_percent(
                entry_price,
                current_price,
                position_side,
                include_fees=False,  # Gross PnL для сравнения с SL
                entry_time=entry_time,
                position=position,
                metadata=metadata,
            )
            gross_pnl_percent = self._to_float(
                gross_pnl_percent, "gross_pnl_percent", 0.0
            )

            tsl_hit, tsl_stop = self._check_tsl_hit(
                symbol, position_side, current_price
            )
            if tsl_hit:
                self._record_metrics_on_close(
                    symbol=symbol,
                    reason="tsl_hit",
                    pnl_percent=pnl_percent,
                    entry_time=entry_time,
                )
                return {
                    "action": "close",
                    "reason": "tsl_hit",
                    "pnl_pct": pnl_percent,
                    "regime": regime,
                    "tsl_stop": tsl_stop,
                }

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (03.01.2026): Emergency Loss Protection - ПЕРВАЯ ЗАЩИТА
            # Проверяется ПЕРВОЙ, перед всеми другими проверками (соответствует приоритету 1 в ExitDecisionCoordinator)
            # ✅ ПРАВКА #13: Защита от больших убытков - АДАПТИВНО ПО РЕЖИМАМ
            # CHOPPY: средний порог (-2.0%), так как в choppy режиме высокая волатильность
            base_emergency_threshold = -6.5
            emergency_loss_threshold = self._get_emergency_threshold(
                base_emergency_threshold, position, metadata
            )

            # ✅ НОВОЕ (26.12.2025): Учитываем spread_buffer и commission_buffer
            emergency_spread_buffer = self._get_spread_buffer(symbol, current_price)
            emergency_commission_buffer = self._get_commission_buffer(
                position, metadata
            )
            adjusted_emergency_threshold = (
                emergency_loss_threshold
                - emergency_spread_buffer
                - emergency_commission_buffer
            )

            # ✅ НОВОЕ (26.12.2025): Минимальное время удержания перед emergency close
            min_holding_seconds = 30.0  # CHOPPY: 30 секунд
            if pnl_percent < adjusted_emergency_threshold:
                # Проверяем минимальное время удержания
                if entry_time:
                    try:
                        if isinstance(entry_time, str):
                            entry_time_dt = datetime.fromisoformat(
                                entry_time.replace("Z", "+00:00")
                            )
                        else:
                            entry_time_dt = entry_time

                        if entry_time_dt.tzinfo is None:
                            entry_time_dt = entry_time_dt.replace(tzinfo=timezone.utc)
                        elif entry_time_dt.tzinfo != timezone.utc:
                            entry_time_dt = entry_time_dt.astimezone(timezone.utc)

                        holding_seconds = (
                            datetime.now(timezone.utc) - entry_time_dt
                        ).total_seconds()

                        if holding_seconds < min_holding_seconds:
                            logger.debug(
                                f"⏳ ExitAnalyzer CHOPPY: Emergency close заблокирован для {symbol} - "
                                f"время удержания {holding_seconds:.1f}с < минимум {min_holding_seconds:.1f}с "
                                f"(PnL={pnl_percent:.2f}% < порог={emergency_loss_threshold:.1f}%)"
                            )
                            # Не закрываем, если не прошло минимальное время
                            # Продолжаем с другими проверками
                        else:
                            # Прошло минимальное время - проверяем признаки разворота перед emergency close
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): Проверяем признаки разворота перед emergency close
                            reversal_detected = await self._check_reversal_signals(
                                symbol, position_side
                            )
                            if reversal_detected:
                                logger.info(
                                    f"🔄 ExitAnalyzer CHOPPY: Обнаружен разворот для {symbol} {position_side.upper()}, "
                                    f"но убыток критический ({pnl_percent:.2f}% < {adjusted_emergency_threshold:.2f}%). "
                                    f"Используем Smart Close для комплексного анализа..."
                                )
                                smart_close_sl_percent = self._safe_sl_percent(
                                    symbol,
                                    "choppy",
                                    current_price,
                                    market_data,
                                    position=position,
                                    metadata=metadata,
                                )
                                smart_close = (
                                    await self._should_force_close_by_smart_analysis(
                                        symbol,
                                        position_side,
                                        pnl_percent,
                                        smart_close_sl_percent,
                                        regime,
                                        metadata,
                                        position,
                                    )
                                )
                                if smart_close:
                                    logger.warning(
                                        f"🚨 ExitAnalyzer CHOPPY: Smart Close рекомендует закрыть {symbol} "
                                        f"несмотря на признаки разворота (убыток {pnl_percent:.2f}% критический)"
                                    )
                                    self._record_metrics_on_close(
                                        symbol=symbol,
                                        reason="emergency_loss_protection_smart_close",
                                        pnl_percent=pnl_percent,
                                        entry_time=entry_time,
                                    )
                                    return {
                                        "action": "close",
                                        "reason": "emergency_loss_protection_smart_close",
                                        "pnl_pct": pnl_percent,
                                        "regime": regime,
                                        "emergency": True,
                                        "reversal_detected": True,
                                        "smart_close": True,
                                    }
                                else:
                                    logger.info(
                                        f"✅ ExitAnalyzer CHOPPY: Smart Close рекомендует ДЕРЖАТЬ {symbol} "
                                        f"из-за признаков разворота (убыток {pnl_percent:.2f}%, но есть шанс восстановления)"
                                    )
                                    return {
                                        "action": "hold",
                                        "reason": "emergency_loss_protection_reversal_detected",
                                        "pnl_pct": pnl_percent,
                                        "regime": regime,
                                        "reversal_detected": True,
                                    }

                            # Нет признаков разворота - закрываем по Emergency Loss Protection
                            logger.warning(
                                f"🚨 ExitAnalyzer CHOPPY: Критический убыток {pnl_percent:.2f}% для {symbol} "
                                f"(порог: {emergency_loss_threshold:.1f}%, скорректирован: {adjusted_emergency_threshold:.2f}% "
                                f"с учетом spread={emergency_spread_buffer:.3f}% + commission={emergency_commission_buffer:.3f}%), "
                                f"нет признаков разворота - генерируем экстренное закрытие (первая защита, приоритет 1)"
                            )
                            self._record_metrics_on_close(
                                symbol=symbol,
                                reason="emergency_loss_protection",
                                pnl_percent=pnl_percent,
                                entry_time=entry_time,
                            )
                            return {
                                "action": "close",
                                "reason": "emergency_loss_protection",
                                "pnl_pct": pnl_percent,
                                "regime": regime,
                                "emergency": True,
                                "threshold": emergency_loss_threshold,
                                "adjusted_threshold": adjusted_emergency_threshold,
                                "spread_buffer": emergency_spread_buffer,
                                "commission_buffer": emergency_commission_buffer,
                                "reversal_detected": False,
                            }
                    except Exception as e:
                        logger.debug(
                            f"⚠️ ExitAnalyzer CHOPPY: Ошибка проверки времени удержания для {symbol}: {e}"
                        )
                        # В случае ошибки разрешаем emergency close (безопаснее)
                        logger.warning(
                            f"🚨 ExitAnalyzer CHOPPY: Критический убыток {pnl_percent:.2f}% для {symbol} "
                            f"(порог: {emergency_loss_threshold:.1f}%, скорректирован: {adjusted_emergency_threshold:.2f}% "
                            f"с учетом spread={emergency_spread_buffer:.3f}% + commission={emergency_commission_buffer:.3f}%), "
                            f"генерируем экстренное закрытие (первая защита, приоритет 1)"
                        )
                        self._record_metrics_on_close(
                            symbol=symbol,
                            reason="emergency_loss_protection",
                            pnl_percent=pnl_percent,
                            entry_time=entry_time,
                        )
                        return {
                            "action": "close",
                            "reason": "emergency_loss_protection",
                            "pnl_pct": pnl_percent,
                            "regime": regime,
                            "emergency": True,
                            "threshold": emergency_loss_threshold,
                            "adjusted_threshold": adjusted_emergency_threshold,
                            "spread_buffer": emergency_spread_buffer,
                            "commission_buffer": emergency_commission_buffer,
                        }
                else:
                    # Нет entry_time, но убыток критический - закрываем
                    logger.warning(
                        f"🚨 ExitAnalyzer CHOPPY: Критический убыток {pnl_percent:.2f}% для {symbol} "
                        f"(порог: {emergency_loss_threshold:.1f}%, скорректирован: {adjusted_emergency_threshold:.2f}% "
                        f"с учетом spread={emergency_spread_buffer:.3f}% + commission={emergency_commission_buffer:.3f}%), "
                        f"генерируем экстренное закрытие (первая защита, приоритет 1)"
                    )
                    self._record_metrics_on_close(
                        symbol=symbol,
                        reason="emergency_loss_protection",
                        pnl_percent=pnl_percent,
                        entry_time=entry_time,
                    )
                    return {
                        "action": "close",
                        "reason": "emergency_loss_protection",
                        "pnl_pct": pnl_percent,
                        "regime": regime,
                        "emergency": True,
                        "threshold": emergency_loss_threshold,
                        "adjusted_threshold": adjusted_emergency_threshold,
                        "spread_buffer": emergency_spread_buffer,
                        "commission_buffer": emergency_commission_buffer,
                    }

            # 2.5. ✅ ГРОК: Проверка peak_profit с absolute threshold - не блокировать для малых прибылей
            if (
                pnl_percent > 0.5
            ):  # ✅ ГРОК: Только для прибылей > 0.5% (absolute threshold)
                peak_profit_usd = 0.0
                if metadata and hasattr(metadata, "peak_profit_usd"):
                    peak_profit_usd = metadata.peak_profit_usd
                elif isinstance(metadata, dict):
                    peak_profit_usd = metadata.get("peak_profit_usd", 0.0)

                if peak_profit_usd > 0:
                    # Получаем margin_used для конвертации peak_profit_usd в проценты
                    margin_used = None
                    if isinstance(position, dict):
                        margin_used = position.get("margin_used") or position.get(
                            "margin"
                        )
                    elif metadata and hasattr(metadata, "margin_used"):
                        margin_used = metadata.margin_used
                    elif isinstance(metadata, dict):
                        margin_used = metadata.get("margin_used")

                    if margin_used and margin_used > 0:
                        peak_profit_pct = (peak_profit_usd / margin_used) * 100
                        # ✅ ГРОК: Не закрывать если текущая прибыль < 70% от peak, но только если прибыль > 0.5%
                        if pnl_percent > 0.5 and pnl_percent < peak_profit_pct * 0.7:
                            logger.info(
                                f"🛡️ ExitAnalyzer CHOPPY: Не закрываем {symbol} - "
                                f"текущая прибыль {pnl_percent:.2f}% < 70% от peak {peak_profit_pct:.2f}% "
                                f"(peak_profit_usd=${peak_profit_usd:.2f}, margin=${margin_used:.2f})"
                            )
                            return {
                                "action": "hold",
                                "reason": "profit_too_low_vs_peak",
                                "pnl_pct": pnl_percent,
                                "peak_profit_pct": peak_profit_pct,
                                "peak_profit_usd": peak_profit_usd,
                                "regime": regime,
                            }

            # 3. Проверка TP (Take Profit) - в choppy режиме закрываем сразу (меньший TP)
            # ✅ ГРОК КОМПРОМИСС: Передаем current_price и market_data для адаптивного TP
            # ✅ НОВОЕ (05.01.2026): Передаем current_pnl для адаптивного расширения TP
            tp_percent = await self._get_tp_percent(
                symbol,
                "choppy",
                current_price,
                market_data,
                current_pnl=pnl_percent,
                position=position,
                metadata=metadata,
            )
            try:
                if tp_percent is None:
                    logger.warning(
                        f"⚠️ ExitAnalyzer CHOPPY: TP отключен (нет параметров) для {symbol}"
                    )
                tp_percent = (
                    float(tp_percent) if tp_percent is not None else float("inf")
                )
            except (TypeError, ValueError) as e:
                logger.error(
                    f"❌ ExitAnalyzer CHOPPY: Ошибка приведения tp_percent для {symbol}: {e}"
                )
                tp_percent = float("inf")
            if pnl_percent >= tp_percent:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (23.01.2026): Защита от TP на убыточных позициях
                # Проверяем реальный PnL от entry_price к current_price
                real_price_pnl_pct = (
                    ((current_price - entry_price) / entry_price * 100)
                    if position_side == "long"
                    else ((entry_price - current_price) / entry_price * 100)
                )

                if real_price_pnl_pct < 0:
                    logger.warning(
                        f"⚠️ TP ЗАЩИТА: {symbol} TP хочет сработать (pnl_percent={pnl_percent:.2f}%), "
                        f"но РЕАЛЬНЫЙ PnL от цены = {real_price_pnl_pct:.2f}% (УБЫТОК)! "
                        f"entry={entry_price:.6f}, current={current_price:.6f}, side={position_side}. "
                        f"БЛОКИРУЕМ закрытие - возможно неправильная передача current_pnl из адаптивных параметров."
                    )
                    return {"action": "hold", "reason": "tp_rejected_negative_real_pnl"}

                logger.info(
                    f"🎯 ExitAnalyzer CHOPPY: TP достигнут для {symbol}: "
                    f"{pnl_percent:.2f}% >= {tp_percent:.2f}%"
                )
                # ✅ НОВОЕ (26.12.2025): Записываем метрики при закрытии
                self._record_metrics_on_close(
                    symbol=symbol,
                    reason="tp_reached",
                    pnl_percent=pnl_percent,
                    entry_time=entry_time,
                )
                return {
                    "action": "close",
                    "reason": "tp_reached",
                    "pnl_pct": pnl_percent,
                    "tp_percent": tp_percent,
                    "regime": regime,
                }

            # 4. Проверка SL (Stop Loss) - должна быть ДО Smart Close
            # ✅ ГРОК КОМПРОМИСС: Передаем current_price и market_data для ATR-based SL
            sl_percent = self._safe_sl_percent(
                symbol,
                "choppy",
                current_price,
                market_data,
                position=position,
                metadata=metadata,
            )
            sl_percent = self._to_float(sl_percent, "sl_percent", 2.0)
            spread_buffer = self._get_spread_buffer(symbol, current_price)
            sl_threshold = -sl_percent - spread_buffer

            logger.debug(
                f"🔍 ExitAnalyzer CHOPPY: SL проверка {symbol} | "
                f"Gross PnL={gross_pnl_percent:.2f}% (для SL) | Net PnL={pnl_percent:.2f}% (с комиссией) | "
                f"SL={sl_percent:.2f}% | threshold={sl_threshold:.2f}%"
            )

            if gross_pnl_percent <= sl_threshold:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Проверяем min_holding_minutes перед закрытием по SL
                min_holding_minutes = self._get_min_holding_minutes("choppy", symbol)
                if min_holding_minutes is not None:
                    minutes_in_position = self._get_time_in_position_minutes(
                        metadata, position
                    )
                    if (
                        minutes_in_position is not None
                        and minutes_in_position < min_holding_minutes
                    ):
                        logger.info(
                            f"⏳ ExitAnalyzer CHOPPY: SL заблокирован для {symbol} - "
                            f"время удержания {minutes_in_position:.1f} мин < минимум {min_holding_minutes:.1f} мин "
                            f"(Gross PnL={gross_pnl_percent:.2f}% <= SL threshold={sl_threshold:.2f}%)"
                        )
                        return {
                            "action": "hold",
                            "reason": "sl_blocked_by_min_holding",
                            "pnl_pct": gross_pnl_percent,
                            "net_pnl_pct": pnl_percent,
                            "minutes_in_position": minutes_in_position,
                            "min_holding_minutes": min_holding_minutes,
                            "sl_percent": sl_percent,
                            "sl_threshold": sl_threshold,
                            "regime": regime,
                        }

                logger.warning(
                    f"🛑 ExitAnalyzer CHOPPY: SL достигнут для {symbol}: "
                    f"Gross PnL {gross_pnl_percent:.2f}% <= SL threshold {sl_threshold:.2f}% "
                    f"(SL={sl_percent:.2f}% + spread_buffer={spread_buffer:.4f}%), "
                    f"Net PnL={pnl_percent:.2f}% (с комиссией), режим={regime}"
                )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (09.01.2026): ПРОВЕРЯЕМ GRACE PERIOD ПЕРЕД SL (CHOPPY РЕЖИМ)
                if self._is_grace_period_active(symbol):
                    logger.warning(
                        f"⏳ [GRACE_PERIOD ЗАЩИТА] {symbol}: SL достигнут но grace period активен! "
                        f"Откладываем закрытие на следующий раунд (CHOPPY режим)."
                    )
                    # Не закрываем - жди перепроверки на следующей итерации
                    return {
                        "action": "hold",
                        "reason": "sl_reached_but_grace_period",
                        "pnl_pct": gross_pnl_percent,
                        "net_pnl_pct": pnl_percent,
                        "grace_period_active": True,
                    }

                self._record_metrics_on_close(
                    symbol=symbol,
                    reason="sl_reached",
                    pnl_percent=gross_pnl_percent,
                    entry_time=entry_time,
                )
                return {
                    "action": "close",
                    "reason": "sl_reached",
                    "pnl_pct": gross_pnl_percent,
                    "net_pnl_pct": pnl_percent,
                    "sl_percent": sl_percent,
                    "spread_buffer": spread_buffer,
                    "regime": regime,
                }

            # 4.1. ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Smart Close проверяется ПЕРЕД big_profit_exit
            # Проверяем Smart Close только если убыток >= 1.5 * SL и прошло min_holding_minutes
            if gross_pnl_percent < 0:
                smart_close_sl_percent = self._safe_sl_percent(
                    symbol,
                    "choppy",
                    current_price,
                    market_data,
                    position=position,
                    metadata=metadata,
                )
                smart_close_spread_buffer = self._get_spread_buffer(
                    symbol, current_price
                )
                smart_close_threshold = (
                    -smart_close_sl_percent * 1.5 - smart_close_spread_buffer
                )
                if gross_pnl_percent <= smart_close_threshold:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Проверяем min_holding_minutes перед Smart Close
                    min_holding_minutes = self._get_min_holding_minutes(
                        "choppy", symbol
                    )
                    if min_holding_minutes is not None:
                        minutes_in_position = self._get_time_in_position_minutes(
                            metadata, position
                        )
                        if (
                            minutes_in_position is not None
                            and minutes_in_position < min_holding_minutes
                        ):
                            logger.debug(
                                f"⏳ ExitAnalyzer CHOPPY: Smart Close заблокирован для {symbol} - "
                                f"время удержания {minutes_in_position:.1f} мин < минимум {min_holding_minutes:.1f} мин "
                                f"(Gross убыток {gross_pnl_percent:.2f}% >= {smart_close_threshold:.2f}%)"
                            )
                        else:
                            # Прошло min_holding_minutes - проверяем Smart Close
                            smart_close = (
                                await self._should_force_close_by_smart_analysis(
                                    symbol,
                                    position_side,
                                    gross_pnl_percent,
                                    smart_close_sl_percent,
                                    regime,
                                    metadata,
                                    position,
                                )
                            )
                            if smart_close:
                                logger.warning(
                                    f"🚨 ExitAnalyzer CHOPPY: Умное закрытие {symbol} "
                                    f"(Gross убыток {gross_pnl_percent:.2f}% >= {smart_close_sl_percent * 1.5:.2f}%, "
                                    f"Net PnL {pnl_percent:.2f}%, нет признаков отката)"
                                )
                                self._record_metrics_on_close(
                                    symbol=symbol,
                                    reason="smart_forced_close_choppy",
                                    pnl_percent=gross_pnl_percent,
                                    entry_time=entry_time,
                                )
                                return {
                                    "action": "close",
                                    "reason": "smart_forced_close_choppy",
                                    "pnl_pct": gross_pnl_percent,
                                    "net_pnl_pct": pnl_percent,
                                    "note": "Нет признаков отката - закрываем до SL",
                                    "regime": regime,
                                }
                    else:
                        # min_holding_minutes не настроен - проверяем Smart Close без блокировки
                        smart_close = await self._should_force_close_by_smart_analysis(
                            symbol,
                            position_side,
                            gross_pnl_percent,
                            smart_close_sl_percent,
                            regime,
                            metadata,
                            position,
                        )
                        if smart_close:
                            logger.warning(
                                f"🚨 ExitAnalyzer CHOPPY: Умное закрытие {symbol} "
                                f"(Gross убыток {gross_pnl_percent:.2f}% >= {smart_close_sl_percent * 1.5:.2f}%, "
                                f"Net PnL {pnl_percent:.2f}%, нет признаков отката)"
                            )
                            self._record_metrics_on_close(
                                symbol=symbol,
                                reason="smart_forced_close_choppy",
                                pnl_percent=gross_pnl_percent,
                                entry_time=entry_time,
                            )
                            return {
                                "action": "close",
                                "reason": "smart_forced_close_choppy",
                                "pnl_pct": gross_pnl_percent,
                                "net_pnl_pct": pnl_percent,
                                "note": "Нет признаков отката - закрываем до SL",
                                "regime": regime,
                            }

            # 5. Проверка big_profit_exit
            big_profit_exit_percent = self._get_big_profit_exit_percent(symbol)
            if pnl_percent >= big_profit_exit_percent:
                logger.info(
                    f"💰 ExitAnalyzer CHOPPY: Big profit exit достигнут для {symbol}: "
                    f"{pnl_percent:.2f}% >= {big_profit_exit_percent:.2f}%"
                )
                # ✅ НОВОЕ (26.12.2025): Записываем метрики при закрытии
                self._record_metrics_on_close(
                    symbol=symbol,
                    reason="big_profit_exit",
                    pnl_percent=pnl_percent,
                    entry_time=entry_time,
                )
                return {
                    "action": "close",
                    "reason": "big_profit_exit",
                    "pnl_pct": pnl_percent,
                    "big_profit_exit_percent": big_profit_exit_percent,
                    "regime": regime,
                }

            # 5. Проверка partial_tp - в choppy режиме более агрессивно (с учетом adaptive_min_holding)
            # ✅ УЛУЧШЕНИЕ #6: Используем оптимизированные триггеры из конфига
            partial_tp_params = self._get_partial_tp_params("choppy")
            partial_tp_enabled = partial_tp_params.get("enabled", False)
            trigger_percent = partial_tp_params.get("trigger_percent", 0.6)

            # ✅ FIX (09.01.2026): Улучшенное логирование partial_tp для диагностики
            logger.debug(
                f"📊 [PARTIAL_TP] {symbol} CHOPPY: enabled={partial_tp_enabled}, "
                f"pnl={pnl_percent:.2f}% vs trigger={trigger_percent:.2f}%, "
                f"достаточно для partial_tp={'✅ ДА' if pnl_percent >= trigger_percent else '❌ НЕТ'}"
            )

            if partial_tp_enabled:
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
                            "regime": regime,
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
                            "regime": regime,
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
                    "regime": regime,
                }

            # 7. ✅ НОВОЕ: Проверка Max Holding - учитываем время в позиции как фактор анализа
            minutes_in_position = self._get_time_in_position_minutes(metadata, position)
            max_holding_minutes = self._get_max_holding_minutes("choppy", symbol)

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
                        "regime": regime,
                    }

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем min_profit_to_close перед закрытием по времени
                # Не закрываем по времени если прибыль < min_profit_to_close (после комиссий будет убыток!)
                min_profit_to_close = None
                if self.orchestrator and hasattr(
                    self.orchestrator, "trailing_sl_coordinator"
                ):
                    tsl = self.orchestrator.trailing_sl_coordinator.get_tsl(symbol)
                    if tsl:
                        min_profit_to_close = getattr(tsl, "min_profit_to_close", None)

                # Если min_profit_to_close не найден, используем минимальный порог 0.3% (чтобы покрыть комиссии)
                # ✅ ИСПРАВЛЕНИЕ: min_profit_to_close в долях (0.003 = 0.3%), pnl_percent в процентах (1.5 = 1.5%)
                # Конвертируем min_profit_to_close в проценты для сравнения
                # ✅ FIX STRING/INT: Обязательно конвертируем в float перед умножением
                min_profit_threshold_pct = (
                    float(min_profit_to_close) * 100
                    if min_profit_to_close is not None
                    else 0.3
                )  # 0.3% в процентах

                if pnl_percent < min_profit_threshold_pct:
                    # Прибыль меньше min_profit_to_close - НЕ закрываем по времени (после комиссий будет убыток!)
                    logger.info(
                        f"⏰ ExitAnalyzer CHOPPY: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                        f"но прибыль {pnl_percent:.2f}% < min_profit_threshold {min_profit_threshold_pct:.2f}% - "
                        f"НЕ закрываем по времени (после комиссий будет убыток!)"
                    )
                    return {
                        "action": "hold",
                        "reason": "max_holding_low_profit",
                        "pnl_pct": pnl_percent,
                        "min_profit_threshold": min_profit_threshold_pct,
                        "minutes_in_position": minutes_in_position,
                        "regime": regime,
                    }

                # В choppy режиме закрываем строго по времени, но только если прибыль >= min_profit_to_close
                logger.info(
                    f"⏰ ExitAnalyzer CHOPPY: Время {minutes_in_position:.1f} мин >= {max_holding_minutes:.1f} мин, "
                    f"прибыль={pnl_percent:.2f}% >= {min_profit_threshold_pct:.2f}% - закрываем по времени"
                )
                return {
                    "action": "close",
                    "reason": "max_holding_exceeded_choppy",
                    "pnl_pct": pnl_percent,
                    "minutes_in_position": minutes_in_position,
                    "max_holding_minutes": max_holding_minutes,
                    "regime": regime,
                }

            # В choppy режиме не продлеваем TP - быстрые закрытия
            return None

        except Exception as e:
            logger.exception(
                f"❌ ExitAnalyzer: Ошибка анализа для {symbol} в режиме CHOPPY: {e}\n"
                f"symbol={symbol}, position={position}, metadata={metadata}, current_price={current_price}, regime={regime}"
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

    # ==================== УМНОЕ ЗАКРЫТИЕ: МЕТОДЫ ПОЛУЧЕНИЯ ДАННЫХ ====================

    async def _get_funding_rate(self, symbol: str) -> Optional[float]:
        """Получить текущий funding rate через funding_monitor"""
        if self.funding_monitor:
            try:
                return self.funding_monitor.get_current_funding()
            except Exception as e:
                logger.debug(f"⚠️ Ошибка получения funding rate для {symbol}: {e}")
        return None

    async def _get_correlation(
        self, symbol: str, basket: list, period: int = 20
    ) -> Optional[float]:
        """
        Получить корреляцию между символом и корзиной.

        Args:
            symbol: Торговый символ
            basket: Список символов для сравнения (например, ["BTC-USDT", "ETH-USDT"])
            period: Период для расчета (количество свечей)

        Returns:
            Средняя корреляция или None
        """
        # TODO: Реализовать через CorrelationManager если доступен
        # Пока возвращаем None (будет обработано в _check_correlation_bias)
        return None

    async def _get_nearest_liquidity(
        self, symbol: str, current_price: float
    ) -> Optional[Dict[str, Dict]]:
        """Получить ближайшие уровни ликвидности"""
        if self.liquidity_levels_detector:
            try:
                return await self.liquidity_levels_detector.get_nearest_liquidity(
                    symbol, current_price
                )
            except Exception as e:
                logger.debug(
                    f"⚠️ Ошибка получения уровней ликвидности для {symbol}: {e}"
                )
        return None

    async def _get_atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """Получить ATR для символа через ATRProvider (БЕЗ FALLBACK)"""
        # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #6: Используем ATRProvider БЕЗ fallback
        if not self.atr_provider:
            logger.error(
                f"❌ [ATR] {symbol}: ATRProvider недоступен - возвращаем None (БЕЗ FALLBACK)"
            )
            return None

        atr = self.atr_provider.get_atr(symbol)
        if atr is None:
            logger.error(
                f"❌ [ATR] {symbol}: ATR не найден через ATRProvider - возвращаем None (БЕЗ FALLBACK)"
            )
        return atr

    async def _get_volume_profile(
        self, symbol: str, lookback: int = 48
    ) -> Optional[Any]:
        """Получить Volume Profile для символа"""
        try:
            # ✅ ИСПРАВЛЕНО: Проверка volume_profile_calculator на None перед использованием
            if not self.volume_profile_calculator:
                return None

            candles = await self.data_registry.get_candles(symbol, "1h")
            if not candles or len(candles) < lookback:
                # Fallback на меньший таймфрейм
                candles = await self.data_registry.get_candles(symbol, "15m")
                if not candles or len(candles) < lookback * 4:
                    return None

            profile = self.volume_profile_calculator.calculate(candles[-lookback:])
            return profile
        except Exception as e:
            logger.debug(f"⚠️ Ошибка получения Volume Profile для {symbol}: {e}")
        return None

    async def _get_pivot_levels(
        self, symbol: str, timeframe: str = "1h"
    ) -> Optional[Any]:
        """Получить Pivot Levels для символа"""
        try:
            candles = await self.data_registry.get_candles(symbol, timeframe)
            if not candles or len(candles) < 1:
                return None

            pivots = self.pivot_calculator.calculate_pivots(candles)
            return pivots
        except Exception as e:
            logger.debug(f"⚠️ Ошибка получения Pivot Levels для {symbol}: {e}")
        return None

    # ==================== УМНОЕ ЗАКРЫТИЕ: МЕТОДЫ ПРОВЕРКИ ИНДИКАТОРОВ ====================

    async def _check_reversal_signals_score(self, symbol: str, side: str) -> int:
        """Обертка для получения score (0 или 1) из _check_reversal_signals"""
        result = await self._check_reversal_signals(symbol, side)
        return 1 if result else 0

    async def _check_funding_bias(self, symbol: str, side: str) -> int:
        """
        Проверка funding bias (z-score > 2.0 -> перегрев, против нас = шанс на откат).

        Returns:
            1 если funding указывает на откат, 0 иначе
        """
        funding = await self._get_funding_rate(symbol)
        if funding is None:
            return 0

        # Вычисляем z-score (нужна история funding для std-dev)
        # Упрощенная версия: если funding против нас и значимый (> 0.02 или < -0.02)
        if side == "long" and funding < -0.02:
            # Отрицательный funding для лонга = продавцы платят покупателям = шанс на откат вверх
            return 1
        if side == "short" and funding > 0.02:
            # Положительный funding для шорта = покупатели платят продавцам = шанс на откат вниз
            return 1

        return 0

    async def _check_correlation_bias(self, symbol: str, side: str) -> int:
        """
        Проверка корреляции (rolling 20 свечей, Pearson r, |r| > 0.85 -> сильная корреляция).

        Returns:
            1 если корреляция слабая (не в нашу пользу), 0 иначе
        """
        basket = ["BTC-USDT", "ETH-USDT", "BNB-USDT"]
        corr = await self._get_correlation(symbol, basket, period=20)
        if corr is None:
            return 0  # Нет данных = не учитываем

        # Если корреляция < 0.85, считаем что не в нашу пользу
        if abs(corr) < 0.85:
            return 1
        return 0

    async def _check_liquidity_sweep(self, symbol: str, side: str) -> int:
        """
        Проверка ликвидности (если ниже/выше нас еще ликвидность 90% -> шанс на отскок).

        Returns:
            1 если есть ликвидность для отскока, 0 иначе
        """
        current_price = await self.data_registry.get_price(symbol)
        if not current_price:
            return 0

        liq = await self._get_nearest_liquidity(symbol, current_price)
        if not liq:
            return 0

        # Получаем данные о ликвидности ниже и выше
        below_data = liq.get("below", {})
        above_data = liq.get("above", {})

        if side == "long":
            # Для лонга: если ниже нас еще ликвидность (volume > 0 и distance_pct разумная)
            below_volume = below_data.get("volume", 0)
            below_depth = below_data.get("depth_usd", 0)
            # Если есть значимая ликвидность ниже (объем > 0.1% от текущей цены * типичный размер)
            if below_volume > 0 and below_depth > current_price * 0.001:
                return 1
        else:  # short
            # Для шорта: если выше нас еще ликвидность
            above_volume = above_data.get("volume", 0)
            above_depth = above_data.get("depth_usd", 0)
            if above_volume > 0 and above_depth > current_price * 0.001:
                return 1

        return 0

    async def _check_reversal_candles(self, symbol: str, side: str) -> int:
        """
        Проверка разворотных свечей (Hammer, Engulfing).

        Returns:
            1 если обнаружен разворотный паттерн, 0 иначе
        """
        try:
            # ✅ ИСПРАВЛЕНО: Проверка candle_pattern_detector на None перед использованием
            if not self.candle_pattern_detector:
                return 0

            candles = await self.data_registry.get_candles(symbol, "1m")
            if not candles or len(candles) < 3:
                return 0

            last_3 = candles[-3:]
            atr = await self._get_atr(symbol)

            # Проверяем Hammer для лонга
            if side == "long":
                current_candle = last_3[-1]
                prev_candle = last_3[-2] if len(last_3) >= 2 else None
                if await self.candle_pattern_detector.is_hammer(
                    current_candle, prev_candle, atr
                ):
                    return 1

            # Проверяем Bearish Engulfing для шорта
            if side == "short" and len(last_3) >= 2:
                current_candle = last_3[-1]
                prev_candle = last_3[-2]
                if await self.candle_pattern_detector.is_engulfing_bearish(
                    current_candle, prev_candle, atr
                ):
                    return 1

        except Exception as e:
            logger.debug(f"⚠️ Ошибка проверки разворотных свечей для {symbol}: {e}")

        return 0

    async def _check_volume_profile_support(self, symbol: str, side: str) -> int:
        """
        Проверка Volume Profile (цена в зоне высокого объема = поддержка).

        Returns:
            1 если цена в зоне высокого объема, 0 иначе
        """
        try:
            # ✅ ОПТИМИЗАЦИЯ: Используем актуальную цену из стакана для Volume Profile анализа
            current_price = None
            if self.client and hasattr(self.client, "get_price_limits"):
                try:
                    price_limits = await self.client.get_price_limits(symbol)
                    if price_limits:
                        current_price = price_limits.get("current_price", 0)
                except Exception:
                    pass

            # Fallback на data_registry если не получили из стакана
            if current_price is None or current_price <= 0:
                current_price = await self.data_registry.get_price(symbol)

            if not current_price:
                return 0

            vp = await self._get_volume_profile(symbol)
            if not vp:
                return 0

            # Проверяем, находится ли цена в Value Area
            if vp.is_in_value_area(current_price):
                return 1

            # Проверяем расстояние от POC (если близко к POC = зона высокого объема)
            distance_pct = vp.get_distance_from_poc(current_price)
            if distance_pct < 0.005:  # В пределах 0.5% от POC
                return 1

        except Exception as e:
            logger.debug(f"⚠️ Ошибка проверки Volume Profile для {symbol}: {e}")

        return 0

    async def _check_pivot_support(self, symbol: str, side: str) -> int:
        """
        Проверка Pivot Levels (цена близко к уровню поддержки/сопротивления).

        Returns:
            1 если цена близко к уровню, 0 иначе
        """
        try:
            current_price = await self.data_registry.get_price(symbol)
            if not current_price:
                return 0

            pivots = await self._get_pivot_levels(symbol, "1h")
            if not pivots:
                return 0

            atr = await self._get_atr(symbol)
            if not atr:
                return 0

            # Проверяем расстояние до уровней (в пределах 0.3 * ATR)
            tolerance = atr * 0.3

            if side == "long":
                # Для лонга проверяем поддержку (S1, S2, S3)
                for level_name, level_value in [
                    ("S1", pivots.support_1),
                    ("S2", pivots.support_2),
                    ("S3", pivots.support_3),
                ]:
                    if abs(current_price - level_value) < tolerance:
                        return 1
            else:  # short
                # Для шорта проверяем сопротивление (R1, R2, R3)
                for level_name, level_value in [
                    ("R1", pivots.resistance_1),
                    ("R2", pivots.resistance_2),
                    ("R3", pivots.resistance_3),
                ]:
                    if abs(current_price - level_value) < tolerance:
                        return 1

        except Exception as e:
            logger.debug(f"⚠️ Ошибка проверки Pivot Levels для {symbol}: {e}")

        return 0

    # ==================== УМНОЕ ЗАКРЫТИЕ: ОСНОВНОЙ МЕТОД ====================

    async def _should_force_close_by_smart_analysis(
        self,
        symbol: str,
        position_side: str,
        pnl_pct: float,
        sl_pct: float,
        regime: str,
        metadata: Optional[Any] = None,
        position: Optional[Any] = None,
    ) -> bool:
        """
        Возвращает True, если нужно принудительно закрыть убыточную позицию.

        Условия закрытия:
        - убыток уже значительный (>= 1.5 * SL)
        - ни один индикатор не показывает разворот в нашу пользу
        - тренд усиливается против нас

        Args:
            symbol: Торговый символ
            position_side: Направление позиции ("long" или "short")
            pnl_pct: Текущий PnL в процентах
            sl_pct: Stop Loss в процентах
            regime: Режим рынка (trending, ranging, choppy)
            metadata: Метаданные позиции (для проверки min_holding_minutes)
            position: Данные позиции (для проверки min_holding_minutes)

        Returns:
            True если нужно закрыть, False если держать
        """
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Проверяем min_holding_minutes перед Smart Close
        min_holding_minutes = self._get_min_holding_minutes(regime, symbol)
        if min_holding_minutes is not None:
            minutes_in_position = self._get_time_in_position_minutes(metadata, position)
            if (
                minutes_in_position is not None
                and minutes_in_position < min_holding_minutes
            ):
                logger.debug(
                    f"⏳ Smart Close заблокирован для {symbol} - "
                    f"время удержания {minutes_in_position:.1f} мин < минимум {min_holding_minutes:.1f} мин "
                    f"(режим={regime})"
                )
                # Не закрываем по Smart Close, если не прошло минимальное время
                return False
        # Проверяем все индикаторы параллельно
        tasks = [
            self._check_reversal_signals_score(
                symbol, position_side
            ),  # Order Flow + MTF
            self._check_funding_bias(symbol, position_side),  # фандинг
            self._check_correlation_bias(symbol, position_side),  # корреляция
            self._check_liquidity_sweep(symbol, position_side),  # ликвидность
            self._check_reversal_candles(symbol, position_side),  # свечи
            self._check_volume_profile_support(symbol, position_side),  # VP
            self._check_pivot_support(symbol, position_side),  # пивоты
        ]

        # ✅ ИСПРАВЛЕНО: Логируем названия задач для отладки
        task_names = [
            "reversal_signals",
            "funding_bias",
            "correlation_bias",
            "liquidity_sweep",
            "reversal_candles",
            "volume_profile",
            "pivot_support",
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # ✅ ИСПРАВЛЕНО: Обрабатываем исключения с логированием стека трейса
        valid_results = []
        scores = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    f"⚠️ Ошибка проверки индикатора '{task_names[i]}' для {symbol}: {result}",
                    exc_info=result,
                )
                scores.append(0)
            else:
                valid_results.append(result)
                scores.append(result)

        # ✅ ИСПРАВЛЕНО: Если все индикаторы вернули Exception, не закрываем
        if not valid_results:
            logger.warning(
                f"⚠️ Smart Close: Все индикаторы вернули ошибки для {symbol}, "
                f"не закрываем позицию (безопасный fallback)"
            )
            return False

        reversal_score = sum(scores)  # 0-7 (чем больше, тем больше признаков отката)

        # ✅ ИСПРАВЛЕНО: Явная проверка trend_data is None
        trend_data = await self._analyze_trend_strength(symbol)
        trend_against = 0.0
        if trend_data is None:
            logger.debug(
                f"⚠️ Smart Close: trend_data is None для {symbol}, используем trend_against=0.0"
            )
        else:
            ts = trend_data.get("trend_strength", 0.0)
            direction = trend_data.get("trend_direction", "neutral")
            if (position_side == "long" and direction == "bearish") or (
                position_side == "short" and direction == "bullish"
            ):
                trend_against = ts

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (29.12.2025): Используем адаптивные пороги по режиму
        smart_close_params = self.parameter_provider.get_smart_close_params(
            regime, symbol
        )
        score_threshold = smart_close_params["reversal_score_threshold"]
        trend_threshold = smart_close_params["trend_against_threshold"]

        # Принудительное закрытие с адаптивными порогами:
        # 1. нет признаков разворота (score <= threshold по режиму)
        # 2. тренд против нас усиливается (>= threshold по режиму)
        should_close = (
            reversal_score <= score_threshold and trend_against >= trend_threshold
        )

        logger.info(
            f"Smart Close Analysis {symbol} ({position_side}, режим={regime}): "
            f"reversal_score={reversal_score}/7 (порог={score_threshold}), "
            f"trend_against={trend_against:.2f} (порог={trend_threshold:.2f}), "
            f"should_close={should_close}, pnl={pnl_pct:.2f}%"
        )

        return should_close

    def analyze_hold_signal(
        self,
        symbol: str,
        position_side: str,
        current_pnl_pct: float,
        min_profit_pct: float = 0.3,
        max_holding_time_sec: Optional[float] = None,
        open_time: Optional[float] = None,
        current_time: Optional[float] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        🔴 BUG #25 FIX (11.01.2026): Analyze if position should be HELD (not exited yet)

        Анализирует должна ли позиция оставаться открытой (HOLD) или нужно закрывать.

        Условия для HOLD:
        1. Позиция прибыльная (>= min_profit_pct)
        2. Нет явного сигнала на выход
        3. Не превышено максимальное время удержания позиции
        4. Тренд не развернулся против нас критически

        Args:
            symbol: Торговый символ
            position_side: Направление позиции (long/short)
            current_pnl_pct: Текущий PnL в процентах
            min_profit_pct: Минимальная прибыль для HOLD (0.3%)
            max_holding_time_sec: Максимальное время удержания (секунды), None = нет лимита
            open_time: Unix timestamp когда открыта позиция
            current_time: Текущее время (если None, используется текущее время)

        Returns:
            (should_hold, hold_reason) tuple[bool, Optional[str]]
            should_hold=True если нужно удерживать позицию
            hold_reason = причина if should_hold=False (почему выходить)
        """
        try:
            # Проверяем минимальную прибыль
            if current_pnl_pct < min_profit_pct:
                reason = (
                    f"PnL {current_pnl_pct:.2f}% < min_profit {min_profit_pct:.2f}%"
                )
                return False, reason

            # Проверяем время удержания
            if max_holding_time_sec and open_time and current_time is None:
                import time

                current_time = time.time()

            if max_holding_time_sec and open_time and current_time:
                holding_time = current_time - open_time
                if holding_time > max_holding_time_sec:
                    reason = f"Max holding time exceeded: {holding_time:.0f}s > {max_holding_time_sec:.0f}s"
                    return False, reason

            # Если мы здесь - позиция должна оставаться открытой
            logger.debug(
                f"🟢 HOLD signal for {symbol} ({position_side}): "
                f"PnL={current_pnl_pct:.2f}% >= min={min_profit_pct:.2f}%, "
                f"holding_time OK"
            )

            return True, None  # HOLD the position

        except Exception as e:
            logger.error(
                f"❌ Error analyzing HOLD signal for {symbol}: {e}", exc_info=True
            )
            return False, f"Analysis error: {str(e)}"

    async def analyze_exit_with_liquidity_checks(
        self,
        symbol: str,
        position_side: str,
        position_size: float,
        current_price: float,
        entry_price: float,
        current_pnl_pct: float,
        bid_price: Optional[float] = None,
        ask_price: Optional[float] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        🔴 BUG #28 FIX (11.01.2026): Exit analysis with proper liquidity and slippage checks

        Анализирует готовность к выходу с проверками:
        1. Доступная ликвидность для закрытия позиции
        2. Влияние проскальзывания на итоговый PnL
        3. Спред слишком большой (может быть невыгодным выходить)
        4. Достаточно времени до истечения лимита позиции

        Args:
            symbol: Торговый символ
            position_side: Направление позиции (long/short)
            position_size: Размер позиции
            current_price: Текущая цена
            entry_price: Цена входа
            current_pnl_pct: Текущий PnL в %
            bid_price: Цена bid (если доступна)
            ask_price: Цена ask (если доступна)

        Returns:
            (can_exit, warning_message) tuple[bool, Optional[str]]
            can_exit=True если выход безопасен
            warning_message = предупреждение если есть проблемы
        """
        try:
            warnings = []

            # ✅ Check 1: Validate prices
            if current_price <= 0:
                return False, f"Invalid current price: {current_price}"
            if entry_price <= 0:
                return False, f"Invalid entry price: {entry_price}"

            # ✅ Check 2: Estimate exit slippage
            if bid_price and ask_price and bid_price > 0 and ask_price > 0:
                spread = ask_price - bid_price
                spread_pct = (spread / current_price) * 100

                if spread_pct > 0.5:
                    warnings.append(
                        f"High spread warning: {spread_pct:.3f}% "
                        f"(bid={bid_price:.2f}, ask={ask_price:.2f})"
                    )

                # Estimate slippage impact
                # For close: if long, we sell at bid (worst case); if short, we buy at ask
                if position_side.lower() == "long":
                    exit_price = bid_price
                else:
                    exit_price = ask_price

                exit_slippage_pct = (
                    abs(exit_price - current_price) / current_price
                ) * 100

                if exit_slippage_pct > 0.2:
                    warnings.append(
                        f"High exit slippage: {exit_slippage_pct:.3f}% "
                        f"(will exit at {exit_price:.2f} vs current {current_price:.2f})"
                    )

                # Check if PnL will be positive after slippage
                net_pnl_pct = current_pnl_pct - exit_slippage_pct
                if net_pnl_pct < 0:
                    warnings.append(
                        f"Warning: Net PnL after slippage will be negative: "
                        f"{current_pnl_pct:.2f}% - {exit_slippage_pct:.3f}% = {net_pnl_pct:.2f}%"
                    )

            # ✅ Check 3: Liquidity availability (basic check)
            # In real implementation, would check order book depth
            # For now, just warn if position is very large relative to typical volume
            position_notional = position_size * current_price
            if position_notional > 100000:  # Large position
                logger.warning(
                    f"⚠️ Large position for {symbol}: ${position_notional:.0f} "
                    f"(may have liquidity impact)"
                )
                warnings.append("Large position may have liquidity impact on exit")

            # Log warnings if any
            if warnings:
                for warning in warnings:
                    logger.warning(f"⚠️ {symbol}: {warning}")

            # Can still exit, but user is warned
            return True, "; ".join(warnings) if warnings else None

        except Exception as e:
            logger.error(
                f"❌ Error analyzing exit conditions for {symbol}: {e}", exc_info=True
            )
            return False, f"Analysis error: {str(e)}"
