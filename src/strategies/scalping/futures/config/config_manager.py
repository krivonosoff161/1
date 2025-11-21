"""
Config Manager для Futures торговли.

Управляет всеми параметрами конфигурации:
- Symbol profiles
- Trailing SL параметры
- Balance profiles
- Regime параметры
- Adaptive risk параметры
"""

from typing import Any, Dict, Optional

from loguru import logger

from src.config import BotConfig


class ConfigManager:
    """
    Менеджер конфигурации для Futures торговли.

    Функции:
    - Загрузка и нормализация symbol_profiles
    - Получение параметров Trailing SL
    - Получение balance profiles
    - Получение regime параметров
    - Получение adaptive risk параметров
    - Валидация параметров
    """

    def __init__(self, config: BotConfig):
        """
        Инициализация Config Manager

        Args:
            config: Конфигурация бота
        """
        self.config = config
        self.scalping_config = config.scalping
        
        # Загружаем symbol_profiles при инициализации
        self.symbol_profiles: Dict[str, Dict[str, Any]] = self.load_symbol_profiles()
        
        logger.info("ConfigManager инициализирован")

    @staticmethod
    def get_config_value(source: Any, key: str, default: Any = None) -> Any:
        """Безопасно извлекает значение из объекта конфигурации или dict."""
        if source is None:
            return default
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default) if hasattr(source, key) else default

    def to_dict(self, raw: Any) -> Dict[str, Any]:
        """Преобразует объект в словарь, поддерживая Pydantic модели и обычные объекты"""
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return dict(raw)
        # ✅ Поддержка Pydantic v2 (model_dump)
        if hasattr(raw, "model_dump"):
            try:
                return raw.model_dump()  # type: ignore[attr-defined]
            except Exception:
                pass
        # ✅ Поддержка Pydantic v1 (dict)
        if hasattr(raw, "dict"):
            try:
                return dict(raw.dict(by_alias=True))  # type: ignore[attr-defined]
            except TypeError:
                try:
                    return dict(raw.dict())  # type: ignore[attr-defined]
                except Exception:
                    pass
        # ✅ Поддержка обычных объектов (__dict__)
        if hasattr(raw, "__dict__"):
            return dict(raw.__dict__)
        return {}

    def deep_merge_dict(
        self, base: Dict[str, Any], override: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Глубокое слияние словарей"""
        merged = dict(base)
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self.deep_merge_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    def normalize_symbol(self, symbol: str) -> str:
        """Нормализует символ для единообразного использования в кэшах и блокировках"""
        # Убираем все разделители и приводим к верхнему регистру
        # "BTC-USDT" → "BTCUSDT", "BTCUSDT" → "BTCUSDT", "BTC-USDT-SWAP" → "BTCUSDT"
        normalized = symbol.replace("-", "").replace("_", "").upper()
        # Если есть SWAP, убираем
        normalized = normalized.replace("SWAP", "")
        return normalized

    def normalize_symbol_profiles(
        self, raw_profiles: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """Нормализует symbol profiles из конфига"""
        profiles: Dict[str, Dict[str, Any]] = {}
        for symbol, profile in (raw_profiles or {}).items():
            normalized: Dict[str, Any] = {}
            profile_dict = self.to_dict(profile)

            # ✅ ВАРИАНТ B: Сохраняем position_multiplier на верхнем уровне символа
            if "position_multiplier" in profile_dict:
                normalized["position_multiplier"] = profile_dict["position_multiplier"]

            # ✅ НОВОЕ: Сохраняем tp_percent на верхнем уровне символа (если есть)
            if "tp_percent" in profile_dict:
                tp_value = profile_dict["tp_percent"]
                # Проверяем, что это число, а не dict
                if isinstance(tp_value, (int, float)):
                    normalized["tp_percent"] = float(tp_value)
                elif isinstance(tp_value, str):
                    try:
                        normalized["tp_percent"] = float(tp_value)
                    except (ValueError, TypeError):
                        logger.warning(
                            f"⚠️ Не удалось конвертировать tp_percent в float для {symbol}: {tp_value}"
                        )

            for regime_name, regime_data in profile_dict.items():
                regime_key = str(regime_name).lower()
                # Пропускаем position_multiplier и tp_percent, так как они уже сохранены выше
                if regime_key in {"position_multiplier", "tp_percent"}:
                    continue
                if regime_key in {"__detection__", "detection"}:
                    normalized["__detection__"] = self.to_dict(regime_data)
                    continue
                regime_dict = self.to_dict(regime_data)
                # ✅ НОВОЕ: Сохраняем tp_percent на уровне режима (если есть)
                if "tp_percent" in regime_dict:
                    tp_value = regime_dict["tp_percent"]
                    # Проверяем, что это число, а не dict
                    if isinstance(tp_value, (int, float)):
                        if regime_key not in normalized:
                            normalized[regime_key] = {}
                        normalized[regime_key]["tp_percent"] = float(tp_value)
                    elif isinstance(tp_value, str):
                        try:
                            if regime_key not in normalized:
                                normalized[regime_key] = {}
                            normalized[regime_key]["tp_percent"] = float(tp_value)
                        except (ValueError, TypeError):
                            logger.warning(
                                f"⚠️ Не удалось конвертировать tp_percent в float для {symbol} ({regime_key}): {tp_value}"
                            )

                for section, section_value in list(regime_dict.items()):
                    # Пропускаем tp_percent, так как он уже обработан выше
                    if section == "tp_percent":
                        continue
                    if isinstance(section_value, dict) or hasattr(
                        section_value, "__dict__"
                    ):
                        section_dict = self.to_dict(section_value)
                        for sub_key, sub_val in list(section_dict.items()):
                            if isinstance(sub_val, dict) or hasattr(
                                sub_val, "__dict__"
                            ):
                                section_dict[sub_key] = self.to_dict(sub_val)
                        regime_dict[section] = section_dict
                normalized[regime_key] = regime_dict
            profiles[symbol] = normalized
        return profiles

    def load_symbol_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Загружает symbol profiles из конфига"""
        scalping_config = getattr(self.config, "scalping", None)
        if not scalping_config:
            return {}
        adaptive_regime = None
        if hasattr(scalping_config, "adaptive_regime"):
            adaptive_regime = getattr(scalping_config, "adaptive_regime", None)
        elif isinstance(scalping_config, dict):
            adaptive_regime = scalping_config.get("adaptive_regime")
        adaptive_dict = self.to_dict(adaptive_regime)
        raw_profiles = adaptive_dict.get("symbol_profiles", {})
        return self.normalize_symbol_profiles(raw_profiles)

    def get_symbol_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Возвращает загруженные symbol profiles"""
        return self.symbol_profiles

    def get_symbol_regime_profile(
        self, symbol: Optional[str], regime: Optional[str]
    ) -> Dict[str, Any]:
        """Получает профиль символа для указанного режима"""
        if not symbol:
            return {}
        profile = self.symbol_profiles.get(symbol, {})
        if not profile:
            return {}
        if regime:
            return self.to_dict(profile.get(regime.lower(), {}))
        return {}

    def get_trailing_sl_params(self, regime: Optional[str] = None) -> Dict[str, Any]:
        """✅ ЭТАП 4: Возвращает параметры Trailing SL с учетом конфига, fallback значений и адаптацией под режим рынка."""
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем правильные fallback значения (как в конфиге)
        # Эти значения используются ТОЛЬКО если конфиг не загружен
        params: Dict[str, Any] = {
            "trading_fee_rate": 0.0010,  # ✅ ОБНОВЛЕНО: 0.10% на круг (0.05% вход + 0.05% выход для taker на OKX)
            "initial_trail": 0.005,  # ✅ ИСПРАВЛЕНО: 0.5% (было 0.05 = 5%)
            "max_trail": 0.01,  # ✅ ИСПРАВЛЕНО: 1% (было 0.2 = 20%)
            "min_trail": 0.003,  # ✅ ИСПРАВЛЕНО: 0.3% (было 0.02 = 2%)
            "loss_cut_percent": None,
            "timeout_loss_percent": None,
            "timeout_minutes": None,
            "min_holding_minutes": None,  # ✅ ЭТАП 4.4
            "min_profit_to_close": None,  # ✅ ЭТАП 4.1
            "extend_time_on_profit": False,  # ✅ ЭТАП 4.3
            "extend_time_multiplier": 1.0,  # ✅ ЭТАП 4.3
            "regime_multiplier": 1.0,  # ✅ НОВОЕ: Множитель режима (из конфига, fallback)
            "trend_strength_boost": 1.0,  # ✅ НОВОЕ: Буст при сильном тренде (из конфига, fallback)
            "check_interval_seconds": 1.5,  # ✅ АДАПТИВНО: Интервал проверки TSL (fallback)
            "min_critical_hold_seconds": 30.0,  # ✅ КРИТИЧЕСКОЕ: Минимальное время для критических убытков (fallback)
            "short_reversal_min_duration": 30,  # ✅ АДАПТИВНО: Short reversal protection (fallback)
            "short_reversal_max_percent": 0.5,  # ✅ АДАПТИВНО: Short reversal protection (fallback)
            "trail_growth_low_multiplier": 1.5,  # ✅ АДАПТИВНО: Trail growth (fallback)
            "trail_growth_medium_multiplier": 2.0,  # ✅ АДАПТИВНО: Trail growth (fallback)
            "trail_growth_high_multiplier": 3.0,  # ✅ АДАПТИВНО: Trail growth (fallback)
        }

        trailing_sl_config = None
        if hasattr(self.config, "futures_modules") and self.config.futures_modules:
            trailing_sl_config = self.get_config_value(
                self.config.futures_modules, "trailing_sl", None
            )

        if trailing_sl_config:
            params["trading_fee_rate"] = self.get_config_value(
                trailing_sl_config, "trading_fee_rate", params["trading_fee_rate"]
            )
            params["initial_trail"] = self.get_config_value(
                trailing_sl_config, "initial_trail", params["initial_trail"]
            )
            params["max_trail"] = self.get_config_value(
                trailing_sl_config, "max_trail", params["max_trail"]
            )
            params["min_trail"] = self.get_config_value(
                trailing_sl_config, "min_trail", params["min_trail"]
            )
            params["loss_cut_percent"] = self.get_config_value(
                trailing_sl_config, "loss_cut_percent", params["loss_cut_percent"]
            )
            params["timeout_loss_percent"] = self.get_config_value(
                trailing_sl_config,
                "timeout_loss_percent",
                params["timeout_loss_percent"],
            )
            params["timeout_minutes"] = self.get_config_value(
                trailing_sl_config, "timeout_minutes", params["timeout_minutes"]
            )
            # ✅ ЭТАП 4.4: Минимальное время удержания
            params["min_holding_minutes"] = self.get_config_value(
                trailing_sl_config, "min_holding_minutes", params["min_holding_minutes"]
            )
            # ✅ ЭТАП 4.1: Минимальный профит для закрытия
            params["min_profit_to_close"] = self.get_config_value(
                trailing_sl_config, "min_profit_to_close", params["min_profit_to_close"]
            )
            # ✅ ЭТАП 4.3: Продлевание времени для прибыльных позиций
            params["extend_time_on_profit"] = self.get_config_value(
                trailing_sl_config,
                "extend_time_on_profit",
                params["extend_time_on_profit"],
            )
            params["extend_time_multiplier"] = self.get_config_value(
                trailing_sl_config,
                "extend_time_multiplier",
                params["extend_time_multiplier"],
            )

            # ✅ АДАПТИВНО: Short reversal protection параметры из общего конфига
            short_reversal_config = self.get_config_value(
                trailing_sl_config, "short_reversal_protection", None
            )
            if short_reversal_config:
                short_reversal_dict = (
                    self.to_dict(short_reversal_config)
                    if not isinstance(short_reversal_config, dict)
                    else short_reversal_config
                )
                params["short_reversal_min_duration"] = self.get_config_value(
                    short_reversal_dict, "min_reversal_duration_seconds", 30
                )
                params["short_reversal_max_percent"] = self.get_config_value(
                    short_reversal_dict, "max_reversal_percent", 0.5
                )

            # ✅ АДАПТИВНО: Trail growth multipliers из общего конфига
            trail_growth_config = self.get_config_value(
                trailing_sl_config, "trail_growth", None
            )
            if trail_growth_config:
                trail_growth_dict = (
                    self.to_dict(trail_growth_config)
                    if not isinstance(trail_growth_config, dict)
                    else trail_growth_config
                )
                params["trail_growth_low_multiplier"] = self.get_config_value(
                    trail_growth_dict, "low_profit_multiplier", 1.5
                )
                params["trail_growth_medium_multiplier"] = self.get_config_value(
                    trail_growth_dict, "medium_profit_multiplier", 2.0
                )
                params["trail_growth_high_multiplier"] = self.get_config_value(
                    trail_growth_dict, "high_profit_multiplier", 3.0
                )

            # ✅ ЭТАП 4.5: Адаптация под режим рынка
            if regime:
                regime_lower = regime.lower() if isinstance(regime, str) else None
                by_regime = self.get_config_value(
                    trailing_sl_config, "by_regime", None
                )
                if by_regime and regime_lower:
                    # Преобразуем by_regime в словарь, если это объект
                    by_regime_dict = (
                        self.to_dict(by_regime)
                        if not isinstance(by_regime, dict)
                        else by_regime
                    )
                    if regime_lower in by_regime_dict:
                        regime_params = by_regime_dict[regime_lower]
                        # Преобразуем regime_params в словарь, если это объект
                        regime_params_dict = (
                            self.to_dict(regime_params)
                            if not isinstance(regime_params, dict)
                            else regime_params
                        )
                        # ✅ КРИТИЧЕСКИЕ: Переопределяем базовые параметры TSL для режима
                        if "initial_trail" in regime_params_dict:
                            params["initial_trail"] = regime_params_dict[
                                "initial_trail"
                            ]
                        if "max_trail" in regime_params_dict:
                            params["max_trail"] = regime_params_dict["max_trail"]
                        if "min_trail" in regime_params_dict:
                            params["min_trail"] = regime_params_dict["min_trail"]
                        if "loss_cut_percent" in regime_params_dict:
                            params["loss_cut_percent"] = regime_params_dict[
                                "loss_cut_percent"
                            ]
                        if "timeout_loss_percent" in regime_params_dict:
                            params["timeout_loss_percent"] = regime_params_dict[
                                "timeout_loss_percent"
                            ]
                        if "timeout_minutes" in regime_params_dict:
                            params["timeout_minutes"] = regime_params_dict[
                                "timeout_minutes"
                            ]
                        if "check_interval_seconds" in regime_params_dict:
                            params["check_interval_seconds"] = regime_params_dict[
                                "check_interval_seconds"
                            ]
                        if "min_critical_hold_seconds" in regime_params_dict:
                            params["min_critical_hold_seconds"] = regime_params_dict[
                                "min_critical_hold_seconds"
                            ]

                        # ✅ Дополнительные параметры
                        if "min_profit_to_close" in regime_params_dict:
                            params["min_profit_to_close"] = regime_params_dict[
                                "min_profit_to_close"
                            ]
                        if "min_holding_minutes" in regime_params_dict:
                            params["min_holding_minutes"] = regime_params_dict[
                                "min_holding_minutes"
                            ]
                        if "extend_time_multiplier" in regime_params_dict:
                            params["extend_time_multiplier"] = regime_params_dict[
                                "extend_time_multiplier"
                            ]
                        if "extend_time_on_profit" in regime_params_dict:
                            params["extend_time_on_profit"] = regime_params_dict[
                                "extend_time_on_profit"
                            ]
                        # ✅ НОВОЕ: Множители режимов для trailing stop (из конфига)
                        if "regime_multiplier" in regime_params_dict:
                            params["regime_multiplier"] = regime_params_dict[
                                "regime_multiplier"
                            ]
                        if "trend_strength_boost" in regime_params_dict:
                            params["trend_strength_boost"] = regime_params_dict[
                                "trend_strength_boost"
                            ]
                        # ✅ АДАПТИВНО: High profit threshold для режима
                        if "high_profit_threshold" in regime_params_dict:
                            params["high_profit_threshold"] = regime_params_dict[
                                "high_profit_threshold"
                            ]

                        # ✅ АДАПТИВНО: Short reversal protection параметры для режима
                        if "short_reversal_protection" in regime_params_dict:
                            reversal_protection = regime_params_dict[
                                "short_reversal_protection"
                            ]
                            if isinstance(reversal_protection, dict):
                                if (
                                    "min_reversal_duration_seconds"
                                    in reversal_protection
                                ):
                                    params[
                                        "short_reversal_min_duration"
                                    ] = reversal_protection[
                                        "min_reversal_duration_seconds"
                                    ]
                                if "max_reversal_percent" in reversal_protection:
                                    params[
                                        "short_reversal_max_percent"
                                    ] = reversal_protection["max_reversal_percent"]

                        # ✅ АДАПТИВНО: Trail growth multipliers для режима
                        if "trail_growth" in regime_params_dict:
                            trail_growth = regime_params_dict["trail_growth"]
                            if isinstance(trail_growth, dict):
                                if "low_profit_multiplier" in trail_growth:
                                    params[
                                        "trail_growth_low_multiplier"
                                    ] = trail_growth["low_profit_multiplier"]
                                if "medium_profit_multiplier" in trail_growth:
                                    params[
                                        "trail_growth_medium_multiplier"
                                    ] = trail_growth["medium_profit_multiplier"]
                                if "high_profit_multiplier" in trail_growth:
                                    params[
                                        "trail_growth_high_multiplier"
                                    ] = trail_growth["high_profit_multiplier"]

            # ✅ АДАПТИВНО: Параметры high_profit из конфига (общие для всех режимов)
            high_profit_config = self.get_config_value(
                trailing_sl_config, "high_profit", None
            )
            if high_profit_config:
                high_profit_dict = (
                    self.to_dict(high_profit_config)
                    if not isinstance(high_profit_config, dict)
                    else high_profit_config
                )
                # Используем threshold из режима если есть, иначе из общего конфига
                params["high_profit_threshold"] = params.get(
                    "high_profit_threshold"
                ) or self.get_config_value(high_profit_dict, "threshold", 0.01)
                params["high_profit_max_factor"] = self.get_config_value(
                    high_profit_dict, "max_profit_factor", 2.0
                )
                params["high_profit_reduction_percent"] = self.get_config_value(
                    high_profit_dict, "reduction_percent_per_1pct", 30
                )
                params["high_profit_min_reduction"] = self.get_config_value(
                    high_profit_dict, "min_reduction_factor", 0.5
                )
            else:
                # Fallback значения
                params["high_profit_threshold"] = params.get(
                    "high_profit_threshold", 0.01
                )
                params["high_profit_max_factor"] = 2.0
                params["high_profit_reduction_percent"] = 30
                params["high_profit_min_reduction"] = 0.5

        # Нормализуем числовые значения
        if params["trading_fee_rate"] is not None:
            try:
                params["trading_fee_rate"] = max(0.0, float(params["trading_fee_rate"]))
            except (TypeError, ValueError):
                logger.warning(
                    f"⚠️ Не удалось преобразовать trading_fee_rate в float: {params['trading_fee_rate']}"
                )
                params[
                    "trading_fee_rate"
                ] = 0.0010  # ✅ ОБНОВЛЕНО: 0.10% на круг (0.05% вход + 0.05% выход для taker на OKX)

        # Нормализуем числовые параметры трейлинга
        for key in (
            "initial_trail",
            "max_trail",
            "min_trail",
            "loss_cut_percent",
            "timeout_loss_percent",
            "timeout_minutes",
            "min_holding_minutes",
            "min_profit_to_close",
            "extend_time_multiplier",
            "regime_multiplier",  # ✅ НОВОЕ: Множитель режима
            "trend_strength_boost",  # ✅ НОВОЕ: Буст при сильном тренде
            "check_interval_seconds",  # ✅ АДАПТИВНО: Интервал проверки TSL
            "short_reversal_min_duration",  # ✅ АДАПТИВНО: Short reversal protection
            "short_reversal_max_percent",  # ✅ АДАПТИВНО: Short reversal protection
            "trail_growth_low_multiplier",  # ✅ АДАПТИВНО: Trail growth
            "trail_growth_medium_multiplier",  # ✅ АДАПТИВНО: Trail growth
            "trail_growth_high_multiplier",  # ✅ АДАПТИВНО: Trail growth
        ):
            if params[key] is not None:
                try:
                    params[key] = float(params[key])
                    if key in (
                        "min_holding_minutes",
                        "extend_time_multiplier",
                        "timeout_minutes",
                    ):
                        params[key] = max(0.0, params[key])
                    else:
                        params[key] = (
                            max(0.0, params[key]) if params[key] >= 0 else None
                        )
                except (TypeError, ValueError):
                    logger.warning(
                        f"⚠️ Не удалось преобразовать {key} в float: {params[key]}"
                    )
                    params[key] = (
                        None
                        if key
                        in (
                            "loss_cut_percent",
                            "timeout_loss_percent",
                            "timeout_minutes",
                            "min_holding_minutes",
                            "min_profit_to_close",
                        )
                        else 1.0
                    )

        # ✅ Нормализуем boolean значение extend_time_on_profit
        if isinstance(params["extend_time_on_profit"], str):
            params["extend_time_on_profit"] = params[
                "extend_time_on_profit"
            ].lower() in ("true", "1", "yes", "on")
        elif params["extend_time_on_profit"] is None:
            params["extend_time_on_profit"] = False
        else:
            params["extend_time_on_profit"] = bool(params["extend_time_on_profit"])

        return params

    def get_balance_profile(self, balance: float) -> Dict[str, Any]:
        """Определяет профиль баланса - ВСЕ параметры из конфига!"""
        balance_profiles = getattr(self.scalping_config, "balance_profiles", {})

        if not balance_profiles:
            logger.error(
                "❌ balance_profiles не найден в конфиге! Проверьте config_futures.yaml"
            )
            raise ValueError("balance_profiles должен быть указан в конфиге")

        # ✅ АДАПТИВНАЯ СИСТЕМА: Профили берутся из конфига, сортируем по threshold
        profile_list = []
        for profile_name, profile_config in balance_profiles.items():
            threshold = getattr(profile_config, "threshold", None)
            if threshold is None:
                logger.warning(
                    f"⚠️ Профиль {profile_name} не имеет threshold, пропускаем"
                )
                continue
            profile_list.append(
                {"name": profile_name, "threshold": threshold, "config": profile_config}
            )

        # Сортируем по threshold (от меньшего к большему)
        profile_list.sort(key=lambda x: x["threshold"])

        if not profile_list:
            logger.error("❌ Не найдено ни одного валидного профиля в конфиге!")
            raise ValueError("Должен быть хотя бы один профиль в balance_profiles")

        # Определяем профиль по балансу
        for profile in profile_list:
            if balance <= profile["threshold"]:
                profile_config = profile["config"]
                profile_name = profile["name"]

                # ✅ ВАРИАНТ B: Прогрессивная адаптация
                progressive = getattr(profile_config, "progressive", False)
                if progressive:
                    min_balance = getattr(profile_config, "min_balance", None)
                    size_at_min = getattr(profile_config, "size_at_min", None)
                    size_at_max = getattr(profile_config, "size_at_max", None)

                    if (
                        min_balance is not None
                        and size_at_min is not None
                        and size_at_max is not None
                    ):
                        threshold = profile_config.threshold

                        # Для профиля 'large' используется max_balance вместо threshold
                        if profile_name == "large":
                            max_balance = getattr(
                                profile_config, "max_balance", threshold
                            )
                            if balance <= min_balance:
                                base_pos_usd = size_at_min
                            elif balance >= max_balance:
                                base_pos_usd = size_at_max
                            else:
                                progress = (balance - min_balance) / (
                                    max_balance - min_balance
                                )
                                base_pos_usd = (
                                    size_at_min + (size_at_max - size_at_min) * progress
                                )
                        else:
                            # Для других профилей
                            if balance <= min_balance:
                                base_pos_usd = size_at_min
                            elif balance >= threshold:
                                base_pos_usd = size_at_max
                            else:
                                progress = (balance - min_balance) / (
                                    threshold - min_balance
                                )
                                base_pos_usd = (
                                    size_at_min + (size_at_max - size_at_min) * progress
                                )

                        logger.debug(
                            f"📊 Прогрессивная адаптация для {profile_name}: "
                            f"баланс ${balance:.2f} → размер ${base_pos_usd:.2f} "
                            f"(min_balance=${min_balance:.2f}, threshold=${threshold:.2f}, "
                            f"size_at_min=${size_at_min:.2f}, size_at_max=${size_at_max:.2f})"
                        )
                    else:
                        # Если параметры прогрессивной адаптации не указаны, используем base_position_usd
                        base_pos_usd = getattr(
                            profile_config, "base_position_usd", None
                        )
                        if base_pos_usd is None or base_pos_usd <= 0:
                            logger.error(
                                f"❌ Профиль {profile_name}: base_position_usd не указан или <= 0 в конфиге!"
                            )
                            raise ValueError(
                                f"base_position_usd должен быть указан в конфиге для профиля {profile_name}"
                            )
                else:
                    # Используем фиксированный base_position_usd
                    base_pos_usd = getattr(profile_config, "base_position_usd", None)
                    if base_pos_usd is None or base_pos_usd <= 0:
                        logger.error(
                            f"❌ Профиль {profile_name}: base_position_usd не указан или <= 0 в конфиге!"
                        )
                        raise ValueError(
                            f"base_position_usd должен быть указан в конфиге для профиля {profile_name}"
                        )

                # ✅ МОДЕРНИЗАЦИЯ: Убираем fallback значения, требуем из конфига
                min_pos_usd = getattr(profile_config, "min_position_usd", None)
                max_pos_usd = getattr(profile_config, "max_position_usd", None)

                if min_pos_usd is None or min_pos_usd <= 0:
                    logger.error(
                        f"❌ min_position_usd не указан в конфиге для профиля {profile_name}! "
                        f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> min_position_usd"
                    )
                    raise ValueError(
                        f"min_position_usd должен быть указан в конфиге для профиля {profile_name}"
                    )
                if max_pos_usd is None or max_pos_usd <= 0:
                    logger.error(
                        f"❌ max_position_usd не указан в конфиге для профиля {profile_name}! "
                        f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_position_usd"
                    )
                    raise ValueError(
                        f"max_position_usd должен быть указан в конфиге для профиля {profile_name}"
                    )

                max_open_positions = getattr(profile_config, "max_open_positions", None)
                if max_open_positions is None or max_open_positions <= 0:
                    logger.error(
                        f"❌ max_open_positions не указан в конфиге для профиля {profile_name}! "
                        f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_open_positions"
                    )
                    raise ValueError(
                        f"max_open_positions должен быть указан в конфиге для профиля {profile_name}"
                    )

                # ✅ МОДЕРНИЗАЦИЯ: Убираем fallback значения, требуем из конфига
                max_position_percent = getattr(
                    profile_config, "max_position_percent", None
                )
                if max_position_percent is None or max_position_percent <= 0:
                    logger.error(
                        f"❌ max_position_percent не указан в конфиге для профиля {profile_name}! "
                        f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_position_percent"
                    )
                    raise ValueError(
                        f"max_position_percent должен быть указан в конфиге для профиля {profile_name}"
                    )

                return {
                    "name": profile_name,
                    "base_position_usd": base_pos_usd,
                    "min_position_usd": min_pos_usd,
                    "max_position_usd": max_pos_usd,
                    "max_open_positions": max_open_positions,
                    "max_position_percent": max_position_percent,
                }

        # Если баланс больше всех порогов - используем последний (самый большой) профиль
        last_profile = profile_list[-1]
        profile_config = last_profile["config"]
        profile_name = last_profile["name"]
        logger.debug(
            f"📊 Баланс {balance:.2f} больше всех порогов, используем профиль {profile_name}"
        )

        # ✅ ВАРИАНТ B: Прогрессивная адаптация для последнего профиля
        progressive = getattr(profile_config, "progressive", False)
        if progressive:
            min_balance = getattr(profile_config, "min_balance", None)
            size_at_min = getattr(profile_config, "size_at_min", None)
            size_at_max = getattr(profile_config, "size_at_max", None)

            if (
                min_balance is not None
                and size_at_min is not None
                and size_at_max is not None
            ):
                # Для профиля 'large' используется max_balance
                if profile_name == "large":
                    max_balance = getattr(profile_config, "max_balance", 999999.0)
                    if balance <= min_balance:
                        base_pos_usd = size_at_min
                    elif balance >= max_balance:
                        base_pos_usd = size_at_max
                    else:
                        progress = (balance - min_balance) / (max_balance - min_balance)
                        base_pos_usd = (
                            size_at_min + (size_at_max - size_at_min) * progress
                        )
                else:
                    threshold = profile_config.threshold
                    if balance <= min_balance:
                        base_pos_usd = size_at_min
                    elif balance >= threshold:
                        base_pos_usd = size_at_max
                    else:
                        progress = (balance - min_balance) / (threshold - min_balance)
                        base_pos_usd = (
                            size_at_min + (size_at_max - size_at_min) * progress
                        )

                logger.debug(
                    f"📊 Прогрессивная адаптация для {profile_name}: "
                    f"баланс ${balance:.2f} → размер ${base_pos_usd:.2f}"
                )
            else:
                base_pos_usd = getattr(profile_config, "base_position_usd", None)
                if base_pos_usd is None or base_pos_usd <= 0:
                    logger.error(
                        f"❌ Профиль {profile_name}: base_position_usd не указан в конфиге!"
                    )
                    raise ValueError(
                        f"base_position_usd должен быть указан в конфиге для профиля {profile_name}"
                    )
        else:
            base_pos_usd = getattr(profile_config, "base_position_usd", None)
            if base_pos_usd is None or base_pos_usd <= 0:
                logger.error(
                    f"❌ Профиль {profile_name}: base_position_usd не указан в конфиге!"
                )
                raise ValueError(
                    f"base_position_usd должен быть указан в конфиге для профиля {profile_name}"
                )

        # ✅ МОДЕРНИЗАЦИЯ: Убираем fallback значения, требуем из конфига
        min_pos_usd = getattr(profile_config, "min_position_usd", None)
        max_pos_usd = getattr(profile_config, "max_position_usd", None)
        if min_pos_usd is None or min_pos_usd <= 0:
            logger.error(
                f"❌ min_position_usd не указан в конфиге для профиля {profile_name}! "
                f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> min_position_usd"
            )
            raise ValueError(
                f"min_position_usd должен быть указан в конфиге для профиля {profile_name}"
            )
        if max_pos_usd is None or max_pos_usd <= 0:
            logger.error(
                f"❌ max_position_usd не указан в конфиге для профиля {profile_name}! "
                f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_position_usd"
            )
            raise ValueError(
                f"max_position_usd должен быть указан в конфиге для профиля {profile_name}"
            )

        max_open_positions = getattr(profile_config, "max_open_positions", None)
        if max_open_positions is None or max_open_positions <= 0:
            logger.error(
                f"❌ max_open_positions не указан в конфиге для профиля {profile_name}! "
                f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_open_positions"
            )
            raise ValueError(
                f"max_open_positions должен быть указан в конфиге для профиля {profile_name}"
            )

        max_position_percent = getattr(profile_config, "max_position_percent", None)
        if max_position_percent is None or max_position_percent <= 0:
            logger.error(
                f"❌ max_position_percent не указан в конфиге для профиля {profile_name}! "
                f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {profile_name} -> max_position_percent"
            )
            raise ValueError(
                f"max_position_percent должен быть указан в конфиге для профиля {profile_name}"
            )

        return {
            "name": profile_name,
            "base_position_usd": base_pos_usd,
            "min_position_usd": min_pos_usd,
            "max_position_usd": max_pos_usd,
            "max_open_positions": max_open_positions,
            "max_position_percent": max_position_percent,
        }

    def get_regime_params(
        self, regime_name: str, symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        """Получает параметры текущего режима из ARM"""
        try:
            scalping_config = getattr(self.config, "scalping", None)
            if not scalping_config:
                logger.warning("scalping_config не найден")
                return {}

            adaptive_regime = None
            if hasattr(scalping_config, "adaptive_regime"):
                adaptive_regime = getattr(scalping_config, "adaptive_regime", None)
            elif isinstance(scalping_config, dict):
                adaptive_regime = scalping_config.get("adaptive_regime", {})

            if not adaptive_regime:
                logger.debug("adaptive_regime не найден в scalping_config")
                return {}

            adaptive_dict = self.to_dict(adaptive_regime)
            regime_params = self.to_dict(adaptive_dict.get(regime_name, {}))

            if symbol:
                symbol_profile = self.symbol_profiles.get(symbol, {})
                regime_profile = symbol_profile.get(regime_name.lower(), {})
                arm_override = self.to_dict(regime_profile.get("arm", {}))
                if arm_override:
                    regime_params = self.deep_merge_dict(regime_params, arm_override)

            return regime_params

        except Exception as e:
            logger.warning(f"Ошибка получения параметров режима {regime_name}: {e}")
            return {}

    def get_fallback_risk_params(self) -> Dict[str, Any]:
        """Возвращает fallback параметры риска (если конфиг недоступен)"""
        return {
            "max_loss_per_trade_percent": 2.0,
            "max_margin_percent": 80.0,
            "max_drawdown_percent": 5.0,
            "max_margin_safety_percent": 90.0,
            "min_balance_usd": 20.0,
            "min_time_between_orders_seconds": 30,
            "position_override_tolerance_percent": 50.0,
            "strength_multipliers": {
                "conflict": 0.5,
                "very_strong": 1.5,
                "strong": 1.2,
                "medium": 1.0,
                "weak": 0.8,
            },
            "strength_thresholds": {
                "very_strong": 0.8,
                "strong": 0.6,
                "medium": 0.4,
            },
        }

    def validate_risk_params(
        self, params: Dict[str, Any], regime: str, profile_name: str
    ) -> Dict[str, Any]:
        """
        Валидация параметров риска из конфига.

        Args:
            params: Параметры для валидации
            regime: Режим рынка
            profile_name: Имя баланс профиля

        Returns:
            Валидированные параметры
        """
        validated = params.copy()

        # Валидация обязательных параметров
        required_params = [
            "max_loss_per_trade_percent",
            "max_margin_percent",
            "max_drawdown_percent",
            "max_margin_safety_percent",
            "min_balance_usd",
            "min_time_between_orders_seconds",
        ]

        fallback_params = self.get_fallback_risk_params()

        for param in required_params:
            if param not in validated or validated[param] is None:
                logger.warning(
                    f"⚠️ Параметр {param} не найден в конфиге для режима={regime}, профиль={profile_name}, "
                    f"используем fallback значение: {fallback_params[param]}"
                )
                validated[param] = fallback_params[param]
            elif (
                not isinstance(validated[param], (int, float)) or validated[param] <= 0
            ):
                logger.error(
                    f"❌ Параметр {param} имеет недопустимое значение: {validated[param]}, "
                    f"используем fallback значение: {fallback_params[param]}"
                )
                validated[param] = fallback_params[param]

        # Валидация strength_multipliers
        if "strength_multipliers" not in validated or not isinstance(
            validated["strength_multipliers"], dict
        ):
            logger.warning(
                f"⚠️ strength_multipliers не найден в конфиге, используем fallback значения"
            )
            validated["strength_multipliers"] = fallback_params["strength_multipliers"]
        else:
            # Валидация каждого множителя
            sm = validated["strength_multipliers"]
            fallback_sm = fallback_params["strength_multipliers"]
            for key in ["conflict", "very_strong", "strong", "medium", "weak"]:
                if (
                    key not in sm
                    or not isinstance(sm[key], (int, float))
                    or sm[key] <= 0
                ):
                    logger.warning(
                        f"⚠️ strength_multipliers[{key}] не найден или невалиден, "
                        f"используем fallback: {fallback_sm[key]}"
                    )
                    sm[key] = fallback_sm[key]

        # Валидация strength_thresholds
        if "strength_thresholds" not in validated or not isinstance(
            validated["strength_thresholds"], dict
        ):
            logger.warning(
                f"⚠️ strength_thresholds не найден в конфиге, используем fallback значения"
            )
            validated["strength_thresholds"] = fallback_params["strength_thresholds"]
        else:
            # Валидация каждого порога
            st = validated["strength_thresholds"]
            fallback_st = fallback_params["strength_thresholds"]
            for key in ["very_strong", "strong", "medium"]:
                if (
                    key not in st
                    or not isinstance(st[key], (int, float))
                    or st[key] <= 0
                ):
                    logger.warning(
                        f"⚠️ strength_thresholds[{key}] не найден или невалиден, "
                        f"используем fallback: {fallback_st[key]}"
                    )
                    st[key] = fallback_st[key]

        return validated

    def get_adaptive_risk_params(
        self,
        balance: float,
        regime: Optional[str] = None,
        symbol: Optional[str] = None,
        signal_generator=None,
    ) -> Dict[str, Any]:
        """
        ✅ НОВОЕ: Получает адаптивные параметры риска с учетом режима рынка и баланса.

        Приоритет параметров:
        1. Режим рынка (ARM) - ПРИОРИТЕТ 1
        2. Баланс профиль (Balance Profiles) - ПРИОРИТЕТ 2
        3. Базовые параметры (fallback) - ПРИОРИТЕТ 3

        Args:
            balance: Текущий баланс
            regime: Режим рынка (trending, ranging, choppy). Если None, определяется автоматически.
            symbol: Символ для торговли (опционально)
            signal_generator: Опциональный signal_generator для определения режима

        Returns:
            Словарь с адаптивными параметрами риска
        """
        try:
            # 1. Получаем базовые параметры из конфига
            risk_config = getattr(self.config, "risk", None)
            if not risk_config:
                logger.warning(
                    "⚠️ risk конфигурация не найдена, используем fallback значения"
                )
                return self.get_fallback_risk_params()

            # Конвертируем в словарь если нужно
            risk_dict = self.to_dict(risk_config)

            # ✅ ОТЛАДКА: Проверяем наличие полей в risk_dict
            if (
                not risk_dict.get("base")
                and not risk_dict.get("by_regime")
                and not risk_dict.get("by_balance")
            ):
                logger.warning(
                    f"⚠️ Поля base, by_regime, by_balance не найдены в risk_config. "
                    f"Доступные поля: {list(risk_dict.keys())}. "
                    f"Используем fallback значения."
                )
                # Пытаемся получить напрямую из объекта
                if hasattr(risk_config, "base"):
                    risk_dict["base"] = self.to_dict(risk_config.base)
                if hasattr(risk_config, "by_regime"):
                    risk_dict["by_regime"] = self.to_dict(risk_config.by_regime)
                if hasattr(risk_config, "by_balance"):
                    risk_dict["by_balance"] = self.to_dict(risk_config.by_balance)

            # Базовые параметры (fallback)
            base_params = self.to_dict(risk_dict.get("base", {}))

            # 2. Определяем баланс профиль
            balance_profile = self.get_balance_profile(balance)
            profile_name = balance_profile.get("name", "small")

            # Параметры по балансу
            by_balance = self.to_dict(risk_dict.get("by_balance", {}))
            balance_params = self.to_dict(by_balance.get(profile_name, {}))

            # 3. Определяем режим рынка (если не указан)
            if not regime:
                if signal_generator and hasattr(signal_generator, "regime_manager") and signal_generator.regime_manager:
                    regime = signal_generator.regime_manager.get_current_regime()
                else:
                    regime = "ranging"  # Fallback режим

            # Нормализуем режим (может быть uppercase или lowercase)
            regime = regime.lower() if regime else "ranging"

            # Параметры по режиму (ПРИОРИТЕТ 1)
            by_regime = self.to_dict(risk_dict.get("by_regime", {}))
            regime_params = self.to_dict(by_regime.get(regime, {}))

            # 4. Объединяем параметры с приоритетом: режим > баланс > базовые
            # Начинаем с базовых параметров
            adaptive_params = base_params.copy()

            # Применяем параметры баланса (перезаписывают базовые)
            adaptive_params.update(balance_params)

            # Применяем параметры режима (перезаписывают баланс и базовые) - ПРИОРИТЕТ 1
            adaptive_params.update(regime_params)

            # 5. Обрабатываем вложенные словари (strength_multipliers, strength_thresholds)
            if "strength_multipliers" in adaptive_params:
                adaptive_params["strength_multipliers"] = self.to_dict(
                    adaptive_params["strength_multipliers"]
                )
            else:
                # Fallback strength_multipliers
                adaptive_params["strength_multipliers"] = {
                    "conflict": 0.5,
                    "very_strong": 1.5,
                    "strong": 1.2,
                    "medium": 1.0,
                    "weak": 0.8,
                }

            if "strength_thresholds" in adaptive_params:
                adaptive_params["strength_thresholds"] = self.to_dict(
                    adaptive_params["strength_thresholds"]
                )
            else:
                # Fallback strength_thresholds
                adaptive_params["strength_thresholds"] = {
                    "very_strong": 0.8,
                    "strong": 0.6,
                    "medium": 0.4,
                }

            # 6. Валидация параметров
            adaptive_params = self.validate_risk_params(
                adaptive_params, regime, profile_name
            )

            logger.debug(
                f"📊 Адаптивные параметры риска: режим={regime}, профиль={profile_name}, "
                f"max_loss={adaptive_params.get('max_loss_per_trade_percent', 2.0)}%, "
                f"max_margin={adaptive_params.get('max_margin_percent', 80.0)}%"
            )

            return adaptive_params

        except Exception as e:
            logger.error(
                f"❌ Ошибка получения адаптивных параметров риска: {e}", exc_info=True
            )
            return self.get_fallback_risk_params()

    def get_adaptive_delay(
        self,
        delay_key: str,
        default_ms: float,
        delays_config: Optional[Any] = None,
        signal_generator=None,
    ) -> float:
        """
        ✅ АДАПТИВНО: Получает адаптивную задержку из конфига по режиму рынка

        Args:
            delay_key: Ключ задержки (api_request_delay_ms, symbol_switch_delay_ms, position_sync_delay_ms)
            default_ms: Значение по умолчанию в миллисекундах
            delays_config: Опциональный delays_config
            signal_generator: Опциональный signal_generator для определения режима

        Returns:
            Задержка в миллисекундах
        """
        try:
            if not delays_config:
                return default_ms

            # Получаем базовое значение
            if isinstance(delays_config, dict):
                base_delay = delays_config.get(delay_key, default_ms)
                by_regime = delays_config.get("by_regime", {})
            else:
                base_delay = getattr(delays_config, delay_key, default_ms)
                by_regime = getattr(delays_config, "by_regime", {})

            # Получаем режим рынка
            regime = None
            if signal_generator and hasattr(signal_generator, "regime_manager") and signal_generator.regime_manager:
                regime_obj = signal_generator.regime_manager.get_current_regime()
                if regime_obj:
                    regime = (
                        regime_obj.lower()
                        if isinstance(regime_obj, str)
                        else str(regime_obj).lower()
                    )

            # Получаем адаптивное значение по режиму
            if regime and by_regime:
                if isinstance(by_regime, dict):
                    regime_config = by_regime.get(regime, {})
                    if isinstance(regime_config, dict):
                        regime_delay = regime_config.get(delay_key, base_delay)
                    else:
                        regime_delay = getattr(regime_config, delay_key, base_delay)
                else:
                    regime_config = getattr(by_regime, regime, None)
                    if regime_config:
                        regime_delay = getattr(regime_config, delay_key, base_delay)
                    else:
                        regime_delay = base_delay

                logger.debug(
                    f"✅ АДАПТИВНО: Задержка {delay_key} для режима {regime}: {regime_delay}ms (базовая: {base_delay}ms)"
                )
                return regime_delay

            return base_delay

        except Exception as e:
            logger.debug(
                f"⚠️ Ошибка получения адаптивной задержки {delay_key}: {e}, используем fallback {default_ms}ms"
            )
            return default_ms

