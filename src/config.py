"""
Configuration management for the trading bot
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()


class _UniqueKeyLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate mapping keys."""


def _construct_mapping_no_duplicates(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            line = key_node.start_mark.line + 1
            raise ValueError(f"Duplicate YAML key '{key}' at line {line}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_no_duplicates,
)


def load_yaml_strict(stream) -> Dict[str, Any]:
    """
    Load YAML with duplicate-key protection.

    Raises:
        ValueError: when duplicate keys are found and strict mode is enabled.
    """
    raw_yaml = stream.read()
    try:
        data = yaml.load(raw_yaml, Loader=_UniqueKeyLoader)  # nosec B506
        return data or {}
    except ValueError as dup_error:
        strict_mode = os.getenv("YAML_DUPLICATE_KEYS_STRICT", "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if strict_mode:
            raise

        logger.warning(
            f"⚠️ Duplicate YAML keys detected ({dup_error}). "
            "Continuing with yaml.safe_load() fallback (last key wins). "
            "Set YAML_DUPLICATE_KEYS_STRICT=0 to disable fail-fast."
        )
        data = yaml.safe_load(raw_yaml)
        return data or {}


class APIConfig(BaseModel):
    api_key: str = Field(..., description="OKX API Key")
    api_secret: str = Field(..., description="OKX API Secret")
    passphrase: str = Field(..., description="OKX Passphrase")
    sandbox: bool = Field(default=True, description="Use sandbox environment")


class RiskConfig(BaseModel):
    max_position_size_percent: float = Field(default=5.0, ge=0.1, le=100.0)
    max_daily_loss_percent: float = Field(default=10.0, ge=1.0, le=50.0)
    risk_per_trade_percent: float = Field(default=1.0, ge=0.1, le=10.0)
    max_open_positions: int = Field(default=3, ge=1, le=10)
    # Адаптивные минимумы для разных размеров баланса
    adaptive_minimums: Optional[Dict] = Field(default=None)
    # ✅ НОВОЕ: Адаптивные параметры риска (base, by_regime, by_balance)
    base: Optional[Dict] = Field(default_factory=dict)
    by_regime: Optional[Dict] = Field(default_factory=dict)
    by_balance: Optional[Dict] = Field(default_factory=dict)
    # Для обратной совместимости
    adaptive_risk: Optional[bool] = Field(default=False)
    balance_threshold: Optional[float] = Field(default=None)
    risk_reduction_factor: Optional[float] = Field(default=None)


class IndicatorConfig(BaseModel):
    sma_fast: int = Field(default=5, ge=2, le=50)
    sma_slow: int = Field(default=20, ge=10, le=200)
    ema_fast: int = Field(default=8, ge=2, le=50)
    ema_slow: int = Field(default=21, ge=10, le=200)
    rsi_period: int = Field(default=14, ge=2, le=50)
    atr_period: int = Field(default=14, ge=2, le=50)
    bollinger_period: int = Field(default=20, ge=5, le=50)
    bollinger_std: float = Field(default=2.0, ge=1.0, le=3.0)


class ScalpingEntryConfig(BaseModel):
    min_volatility_atr: float = Field(default=0.0005, ge=0.0001)
    rsi_overbought: int = Field(default=70, ge=60, le=90)
    rsi_oversold: int = Field(default=30, ge=10, le=40)
    volume_threshold: float = Field(default=1.2, ge=1.0, le=3.0)


class ScalpingExitConfig(BaseModel):
    take_profit_atr_multiplier: float = Field(default=2.0, ge=1.0, le=5.0)
    stop_loss_atr_multiplier: float = Field(default=1.5, ge=0.5, le=3.0)
    max_holding_minutes: int = Field(default=15, ge=1, le=60)


class BalanceProfile(BaseModel):
    # Основные поля (обязательные для всех режимов)
    threshold: float = Field(default=1000.0, description="Порог баланса для профиля")
    threshold_usd: float = Field(
        default=None, description="Альтернативное название для Spot"
    )
    base_position_usd: float = Field(default=50.0, description="Базовый размер позиции")
    max_open_positions: int = Field(default=2, description="Максимум открытых позиций")
    max_position_percent: float = Field(
        default=5.0, description="Максимальный % от баланса"
    )

    # Опциональные поля для разных режимов
    min_position_usd: float = Field(
        default=10.0, description="Минимальный размер позиции"
    )

    # Spot-специфичные поля (опциональные для Futures)
    tp_atr_multiplier_boost: float = Field(default=1.0, description="Буст для TP")
    sl_atr_multiplier_boost: float = Field(default=1.0, description="Буст для SL")
    ph_threshold_multiplier: float = Field(default=1.0, description="Множитель PH")
    min_score_boost: int = Field(default=0, description="Буст для минимального скора")

    class Config:
        extra = "allow"  # Разрешаем дополнительные поля из YAML


class ImpulseRelaxOverride(BaseModel):
    liquidity: Optional[float] = None
    order_flow: Optional[float] = None
    allow_mtf_bypass: Optional[bool] = None
    bypass_correlation: Optional[bool] = None


class ImpulseTrailingOverride(BaseModel):
    initial_trail: Optional[float] = None
    max_trail: Optional[float] = None
    min_trail: Optional[float] = None
    step_profit: Optional[float] = None
    step_trail: Optional[float] = None
    aggressive_max_trail: Optional[float] = None
    loss_cut_percent: Optional[float] = None
    timeout_minutes: Optional[float] = None


class ImpulseOverrides(BaseModel):
    relax: Optional[ImpulseRelaxOverride] = None
    trailing: Optional[ImpulseTrailingOverride] = None


class PositionProfile(BaseModel):
    base_position_usd: Optional[float] = None
    min_position_usd: Optional[float] = None
    max_position_usd: Optional[float] = None
    max_open_positions: Optional[int] = None
    max_position_percent: Optional[float] = None


class LiquidityThresholdOverride(BaseModel):
    min_daily_volume_usd: Optional[float] = None
    min_best_bid_volume_usd: Optional[float] = None
    min_best_ask_volume_usd: Optional[float] = None
    min_orderbook_depth_usd: Optional[float] = None
    max_spread_percent: Optional[float] = None


class OrderFlowThresholdOverride(BaseModel):
    window: Optional[int] = None
    long_threshold: Optional[float] = None
    short_threshold: Optional[float] = None
    min_total_depth_usd: Optional[float] = None


class FundingThresholdOverride(BaseModel):
    max_positive_rate: Optional[float] = None
    max_negative_rate: Optional[float] = None
    max_abs_rate: Optional[float] = None


class VolatilityThresholdOverride(BaseModel):
    min_range_percent: Optional[float] = None
    max_range_percent: Optional[float] = None
    min_atr_percent: Optional[float] = None
    max_atr_percent: Optional[float] = None


class RegimeFilterOverrides(BaseModel):
    liquidity: Optional[LiquidityThresholdOverride] = None
    order_flow: Optional[OrderFlowThresholdOverride] = None
    funding: Optional[FundingThresholdOverride] = None
    volatility: Optional[VolatilityThresholdOverride] = None


class SymbolRegimeConfig(BaseModel):
    arm: Optional[Dict[str, Any]] = None
    position: Optional[PositionProfile] = None
    filters: Optional[RegimeFilterOverrides] = None
    impulse: Optional[ImpulseOverrides] = None

    class Config:
        extra = "allow"


class SymbolProfile(BaseModel):
    detection: Optional[Dict[str, Any]] = Field(default=None, alias="__detection__")
    trending: Optional[SymbolRegimeConfig] = None
    ranging: Optional[SymbolRegimeConfig] = None
    choppy: Optional[SymbolRegimeConfig] = None

    class Config:
        extra = "allow"
        allow_population_by_field_name = True


class AdaptiveRegimeConfig(BaseModel):
    enabled: bool = True
    detection: Dict[str, Any] = Field(default_factory=dict)
    trending: Dict[str, Any] = Field(default_factory=dict)
    ranging: Dict[str, Any] = Field(default_factory=dict)
    choppy: Dict[str, Any] = Field(default_factory=dict)
    symbol_profiles: Dict[str, SymbolProfile] = Field(default_factory=dict)

    class Config:
        extra = "allow"


class ScalpingConfig(BaseModel):
    enabled: bool = Field(default=True)
    symbols: List[str] = Field(default=["BTC-USDT", "ETH-USDT"])
    timeframe: str = Field(default="1m")
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)
    entry: ScalpingEntryConfig = Field(default_factory=ScalpingEntryConfig)
    exit: ScalpingExitConfig = Field(default_factory=ScalpingExitConfig)
    max_trades_per_hour: int = Field(default=10, ge=1, le=50)
    cooldown_after_loss_minutes: int = Field(default=5, ge=1, le=30)
    min_signal_strength: float = Field(default=0.3, ge=0.0, le=1.0)
    check_interval: float = Field(default=5.0, ge=0.5, le=60.0)
    max_concurrent_signals: int = Field(default=5, ge=1, le=20)

    # Futures-specific parameters
    tp_percent: Optional[float] = Field(
        default=None, ge=0.1, le=10.0, description="Take Profit %"
    )
    sl_percent: Optional[float] = Field(
        default=None, ge=0.1, le=10.0, description="Stop Loss %"
    )
    signal_cooldown_seconds: float = Field(
        default=0.0,
        ge=0.0,
        le=600.0,
        description="Минимальная задержка между сигналами на символ",
    )

    class Config:
        extra = "allow"  # Разрешаем дополнительные поля из YAML

    # Balance Profiles - адаптивные параметры по размеру баланса
    balance_profiles: Dict[str, BalanceProfile] = Field(default_factory=dict)

    # ✅ КРИТИЧЕСКОЕ: Signal Generator конфигурация (fail-fast)
    signal_generator: Dict[str, Any] = Field(default_factory=dict)
    # ✅ НОВОЕ: Order Executor конфигурация
    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем Dict без Optional, чтобы Pydantic загружал из YAML
    # Проблема: Pydantic v2 с extra="allow" может не загружать поля с default_factory=dict
    # Решение: Используем обычный Dict с проверкой в коде
    order_executor: Dict[str, Any] = Field(default_factory=dict)

    # PHASE 1 Modules (flexible dict для хранения настроек модулей)
    multi_timeframe_enabled: bool = Field(default=False)
    multi_timeframe: Dict = Field(default_factory=dict)
    correlation_filter_enabled: bool = Field(default=False)
    correlation_filter: Dict = Field(default_factory=dict)
    adx_filter_enabled: bool = Field(default=False)  # 🆕 ADX Filter
    adx_filter: Dict = Field(default_factory=dict)  # 🆕 ADX параметры
    time_filter_enabled: bool = Field(default=False)
    time_filter: Dict = Field(default_factory=dict)
    volatility_modes_enabled: bool = Field(default=False)
    volatility_modes: Dict = Field(default_factory=dict)
    pivot_points_enabled: bool = Field(
        default=True
    )  # ✅ ИСПРАВЛЕНО: Включено по умолчанию
    pivot_points: Dict = Field(default_factory=dict)
    volume_profile_enabled: bool = Field(
        default=True
    )  # ✅ ИСПРАВЛЕНО: Включено по умолчанию
    volume_profile: Dict = Field(default_factory=dict)
    balance_checker_enabled: bool = Field(default=False)
    balance_checker: Dict = Field(default_factory=dict)
    adaptive_regime_enabled: bool = Field(default=False)
    adaptive_regime: AdaptiveRegimeConfig = Field(default_factory=AdaptiveRegimeConfig)

    # ✅ НОВОЕ: Order Executor конфигурация
    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем Dict с default_factory=dict
    # Pydantic v2 с extra="allow" должен загружать дополнительные поля из YAML
    order_executor: Dict[str, Any] = Field(
        default_factory=dict,
        description="Конфигурация order_executor с limit_order и by_symbol/by_regime",
    )


class TradingConfig(BaseModel):
    symbols: List[str] = Field(default=["BTC-USDT", "ETH-USDT"])
    base_currency: str = Field(default="USDT")


class FundingFilterConfig(BaseModel):
    enabled: bool = Field(default=True)
    max_positive_rate: float = Field(
        default=0.0006, description="Максимальный допустимый funding для лонга (доля)"
    )
    max_negative_rate: float = Field(
        default=0.0006, description="Максимальный допустимый funding для шорта (доля)"
    )
    max_abs_rate: float = Field(
        default=0.0008,
        description="Абсолютный порог funding вне зависимости от стороны",
    )
    include_next_funding: bool = Field(
        default=True, description="Учитывать прогноз следующего периода funding"
    )
    refresh_interval_seconds: int = Field(
        default=300, description="Интервал обновления кэша funding (секунды)", ge=10
    )


class LiquiditySymbolOverride(BaseModel):
    min_daily_volume_usd: Optional[float] = None
    min_best_bid_volume_usd: Optional[float] = None
    min_best_ask_volume_usd: Optional[float] = None
    min_orderbook_depth_usd: Optional[float] = None
    max_spread_percent: Optional[float] = None


class LiquidityRegimeMultiplier(BaseModel):
    min_daily_volume_multiplier: Optional[float] = None
    min_best_bid_volume_multiplier: Optional[float] = None
    min_best_ask_volume_multiplier: Optional[float] = None
    min_orderbook_depth_multiplier: Optional[float] = None
    max_spread_multiplier: Optional[float] = None


class LiquidityFilterConfig(BaseModel):
    enabled: bool = Field(default=True)
    min_daily_volume_usd: float = Field(
        default=20_000_000.0, description="Минимальный 24ч объём в USD"
    )
    min_best_bid_volume_usd: float = Field(
        default=250_000.0, description="Минимальный объём на лучшем bid (USD)"
    )
    min_best_ask_volume_usd: float = Field(
        default=250_000.0, description="Минимальный объём на лучшем ask (USD)"
    )
    min_orderbook_depth_usd: float = Field(
        default=500_000.0, description="Минимальная суммарная глубина стакана (USD)"
    )
    depth_levels: int = Field(
        default=5,
        description="Количество уровней стакана для оценки глубины",
        ge=1,
        le=20,
    )
    max_spread_percent: float = Field(
        default=0.25, description="Максимально допустимый спред в процентах"
    )
    refresh_interval_seconds: int = Field(
        default=30, description="Интервал обновления кэша ликвидности (секунды)", ge=5
    )
    symbol_overrides: Dict[str, LiquiditySymbolOverride] = Field(
        default_factory=dict,
        description="Индивидуальные пороги ликвидности по символам",
    )
    fail_open_enabled: bool = Field(
        default=False,
        description="Включить временное ослабление порогов при серии блокировок",
    )
    max_consecutive_blocks: int = Field(
        default=5,
        ge=1,
        description="Количество подряд блокировок перед ослаблением порогов",
    )
    relax_multiplier: float = Field(
        default=0.5,
        gt=0.0,
        description="Множитель ослабления объёмных порогов (значение <1 уменьшает требования)",
    )
    relax_duration_seconds: int = Field(
        default=60, ge=1, description="Длительность ослабления порогов (секунды)"
    )
    regime_multipliers: Dict[str, LiquidityRegimeMultiplier] = Field(
        default_factory=dict,
        description="Множители порогов по режимам ARM",
    )


class OrderFlowRegimeProfile(BaseModel):
    window: Optional[int] = None
    long_threshold: Optional[float] = None
    short_threshold: Optional[float] = None
    min_total_depth_usd: Optional[float] = None


class OrderFlowFilterConfig(BaseModel):
    enabled: bool = Field(default=True)
    window: int = Field(default=50, ge=5, le=500)
    long_threshold: float = Field(
        default=0.05, description="Минимальный delta для подтверждения лонга"
    )
    short_threshold: float = Field(
        default=-0.05, description="Максимальный delta для подтверждения шорта"
    )
    min_total_depth_usd: float = Field(
        default=300_000.0, description="Минимальная суммарная глубина стакана (USD)"
    )
    refresh_interval_seconds: int = Field(
        default=15, description="Интервал обновления кэша ордер флоу (секунды)", ge=5
    )
    fail_open_enabled: bool = Field(
        default=False,
        description="Включить временное ослабление порогов, если фильтр блокирует сигналы подряд",
    )
    max_consecutive_blocks: int = Field(
        default=4,
        ge=1,
        description="Количество подряд блокировок до активации fail-open",
    )
    relax_multiplier: float = Field(
        default=0.5,
        gt=0.0,
        description="Множитель ослабления порогов order flow (значение <1 снижает требования)",
    )
    relax_duration_seconds: int = Field(
        default=30,
        ge=1,
        description="Длительность ослабления порогов order flow (секунды)",
    )
    regime_profiles: Dict[str, OrderFlowRegimeProfile] = Field(
        default_factory=dict,
        description="Наборы порогов OrderFlow по режимам ARM",
    )


class VolatilityFilterConfig(BaseModel):
    enabled: bool = Field(default=True)
    lookback_candles: int = Field(default=30, ge=5, le=200)
    min_range_percent: float = Field(
        default=0.15, description="Минимальный диапазон движения цены (проценты)"
    )
    max_range_percent: float = Field(
        default=3.5, description="Максимальный диапазон движения цены (проценты)"
    )
    min_atr_percent: float = Field(
        default=0.05,
        description="Минимальное значение ATR относительно цены (проценты)",
    )
    max_atr_percent: float = Field(
        default=2.0,
        description="Максимальное значение ATR относительно цены (проценты)",
    )


class ImpulseTrailingConfig(BaseModel):
    initial_trail: float = Field(
        default=0.003,
        ge=0.0,
        le=0.1,
        description="Стартовый трейл для импульсной сделки",
    )
    max_trail: float = Field(
        default=0.02,
        ge=0.0,
        le=0.2,
        description="Максимальный трейл для импульсной сделки",
    )
    min_trail: float = Field(
        default=0.001,
        ge=0.0,
        le=0.1,
        description="Минимальный трейл для импульсной сделки",
    )
    step_profit: float = Field(
        default=0.003,
        ge=0.0,
        le=0.1,
        description="Шаг прибыли (в долях) для последовательного подтягивания трейла",
    )
    step_trail: float = Field(
        default=0.001,
        ge=0.0,
        le=0.05,
        description="Насколько увеличивать трейл при каждом шаге прибыли",
    )
    aggressive_max_trail: Optional[float] = Field(
        default=0.03,
        ge=0.0,
        le=0.2,
        description="Ограничение трейла в агрессивном режиме (если None — используем max_trail)",
    )
    loss_cut_percent: Optional[float] = Field(
        default=0.015,
        ge=0.0,
        le=0.2,
        description="Принудительное закрытие при откате (в долях или процентах)",
    )
    timeout_minutes: Optional[float] = Field(
        default=3.0,
        ge=0.0,
        le=30.0,
        description="Максимальное время удержания импульсной позиции",
    )


class ImpulseRelaxConfig(BaseModel):
    liquidity_multiplier: float = Field(
        default=0.7,
        gt=0.0,
        le=1.0,
        description="Множитель ослабления порогов LiquidityFilter",
    )
    order_flow_multiplier: float = Field(
        default=0.6,
        gt=0.0,
        le=1.0,
        description="Множитель ослабления порогов OrderFlowFilter",
    )
    allow_mtf_bypass: bool = Field(
        default=True, description="Пропускать проверку MTF для импульсных сигналов"
    )
    bypass_correlation: bool = Field(
        default=False,
        description="Игнорировать CorrelationFilter для импульсных сигналов",
    )


class ImpulseTradingConfig(BaseModel):
    enabled: bool = Field(default=False)
    lookback_candles: int = Field(
        default=6, ge=3, le=120, description="Количество свечей для оценки импульса"
    )
    min_body_atr_ratio: float = Field(
        default=1.6,
        ge=0.5,
        le=10.0,
        description="Минимальное отношение тела свечи к ATR для признания импульса",
    )
    min_volume_ratio: float = Field(
        default=1.4,
        ge=0.5,
        le=10.0,
        description="Минимальное отношение объема к среднему за lookback",
    )
    pivot_lookback: int = Field(
        default=20,
        ge=5,
        le=200,
        description="Глубина поиска предыдущих экстремумов для подтверждения пробоя",
    )
    min_breakout_percent: float = Field(
        default=0.002,
        ge=0.0,
        le=0.1,
        description="Минимальное превышение предыдущего экстремума (в долях)",
    )
    max_wick_ratio: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Максимальная доля тени относительно тела (чтобы свеча была импульсной)",
    )
    trailing: ImpulseTrailingConfig = Field(
        default_factory=ImpulseTrailingConfig,
        description="Профиль трейлинга для импульсных сделок",
    )
    relax: ImpulseRelaxConfig = Field(
        default_factory=ImpulseRelaxConfig,
        description="Настройки ослабления фильтров для импульсных сделок",
    )


