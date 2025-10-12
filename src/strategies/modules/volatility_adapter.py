"""
Volatility Adapter Module

Адаптирует параметры торговой стратегии в зависимости от текущего режима
волатильности рынка (LOW/NORMAL/HIGH).

Использует детекцию режима рынка для динамической настройки:
- Stop Loss / Take Profit множителей
- Порога scoring для входа
- Размера позиции
- Таймаутов и cooldown
"""

from enum import Enum
from typing import Dict, Optional

from loguru import logger
from pydantic import BaseModel, Field


class VolatilityRegime(str, Enum):
    """Режимы волатильности рынка"""

    LOW = "LOW_VOL"  # Низкая волатильность (< 1% ATR)
    NORMAL = "NORMAL"  # Нормальная волатильность (1-2% ATR)
    HIGH = "HIGH_VOL"  # Высокая волатильность (> 2% ATR)


class VolatilityModeConfig(BaseModel):
    """Конфигурация режима волатильности"""

    enabled: bool = Field(default=True, description="Включить адаптацию")

    # Пороги определения режима
    low_volatility_threshold: float = Field(
        default=0.01, ge=0.005, le=0.02, description="Порог низкой волатильности (1%)"
    )
    high_volatility_threshold: float = Field(
        default=0.02, ge=0.015, le=0.05, description="Порог высокой волатильности (2%)"
    )

    # LOW VOLATILITY режим (узкие диапазоны, частые сделки)
    low_vol_sl_multiplier: float = Field(
        default=1.5, ge=1.0, le=3.0, description="SL множитель для LOW"
    )
    low_vol_tp_multiplier: float = Field(
        default=1.0, ge=0.5, le=2.0, description="TP множитель для LOW"
    )
    low_vol_score_threshold: int = Field(
        default=6, ge=4, le=10, description="Score порог для LOW (легче входить)"
    )
    low_vol_position_size_multiplier: float = Field(
        default=1.2, ge=0.8, le=1.5, description="Размер позиции для LOW"
    )

    # NORMAL режим (стандартные параметры)
    normal_vol_sl_multiplier: float = Field(
        default=2.5, ge=1.5, le=4.0, description="SL множитель для NORMAL"
    )
    normal_vol_tp_multiplier: float = Field(
        default=1.5, ge=1.0, le=3.0, description="TP множитель для NORMAL"
    )
    normal_vol_score_threshold: int = Field(
        default=7, ge=5, le=10, description="Score порог для NORMAL"
    )
    normal_vol_position_size_multiplier: float = Field(
        default=1.0, ge=0.8, le=1.5, description="Размер позиции для NORMAL"
    )

    # HIGH VOLATILITY режим (широкие стопы, осторожная торговля)
    high_vol_sl_multiplier: float = Field(
        default=3.5, ge=2.0, le=5.0, description="SL множитель для HIGH"
    )
    high_vol_tp_multiplier: float = Field(
        default=2.5, ge=1.5, le=4.0, description="TP множитель для HIGH"
    )
    high_vol_score_threshold: int = Field(
        default=8, ge=6, le=11, description="Score порог для HIGH (строже)"
    )
    high_vol_position_size_multiplier: float = Field(
        default=0.7, ge=0.5, le=1.0, description="Размер позиции для HIGH (меньше риск)"
    )


class VolatilityParameters(BaseModel):
    """Адаптированные параметры для текущего режима"""

    regime: VolatilityRegime
    sl_multiplier: float
    tp_multiplier: float
    score_threshold: int
    position_size_multiplier: float
    description: str


