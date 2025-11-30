# 🧠 Архитектура "умного фильтра" для закрытия позиций (29.11.2025)

## 📊 Текущая архитектура

### Существующие модули:
1. **PositionMonitor** (`positions/position_monitor.py`)
   - Периодически проверяет все позиции
   - Вызывает `ExitAnalyzer` для анализа
   - НО: не используется активно в orchestrator

2. **ExitAnalyzer** (`positions/exit_analyzer.py`)
   - Анализирует позиции и принимает решения
   - Использует ADX, Order Flow, MTF
   - НО: не использует RSI, MACD, Bollinger для закрытия

3. **TrailingSLCoordinator** (`coordinators/trailing_sl_coordinator.py`)
   - Управляет Trailing Stop Loss
   - Уже интегрирован в orchestrator
   - НО: не использует индикаторы для "умных" решений

---

## 🎯 Предлагаемое решение: SmartExitCoordinator

### Концепция:
**Отдельный координатор**, который:
- ✅ Держит в себе все открытые позиции (через PositionRegistry)
- ✅ Постоянно мониторит их (используя PositionMonitor)
- ✅ Анализирует через индикаторы (RSI, MACD, Bollinger, ADX)
- ✅ Принимает "умные" решения о закрытии
- ✅ Интегрирован в систему (как TrailingSLCoordinator)

### Архитектура:

```
┌─────────────────────────────────────────────────────────┐
│              FuturesScalpingOrchestrator                   │
│                                                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │      SmartExitCoordinator (НОВЫЙ МОДУЛЬ)         │   │
│  │                                                    │   │
│  │  ┌────────────────────────────────────────────┐  │   │
│  │  │  PositionMonitor                            │  │   │
│  │  │  - Периодически проверяет все позиции      │  │   │
│  │  │  - Интервал: 5 секунд (настраивается)      │  │   │
│  │  └────────────────────────────────────────────┘  │   │
│  │                                                    │   │
│  │  ┌────────────────────────────────────────────┐  │   │
│  │  │  SmartExitAnalyzer (РАСШИРЕННЫЙ)            │  │   │
│  │  │  - Использует ExitAnalyzer (базовая логика) │  │   │
│  │  │  - Добавляет "умный" фильтр индикаторов:    │  │   │
│  │  │    * RSI - перекупленность/перепроданность  │  │   │
│  │  │    * MACD - разворот сигнала                │  │   │
│  │  │    * Bollinger - пробой уровней            │  │   │
│  │  │    * ADX - сила тренда                      │  │   │
│  │  └────────────────────────────────────────────┘  │   │
│  │                                                    │   │
│  │  ┌────────────────────────────────────────────┐  │   │
│  │  │  PositionRegistry (источник данных)       │  │   │
│  │  │  - Все открытые позиции                    │  │   │
│  │  │  - Метаданные (entry_price, regime, etc)  │  │   │
│  │  └────────────────────────────────────────────┘  │   │
│  │                                                    │   │
│  │  ┌────────────────────────────────────────────┐  │   │
│  │  │  DataRegistry (источник индикаторов)      │  │   │
│  │  │  - RSI, MACD, Bollinger, ADX              │  │   │
│  │  │  - Рыночные данные (OHLCV)                 │  │   │
│  │  └────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────┘   │
│                                                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │  PositionManager (существующий)                   │   │
│  │  - PH, Profit Drawdown, TP/SL, MAX_HOLDING       │   │
│  └──────────────────────────────────────────────────┘   │
│                                                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │  TrailingSLCoordinator (существующий)            │   │
│  │  - Trailing Stop Loss                            │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 🔄 Последовательность работы

### 1. Инициализация (в orchestrator):
```python
# В __init__ orchestrator:
self.smart_exit_coordinator = SmartExitCoordinator(
    position_registry=self.position_registry,
    data_registry=self.data_registry,
    signal_generator=self.signal_generator,
    config_manager=self.config_manager,
    close_position_callback=self._close_position,  # Метод закрытия
    scalping_config=self.scalping_config,
)
```

### 2. Запуск (в start):
```python
# В start orchestrator:
await self.smart_exit_coordinator.start()
```

### 3. Работа (в фоне):
```python
# SmartExitCoordinator работает в фоне:
# - PositionMonitor проверяет позиции каждые 5 секунд
# - SmartExitAnalyzer анализирует каждую позицию
# - Если нужно закрыть - вызывает close_position_callback
```

---

## 💡 Преимущества такого подхода

### ✅ Отдельный модуль:
- Не усложняет существующий код
- Легко тестировать
- Легко отключать/включать

### ✅ Интегрирован в систему:
- Использует PositionRegistry (единый источник данных)
- Использует DataRegistry (единый источник индикаторов)
- Использует существующие механизмы закрытия

### ✅ "Умный" анализ:
- Использует все индикаторы (RSI, MACD, Bollinger, ADX)
- Принимает решения на основе анализа
- Не блокирует существующие механизмы (PH, Profit Drawdown)

### ✅ Не замедляет:
- Работает в фоне (async)
- Не блокирует основной цикл
- Можно настроить интервал проверки

---

## 📝 Реализация

### Файл: `src/strategies/scalping/futures/coordinators/smart_exit_coordinator.py`

```python
"""
SmartExitCoordinator - "Умный" координатор закрытия позиций.

Использует индикаторы (RSI, MACD, Bollinger, ADX) для принятия решений о закрытии.
Работает в фоне, постоянно мониторит открытые позиции.
"""

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from ..core.data_registry import DataRegistry
from ..core.position_registry import PositionRegistry
from ..positions.exit_analyzer import ExitAnalyzer
from ..positions.position_monitor import PositionMonitor