class FuturesModulesConfig(BaseModel):
    """Конфигурация Futures-специфичных модулей"""

    slippage_guard: Optional[Dict] = Field(default_factory=dict)
    order_flow: Optional[OrderFlowFilterConfig] = Field(
        default_factory=OrderFlowFilterConfig
    )
    micro_pivot: Optional[Dict] = Field(default_factory=dict)
    trailing_sl: Optional[Dict] = Field(default_factory=dict)
    reentry_guard: Optional[Dict] = Field(default_factory=dict)  # ✅ L2-4 FIX
    funding_monitor: Optional[Dict] = Field(default_factory=dict)
    max_size_limiter: Optional[Dict] = Field(default_factory=dict)
    funding_filter: Optional[FundingFilterConfig] = Field(
        default_factory=FundingFilterConfig
    )
    liquidity_filter: Optional[LiquidityFilterConfig] = Field(
        default_factory=LiquidityFilterConfig
    )
    volatility_filter: Optional[VolatilityFilterConfig] = Field(
        default_factory=VolatilityFilterConfig
    )
    impulse_trading: Optional[ImpulseTradingConfig] = Field(
        default_factory=ImpulseTradingConfig
    )
    margin: Optional[Dict] = Field(
        default=None,
        description="✅ ОБЯЗАТЕЛЬНО: Параметры маржи с адаптивными значениями для режимов (trending/ranging/choppy)",
    )