class VolatilityAdapter:
    """
    Адаптер волатильности для динамической настройки параметров.

    Определяет текущий режим волатильности и возвращает оптимизированные
    параметры для торговли в этом режиме.

    Example:
        >>> config = VolatilityModeConfig(enabled=True)
        >>> adapter = VolatilityAdapter(config)
        >>> params = adapter.get_parameters(current_volatility=0.025)
        >>> logger.info(f"Regime: {params.regime}, SL: {params.sl_multiplier}x")
    """

    def __init__(self, config: VolatilityModeConfig):
        """
        Инициализация адаптера волатильности.

        Args:
            config: Конфигурация режимов волатильности
        """
        self.config = config
        self.current_regime: Optional[VolatilityRegime] = None
        self.regime_change_count = 0

        logger.info(
            f"Volatility Adapter initialized: "
            f"LOW<{config.low_volatility_threshold:.1%}, "
            f"HIGH>{config.high_volatility_threshold:.1%}"
        )

    def get_parameters(
        self, current_volatility: float, market_regime: Optional[str] = None
    ) -> VolatilityParameters:
        """
        Получить адаптированные параметры для текущей волатильности.

        Args:
            current_volatility: Текущая волатильность (например, ATR / Price)
            market_regime: Дополнительная информация о режиме рынка

        Returns:
            VolatilityParameters: Оптимизированные параметры

        Example:
            >>> # ATR = 50, Price = 2000 -> volatility = 0.025 (2.5%)
            >>> params = adapter.get_parameters(current_volatility=0.025)
            >>> # Получаем HIGH volatility режим
        """
        if not self.config.enabled:
            # Если адаптация выключена - возвращаем NORMAL параметры
            return self._get_normal_parameters()

        # Определяем режим волатильности
        new_regime = self._detect_volatility_regime(current_volatility)

        # Логируем смену режима
        if new_regime != self.current_regime:
            self._log_regime_change(self.current_regime, new_regime, current_volatility)
            self.current_regime = new_regime
            self.regime_change_count += 1

        # Получаем параметры для режима
        if new_regime == VolatilityRegime.LOW:
            return self._get_low_volatility_parameters()
        elif new_regime == VolatilityRegime.HIGH:
            return self._get_high_volatility_parameters()
        else:
            return self._get_normal_parameters()

    def _detect_volatility_regime(self, volatility: float) -> VolatilityRegime:
        """
        Определить режим волатильности на основе текущего значения.

        Args:
            volatility: Текущая волатильность (ATR / Price)

        Returns:
            VolatilityRegime: Определенный режим
        """
        if volatility < self.config.low_volatility_threshold:
            return VolatilityRegime.LOW
        elif volatility > self.config.high_volatility_threshold:
            return VolatilityRegime.HIGH
        else:
            return VolatilityRegime.NORMAL

    def _get_low_volatility_parameters(self) -> VolatilityParameters:
        """Параметры для низкой волатильности"""
        return VolatilityParameters(
            regime=VolatilityRegime.LOW,
            sl_multiplier=self.config.low_vol_sl_multiplier,
            tp_multiplier=self.config.low_vol_tp_multiplier,
            score_threshold=self.config.low_vol_score_threshold,
            position_size_multiplier=self.config.low_vol_position_size_multiplier,
            description="Low volatility: Tight stops, easier entry, larger positions",
        )

    def _get_normal_parameters(self) -> VolatilityParameters:
        """Параметры для нормальной волатильности"""
        return VolatilityParameters(
            regime=VolatilityRegime.NORMAL,
            sl_multiplier=self.config.normal_vol_sl_multiplier,
            tp_multiplier=self.config.normal_vol_tp_multiplier,
            score_threshold=self.config.normal_vol_score_threshold,
            position_size_multiplier=self.config.normal_vol_position_size_multiplier,
            description="Normal volatility: Standard parameters",
        )

    def _get_high_volatility_parameters(self) -> VolatilityParameters:
        """Параметры для высокой волатильности"""
        return VolatilityParameters(
            regime=VolatilityRegime.HIGH,
            sl_multiplier=self.config.high_vol_sl_multiplier,
            tp_multiplier=self.config.high_vol_tp_multiplier,
            score_threshold=self.config.high_vol_score_threshold,
            position_size_multiplier=self.config.high_vol_position_size_multiplier,
            description="High volatility: Wide stops, stricter entry, smaller positions",
        )

    def _log_regime_change(
        self,
        old_regime: Optional[VolatilityRegime],
        new_regime: VolatilityRegime,
        volatility: float,
    ):
        """
        Логировать смену режима волатильности.

        Args:
            old_regime: Предыдущий режим
            new_regime: Новый режим
            volatility: Текущая волатильность
        """
        if old_regime is None:
            logger.info(
                f"📊 VOLATILITY REGIME DETECTED: {new_regime.value} "
                f"(volatility: {volatility:.2%})"
            )
        else:
            logger.warning(
                f"📊 VOLATILITY REGIME CHANGED: {old_regime.value} → {new_regime.value} "
                f"(volatility: {volatility:.2%}, change #{self.regime_change_count})"
            )

        # Логируем новые параметры (напрямую получаем, избегая рекурсии)
        if new_regime == VolatilityRegime.LOW:
            params = self._get_low_volatility_parameters()
        elif new_regime == VolatilityRegime.HIGH:
            params = self._get_high_volatility_parameters()
        else:
            params = self._get_normal_parameters()
            
        logger.info(
            f"   New parameters: "
            f"SL={params.sl_multiplier}x ATR, "
            f"TP={params.tp_multiplier}x ATR, "
            f"Score≥{params.score_threshold}/12, "
            f"Size={params.position_size_multiplier}x"
        )

    def get_regime_info(self) -> Dict:
        """
        Получить информацию о текущем режиме.

        Returns:
            Dict с информацией о режиме
        """
        return {
            "enabled": self.config.enabled,
            "current_regime": self.current_regime.value if self.current_regime else None,
            "regime_changes": self.regime_change_count,
            "low_threshold": self.config.low_volatility_threshold,
            "high_threshold": self.config.high_volatility_threshold,
        }

    def calculate_volatility(
        self, atr: float, price: float, normalize: bool = True
    ) -> float:
        """
        Рассчитать волатильность из ATR и цены.

        Args:
            atr: Average True Range
            price: Текущая цена
            normalize: Нормализовать к цене (%)

        Returns:
            float: Волатильность (% если normalize=True)

        Example:
            >>> # ATR=50, Price=2000
            >>> vol = adapter.calculate_volatility(50, 2000)
            >>> # vol = 0.025 (2.5%)
        """
        if price <= 0:
            logger.error(f"Invalid price: {price}")
            return 0.0

        if normalize:
            # Нормализуем ATR к цене (получаем процент)
            return atr / price
        else:
            # Возвращаем сырой ATR
            return atr

    def should_adjust_parameters(
        self, volatility: float, last_check_volatility: float, threshold: float = 0.003
    ) -> bool:
        """
        Проверить нужно ли перерасчитать параметры.

        Args:
            volatility: Текущая волатильность
            last_check_volatility: Волатильность при последней проверке
            threshold: Порог изменения для пересчета (0.3% по умолчанию)

        Returns:
            bool: True если нужен пересчет

        Example:
            >>> # Волатильность изменилась с 1.5% до 2.1% (разница 0.6%)
            >>> should_adjust = adapter.should_adjust_parameters(0.021, 0.015)
            >>> # True (больше порога 0.3%)
        """
        change = abs(volatility - last_check_volatility)
        return change >= threshold

    def get_adjusted_score_threshold(
        self, base_threshold: int, current_volatility: float
    ) -> int:
        """
        Получить адаптированный порог scoring.

        Args:
            base_threshold: Базовый порог из конфига
            current_volatility: Текущая волатильность

        Returns:
            int: Адаптированный порог

        Example:
            >>> # В HIGH VOL режиме порог строже
            >>> threshold = adapter.get_adjusted_score_threshold(7, 0.025)
            >>> # threshold = 8
        """
        params = self.get_parameters(current_volatility)
        return params.score_threshold