class SmartExitCoordinator:
    """
    "Умный" координатор закрытия позиций.
    
    Постоянно мониторит открытые позиции и принимает решения
    на основе анализа индикаторов.
    """
    
    def __init__(
        self,
        position_registry: PositionRegistry,
        data_registry: DataRegistry,
        signal_generator,
        config_manager,
        close_position_callback: Callable[[str, str], Awaitable[None]],
        scalping_config,
        orchestrator=None,
        check_interval: float = 5.0,  # Интервал проверки в секундах
    ):
        """
        Инициализация SmartExitCoordinator.
        
        Args:
            position_registry: Реестр позиций
            data_registry: Реестр данных (индикаторы)
            signal_generator: SignalGenerator для получения индикаторов
            config_manager: ConfigManager для параметров
            close_position_callback: Функция для закрытия позиции
            scalping_config: Конфигурация скальпинга
            orchestrator: Orchestrator (опционально)
            check_interval: Интервал проверки позиций в секундах
        """
        self.position_registry = position_registry
        self.data_registry = data_registry
        self.signal_generator = signal_generator
        self.config_manager = config_manager
        self.close_position_callback = close_position_callback
        self.scalping_config = scalping_config
        self.orchestrator = orchestrator
        self.check_interval = check_interval
        
        # Создаем ExitAnalyzer
        self.exit_analyzer = ExitAnalyzer(
            position_registry=position_registry,
            data_registry=data_registry,
            orchestrator=orchestrator,
            config_manager=config_manager,
            signal_generator=signal_generator,
        )
        
        # Создаем PositionMonitor
        self.position_monitor = PositionMonitor(
            position_registry=position_registry,
            data_registry=data_registry,
            exit_analyzer=self.exit_analyzer,
            check_interval=check_interval,
        )
        
        # Устанавливаем ExitAnalyzer в PositionMonitor
        self.position_monitor.set_exit_analyzer(self.exit_analyzer)
        
        self.is_running = False
        
        logger.info(
            f"✅ SmartExitCoordinator инициализирован "
            f"(check_interval={check_interval} сек)"
        )
    
    async def start(self) -> None:
        """Запуск мониторинга позиций."""
        if self.is_running:
            logger.warning("⚠️ SmartExitCoordinator: Уже запущен")
            return
        
        self.is_running = True
        
        # Запускаем PositionMonitor
        await self.position_monitor.start()
        
        logger.info("🚀 SmartExitCoordinator: Запущен")
    
    async def stop(self) -> None:
        """Остановка мониторинга позиций."""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # Останавливаем PositionMonitor
        await self.position_monitor.stop()
        
        logger.info("🛑 SmartExitCoordinator: Остановлен")
    
    async def check_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Проверить конкретную позицию с "умным" анализом.
        
        Args:
            symbol: Торговый символ
            
        Returns:
            Решение о закрытии или None
        """
        try:
            # 1. Получаем базовое решение от ExitAnalyzer
            decision = await self.exit_analyzer.analyze_position(symbol)
            
            if not decision:
                return None
            
            # 2. Применяем "умный" фильтр индикаторов
            smart_decision = await self._apply_smart_filter(symbol, decision)
            
            # 3. Если решение - закрыть, выполняем закрытие
            if smart_decision and smart_decision.get("action") == "close":
                reason = smart_decision.get("reason", "smart_exit")
                await self.close_position_callback(symbol, reason)
                logger.info(
                    f"✅ SmartExitCoordinator: Закрыта позиция {symbol} "
                    f"(reason={reason})"
                )
            
            return smart_decision
            
        except Exception as e:
            logger.error(
                f"❌ SmartExitCoordinator: Ошибка проверки {symbol}: {e}",
                exc_info=True,
            )
            return None
    
    async def _apply_smart_filter(
        self, symbol: str, decision: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Применить "умный" фильтр индикаторов к решению.
        
        Args:
            symbol: Торговый символ
            decision: Решение от ExitAnalyzer
            
        Returns:
            Отфильтрованное решение или None
        """
        try:
            # Получаем рыночные данные и индикаторы
            market_data = await self.data_registry.get_market_data(symbol)
            if not market_data:
                return decision  # Нет данных - возвращаем исходное решение
            
            indicators = market_data.indicators if hasattr(market_data, "indicators") else {}
            
            # Получаем позицию для определения направления
            position = await self.position_registry.get_position(symbol)
            if not position:
                return decision
            
            position_side = None
            if isinstance(position, dict):
                position_side = position.get("posSide", "long").lower()
            else:
                metadata = await self.position_registry.get_metadata(symbol)
                if metadata:
                    position_side = getattr(metadata, "position_side", "long")
            
            if not position_side:
                return decision
            
            # Проверяем индикаторы
            # 1. RSI - перекупленность/перепроданность
            rsi = indicators.get("RSI")
            if rsi:
                if position_side == "long" and rsi > 70:
                    # LONG позиция, RSI перекуплен - можно закрывать
                    logger.debug(
                        f"📊 SmartExit: {symbol} LONG, RSI={rsi:.1f} перекуплен, "
                        f"разрешаем закрытие"
                    )
                    return decision
                elif position_side == "short" and rsi < 30:
                    # SHORT позиция, RSI перепродан - можно закрывать
                    logger.debug(
                        f"📊 SmartExit: {symbol} SHORT, RSI={rsi:.1f} перепродан, "
                        f"разрешаем закрытие"
                    )
                    return decision
                elif position_side == "long" and rsi < 50:
                    # LONG позиция, RSI не перекуплен - тренд может продолжиться
                    logger.debug(
                        f"📊 SmartExit: {symbol} LONG, RSI={rsi:.1f} не перекуплен, "
                        f"блокируем закрытие (тренд может продолжиться)"
                    )
                    return None  # Блокируем закрытие
                elif position_side == "short" and rsi > 50:
                    # SHORT позиция, RSI не перепродан - тренд может продолжиться
                    logger.debug(
                        f"📊 SmartExit: {symbol} SHORT, RSI={rsi:.1f} не перепродан, "
                        f"блокируем закрытие (тренд может продолжиться)"
                    )
                    return None  # Блокируем закрытие
            
            # 2. MACD - разворот сигнала
            macd = indicators.get("MACD")
            if macd:
                macd_line = macd.get("macd", 0)
                signal_line = macd.get("signal", 0)
                
                if position_side == "long":
                    if macd_line < signal_line:
                        # LONG позиция, MACD медвежий - можно закрывать
                        logger.debug(
                            f"📊 SmartExit: {symbol} LONG, MACD медвежий "
                            f"(macd={macd_line:.4f} < signal={signal_line:.4f}), "
                            f"разрешаем закрытие"
                        )
                        return decision
                    else:
                        # LONG позиция, MACD бычий - тренд может продолжиться
                        logger.debug(
                            f"📊 SmartExit: {symbol} LONG, MACD бычий "
                            f"(macd={macd_line:.4f} > signal={signal_line:.4f}), "
                            f"блокируем закрытие"
                        )
                        return None
                else:  # short
                    if macd_line > signal_line:
                        # SHORT позиция, MACD бычий - можно закрывать
                        logger.debug(
                            f"📊 SmartExit: {symbol} SHORT, MACD бычий "
                            f"(macd={macd_line:.4f} > signal={signal_line:.4f}), "
                            f"разрешаем закрытие"
                        )
                        return decision
                    else:
                        # SHORT позиция, MACD медвежий - тренд может продолжиться
                        logger.debug(
                            f"📊 SmartExit: {symbol} SHORT, MACD медвежий "
                            f"(macd={macd_line:.4f} < signal={signal_line:.4f}), "
                            f"блокируем закрытие"
                        )
                        return None
            
            # 3. Если индикаторы не блокируют - возвращаем исходное решение
            return decision
            
        except Exception as e:
            logger.debug(
                f"⚠️ SmartExitCoordinator: Ошибка применения фильтра для {symbol}: {e}"
            )
            return decision  # В случае ошибки возвращаем исходное решение