class BotConfig(BaseModel):
    api: Dict[str, APIConfig]
    trading: TradingConfig
    risk: RiskConfig
    scalping: ScalpingConfig
    manual_pools: Optional[Dict] = Field(default_factory=dict)
    futures_modules: Optional[FuturesModulesConfig] = Field(default=None)

    @classmethod
    def load_from_file(cls, config_path: str = "config.yaml") -> "BotConfig":
        """
        Загрузка конфигурации из YAML файла.

        Читает YAML файл, подставляет переменные окружения
        и валидирует конфигурацию через Pydantic модели.

        Args:
            config_path: Путь к YAML файлу конфигурации (default: config.yaml)

        Returns:
            BotConfig: Валидированный объект конфигурации

        Raises:
            FileNotFoundError: Если файл конфигурации не найден
            yaml.YAMLError: При ошибках парсинга YAML
            pydantic.ValidationError: При невалидной конфигурации
        """
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_file, "r", encoding="utf-8") as f:
            raw_config = load_yaml_strict(f)

        # Replace environment variable placeholders
        raw_config = cls._substitute_env_vars(raw_config)

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Убеждаемся, что order_executor загружается из YAML
        # Проблема: Pydantic v2 может не загружать дополнительные поля даже с extra="allow"
        # если они определены в модели с default=None или default_factory
        # Решение: Явно проверяем наличие order_executor в raw_config и убеждаемся, что он передается
        # Если order_executor есть в YAML, но не определен в модели явно, Pydantic может его игнорировать
        # Поэтому мы явно проверяем и логируем для диагностики
        if "scalping" in raw_config and isinstance(raw_config["scalping"], dict):
            scalping_raw = raw_config["scalping"]
            if "order_executor" in scalping_raw:
                # order_executor есть в YAML, Pydantic должен загрузить его благодаря extra="allow"
                # Но если он определен в модели с default=None, Pydantic может использовать default
                # Поэтому убеждаемся, что он передается явно
                pass  # Pydantic должен загрузить автоматически с extra="allow"

        config_obj = cls(**raw_config)

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если order_executor или signal_generator не загрузились через Pydantic,
        # загружаем их вручную из raw_config
        if hasattr(config_obj, "scalping") and "scalping" in raw_config:
            scalping_raw = raw_config["scalping"]
            if "order_executor" in scalping_raw:
                order_executor_raw = scalping_raw["order_executor"]
                # Проверяем, загрузился ли order_executor в scalping_config
                # Проверяем не только None, но и пустой словарь {}
                order_executor_current = getattr(
                    config_obj.scalping, "order_executor", None
                )
                if order_executor_current is None or (
                    isinstance(order_executor_current, dict)
                    and len(order_executor_current) == 0
                ):
                    # Если не загрузился или пустой, устанавливаем вручную
                    logger.debug(
                        f"✅ order_executor вручную устанавливается в scalping_config (было: {order_executor_current})"
                    )
                    if isinstance(config_obj.scalping, dict):
                        config_obj.scalping["order_executor"] = order_executor_raw
                    else:
                        # Для Pydantic модели устанавливаем через setattr (более надежно, чем __dict__)
                        setattr(
                            config_obj.scalping, "order_executor", order_executor_raw
                        )
                        logger.debug(
                            f"✅ order_executor установлен через setattr: {type(getattr(config_obj.scalping, 'order_executor', None))}"
                        )

            # Аналогичная обработка для signal_generator
            if "signal_generator" in scalping_raw:
                signal_generator_raw = scalping_raw["signal_generator"]
                # Всегда устанавливаем, даже если пустой
                logger.debug(
                    f"✅ signal_generator найден в raw_config, keys: {list(signal_generator_raw.keys()) if isinstance(signal_generator_raw, dict) else 'not dict'}"
                )
                setattr(config_obj.scalping, "signal_generator", signal_generator_raw)
                logger.debug(
                    f"✅ signal_generator установлен, проверка: {getattr(config_obj.scalping, 'signal_generator', {}).get('ws_fresh_max_age', 'NOT SET')}"
                )
                logger.debug(
                    f"✅ signal_generator установлен: {type(getattr(config_obj.scalping, 'signal_generator', None))}"
                )
            else:
                logger.debug("❌ signal_generator не найден в raw_config")

        return config_obj

    @staticmethod
    def _substitute_env_vars(obj: Any) -> Any:
        """
        Рекурсивная подстановка переменных окружения в конфигурации.

        Проходит по всей структуре конфигурации и заменяет строки вида
        ${VARIABLE_NAME} на значения из переменных окружения.

        Args:
            obj: Объект конфигурации (dict, list, str или другой тип)

        Returns:
            Any: Объект с подставленными переменными окружения

        Example:
            >>> _substitute_env_vars({"key": "${API_KEY}"})
            {"key": "actual_api_key_value"}
        """
        if isinstance(obj, dict):
            return {
                key: BotConfig._substitute_env_vars(value) for key, value in obj.items()
            }
        elif isinstance(obj, list):
            return [BotConfig._substitute_env_vars(item) for item in obj]
        elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            env_var = obj[2:-1]
            return os.getenv(env_var, obj)
        else:
            return obj

    def get_okx_config(self) -> APIConfig:
        """
        Получение конфигурации API биржи OKX.

        Извлекает специфичную конфигурацию для OKX из общего
        словаря API конфигураций.

        Returns:
            APIConfig: Конфигурация API для OKX (ключи, sandbox режим)

        Raises:
            KeyError: Если конфигурация OKX не найдена
        """
        return self.api["okx"]


# Global configuration instance
config: Optional[BotConfig] = None


def load_config(config_path: str = "config.yaml") -> BotConfig:
    """
    Загрузка и инициализация глобальной конфигурации бота.

    Загружает конфигурацию из файла и сохраняет в глобальную переменную
    для доступа из любой части приложения.

    Args:
        config_path: Путь к YAML файлу конфигурации (default: config.yaml)

    Returns:
        BotConfig: Загруженная и валидированная конфигурация

    Raises:
        FileNotFoundError: Если файл конфигурации не найден
        ValueError: При невалидных значениях в конфигурации
    """
    global config
    config = BotConfig.load_from_file(config_path)
    return config


def get_config() -> BotConfig:
    """
    Получение текущего экземпляра глобальной конфигурации.

    Возвращает ранее загруженную конфигурацию. Если конфигурация
    не была загружена, выбрасывает исключение.

    Returns:
        BotConfig: Текущий экземпляр конфигурации

    Raises:
        RuntimeError: Если конфигурация не была загружена через load_config()

    Example:
        >>> load_config("config.yaml")
        >>> config = get_config()
        >>> print(config.risk.max_position_size_percent)
    """
    if config is None:
        raise RuntimeError("Configuration not loaded. Call load_config() first.")
    return config
