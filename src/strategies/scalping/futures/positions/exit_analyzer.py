"""
ExitAnalyzer - Централизованное управление закрытием позиций.

Анализирует позиции и принимает решения о закрытии/продлении для каждого режима.
Использует все ресурсы бота: ADX, Order Flow, MTF, индикаторы.
"""

from datetime import datetime
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
        """
        self.position_registry = position_registry
        self.data_registry = data_registry
        self.exit_decision_logger = exit_decision_logger
        self.orchestrator = orchestrator
        self.config_manager = config_manager
        self.signal_generator = signal_generator

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
        try:
            # Получаем позицию и метаданные
            position = await self.position_registry.get_position(symbol)
            metadata = await self.position_registry.get_metadata(symbol)

            if not position:
                logger.debug(f"ℹ️ ExitAnalyzer: Позиция {symbol} не найдена")
                return None

            # Получаем режим рынка
            regime = None
            if metadata and hasattr(metadata, "regime"):
                regime = metadata.regime
            elif isinstance(position, dict):
                regime = position.get("regime")

            # Если режим не найден, получаем из DataRegistry или signal_generator
            if not regime:
                regime_data = await self.data_registry.get_regime(symbol)
                if regime_data:
                    if hasattr(regime_data, "regime"):
                        regime = regime_data.regime
                    elif isinstance(regime_data, dict):
                        regime = regime_data.get("regime")

            # Если все еще не найден, пробуем из signal_generator
            if not regime and self.signal_generator:
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
                except Exception as e:
                    logger.debug(
                        f"⚠️ ExitAnalyzer: Не удалось получить режим из signal_generator: {e}"
                    )

            # Fallback на ranging
            if not regime:
                regime = "ranging"

            # Получаем рыночные данные
            market_data = await self.data_registry.get_market_data(symbol)
            current_price = await self.data_registry.get_price(symbol)

            if not current_price:
                logger.warning(f"⚠️ ExitAnalyzer: Нет цены для {symbol}")
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

            # Логируем решение
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
            logger.error(
                f"❌ ExitAnalyzer: Ошибка анализа позиции {symbol}: {e}", exc_info=True
            )
            return None

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    def _calculate_pnl_percent(
        self,
        entry_price: float,
        current_price: float,
        position_side: str,
        include_fees: bool = True,
    ) -> float:
        """
        Расчет PnL% с учетом комиссии.

        Args:
            entry_price: Цена входа
            current_price: Текущая цена
            position_side: Направление позиции ("long" или "short")
            include_fees: Учитывать комиссию

        Returns:
            PnL% от цены (с комиссией если include_fees=True)
        """
        if entry_price == 0:
            return 0.0

        # Базовая прибыль без комиссии
        if position_side.lower() == "long":
            gross_profit_pct = (current_price - entry_price) / entry_price
        else:  # short
            gross_profit_pct = (entry_price - current_price) / entry_price

        # Учитываем комиссию если нужно
        if include_fees:
            # Получаем комиссию из конфига (примерно 0.1% на круг)
            trading_fee_rate = 0.0010  # 0.1% по умолчанию
            if self.scalping_config:
                commission_config = getattr(self.scalping_config, "commission", {})
                if isinstance(commission_config, dict):
                    trading_fee_rate = commission_config.get("trading_fee_rate", 0.0010)
                elif hasattr(commission_config, "trading_fee_rate"):
                    trading_fee_rate = getattr(
                        commission_config, "trading_fee_rate", 0.0010
                    )

            net_profit_pct = gross_profit_pct - trading_fee_rate
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
            else:
                position_side = "long"  # Последний fallback

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
            elif isinstance(metadata, dict):
                entry_time_str = metadata.get("entry_time")
                if entry_time_str:
                    if isinstance(entry_time_str, str):
                        try:
                            entry_time = datetime.fromisoformat(
                                entry_time_str.replace("Z", "+00:00")
                            )
                        except:
                            pass
                    elif isinstance(entry_time_str, datetime):
                        entry_time = entry_time_str

            if not entry_time:
                # Если entry_time не найден, разрешаем partial_tp (без проверки времени)
                return True, "entry_time не найден, пропускаем проверку min_holding"

            # Рассчитываем время удержания в минутах
            duration_minutes = (datetime.now() - entry_time).total_seconds() / 60.0

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

            # 2. Рассчитываем PnL
            pnl_percent = self._calculate_pnl_percent(
                entry_price, current_price, position_side, include_fees=True
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
                trigger_percent = partial_tp_params.get("trigger_percent", 0.4)
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

            # 2. Рассчитываем PnL
            pnl_percent = self._calculate_pnl_percent(
                entry_price, current_price, position_side, include_fees=True
            )

            # 3. Проверка TP (Take Profit) - в ranging режиме закрываем сразу
            tp_percent = self._get_tp_percent(symbol, "ranging")
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
            if partial_tp_params.get("enabled", False):
                trigger_percent = partial_tp_params.get("trigger_percent", 0.6)
                if pnl_percent >= trigger_percent:
                    # ✅ Проверяем adaptive_min_holding перед partial_tp
                    (
                        can_partial_close,
                        min_holding_info,
                    ) = await self._check_adaptive_min_holding_for_partial_tp(
                        symbol, metadata, pnl_percent, "ranging"
                    )

                    if can_partial_close:
                        fraction = partial_tp_params.get("fraction", 0.6)
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

            # В ranging режиме не продлеваем TP - более консервативный подход
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

            # 2. Рассчитываем PnL
            pnl_percent = self._calculate_pnl_percent(
                entry_price, current_price, position_side, include_fees=True
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
            partial_tp_params = self._get_partial_tp_params("choppy")
            if partial_tp_params.get("enabled", False):
                trigger_percent = partial_tp_params.get("trigger_percent", 0.3)
                if pnl_percent >= trigger_percent:
                    # ✅ Проверяем adaptive_min_holding перед partial_tp
                    (
                        can_partial_close,
                        min_holding_info,
                    ) = await self._check_adaptive_min_holding_for_partial_tp(
                        symbol, metadata, pnl_percent, "choppy"
                    )

                    if can_partial_close:
                        fraction = partial_tp_params.get(
                            "fraction", 0.7
                        )  # Закрываем больше позиции
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
