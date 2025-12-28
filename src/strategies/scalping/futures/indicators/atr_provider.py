"""
ATR Provider - Синхронный доступ к ATR значениям.

Решает проблему async/sync конфликта при получении ATR в синхронных методах.
Кэширует ATR значения из DataRegistry для быстрого доступа.
"""

from typing import Dict, Optional

from loguru import logger


class ATRProvider:
    """
    Провайдер ATR значений для синхронного доступа.

    Кэширует ATR из DataRegistry и предоставляет синхронный интерфейс.
    Используется в ExitAnalyzer для расчета ATR-based TP/SL.
    """

    def __init__(self, data_registry=None):
        """
        Инициализация ATR Provider.

        Args:
            data_registry: DataRegistry для получения ATR (опционально)
        """
        self.data_registry = data_registry
        # Кэш ATR значений: symbol -> atr_value
        self._atr_cache: Dict[str, float] = {}
        # Время последнего обновления: symbol -> timestamp
        self._cache_timestamps: Dict[str, float] = {}
        # TTL кэша: 60 секунд (✅ УВЕЛИЧЕНО 28.12.2025 для уменьшения запросов)
        self._cache_ttl_seconds = 60.0

    def get_atr(self, symbol: str, fallback: Optional[float] = None) -> Optional[float]:
        """
        Получить ATR значение для символа (синхронно).

        Приоритет:
        1. Кэш (если свежий)
        2. DataRegistry._indicators (если доступен)
        3. Fallback значение

        Args:
            symbol: Торговый символ
            fallback: Значение по умолчанию если ATR не найден

        Returns:
            ATR значение или None
        """
        import time

        # 1. Проверяем кэш
        if symbol in self._atr_cache:
            cache_time = self._cache_timestamps.get(symbol, 0)
            current_time = time.time()

            if current_time - cache_time < self._cache_ttl_seconds:
                # Кэш свежий
                return self._atr_cache[symbol]

        # 2. Пробуем получить из DataRegistry (если доступен)
        if self.data_registry:
            try:
                # DataRegistry._indicators - это словарь, доступ синхронный
                if hasattr(self.data_registry, "_indicators"):
                    indicators = self.data_registry._indicators.get(symbol, {})
                    if indicators:
                        # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: Проверяем доступные ключи
                        available_keys = list(indicators.keys())
                        logger.debug(
                            f"🔍 ATRProvider: Проверка ATR для {symbol}, доступные ключи: {available_keys}"
                        )
                        
                        # Пробуем разные ключи для ATR
                        atr_value = (
                            indicators.get("atr")
                            or indicators.get("ATR")
                            or indicators.get("atr_1m")
                            or indicators.get("atr_14")
                        )

                        if atr_value is not None:
                            try:
                                atr_float = float(atr_value)
                                if atr_float > 0:
                                    # Обновляем кэш
                                    self._atr_cache[symbol] = atr_float
                                    self._cache_timestamps[symbol] = time.time()
                                    logger.debug(
                                        f"✅ ATRProvider: ATR получен из DataRegistry для {symbol}: {atr_float:.6f}"
                                    )
                                    return atr_float
                                else:
                                    logger.debug(
                                        f"⚠️ ATRProvider: ATR найден для {symbol}, но равен 0 или отрицательный: {atr_float}"
                                    )
                            except (ValueError, TypeError) as e:
                                logger.debug(
                                    f"⚠️ ATRProvider: Ошибка конвертации ATR для {symbol}: {e}, value={atr_value}"
                                )
                        else:
                            logger.debug(
                                f"⚠️ ATRProvider: ATR не найден в доступных ключах для {symbol}, "
                                f"проверенные ключи: ['atr', 'ATR', 'atr_1m', 'atr_14']"
                            )
                    else:
                        logger.debug(
                            f"⚠️ ATRProvider: Нет индикаторов для {symbol} в DataRegistry"
                        )
            except Exception as e:
                logger.debug(
                    f"⚠️ ATRProvider: Ошибка получения ATR из DataRegistry для {symbol}: {e}"
                )

        # 3. Fallback
        if fallback is not None:
            logger.debug(
                f"⚠️ ATRProvider: ATR не найден для {symbol}, используем fallback: {fallback:.6f}"
            )
            return fallback

        logger.debug(f"⚠️ ATRProvider: ATR не найден для {symbol}, возвращаем None")
        return None

    def update_atr(self, symbol: str, atr_value: float) -> None:
        """
        Обновить ATR значение в кэше.

        Args:
            symbol: Торговый символ
            atr_value: Значение ATR
        """
        import time

        self._atr_cache[symbol] = float(atr_value)
        self._cache_timestamps[symbol] = time.time()

        logger.debug(f"✅ ATRProvider: ATR обновлен для {symbol}: {atr_value:.6f}")

    def clear_cache(self, symbol: Optional[str] = None) -> None:
        """
        Очистить кэш ATR.

        Args:
            symbol: Символ для очистки (если None - очистить все)
        """
        if symbol:
            self._atr_cache.pop(symbol, None)
            self._cache_timestamps.pop(symbol, None)
            logger.debug(f"✅ ATRProvider: Кэш очищен для {symbol}")
        else:
            self._atr_cache.clear()
            self._cache_timestamps.clear()
            logger.debug("✅ ATRProvider: Весь кэш очищен")