```

---

## 🔧 Интеграция в Orchestrator

### 1. Импорт:
```python
from .coordinators.smart_exit_coordinator import SmartExitCoordinator
```

### 2. Инициализация (в __init__):
```python
# После создания position_registry и data_registry:
self.smart_exit_coordinator = SmartExitCoordinator(
    position_registry=self.position_registry,
    data_registry=self.data_registry,
    signal_generator=self.signal_generator,
    config_manager=self.config_manager,
    close_position_callback=self._close_position,
    scalping_config=self.scalping_config,
    orchestrator=self,
    check_interval=5.0,  # Проверка каждые 5 секунд
)
```

### 3. Запуск (в start):
```python
# После запуска других координаторов:
await self.smart_exit_coordinator.start()
```

### 4. Остановка (в stop):
```python
# Перед остановкой других координаторов:
await self.smart_exit_coordinator.stop()
```

---

## ✅ Преимущества

1. **Отдельный модуль** - не усложняет существующий код
2. **Интегрирован в систему** - использует существующие компоненты
3. **"Умный" анализ** - использует все индикаторы
4. **Не замедляет** - работает в фоне
5. **Легко отключать** - можно закомментировать запуск

---

## 🎯 Итог

**Создаем отдельный координатор `SmartExitCoordinator`, который:**
- ✅ Держит в себе открытые позиции (через PositionRegistry)
- ✅ Постоянно мониторит их (через PositionMonitor)
- ✅ Анализирует через индикаторы (RSI, MACD, Bollinger, ADX)
- ✅ Принимает "умные" решения о закрытии
- ✅ Интегрирован в систему (как TrailingSLCoordinator)

**Это НЕ усложнит систему, а наоборот - сделает ее более модульной и понятной!**

