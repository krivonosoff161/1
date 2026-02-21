# 🏗️ ПОЛНЫЙ АНАЛИЗ АРХИТЕКТУРЫ ТОРГОВОГО БОТА OKX

> **Полный технический анализ торгового бота для Futures и Spot торговли на бирже OKX**

**Дата создания:** 05 января 2026  
**Версия:** 1.0  
**Статус:** Полный анализ архитектуры и потоков данных

---

## 📋 СОДЕРЖАНИЕ

1. [Структура проекта и инициализация](#1-структура-проекта-и-инициализация)
2. [Источники данных и анализ](#2-источники-данных-и-анализ)
3. [Процесс принятия решений](#3-процесс-принятия-решений)
4. [Размещение ордеров и управление позициями](#4-размещение-ордеров-и-управление-позициями)
5. [Ключевые компоненты и их роли](#5-ключевые-компоненты-и-их-роли)
6. [Параметры и конфигурация](#6-параметры-и-конфигурация)
7. [Тестирование и валидация](#7-тестирование-и-валидация)
8. [Полный список файлов проекта](#8-полный-список-файлов-проекта)

---

## 1. СТРУКТУРА ПРОЕКТА И ИНИЦИАЛИЗАЦИЯ

### 1.1 Точка входа: `run.py`

**Файл:** `run.py` (корень проекта)

**Назначение:** Главная точка входа для запуска бота. Позволяет выбрать режим торговли (Spot или Futures).

**Процесс запуска:**

```python
# 1. Парсинг аргументов командной строки
parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['spot', 'futures'])
parser.add_argument('--interactive', action='store_true')

# 2. Выбор режима торговли
if args.mode == 'spot':
    await run_spot_bot()
elif args.mode == 'futures':
    await run_futures_bot()
else:
    # Интерактивный выбор
    mode = input("Выберите режим (spot/futures): ")
```

**Импорты:**
- `src.main_spot` - для Spot торговли
- `src.main_futures` - для Futures торговли

**Зависимости:**
- `asyncio` - асинхронное выполнение
- `loguru` - логирование

---

### 1.2 Инициализация Futures бота: `src/main_futures.py`

**Файл:** `src/main_futures.py`

**Назначение:** Инициализация и запуск Futures торгового бота.

**Процесс инициализации:**

```python
async def main():
    # 1. Загрузка конфигурации
    config = load_config('config/config_futures.yaml')
    
    # 2. Инициализация клиента OKX
    client = OKXFuturesClient(
        api_key=os.getenv('OKX_API_KEY'),
        api_secret=os.getenv('OKX_API_SECRET'),
        passphrase=os.getenv('OKX_PASSPHRASE'),
        sandbox=config.get('sandbox', False)
    )
    
    # 3. Создание оркестратора
    orchestrator = FuturesScalpingOrchestrator(
        client=client,
        config=config
    )
    
    # 4. Запуск бота
    await orchestrator.start()
    await orchestrator.run()
```

**Ключевые шаги:**

1. **Загрузка конфигурации:**
   - Чтение `config/config_futures.yaml`
   - Парсинг через Pydantic модели
   - Валидация параметров

2. **Инициализация клиента:**
   - Создание `OKXFuturesClient`
   - Проверка API ключей
   - Установка sandbox/production режима

3. **Создание оркестратора:**
   - Инициализация всех модулей
   - Настройка зависимостей
   - Подключение к WebSocket

---

### 1.3 Главный оркестратор: `src/strategies/scalping/futures/orchestrator.py`

**Файл:** `src/strategies/scalping/futures/orchestrator.py`

**Класс:** `FuturesScalpingOrchestrator`

**Назначение:** Координирует все модули бота, управляет жизненным циклом торговли.

**Инициализация модулей (метод `__init__`):**

```python
def __init__(self, client, config):
    # 1. Базовые компоненты
    self.client = client
    self.config = config
    self.is_running = False
    
    # 2. Менеджеры конфигурации
    self.config_manager = ConfigManager(config)
    self.parameter_provider = ParameterProvider(config_manager)
    
    # 3. Реестры данных
    self.data_registry = DataRegistry()
    self.position_registry = PositionRegistry()
    
    # 4. Генератор сигналов
    self.signal_generator = FuturesSignalGenerator(
        client=client,
        config_manager=config_manager,
        data_registry=data_registry,
        regime_manager=regime_manager
    )
    
    # 5. Координаторы
    self.signal_coordinator = SignalCoordinator(...)
    self.order_coordinator = OrderCoordinator(...)
    self.exit_decision_coordinator = ExitDecisionCoordinator(...)
    
    # 6. Менеджеры позиций
    self.position_manager = FuturesPositionManager(...)
    self.entry_manager = EntryManager(...)
    
    # 7. Системы управления рисками
    self.risk_manager = RiskManager(...)
    self.margin_calculator = MarginCalculator(...)
    self.liquidation_guard = LiquidationGuard(...)
    
    # 8. Trading Control Center
    self.trading_control_center = TradingControlCenter(...)
```

**Последовательность инициализации:**

1. **Базовая настройка:**
   - Загрузка конфигурации
   - Инициализация клиента
   - Настройка логирования

2. **Менеджеры конфигурации:**
   - `ConfigManager` - управление конфигурацией
   - `ParameterProvider` - единый доступ к параметрам

3. **Реестры:**
   - `DataRegistry` - хранение рыночных данных и индикаторов
   - `PositionRegistry` - хранение информации о позициях

4. **Генерация сигналов:**
   - `FuturesSignalGenerator` - генерация торговых сигналов
   - `AdaptiveRegimeManager` - определение режима рынка

5. **Координаторы:**
   - `SignalCoordinator` - обработка сигналов
   - `OrderCoordinator` - управление ордерами
   - `ExitDecisionCoordinator` - решения о закрытии

6. **Управление позициями:**
   - `EntryManager` - открытие позиций
   - `ExitAnalyzer` - анализ закрытия
   - `PositionManager` - общее управление

7. **Системы защиты:**
   - `RiskManager` - управление рисками
   - `LiquidationGuard` - защита от ликвидации
   - `SlippageGuard` - защита от проскальзывания

8. **Trading Control Center:**
   - Центральный координатор торгового цикла

---

### 1.4 Загрузка конфигурации: `src/config.py`

**Файл:** `src/config.py`

**Функции:**

```python
def load_config(config_path: str) -> Dict:
    """Загрузка YAML конфигурации"""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config

def validate_config(config: Dict) -> bool:
    """Валидация конфигурации"""
    # Проверка обязательных полей
    # Валидация типов
    # Проверка диапазонов значений
```

**Конфигурационные файлы:**

1. **`config/config_futures.yaml`** - основная конфигурация Futures
   - Параметры стратегии
   - Настройки рисков
   - Параметры режимов (trending/ranging/choppy)
   - Настройки символов

2. **`config/config_spot.yaml`** - конфигурация Spot
   - Manual Pool Strategy
   - Параметры OCO ордеров
   - Настройки баланса

3. **`config/features.yaml`** - флаги функций
   - Включение/выключение модулей
   - Экспериментальные функции

4. **`config/manual_pools.yaml`** - ручные пулы для Spot
   - Распределение средств по пулам
   - Лимиты на пулы

---

### 1.5 ConfigManager: `src/strategies/scalping/futures/config/config_manager.py`

**Класс:** `ConfigManager`

**Назначение:** Централизованное управление конфигурацией, загрузка параметров для символов и режимов.

**Ключевые методы:**

```python
class ConfigManager:
    def get_symbol_profile(self, symbol: str) -> Dict:
        """Получить профиль символа"""
        
    def get_regime_params(self, symbol: str, regime: str) -> Dict:
        """Получить параметры режима для символа"""
        
    def get_adaptive_risk_params(self, balance: float) -> Dict:
        """Получить адаптивные параметры риска по балансу"""
        
    def get_tp_sl_params(self, symbol: str, regime: str) -> Dict:
        """Получить параметры TP/SL"""
```

**Иерархия параметров:**

1. **Глобальные параметры** (из `config_futures.yaml`)
2. **Параметры режима** (trending/ranging/choppy)
3. **Параметры символа** (переопределения в `symbol_profiles`)
4. **Адаптивные параметры** (на основе баланса)

---

### 1.6 ParameterProvider: `src/strategies/scalping/futures/config/parameter_provider.py`

**Класс:** `ParameterProvider`

**Назначение:** Единая точка доступа к параметрам для всех модулей.

**Преимущества:**
- Единый интерфейс для доступа к параметрам
- Кэширование параметров
- Автоматическое применение иерархии (глобальные → режим → символ)

**Методы:**

```python
class ParameterProvider:
    async def get_entry_params(self, symbol: str, regime: str) -> Dict:
        """Параметры входа"""
        
    async def get_exit_params(self, symbol: str, regime: str) -> Dict:
        """Параметры выхода"""
        
    async def get_risk_params(self, symbol: str, balance: float) -> Dict:
        """Параметры риска"""
```

---

## 2. ИСТОЧНИКИ ДАННЫХ И АНАЛИЗ

### 2.1 Источники данных

**1. REST API OKX:**
- Исторические свечи (5m, 15m, 1h)
- Текущие цены
- Order book
- Funding rate
- Баланс и позиции

**2. WebSocket OKX:**
- Реальное время: тики, свечи
- Обновления позиций
- Обновления ордеров

**3. DataRegistry:**
- Кэш индикаторов
- Кэш режимов рынка
- Кэш свечей

**4. Логи:**
- История торговых решений
- Метрики производительности
- Ошибки и предупреждения

---

### 2.2 Загрузка и обработка данных

**Процесс загрузки свечей:**

```python
# 1. Получение свечей через REST API
candles = await client.get_candles(
    symbol='BTC-USDT',
    timeframe='5m',
    limit=100
)

# 2. Сохранение в DataRegistry
await data_registry.update_candles('BTC-USDT', candles)

# 3. Обновление через WebSocket
websocket.on('candle', lambda data: 
    data_registry.update_candles(data.symbol, [data.candle])
)
```

**Обработка данных:**

1. **Нормализация:**
   - Конвертация в формат OHLCV
   - Проверка валидности
   - Заполнение пропусков

2. **Кэширование:**
   - Сохранение в `DataRegistry`
   - TTL для кэша
   - Автоматическая очистка

3. **Обновление:**
   - WebSocket обновления в реальном времени
   - Периодическая синхронизация через REST

---

### 2.3 Конвейер анализа

**Расчет индикаторов:**

```python
# 1. Получение свечей
candles = await data_registry.get_candles('BTC-USDT', limit=100)

# 2. Расчет базовых индикаторов
indicators = {
    'rsi': calculate_rsi(candles, period=14),
    'macd': calculate_macd(candles, fast=12, slow=26, signal=9),
    'atr': calculate_atr(candles, period=14),
    'sma_20': calculate_sma(candles, period=20),
    'ema_12': calculate_ema(candles, period=12),
    'ema_26': calculate_ema(candles, period=26),
    'bb_upper': calculate_bb_upper(candles, period=20, std=2),
    'bb_lower': calculate_bb_lower(candles, period=20, std=2),
}

# 3. Расчет ADX (для определения тренда)
adx = calculate_adx(candles, period=14)
di_plus = get_di_plus()
di_minus = get_di_minus()

# 4. Сохранение в DataRegistry
await data_registry.update_indicators('BTC-USDT', indicators)
```

**Используемые индикаторы:**

1. **RSI (Relative Strength Index):**
   - Период: 14 (настраивается)
   - Перекупленность: > 70
   - Перепроданность: < 30

2. **MACD (Moving Average Convergence Divergence):**
   - Fast: 12, Slow: 26, Signal: 9
   - Сигнал: пересечение линий

3. **ATR (Average True Range):**
   - Период: 14
   - Используется для расчета волатильности

4. **SMA/EMA:**
   - SMA 20, EMA 12, EMA 26
   - Определение тренда

5. **Bollinger Bands:**
   - Период: 20, Std: 2.0
   - Уровни поддержки/сопротивления

6. **ADX (Average Directional Index):**
   - Период: 14
   - Сила тренда и направление (+DI/-DI)

---

### 2.4 Определение рыночных режимов

**Адаптивный менеджер режимов:** `src/strategies/scalping/futures/adaptivity/regime_manager.py`

**Класс:** `AdaptiveRegimeManager`

**Режимы рынка:**

1. **TRENDING (Трендовый):**
   - ADX > 30
   - Сильное направленное движение
   - Высокая уверенность в направлении

2. **RANGING (Боковой):**
   - ADX < 25
   - Боковое движение в диапазоне
   - Низкая волатильность

3. **CHOPPY (Хаотичный):**
   - Высокая волатильность (> 5%)
   - Много разворотов
   - Неопределенное направление

**Процесс определения режима:**

```python
def detect_regime(self, candles: List[OHLCV], current_price: float) -> RegimeDetectionResult:
    # 1. Расчет индикаторов
    indicators = self._calculate_regime_indicators(candles, current_price)
    
    # 2. Расчет scores для каждого режима
    choppy_score = calculate_choppy_score(indicators)
    trending_score = calculate_trending_score(indicators)
    ranging_score = calculate_ranging_score(indicators)
    
    # 3. Выбор режима с максимальным score
    best_regime = max([CHOPPY, TRENDING, RANGING], key=lambda r: scores[r])
    
    # 4. Расчет confidence
    confidence = scores[best_regime]
    
    return RegimeDetectionResult(
        regime=best_regime,
        confidence=confidence,
        indicators=indicators,
        reason=reason
    )
```

**Факторы определения режима:**

1. **ADX значение:**
   - Высокий ADX (> 30) → TRENDING
   - Низкий ADX (< 25) → RANGING

2. **Волатильность:**
   - Высокая (> 5%) → CHOPPY
   - Низкая (< 2%) → RANGING

3. **Развороты:**
   - Много разворотов (> 5) → CHOPPY
   - Мало разворотов → TRENDING/RANGING

4. **Объем:**
   - Высокий объем → TRENDING
   - Низкий объем → RANGING

---

## 3. ПРОЦЕСС ПРИНЯТИЯ РЕШЕНИЙ

### 3.1 Генерация сигналов

**Генератор сигналов:** `src/strategies/scalping/futures/signal_generator.py`

**Класс:** `FuturesSignalGenerator`

**Процесс генерации:**

```python
async def generate_signals(self) -> List[Dict]:
    signals = []
    
    for symbol in self.symbols:
        # 1. Получение рыночных данных
        market_data = await self._get_market_data(symbol)
        
        # 2. Определение режима
        regime = await self.regime_manager.update_regime(
            market_data.ohlcv_data,
            market_data.current_price
        )
        
        # 3. Расчет индикаторов
        indicators = await self._calculate_indicators(symbol, market_data)
        
        # 4. Генерация базовых сигналов
        base_signals = await self._generate_base_signals(
            symbol, market_data, indicators, regime
        )
        
        # 5. Применение фильтров
        filtered_signals = await self._apply_filters(base_signals)
        
        signals.extend(filtered_signals)
    
    return signals
```

**Типы сигналов:**

1. **RSI сигналы:**
   - LONG: RSI < 30 (перепроданность)
   - SHORT: RSI > 70 (перекупленность)

2. **MACD сигналы:**
   - LONG: MACD > Signal AND Histogram > 0
   - SHORT: MACD < Signal AND Histogram < 0

3. **Импульсные сигналы:**
   - LONG: Зеленая свеча + подтверждение тренда
   - SHORT: Красная свеча + подтверждение тренда

4. **MA сигналы:**
   - LONG: EMA12 > EMA26 AND Цена > EMA12
   - SHORT: EMA12 < EMA26 AND Цена < EMA12

**Система оценки (Scoring):**

```python
# Базовые баллы (0-12):
long_score = 0
short_score = 0

# SMA Trend: +1
if sma_20 < current_price:
    long_score += 1
else:
    short_score += 1

# EMA Trend: +2
if ema_12 > ema_26:
    long_score += 2
else:
    short_score += 2

# RSI: +2
if rsi < 30:
    long_score += 2
elif rsi > 70:
    short_score += 2

# Bollinger Bands: +2
if price <= bb_lower:
    long_score += 2
elif price >= bb_upper:
    short_score += 2

# Volume: +2
if volume > volume_ma * 1.2:
    if long_score > short_score:
        long_score += 2
    else:
        short_score += 2

# MACD: +2
if macd_line > signal_line and histogram > 0:
    long_score += 2
elif macd_line < signal_line and histogram < 0:
    short_score += 2

# Бонусы от фильтров:
# - Multi-Timeframe: +1-3
# - Pivot Points: +1-3
# - Volume Profile: +1-3

# Минимальный порог (адаптивный):
threshold = get_regime_threshold(regime)  # TRENDING: 6, RANGING: 4, CHOPPY: 7

if long_score >= threshold and long_score > short_score:
    signal = {
        'symbol': symbol,
        'side': 'LONG',
        'strength': long_score / 12.0,
        'confidence': calculate_confidence(long_score, indicators),
        'regime': regime
    }
```

---

### 3.2 Параметры, влияющие на решения

**1. TP/SL соотношения:**

```python
# Адаптивные по режиму:
trending_params = {
    'tp_atr_multiplier': 2.5,  # TP = 2.5 × ATR
    'sl_atr_multiplier': 1.2    # SL = 1.2 × ATR
}

ranging_params = {
    'tp_atr_multiplier': 2.0,
    'sl_atr_multiplier': 1.5
}

choppy_params = {
    'tp_atr_multiplier': 1.5,
    'sl_atr_multiplier': 1.0
}
```

**2. Leverage (адаптивное):**

```python
# На основе силы сигнала:
if strength < 0.3:
    leverage = 3x  # very_weak
elif strength < 0.5:
    leverage = 5x  # weak
elif strength < 0.7:
    leverage = 10x  # medium
elif strength < 0.9:
    leverage = 20x  # strong
else:
    leverage = 30x  # very_strong
```

**3. Размер позиции:**

```python
# Адаптивный по балансу:
if balance < 1500:
    profile = 'small'
    base_size = 50
    max_size = 120
elif balance < 3500:
    profile = 'medium'
    base_size = 100
    max_size = 200
else:
    profile = 'large'
    base_size = 200
    max_size = 400

# Корректировка на волатильность:
atr_percent = atr / current_price
volatility_multiplier = calculate_multiplier(atr_percent, regime)
position_size = base_size * volatility_multiplier * regime_multiplier
```

---

### 3.3 Правила управления рисками

**1. Максимум открытых позиций:**

```python
# По профилю баланса:
max_positions = {
    'small': 2,
    'medium': 3,
    'large': 3
}

# Проверка перед открытием:
if len(active_positions) >= max_positions[balance_profile]:
    block_signal(reason='max_positions_reached')
```

**2. Стоп-лосс:**

```python
# Адаптивный по режиму:
sl_distance = atr * sl_atr_multiplier[regime]

# Защита от ликвидации:
liquidation_price = calculate_liquidation_price(
    entry_price, leverage, margin
)
min_sl_distance = abs(entry_price - liquidation_price) * 1.1

if sl_distance < min_sl_distance:
    sl_distance = min_sl_distance
```

**3. Тейк-профит:**

```python
# Адаптивный по режиму:
tp_distance = atr * tp_atr_multiplier[regime]

# Partial TP:
if profit > tp_distance * 0.5:
    close_partial(50%)  # Закрыть 50% позиции
```

**4. Максимальная просадка:**

```python
# Дневной лимит:
max_daily_loss = balance * 0.10  # 10%

if daily_loss >= max_daily_loss:
    stop_trading(reason='max_daily_loss_reached')
```

---

### 3.4 ParameterProvider

**Единый доступ к параметрам:**

```python
class ParameterProvider:
    async def get_entry_params(self, symbol: str, regime: str) -> Dict:
        """Параметры входа"""
        return {
            'min_score_threshold': self._get_threshold(symbol, regime),
            'position_size_multiplier': self._get_size_multiplier(symbol, regime),
            'leverage': self._get_leverage(symbol, regime),
        }
    
    async def get_exit_params(self, symbol: str, regime: str) -> Dict:
        """Параметры выхода"""
        return {
            'tp_atr_multiplier': self._get_tp_multiplier(symbol, regime),
            'sl_atr_multiplier': self._get_sl_multiplier(symbol, regime),
            'max_holding_minutes': self._get_max_holding(symbol, regime),
        }
```

**Иерархия параметров:**

1. Глобальные (config_futures.yaml)
2. Режим (trending/ranging/choppy)
3. Символ (symbol_profiles)
4. Адаптивные (на основе баланса/статистики)

---

## 4. РАЗМЕЩЕНИЕ ОРДЕРОВ И УПРАВЛЕНИЕ ПОЗИЦИЯМИ

### 4.1 Размещение ордеров

**Исполнитель ордеров:** `src/strategies/scalping/futures/order_executor.py`

**Класс:** `FuturesOrderExecutor`

**Типы ордеров:**

1. **MARKET (Рыночный):**
   - Мгновенное исполнение
   - Комиссия: 0.05% (taker)
   - Используется для срочного входа/выхода

2. **LIMIT (Лимитный):**
   - Исполнение по указанной цене
   - Комиссия: 0.02% (maker)
   - Используется для экономии на комиссиях

3. **POST-ONLY:**
   - Гарантирует maker комиссию
   - Не исполняется как taker
   - Используется для оптимизации комиссий

**Процесс размещения:**

```python
async def place_order(self, signal: Dict) -> Dict:
    # 1. Расчет параметров ордера
    symbol = signal['symbol']
    side = signal['side']  # 'buy' или 'sell'
    size = calculate_position_size(signal)
    leverage = calculate_leverage(signal)
    
    # 2. Выбор типа ордера
    order_type = self._select_order_type(signal)
    
    # 3. Расчет цены
    if order_type == 'LIMIT':
        price = self._calculate_limit_price(signal)
    else:
        price = None  # MARKET
    
    # 4. Размещение на бирже
    order = await self.client.place_order(
        symbol=symbol,
        side=side,
        order_type=order_type,
        size=size,
        price=price,
        leverage=leverage
    )
    
    # 5. Ожидание исполнения
    if order_type == 'LIMIT':
        await self._wait_for_fill(order, timeout=30)
    
    return order
```

**Расчет лимитной цены:**

```python
def _calculate_limit_price(self, signal: Dict) -> float:
    current_price = signal['current_price']
    side = signal['side']
    offset_percent = 0.001  # 0.1% от текущей цены
    
    if side == 'buy':
        # Покупаем ниже текущей цены
        limit_price = current_price * (1 - offset_percent)
    else:
        # Продаем выше текущей цены
        limit_price = current_price * (1 + offset_percent)
    
    # Округление до шага цены
    limit_price = round_to_tick_size(limit_price, tick_size)
    
    return limit_price
```

---

### 4.2 Переход от ордера к позиции

**Процесс:**

```python
# 1. Размещение ордера
order = await order_executor.place_order(signal)

# 2. Ожидание исполнения
if order['status'] == 'filled':
    # 3. Регистрация позиции в PositionRegistry
    position = await position_registry.register_position(
        symbol=signal['symbol'],
        side=signal['side'],
        entry_price=order['fill_price'],
        size=order['filled_size'],
        leverage=order['leverage'],
        regime=signal['regime'],
        entry_time=datetime.now()
    )
    
    # 4. Инициализация Trailing Stop Loss
    await trailing_sl_coordinator.initialize(
        symbol=signal['symbol'],
        entry_price=order['fill_price'],
        side=signal['side'],
        initial_sl=calculate_initial_sl(signal)
    )
    
    # 5. Запись метрик
    await conversion_metrics.record_signal_executed(
        symbol=signal['symbol'],
        signal_type=signal.get('type'),
        regime=signal['regime']
    )
```

---

### 4.3 Мониторинг позиции

**Менеджер позиций:** `src/strategies/scalping/futures/position_manager.py`

**Класс:** `FuturesPositionManager`

**Отслеживание PnL:**

```python
async def calculate_pnl(self, position: Dict) -> float:
    current_price = await self._get_current_price(position['symbol'])
    entry_price = position['entry_price']
    size = position['size']
    side = position['side']
    leverage = position['leverage']
    
    if side == 'long':
        pnl_percent = ((current_price - entry_price) / entry_price) * leverage * 100
    else:
        pnl_percent = ((entry_price - current_price) / entry_price) * leverage * 100
    
    return pnl_percent
```

**Расчет просадки:**

```python
async def calculate_drawdown(self, position: Dict) -> float:
    current_pnl = await self.calculate_pnl(position)
    peak_profit = position.get('peak_profit', 0)
    
    if current_pnl < peak_profit:
        drawdown = peak_profit - current_pnl
    else:
        drawdown = 0
        position['peak_profit'] = current_pnl
    
    return drawdown
```

---

### 4.4 Логика решений о выходе

**Exit Analyzer:** `src/strategies/scalping/futures/positions/exit_analyzer.py`

**Класс:** `ExitAnalyzer`

**Условия закрытия:**

1. **Take Profit:**
```python
if current_pnl >= tp_percent:
    close_position(reason='tp_reached')
```

2. **Stop Loss:**
```python
if current_pnl <= -sl_percent:
    close_position(reason='sl_reached')
```

3. **Trailing Stop Loss:**
```python
if current_price <= trailing_sl_price:
    close_position(reason='trailing_sl_hit')
```

4. **Максимальное время удержания:**
```python
holding_time = datetime.now() - position['entry_time']
if holding_time >= max_holding_time:
    close_position(reason='max_holding_time')
```

5. **Умное закрытие (Exit Analyzer):**
```python
exit_decision = await exit_analyzer.analyze_position(symbol)

if exit_decision['should_close']:
    close_position(
        reason=exit_decision['reason'],
        urgency=exit_decision['urgency']
    )
```

**Адаптивная логика закрытия:**

```python
# TRENDING режим:
# - Продление TP при сильном тренде
# - Защита прибыли через trailing stop
# - Максимальное время: 45 минут

# RANGING режим:
# - Быстрый выход при достижении TP
# - Строгий SL
# - Максимальное время: 15 минут

# CHOPPY режим:
# - Очень быстрый выход
# - Узкий SL
# - Максимальное время: 10 минут
```

---

## 5. КЛЮЧЕВЫЕ КОМПОНЕНТЫ И ИХ РОЛИ

### 5.1 Orchestrator

**Файл:** `src/strategies/scalping/futures/orchestrator.py`

**Класс:** `FuturesScalpingOrchestrator`

**Роль:** Главный координатор всех модулей бота.

**Ответственность:**
- Инициализация всех модулей
- Управление жизненным циклом
- Координация торгового цикла
- Обработка ошибок
- Graceful shutdown

**Ключевые методы:**
- `start()` - запуск бота
- `run()` - главный цикл
- `stop()` - остановка бота
- `_sync_positions_with_exchange()` - синхронизация с биржей

---

### 5.2 Trading Control Center

**Файл:** `src/strategies/scalping/futures/core/trading_control_center.py`

**Класс:** `TradingControlCenter`

**Роль:** Центральный координатор торгового цикла.

**Ответственность:**
- Главный торговый цикл
- Обновление состояния
- Генерация и обработка сигналов
- Управление позициями
- Мониторинг ордеров

**Главный цикл:**

```python
async def run_main_loop(self):
    while self.is_running:
        # 1. Обновление состояния
        await self.update_state()
        
        # 2. Генерация сигналов
        signals = await self.signal_generator.generate_signals()
        
        # 3. Обработка сигналов
        await self.signal_coordinator.process_signals(signals)
        
        # 4. Управление позициями
        await self._manage_positions()
        
        # 5. Мониторинг ордеров
        await self._monitor_orders()
        
        # 6. Синхронизация с биржей
        await self._sync_positions_with_exchange()
        
        # 7. Обновление статистики
        await self._update_statistics()
        
        await asyncio.sleep(6)  # Цикл каждые 6 секунд
```

---

### 5.3 Signal Generator

**Файл:** `src/strategies/scalping/futures/signal_generator.py`

**Класс:** `FuturesSignalGenerator`

**Роль:** Генерация торговых сигналов на основе технического анализа.

**Ответственность:**
- Расчет индикаторов
- Генерация сигналов (LONG/SHORT)
- Применение базовых фильтров
- Адаптация под режим рынка

**Ключевые методы:**
- `generate_signals()` - генерация всех сигналов
- `_generate_base_signals()` - базовые сигналы
- `_generate_rsi_signals()` - RSI сигналы
- `_generate_macd_signals()` - MACD сигналы
- `_calculate_indicators()` - расчет индикаторов

---

### 5.4 Signal Coordinator

**Файл:** `src/strategies/scalping/futures/coordinators/signal_coordinator.py`

**Класс:** `SignalCoordinator`

**Роль:** Координация обработки торговых сигналов.

**Ответственность:**
- Валидация сигналов
- Применение фильтров
- Проверка рисков
- Исполнение сигналов через EntryManager

**Процесс обработки:**

```python
async def process_signals(self, signals: List[Dict]):
    for signal in signals:
        # 1. Валидация
        if not self._validate_signal(signal):
            continue
        
        # 2. Проверка рисков
        if not await self._check_risks(signal):
            continue
        
        # 3. Применение фильтров
        if not await self._apply_filters(signal):
            continue
        
        # 4. Исполнение через EntryManager
        await self.entry_manager.open_position(signal)
```

---

### 5.5 Entry Manager

**Файл:** `src/strategies/scalping/futures/positions/entry_manager.py`

**Класс:** `EntryManager`

**Роль:** Централизованное открытие позиций.

**Ответственность:**
- Расчет размера позиции
- Расчет leverage
- Размещение ордера
- Регистрация позиции

---

### 5.6 Exit Analyzer

**Файл:** `src/strategies/scalping/futures/positions/exit_analyzer.py`

**Класс:** `ExitAnalyzer`

**Роль:** Умный анализ позиций для принятия решений о закрытии.

**Ответственность:**
- Анализ текущего состояния позиции
- Адаптивная логика закрытия
- Продление TP при сильном тренде
- Защита прибыли

---

### 5.7 Position Registry

**Файл:** `src/strategies/scalping/futures/core/position_registry.py`

**Класс:** `PositionRegistry`

**Роль:** Единый реестр всех позиций.

**Ответственность:**
- Хранение метаданных позиций
- Отслеживание peak_profit
- Управление флагами (partial_tp_executed)
- Thread-safe доступ

---

### 5.8 Data Registry

**Файл:** `src/strategies/scalping/futures/core/data_registry.py`

**Класс:** `DataRegistry`

**Роль:** Централизованное хранение рыночных данных.

**Ответственность:**
- Хранение свечей
- Хранение индикаторов
- Хранение режимов рынка
- Кэширование данных

---

### 5.9 Поток данных между компонентами

```
┌─────────────────┐
│   Orchestrator  │
└────────┬────────┘
         │
         ├───► TradingControlCenter
         │         │
         │         ├───► SignalGenerator
         │         │         │
         │         │         └───► DataRegistry
         │         │
         │         ├───► SignalCoordinator
         │         │         │
         │         │         ├───► EntryManager
         │         │         │         │
         │         │         │         └───► OrderExecutor
         │         │         │
         │         │         └───► FilterManager
         │         │
         │         ├───► PositionManager
         │         │         │
         │         │         ├───► ExitAnalyzer
         │         │         │
         │         │         └───► TrailingSLCoordinator
         │         │
         │         └───► OrderCoordinator
         │
         └───► PositionRegistry
                   │
                   └───► PositionSync
```

---

## 6. ПАРАМЕТРЫ И КОНФИГУРАЦИЯ

### 6.1 Настраиваемые параметры

**Глобальные параметры (config_futures.yaml):**

```yaml
# Торговые символы
symbols:
  - BTC-USDT
  - ETH-USDT
  - SOL-USDT

# Леверидж по умолчанию
leverage: 5

# Параметры режимов
adaptive_regime:
  trending:
    min_score_threshold: 6
    max_trades_per_hour: 15
    tp_atr_multiplier: 2.5
    sl_atr_multiplier: 1.2
  ranging:
    min_score_threshold: 4
    max_trades_per_hour: 10
    tp_atr_multiplier: 2.0
    sl_atr_multiplier: 1.5
  choppy:
    min_score_threshold: 7
    max_trades_per_hour: 5
    tp_atr_multiplier: 1.5
    sl_atr_multiplier: 1.0
```

**Параметры символов:**

```yaml
symbol_profiles:
  BTC-USDT:
    position_multiplier: 1.2
    tp_percent: 5.0
    sl_percent: 1.0
  ETH-USDT:
    position_multiplier: 1.0
    tp_percent: 4.0
    sl_percent: 0.8
```

**Адаптивные параметры риска:**

```yaml
adaptive_risk:
  small:  # balance < $1,500
    max_position_size: 120
    max_open_positions: 2
    max_loss_percent: 8.0
  medium:  # $1,500 <= balance < $3,500
    max_position_size: 200
    max_open_positions: 3
    max_loss_percent: 6.0
  large:  # balance >= $3,500
    max_position_size: 400
    max_open_positions: 3
    max_loss_percent: 5.0
```

---

### 6.2 Динамический расчет параметров

**Адаптация по балансу:**

```python
def get_balance_profile(balance: float) -> str:
    if balance < 1500:
        return 'small'
    elif balance < 3500:
        return 'medium'
    else:
        return 'large'

def get_adaptive_params(balance: float, regime: str) -> Dict:
    profile = get_balance_profile(balance)
    base_params = config['adaptive_risk'][profile]
    regime_params = config['adaptive_regime'][regime]
    
    return {
        **base_params,
        **regime_params
    }
```

**Адаптация по статистике:**

```python
def get_dynamic_threshold(symbol: str, regime: str) -> float:
    win_rate = trading_statistics.get_win_rate(symbol, regime)
    base_threshold = config['adaptive_regime'][regime]['min_score_threshold']
    
    # Снижаем порог при высокой win rate
    if win_rate > 0.6:
        threshold = base_threshold * 0.9
    elif win_rate < 0.4:
        threshold = base_threshold * 1.1
    else:
        threshold = base_threshold
    
    return threshold
```

---

## 7. ТЕСТИРОВАНИЕ И ВАЛИДАЦИЯ

### 7.1 Фреймворк тестирования

**Файл:** `scripts/parameter_tester.py` (если существует)

**Назначение:** Тестирование параметров стратегии на исторических данных.

**Процесс:**

1. Загрузка исторических данных
2. Симуляция торговли с различными параметрами
3. Расчет метрик (win rate, Sharpe ratio, max drawdown)
4. Сравнение результатов
5. Выбор оптимальных параметров

---

### 7.2 Сценарии тестирования

**1. Бэктестинг:**
- Тестирование на исторических данных
- Валидация логики сигналов
- Проверка фильтров

**2. Paper Trading:**
- Торговля на реальных данных без реальных денег
- Проверка исполнения ордеров
- Валидация рисков

**3. Sandbox режим:**
- Торговля на тестовой среде OKX
- Реальные API вызовы
- Без реальных денег

---

## 8. ПОЛНЫЙ ПОТОК ОТ ИНИЦИАЛИЗАЦИИ ДО ЗАКРЫТИЯ ПОЗИЦИИ

### 8.1 Полная последовательность запуска

```
1. run.py
   └─> Выбор режима (spot/futures)
       └─> src/main_futures.py
           └─> Загрузка config/config_futures.yaml
           └─> Создание FuturesScalpingOrchestrator
           └─> orchestrator.start()
               ├─> _verify_initialization() - проверка модулей
               ├─> _initialize_client() - инициализация OKX клиента
               ├─> _start_trading_modules() - инициализация торговых модулей
               │   ├─> signal_generator.initialize()
               │   │   ├─> AdaptiveRegimeManager инициализация
               │   │   ├─> Загрузка исторических данных
               │   │   └─> Расчет начальных индикаторов
               │   ├─> order_executor.initialize()
               │   └─> position_manager.initialize()
               ├─> websocket_coordinator.initialize_websocket()
               │   └─> Подключение к WebSocket OKX
               │   └─> Подписка на тикеры, свечи, позиции
               ├─> _start_safety_modules() - модули безопасности
               ├─> _reset_all_states() - очистка состояний
               └─> Загрузка существующих позиций с биржи
           └─> orchestrator.run()
               └─> trading_control_center.run_main_loop()
```

### 8.2 Главный торговый цикл (детально)

**Цикл выполняется каждые ~6 секунд:**

```python
while is_running:
    # 1. ОБНОВЛЕНИЕ СОСТОЯНИЯ
    await update_state()
    ├─> Получение баланса с биржи
    ├─> Обновление позиций через WebSocket
    └─> Обновление ордеров
    
    # 2. ГЕНЕРАЦИЯ СИГНАЛОВ
    signals = await signal_generator.generate_signals()
    ├─> Для каждого символа (BTC-USDT, ETH-USDT...):
    │   ├─> Получение свечей из DataRegistry
    │   ├─> Определение режима (AdaptiveRegimeManager)
    │   │   ├─> Расчет ADX, DI+, DI-
    │   │   ├─> Анализ волатильности
    │   │   └─> Выбор режима: TRENDING/RANGING/CHOPPY
    │   ├─> Расчет индикаторов
    │   │   ├─> RSI, MACD, ATR
    │   │   ├─> SMA 20, EMA 12, EMA 26
    │   │   ├─> Bollinger Bands
    │   │   └─> Сохранение в DataRegistry
    │   ├─> Генерация базовых сигналов
    │   │   ├─> RSI сигналы (перекупленность/перепроданность)
    │   │   ├─> MACD сигналы (пересечение линий)
    │   │   ├─> Импульсные сигналы
    │   │   └─> MA сигналы (тренд)
    │   ├─> Расчет score (0-12 баллов)
    │   │   ├─> SMA Trend: +1
    │   │   ├─> EMA Trend: +2
    │   │   ├─> RSI: +2
    │   │   ├─> Bollinger Bands: +2
    │   │   ├─> Volume: +2
    │   │   └─> MACD: +2
    │   ├─> Бонусы от фильтров: +1-3
    │   └─> Проверка порога (адаптивный по режиму)
    
    # 3. ОБРАБОТКА СИГНАЛОВ
    await signal_coordinator.process_signals(signals)
    ├─> Для каждого сигнала:
    │   ├─> Валидация сигнала
    │   │   ├─> Проверка минимального score
    │   │   ├─> Проверка существующей позиции
    │   │   └─> Проверка блокировок (circuit breaker)
    │   ├─> Проверка рисков
    │   │   ├─> Максимум открытых позиций
    │   │   ├─> Достаточно маржи
    │   │   └─> Проверка лимитов
    │   ├─> Применение фильтров
    │   │   ├─> ADX Filter
    │   │   ├─> Multi-Timeframe Filter
    │   │   ├─> Pivot Points Filter
    │   │   ├─> Volume Profile Filter
    │   │   ├─> Liquidity Filter
    │   │   ├─> Momentum Filter
    │   │   ├─> Volatility Regime Filter
    │   │   ├─> Order Flow Filter
    │   │   └─> Funding Rate Filter
    │   └─> Исполнение через EntryManager
    │       ├─> Расчет размера позиции
    │       ├─> Расчет leverage (адаптивный)
    │       ├─> Размещение ордера (LIMIT/MARKET)
    │       └─> Регистрация позиции в PositionRegistry
    
    # 4. УПРАВЛЕНИЕ ПОЗИЦИЯМИ
    await manage_positions()
    ├─> Для каждой открытой позиции:
    │   ├─> Расчет текущего PnL
    │   ├─> Проверка Take Profit
    │   ├─> Проверка Stop Loss
    │   ├─> Проверка Trailing Stop Loss
    │   ├─> Проверка максимального времени удержания
    │   └─> Анализ через ExitAnalyzer
    │       ├─> Адаптивная логика закрытия
    │       ├─> Продление TP при сильном тренде
    │       └─> Защита прибыли
    
    # 5. МОНИТОРИНГ ОРДЕРОВ
    await order_coordinator.monitor_limit_orders()
    ├─> Проверка таймаутов лимитных ордеров
    └─> Замена на рыночные при необходимости
    
    # 6. СИНХРОНИЗАЦИЯ С БИРЖЕЙ
    await _sync_positions_with_exchange()
    ├─> Получение позиций с биржи
    ├─> Обнаружение drift позиций
    └─> Обновление PositionRegistry
    
    # 7. ОБНОВЛЕНИЕ СТАТИСТИКИ
    await update_performance()
    ├─> Обновление метрик конверсии
    ├─> Обновление метрик времени удержания
    └─> Проверка алертов
    
    # 8. ПРОВЕРКА TRAILING STOP LOSS
    await trailing_sl_coordinator.update_all()
    └─> Обновление TSL для всех позиций
    
    await asyncio.sleep(6)  # Цикл каждые 6 секунд
```

### 8.3 Полный поток открытия позиции

```
1. ГЕНЕРАЦИЯ СИГНАЛА
   signal_generator.generate_signals()
   └─> Создание сигнала:
       {
           'symbol': 'BTC-USDT',
           'side': 'LONG',
           'strength': 0.75,
           'confidence': 0.85,
           'regime': 'TRENDING',
           'current_price': 45000.0,
           'indicators': {...}
       }

2. ОБРАБОТКА СИГНАЛА
   signal_coordinator.process_signals([signal])
   ├─> Валидация: ✓
   ├─> Проверка рисков: ✓
   ├─> Применение фильтров: ✓
   └─> entry_manager.open_position(signal)

3. ОТКРЫТИЕ ПОЗИЦИИ
   entry_manager.open_position(signal)
   ├─> Получение параметров из ParameterProvider
   │   ├─> position_size_multiplier
   │   ├─> leverage
   │   └─> tp_atr_multiplier, sl_atr_multiplier
   ├─> Расчет размера позиции
   │   ├─> base_size = 100 (из конфига)
   │   ├─> multiplier = 1.2 (для BTC-USDT)
   │   ├─> volatility_multiplier = 1.1 (высокая волатильность)
   │   └─> position_size = 100 * 1.2 * 1.1 = 132
   ├─> Расчет leverage (адаптивный)
   │   ├─> strength = 0.75
   │   └─> leverage = 20x (strong signal)
   ├─> Расчет TP/SL
   │   ├─> ATR = 500
   │   ├─> tp_distance = 500 * 2.5 = 1250 (TRENDING режим)
   │   ├─> sl_distance = 500 * 1.2 = 600
   │   ├─> tp_price = 45000 + 1250 = 46250
   │   └─> sl_price = 45000 - 600 = 44400
   ├─> Размещение ордера
   │   ├─> order_type = 'LIMIT' (для экономии комиссий)
   │   ├─> limit_price = 45000 * 0.999 = 44955 (0.1% ниже)
   │   └─> order = await client.place_order(...)
   └─> Регистрация позиции
       ├─> position_registry.register_position(...)
       ├─> Инициализация Trailing Stop Loss
       └─> Запись метрик (conversion_metrics.record_signal_executed)
```

### 8.4 Полный поток закрытия позиции

```
1. МОНИТОРИНГ ПОЗИЦИИ
   manage_positions()
   └─> Для каждой позиции:
       ├─> Расчет текущего PnL
       │   ├─> current_price = 46000
       │   ├─> entry_price = 45000
       │   ├─> leverage = 20x
       │   └─> pnl_percent = ((46000-45000)/45000) * 20 * 100 = 4.44%
       ├─> Проверка Take Profit
       │   └─> pnl >= tp_percent? (4.44% >= 2.5%?) → ДА
       ├─> Проверка Stop Loss
       │   └─> pnl <= -sl_percent? → НЕТ
       ├─> Проверка Trailing Stop Loss
       │   └─> current_price <= trailing_sl_price? → НЕТ
       └─> Анализ через ExitAnalyzer
           └─> exit_analyzer.analyze_position(symbol)

2. АНАЛИЗ ПОЗИЦИИ
   exit_analyzer.analyze_position(symbol)
   ├─> Получение данных позиции
   ├─> Анализ текущего состояния
   │   ├─> Режим рынка: TRENDING
   │   ├─> Тренд продолжается: ДА
   │   └─> Сила тренда: ВЫСОКАЯ
   ├─> Адаптивная логика
   │   ├─> TRENDING режим: продление TP
   │   ├─> Текущий TP: 2.5%
   │   └─> Новый TP: 3.5% (продление)
   └─> Решение: НЕ ЗАКРЫВАТЬ (продлить TP)

3. ЗАКРЫТИЕ ПОЗИЦИИ (когда условие выполнено)
   position_manager.close_position(symbol, reason='tp_reached')
   ├─> Получение позиции из PositionRegistry
   ├─> Размещение ордера на закрытие
   │   ├─> side = 'sell' (для LONG позиции)
   │   ├─> size = position.size
   │   └─> order_type = 'MARKET' (быстрое закрытие)
   ├─> Ожидание исполнения
   ├─> Обновление PositionRegistry
   │   └─> Удаление позиции
   ├─> Запись метрик
   │   ├─> conversion_metrics.record_position_closed(...)
   │   ├─> holding_time_metrics.record_close(...)
   │   └─> trading_statistics.record_trade(...)
   └─> Логирование результата
```

---

## 9. ПОЛНЫЙ СПИСОК ФАЙЛОВ ПРОЕКТА

### 9.1 Корневые файлы

| Файл | Описание | Роль |
|------|----------|------|
| `run.py` | Точка входа | Выбор режима торговли (Spot/Futures) |
| `config.yaml` | Legacy конфигурация | Устаревший конфиг (не используется) |
| `requirements.txt` | Зависимости Python | Список пакетов для установки |
| `README.md` | Документация | Основная документация проекта |
| `ПОЛНОЕ_ОПИСАНИЕ_ТОРГОВОГО_БОТА.md` | Полное описание | Техническая документация для AI |
| `BOT_ARCHITECTURE_FULL_ANALYSIS.md` | Этот файл | Полный анализ архитектуры |

### 9.2 Конфигурационные файлы

| Файл | Описание | Роль |
|------|----------|------|
| `config/config_futures.yaml` | Конфигурация Futures | Основные параметры Futures торговли |
| `config/config_spot.yaml` | Конфигурация Spot | Параметры Spot торговли |
| `config/features.yaml` | Флаги функций | Включение/выключение модулей |
| `config/manual_pools.yaml` | Ручные пулы | Распределение средств для Spot |

### 9.3 Основные модули (src/)

#### 9.3.1 Точки входа

| Файл | Описание | Роль |
|------|----------|------|
| `src/main_futures.py` | Запуск Futures бота | Инициализация и запуск Futures торговли |
| `src/main_spot.py` | Запуск Spot бота | Инициализация и запуск Spot торговли |
| `src/config.py` | Загрузка конфигурации | Парсинг YAML конфигов |

#### 9.3.2 Клиенты биржи

| Файл | Описание | Роль |
|------|----------|------|
| `src/clients/futures_client.py` | OKX Futures клиент | REST API для Futures |
| `src/clients/spot_client.py` | OKX Spot клиент | REST API для Spot |

#### 9.3.3 Futures стратегия (src/strategies/scalping/futures/)

**Оркестратор:**
| Файл | Описание | Роль |
|------|----------|------|
| `orchestrator.py` | Главный оркестратор | Координация всех модулей Futures бота |

**Генерация сигналов:**
| Файл | Описание | Роль |
|------|----------|------|
| `signal_generator.py` | Генератор сигналов | Генерация торговых сигналов на основе ТА |
| `signals/rsi_signal_generator.py` | RSI сигналы | Генерация RSI сигналов |
| `signals/macd_signal_generator.py` | MACD сигналы | Генерация MACD сигналов |
| `signals/filter_manager.py` | Менеджер фильтров | Применение фильтров к сигналам |

**Координаторы:**
| Файл | Описание | Роль |
|------|----------|------|
| `coordinators/signal_coordinator.py` | Координатор сигналов | Обработка и валидация сигналов |
| `coordinators/order_coordinator.py` | Координатор ордеров | Управление ордерами |
| `coordinators/exit_decision_coordinator.py` | Координатор выходов | Решения о закрытии позиций |
| `coordinators/trailing_sl_coordinator.py` | Координатор TSL | Управление Trailing Stop Loss |
| `coordinators/smart_exit_coordinator.py` | Умный выход | Адаптивная логика закрытия |
| `coordinators/websocket_coordinator.py` | WebSocket координатор | Управление WebSocket соединениями |

**Управление позициями:**
| Файл | Описание | Роль |
|------|----------|------|
| `position_manager.py` | Менеджер позиций | Общее управление позициями |
| `positions/entry_manager.py` | Менеджер входа | Открытие позиций |
| `positions/exit_analyzer.py` | Анализатор выхода | Анализ позиций для закрытия |
| `positions/position_scaling_manager.py` | Лестничный вход | Добавление к позиции |
| `positions/stop_loss_manager.py` | Менеджер SL | Управление Stop Loss |
| `positions/take_profit_manager.py` | Менеджер TP | Управление Take Profit |
| `positions/position_monitor.py` | Монитор позиций | Мониторинг открытых позиций |
| `positions/peak_profit_tracker.py` | Трекер прибыли | Отслеживание максимальной прибыли |

**Ядро:**
| Файл | Описание | Роль |
|------|----------|------|
| `core/trading_control_center.py` | Центр управления | Главный торговый цикл |
| `core/data_registry.py` | Реестр данных | Хранение рыночных данных и индикаторов |
| `core/position_registry.py` | Реестр позиций | Хранение метаданных позиций |
| `core/position_sync.py` | Синхронизация позиций | Синхронизация с биржей |
| `core/candle_buffer.py` | Буфер свечей | Кэширование свечей |

**Конфигурация:**
| Файл | Описание | Роль |
|------|----------|------|
| `config/config_manager.py` | Менеджер конфигурации | Управление параметрами |
| `config/parameter_provider.py` | Провайдер параметров | Единый доступ к параметрам |

**Адаптивность:**
| Файл | Описание | Роль |
|------|----------|------|
| `adaptivity/regime_manager.py` | Менеджер режимов | Определение режима рынка |
| `adaptivity/parameter_adapter.py` | Адаптер параметров | Адаптация параметров |
| `adaptivity/filter_parameters.py` | Параметры фильтров | Адаптивные параметры фильтров |
| `adaptivity/balance_manager.py` | Менеджер баланса | Адаптация по балансу |

**Риски:**
| Файл | Описание | Роль |
|------|----------|------|
| `risk_manager.py` | Менеджер рисков | Управление рисками |
| `risk/adaptive_leverage.py` | Адаптивное плечо | Расчет leverage по силе сигнала |
| `risk/liquidation_protector.py` | Защита от ликвидации | Защита от ликвидации |
| `risk/margin_monitor.py` | Монитор маржи | Мониторинг маржи |
| `risk/max_size_limiter.py` | Ограничитель размера | Ограничение размера позиций |

**Индикаторы:**
| Файл | Описание | Роль |
|------|----------|------|
| `indicators/indicator_calculator.py` | Калькулятор индикаторов | Расчет индикаторов |
| `indicators/atr_provider.py` | Провайдер ATR | Расчет ATR |
| `indicators/fast_adx.py` | Быстрый ADX | Оптимизированный расчет ADX |
| `indicators/futures_volume_profile.py` | Volume Profile | Расчет Volume Profile |
| `indicators/micro_pivot_calculator.py` | Микро пивоты | Расчет пивотов |
| `indicators/liquidity_levels.py` | Уровни ликвидности | Определение уровней ликвидности |
| `indicators/order_flow_indicator.py` | Order Flow | Анализ потока ордеров |
| `indicators/trailing_stop_loss.py` | Trailing Stop Loss | Расчет TSL |
| `indicators/funding_rate_monitor.py` | Монитор funding rate | Отслеживание funding rate |

**Фильтры:**
| Файл | Описание | Роль |
|------|----------|------|
| `filters/volatility_regime_filter.py` | Фильтр волатильности | Фильтрация по волатильности |
| `filters/momentum_filter.py` | Фильтр импульса | Фильтрация по импульсу |
| `filters/liquidity_filter.py` | Фильтр ликвидности | Фильтрация по ликвидности |
| `filters/order_flow_filter.py` | Фильтр потока ордеров | Фильтрация по потоку ордеров |
| `filters/funding_rate_filter.py` | Фильтр funding rate | Фильтрация по funding rate |

**Метрики:**
| Файл | Описание | Роль |
|------|----------|------|
| `metrics/conversion_metrics.py` | Метрики конверсии | Отслеживание конверсии сигналов |
| `metrics/holding_time_metrics.py` | Метрики времени удержания | Статистика времени удержания |
| `metrics/alert_manager.py` | Менеджер алертов | Управление алертами |

**Расчеты:**
| Файл | Описание | Роль |
|------|----------|------|
| `calculations/position_sizer.py` | Калькулятор размера | Расчет размера позиции |
| `calculations/margin_calculator.py` | Калькулятор маржи | Расчет маржи |
| `calculations/pnl_calculator.py` | Калькулятор PnL | Расчет прибыли/убытка |
| `calculations/balance_calculator.py` | Калькулятор баланса | Расчет баланса |
| `calculations/regime_calculator.py` | Калькулятор режима | Расчет режима рынка |

**Исполнение ордеров:**
| Файл | Описание | Роль |
|------|----------|------|
| `order_executor.py` | Исполнитель ордеров | Размещение ордеров на бирже |

**WebSocket:**
| Файл | Описание | Роль |
|------|----------|------|
| `websocket_manager.py` | Менеджер WebSocket | Управление WebSocket соединениями |
| `private_websocket_manager.py` | Приватный WebSocket | WebSocket для приватных данных |

**Логирование:**
| Файл | Описание | Роль |
|------|----------|------|
| `logging/debug_logger.py` | Debug логгер | Детальное логирование |
| `logging/structured_logger.py` | Структурированный логгер | Структурированное логирование |
| `logging/logger_factory.py` | Фабрика логгеров | Создание логгеров |

#### 9.3.4 Spot стратегия (src/strategies/scalping/spot/)

| Файл | Описание | Роль |
|------|----------|------|
| `orchestrator.py` | Spot оркестратор | Координация Spot торговли |
| `signal_generator.py` | Генератор сигналов | Генерация Spot сигналов |
| `order_executor.py` | Исполнитель ордеров | Размещение Spot ордеров |
| `position_manager.py` | Менеджер позиций | Управление Spot позициями |
| `risk_manager.py` | Менеджер рисков | Управление рисками Spot |
| `batch_order_manager.py` | Менеджер батчей | Управление батч-ордерами |
| `websocket_orchestrator.py` | WebSocket оркестратор | Управление WebSocket для Spot |

#### 9.3.5 Общие модули

**Индикаторы:**
| Файл | Описание | Роль |
|------|----------|------|
| `src/indicators/base.py` | Базовые индикаторы | Базовые функции индикаторов |
| `src/indicators/talib_wrapper.py` | TA-Lib обертка | Обертка для TA-Lib |
| `src/indicators/advanced/candle_patterns.py` | Паттерны свечей | Определение паттернов |
| `src/indicators/advanced/pivot_calculator.py` | Калькулятор пивотов | Расчет пивотов |
| `src/indicators/advanced/volume_profile.py` | Volume Profile | Расчет Volume Profile |

**Фильтры:**
| Файл | Описание | Роль |
|------|----------|------|
| `src/filters/correlation_manager.py` | Менеджер корреляции | Анализ корреляции |
| `src/filters/time_session_manager.py` | Менеджер сессий | Управление торговыми сессиями |

**Риски:**
| Файл | Описание | Роль |
|------|----------|------|
| `src/risk/risk_controller.py` | Контроллер рисков | Контроль рисков |
| `src/risk/risk_controller_config.py` | Конфиг рисков | Конфигурация рисков |

**Утилиты:**
| Файл | Описание | Роль |
|------|----------|------|
| `src/utils/logging_setup.py` | Настройка логирования | Настройка loguru |
| `src/utils/telegram_notifier.py` | Telegram уведомления | Отправка уведомлений |

**WebSocket:**
| Файл | Описание | Роль |
|------|----------|------|
| `src/websocket_manager.py` | Общий WebSocket менеджер | Управление WebSocket |
| `src/market_data_websocket.py` | WebSocket рыночных данных | Получение рыночных данных |
| `src/websocket_order_executor.py` | WebSocket исполнитель | Исполнение ордеров через WebSocket |

**Баланс:**
| Файл | Описание | Роль |
|------|----------|------|
| `src/balance/adaptive_balance_manager.py` | Адаптивный баланс | Адаптация по балансу |

### 9.4 Вспомогательные файлы

**Скрипты анализа:**
| Файл | Описание | Роль |
|------|----------|------|
| `analyze_logs.py` | Анализ логов | Анализ торговых логов |
| `analyze_sol_trade.py` | Анализ SOL сделки | Анализ конкретной сделки |

**Batch файлы:**
| Файл | Описание | Роль |
|------|----------|------|
| `analyze_logs.bat` | Запуск анализа логов | Windows batch для анализа |
| `analyze_exit_decisions.bat` | Анализ решений о выходе | Анализ закрытий позиций |
| `clean_logs.bat` | Очистка логов | Удаление старых логов |
| `clear_cache.bat` | Очистка кэша | Очистка кэша |
| `debug_console.bat` | Debug консоль | Запуск debug режима |

### 9.5 Документация

**Основная документация:**
- `docs/` - основная папка документации
- `docs/analysis/` - анализ работы бота
- `docs/architecture/` - архитектурная документация
- `docs/current/` - текущие задачи и статусы

**Примечание:** Полный список всех 15181 файлов проекта слишком объемен для включения в этот документ. Выше перечислены только ключевые файлы, участвующие в торговой логике.

---

**Дата создания:** 05 января 2026  
**Версия:** 1.0  
**Статус:** Завершен
