"""
Configuration management for the trading bot
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()


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
    threshold_usd: int = Field(..., description="Минимальный баланс для профиля")
    base_position_usd: int = Field(..., description="Базовый размер позиции")
    max_open_positions: int = Field(..., description="Максимум открытых позиций")
    max_position_percent: int = Field(..., description="Максимальный % от баланса")
    tp_atr_multiplier_boost: float = Field(..., description="Буст для TP")
    sl_atr_multiplier_boost: float = Field(..., description="Буст для SL")
    ph_threshold_multiplier: float = Field(..., description="Множитель PH")
    min_score_boost: int = Field(..., description="Буст для минимального скора")


class ScalpingConfig(BaseModel):
    enabled: bool = Field(default=True)
    symbols: List[str] = Field(default=["BTC-USDT", "ETH-USDT"])
    timeframe: str = Field(default="1m")
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)
    entry: ScalpingEntryConfig = Field(default_factory=ScalpingEntryConfig)
    exit: ScalpingExitConfig = Field(default_factory=ScalpingExitConfig)
    max_trades_per_hour: int = Field(default=10, ge=1, le=50)
    cooldown_after_loss_minutes: int = Field(default=5, ge=1, le=30)

    # Balance Profiles - адаптивные параметры по размеру баланса
    balance_profiles: Dict[str, BalanceProfile] = Field(default_factory=dict)

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
    pivot_points_enabled: bool = Field(default=False)
    pivot_points: Dict = Field(default_factory=dict)
    volume_profile_enabled: bool = Field(default=False)
    volume_profile: Dict = Field(default_factory=dict)
    balance_checker_enabled: bool = Field(default=False)
    balance_checker: Dict = Field(default_factory=dict)
    adaptive_regime_enabled: bool = Field(default=False)
    adaptive_regime: Dict = Field(default_factory=dict)


class TradingConfig(BaseModel):
    symbols: List[str] = Field(default=["BTC-USDT", "ETH-USDT"])
    base_currency: str = Field(default="USDT")


class BotConfig(BaseModel):
    api: Dict[str, APIConfig]
    trading: TradingConfig
    risk: RiskConfig
    scalping: ScalpingConfig
    manual_pools: Optional[Dict] = Field(default_factory=dict)

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
            raw_config = yaml.safe_load(f)

        # Replace environment variable placeholders
        raw_config = cls._substitute_env_vars(raw_config)

        return cls(**raw_config)

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
