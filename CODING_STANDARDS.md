# 📐 СТАНДАРТЫ КОДИРОВАНИЯ ПРОЕКТА

## 🎯 ОБЩИЕ ПРИНЦИПЫ

### Философия кода:
1. **Читаемость важнее краткости** - код читается чаще чем пишется
2. **Явное лучше неявного** - не используем "магию"
3. **Простота важнее умности** - простой код = меньше багов
4. **DRY (Don't Repeat Yourself)** - но не фанатично
5. **KISS (Keep It Simple, Stupid)** - не усложняем без причины

---

## 🐍 PYTHON STYLE GUIDE

### Базовый стандарт: **PEP 8**

Используем автоформатирование:
- **black** (line length: 88)
- **isort** (сортировка импортов)
- **flake8** (линтер)

### Naming Conventions:

```python
# ✅ ПРАВИЛЬНО

# Переменные и функции: snake_case
user_balance = 1000.0
def calculate_position_size(): pass

# Классы: PascalCase
class ScalpingEngine: pass
class MultiTimeframeFilter: pass

# Константы: UPPER_SNAKE_CASE
MAX_POSITION_SIZE = 5.0
DEFAULT_TIMEOUT = 30

# Приватные методы/переменные: _leading_underscore
class Strategy:
    def __init__(self):
        self._internal_state = {}
    
    def _calculate_internal(self): pass

# "Очень" приватные: __double_leading
class Strategy:
    def __init__(self):
        self.__secret_data = {}

# ❌ НЕПРАВИЛЬНО

userBalance = 1000  # ❌ camelCase
def CalculateSize(): pass  # ❌ PascalCase для функции
max_position_size = 5.0  # ❌ константа не в UPPER_CASE
class scalping_engine: pass  # ❌ snake_case для класса
```

---

## 📝 ДОКУМЕНТАЦИЯ КОДА

### Docstrings (обязательны!)

```python
# ✅ ПРАВИЛЬНО

def calculate_position_size(
    balance: float,
    risk_percent: float,
    sl_distance: float
) -> float:
    """
    Рассчитать размер позиции на основе риска.
    
    Использует фиксированный процент риска от баланса для определения
    оптимального размера позиции с учетом расстояния до stop-loss.
    
    Args:
        balance: Текущий баланс счета в USDT
        risk_percent: Процент риска на сделку (обычно 1.0)
        sl_distance: Расстояние до stop-loss в USDT
        
    Returns:
        float: Размер позиции в единицах базового актива
        
    Raises:
        ValueError: Если sl_distance равен 0
        
    Example:
        >>> calculate_position_size(1000.0, 1.0, 5.0)
        2.0  # Рискуем $10 (1%), SL на $5, позиция 2 единицы
    """
    if sl_distance <= 0:
        raise ValueError("SL distance must be positive")
    
    risk_amount = balance * (risk_percent / 100)
    position_size = risk_amount / sl_distance
    
    return position_size


# ❌ НЕПРАВИЛЬНО

def calc_size(b, r, sl):  # Нет docstring!
    return b * r / sl  # Непонятные имена, нет проверок
```

---

### Комментарии

```python
# ✅ ПРАВИЛЬНО - объясняют ПОЧЕМУ, не ЧТО

# Используем более широкий SL в HIGH VOL режиме, чтобы избежать
# ложных срабатываний из-за повышенного шума рынка
if regime == "HIGH_VOL":
    sl_multiplier = 3.5  # Было 2.5

# Минимум $30 для ордера из-за комиссий OKX (0.1% × 2 = 0.2%)
# При меньшей сумме комиссия съест всю прибыль
MIN_ORDER_VALUE = 30.0


# ❌ НЕПРАВИЛЬНО - очевидные вещи

# Увеличиваем sl_multiplier
sl_multiplier = 3.5  # ❌ Видно и без комментария!

# Устанавливаем минимум
MIN_ORDER_VALUE = 30.0  # ❌ Не объясняет ПОЧЕМУ
```

---

## 🏗️ СТРУКТУРА КОДА

### Порядок элементов в классе:

```python
class ScalpingEngine:
    """
    1. Docstring класса
    """
    
    # 2. Константы класса
    MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 30
    
    # 3. __init__ всегда первым
    def __init__(self, client, config):
        # 3.1 Параметры
        self.client = client
        self.config = config
        
        # 3.2 Состояние
        self.active = True
        self.positions = {}
        
        # 3.3 Инициализация компонентов
        self._init_indicators()
        self._init_modules()
    
    # 4. Публичные методы
    async def run(self): pass
    async def process_tick(self): pass
    def get_positions(self): pass
    
    # 5. Приватные методы (группируем по функциональности)
    # 5.1 Инициализация
    def _init_indicators(self): pass
    def _init_modules(self): pass
    
    # 5.2 Обработка данных
    def _process_tick(self): pass
    def _calculate_indicators(self): pass
    
    # 5.3 Генерация сигналов
    def _generate_signal(self): pass
    def _calculate_score(self): pass
    
    # 5.4 Управление позициями
    def _open_position(self): pass
    def _close_position(self): pass
    
    # 6. Свойства (properties)
    @property
    def is_active(self): return self.active
    
    # 7. Статические/классовые методы в конце
    @staticmethod
    def _validate_price(price): pass
```

---

### Длина функций:

```python
# ✅ ПРАВИЛЬНО - короткие функции (до 50 строк)

def calculate_score(self, indicators):
    """Расчет scoring (короткая функция)"""
    long_score = self._calculate_long_score(indicators)
    short_score = self._calculate_short_score(indicators)
    return long_score, short_score

def _calculate_long_score(self, indicators):
    """Разбили на подфункции"""
    score = 0
    score += self._score_trend(indicators)
    score += self._score_momentum(indicators)
    score += self._score_volume(indicators)
    return score


# ❌ НЕПРАВИЛЬНО - монстр-функция (200+ строк)

def generate_signal(self, indicators):
    """Делает ВСЁ в одной функции"""
    # 200 строк кода...
    # Сложно понять
    # Сложно тестировать
    # Сложно модифицировать
```

**Правило**: Если функция >50 строк → разбить на подфункции!

---

## 🎨 ФОРМАТИРОВАНИЕ

### Импорты:

```python
# ✅ ПРАВИЛЬНО - группировка и сортировка

# 1. Стандартная библиотека
import asyncio
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# 2. Сторонние библиотеки
import numpy as np
from loguru import logger
from pydantic import BaseModel

# 3. Локальные импорты
from src.config import ScalpingConfig
from src.models import Position, Signal
from src.okx_client import OKXClient


# ❌ НЕПРАВИЛЬНО - вперемешку

from src.config import ScalpingConfig
import numpy as np
from datetime import datetime
from loguru import logger
import asyncio
from src.models import Position
```

**Автоматизация**: `isort src/` (автосортировка)

---

### Пробелы и отступы:

```python
# ✅ ПРАВИЛЬНО

# Отступ: 4 пробела (НЕ табы!)
def function():
    if condition:
        do_something()

# Пробелы вокруг операторов
result = value1 + value2
score = base_score * 2

# Нет пробелов внутри скобок
function(arg1, arg2, arg3)
my_list = [1, 2, 3]

# Пробелы после запятых
def func(a, b, c): pass


# ❌ НЕПРАВИЛЬНО

def function():
  if condition:  # ❌ 2 пробела
    do_something()

result=value1+value2  # ❌ Нет пробелов
function( arg1,arg2 )  # ❌ Лишние пробелы
```

**Автоматизация**: `black src/` (автоформат)

---

## 🔍 TYPE HINTS (Аннотации типов)

```python
# ✅ ПРАВИЛЬНО - всегда используем type hints

from typing import Dict, List, Optional, Union

def calculate_score(
    indicators: Dict[str, float],
    config: ScalpingConfig
) -> tuple[float, float]:
    """Возвращает (long_score, short_score)"""
    long_score: float = 0.0
    short_score: float = 0.0
    # ...
    return long_score, short_score

async def get_candles(
    symbol: str,
    timeframe: str = "1m",
    limit: int = 100
) -> List[Candle]:
    """Получить свечи"""
    # ...

class Position:
    symbol: str
    side: PositionSide
    entry_price: float
    quantity: float
    stop_loss: Optional[float] = None  # Может быть None


# ❌ НЕПРАВИЛЬНО - нет type hints

def calculate_score(indicators, config):  # ❌ Нет типов!
    long_score = 0.0
    short_score = 0.0
    return long_score, short_score
```

**Проверка**: `mypy src/` (статическая проверка типов)

---

## 🛡️ ОБРАБОТКА ОШИБОК

### Try-Except блоки:

```python
# ✅ ПРАВИЛЬНО - конкретные исключения

try:
    order = await self.client.place_order(symbol, side, quantity)
except OKXAPIError as e:
    logger.error(f"OKX API error: {e}")
    # Обрабатываем специфично
except NetworkError as e:
    logger.error(f"Network error: {e}")
    await asyncio.sleep(5)  # Ждем и повторяем
except Exception as e:
    logger.critical(f"Unexpected error: {e}")
    raise  # Пробрасываем дальше


# ❌ НЕПРАВИЛЬНО - catch-all

try:
    order = await self.client.place_order(...)
except Exception:  # ❌ Слишком широко!
    pass  # ❌ Молча игнорируем ошибку!
```

---

### Логирование ошибок:

```python
# ✅ ПРАВИЛЬНО - детальное логирование

try:
    result = await self._risky_operation(symbol, quantity)
except ValueError as e:
    logger.error(
        f"Invalid value for {symbol}: {e}\n"
        f"Symbol: {symbol}, Quantity: {quantity}\n"
        f"Stack trace:", exc_info=True
    )
    return None

# ❌ НЕПРАВИЛЬНО

try:
    result = await self._risky_operation(symbol, quantity)
except ValueError:
    logger.error("Error")  # ❌ Не понятно ЧТО и ГДЕ!
    return None
```

---

## 🧪 ТЕСТИРОВАНИЕ

### Каждый модуль должен иметь тесты:

```python
# tests/unit/test_multi_timeframe.py

import pytest
from src.strategies.modules.multi_timeframe import MultiTimeframeFilter

class TestMultiTimeframeFilter:
    """Тесты MTF модуля"""
    
    @pytest.fixture
    def mtf_filter(self):
        """Фикстура для создания фильтра"""
        config = MTFConfig(
            confirmation_timeframe="5m",
            score_bonus=2
        )
        return MultiTimeframeFilter(mock_client, config)
    
    def test_bullish_confirmation(self, mtf_filter):
        """Тест бычьего подтверждения"""
        # Arrange
        mock_candles_5m = create_bullish_candles()
        
        # Act
        result = mtf_filter.check_confirmation("BTC-USDT", "LONG")
        
        # Assert
        assert result.confirmed == True
        assert result.bonus == 2
        assert result.blocked == False
    
    def test_bearish_blocks_long(self, mtf_filter):
        """Тест блокировки LONG при медвежьем тренде"""
        mock_candles_5m = create_bearish_candles()
        
        result = mtf_filter.check_confirmation("BTC-USDT", "LONG")
        
        assert result.confirmed == False
        assert result.blocked == True  # Блокируем!
```

**Требования**:
- ✅ Coverage >80% для каждого модуля
- ✅ Тесты пишутся ВМЕСТЕ с кодом (не потом!)
- ✅ Все публичные методы покрыты тестами
- ✅ Критичные приватные методы тоже

**Запуск**: `pytest tests/ --cov=src --cov-report=html`

---

## 📦 МОДУЛИ И ИМПОРТЫ

### Структура модуля:

```python
"""
Краткое описание модуля.

Более детальное описание что делает модуль,
как его использовать, примеры.
"""

# Импорты (см. выше - группировка)

# Константы модуля
DEFAULT_PERIOD = 14
MAX_VALUE = 100.0

# Классы и функции

# В конце - главный блок (если нужен)
if __name__ == "__main__":
    # Только для отладки модуля
    pass
```

---

### Относительные vs Абсолютные импорты:

```python
# ✅ ПРАВИЛЬНО - абсолютные импорты (предпочтительно)

from src.strategies.modules.multi_timeframe import MultiTimeframeFilter
from src.indicators.base import RSI, MACD
from src.filters.regime_detector import EnhancedRegimeDetector


# ⚠️ ДОПУСТИМО - относительные (внутри пакета)

# В файле src/strategies/modules/correlation_filter.py
from .multi_timeframe import MultiTimeframeFilter  # Соседний модуль
from ..base_strategy import BaseStrategy  # Родительская папка


# ❌ НЕПРАВИЛЬНО - смешивание

from src.strategies.modules.multi_timeframe import MTF  # Абсолютный
from .correlation_filter import CorrelationFilter  # Относительный
# ^ НЕ мешаем в одном файле!
```

---

## 🎯 ASYNC/AWAIT

### Правила асинхронности:

```python
# ✅ ПРАВИЛЬНО

# Функции работающие с I/O - async
async def fetch_candles(symbol: str) -> List[Candle]:
    """Получить свечи (I/O операция)"""
    response = await client.get(...)  # await для async вызовов
    return parse_candles(response)

# Функции вычислений - обычные (НЕ async)
def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Расчет RSI (вычисления, НЕ I/O)"""
    # Чистые вычисления - не нужен async
    gains = ...
    losses = ...
    return rs / (1 + rs) * 100


# ❌ НЕПРАВИЛЬНО

async def calculate_rsi(...):  # ❌ async без I/O!
    # Просто вычисления, зачем async?
    return result

def fetch_candles(...):  # ❌ I/O без async!
    response = client.get(...)  # Блокирующий вызов!
    return response
```

---

### Обработка async ошибок:

```python
# ✅ ПРАВИЛЬНО

async def safe_api_call(self, operation_name: str, coro):
    """Безопасный async вызов с retry"""
    for attempt in range(3):
        try:
            result = await coro
            return result
        except asyncio.TimeoutError:
            logger.warning(f"{operation_name} timeout (attempt {attempt + 1}/3)")
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
        except Exception as e:
            logger.error(f"{operation_name} failed: {e}")
            raise
    
    raise TimeoutError(f"{operation_name} failed after 3 attempts")
```

---

## 🔧 КОНФИГУРАЦИЯ

### Pydantic для валидации:

```python
# ✅ ПРАВИЛЬНО

from pydantic import BaseModel, Field, validator

class ScalpingConfig(BaseModel):
    """Конфигурация скальпинг стратегии"""
    
    # Со значениями по умолчанию и ограничениями
    max_position_size: float = Field(
        default=5.0,
        gt=0,           # Больше 0
        le=10.0,        # Максимум 10%
        description="Максимальный размер позиции в % от баланса"
    )
    
    scoring_threshold: int = Field(
        default=7,
        ge=0,
        le=12,
        description="Минимальный score для входа (из 12)"
    )
    
    @validator('scoring_threshold')
    def validate_threshold(cls, v):
        """Кастомная валидация"""
        if v < 5:
            logger.warning(f"Very low threshold: {v}/12")
        return v


# config.yaml загружается и валидируется

config_dict = yaml.safe_load(open("config.yaml"))
config = ScalpingConfig(**config_dict['scalping'])  # Автовалидация!

# Если некорректно → ValidationError с детальным сообщением
```

---

## 📊 ЛОГИРОВАНИЕ

### Уровни логов:

```python
# DEBUG - детали для отладки
logger.debug(f"MTF check: 5m EMA8={ema8:.2f}, EMA21={ema21:.2f}")

# INFO - важные события
logger.info(f"✅ {symbol} LONG opened @ ${price:.2f}, size: {qty}")

# WARNING - предупреждения (не критично)
logger.warning(f"⚠️ {symbol} Low volume: {volume:.2f} (threshold: {threshold})")

# ERROR - ошибки (восстановимые)
logger.error(f"❌ Failed to place order: {error}")

# CRITICAL - критические ошибки (невосстановимые)
logger.critical(f"🚨 CRITICAL: Borrowed funds detected! Stopping bot.")
```

### Формат сообщений:

```python
# ✅ ПРАВИЛЬНО - структурированные, с контекстом

logger.info(
    f"🎯 SIGNAL: {symbol} {side} | "
    f"Score: {score}/12 ({score/12:.0%}) | "
    f"Price: ${price:,.2f} | "
    f"Confidence: {confidence:.1%}"
)

logger.error(
    f"❌ Order failed: {symbol} {side}\n"
    f"   Reason: {error}\n"
    f"   Details: Qty={qty}, Price=${price:.2f}\n"
    f"   Balance: ${balance:.2f}"
)


# ❌ НЕПРАВИЛЬНО - непонятные

logger.info("Signal")  # ❌ Что за сигнал?
logger.error("Error")  # ❌ Какая ошибка? Где?
```

---

## 🚫 ЧЕГО ИЗБЕГАТЬ

### 1. Магические числа:

```python
# ❌ ПЛОХО

if score >= 7:  # ❌ Откуда 7?
    open_position()

sl_distance = atr * 2.5  # ❌ Откуда 2.5?


# ✅ ХОРОШО

MIN_SCORE_THRESHOLD = 7  # Константа с понятным именем
if score >= MIN_SCORE_THRESHOLD:
    open_position()

SL_ATR_MULTIPLIER = 2.5  # Из конфигурации
sl_distance = atr * self.config.exit.sl_multiplier
```

---

### 2. Глубокая вложенность:

```python
# ❌ ПЛОХО - 5 уровней вложенности

def process(data):
    if data:
        if data.valid:
            if data.price > 0:
                if data.quantity > 0:
                    if data.symbol in allowed:
                        # Логика на 5м уровне!
                        return result


# ✅ ХОРОШО - ранний return

def process(data):
    # Guard clauses
    if not data:
        return None
    if not data.valid:
        return None
    if data.price <= 0:
        return None
    if data.quantity <= 0:
        return None
    if data.symbol not in allowed:
        return None
    
    # Основная логика на 1м уровне!
    return result
```

---

### 3. Мутабельные defaults:

```python
# ❌ ОПАСНО!

def add_position(symbol, positions={}):  # ❌ Мутабельный default!
    positions[symbol] = Position()
    return positions

# Вызов 1: add_position("BTC") → {"BTC": ...}
# Вызов 2: add_position("ETH") → {"BTC": ..., "ETH": ...}  ← УПС!


# ✅ ПРАВИЛЬНО

def add_position(symbol, positions=None):
    if positions is None:
        positions = {}  # Создаем новый каждый раз
    positions[symbol] = Position()
    return positions
```

---

## 📁 ОРГАНИЗАЦИЯ ФАЙЛОВ

### Один класс = один файл (для больших классов):

```python
# ✅ ХОРОШО

src/strategies/scalping_engine.py   # Только ScalpingEngine (1500 строк)
src/strategies/grid_engine.py       # Только GridTradingEngine (800 строк)


# ❌ ПЛОХО

src/strategies/engines.py           # ScalpingEngine + GridEngine (2300 строк!)
```

---

### __init__.py для экспорта:

```python
# src/strategies/modules/__init__.py

"""
Модули улучшений для торговых стратегий.
"""

from .multi_timeframe import MultiTimeframeFilter
from .correlation_filter import CorrelationFilter
from .time_filter import TimeSessionManager

__all__ = [
    "MultiTimeframeFilter",
    "CorrelationFilter",
    "TimeSessionManager",
]

# Использование:
from src.strategies.modules import MultiTimeframeFilter
# Вместо:
# from src.strategies.modules.multi_timeframe import MultiTimeframeFilter
```

---

## 🔄 GIT WORKFLOW

### Commit messages:

```bash
# ✅ ПРАВИЛЬНО - структурированные

git commit -m "feat: add Multi-timeframe confirmation module

- Implemented 5m timeframe checking
- Added EMA8/21 confirmation logic
- Integration with Scoring system (+2 bonus)
- Tests added (85% coverage)

Closes #12"


# ❌ НЕПРАВИЛЬНО

git commit -m "changes"
git commit -m "fix"
git commit -m "asdfasdf"
```

**Формат**:
```
<type>: <короткое описание>

<детали>
<что изменилось>
<зачем>

<ссылки на issues>
```

**Types**:
- `feat:` - новая фича
- `fix:` - баг фикс
- `refactor:` - рефакторинг
- `docs:` - документация
- `test:` - тесты
- `chore:` - рутина (зависимости, конфиг)

---

### Branching strategy:

```bash
# main (master) - стабильная версия
# develop - разработка
# feature/* - новые фичи

# Работа над новым модулем:
git checkout -b feature/multi-timeframe
# ... разработка ...
git commit -m "feat: add MTF module"
git push origin feature/multi-timeframe

# Pull Request → код-ревью → мерж в develop
# Когда develop стабилен → мерж в main
```

---

## ✅ CODE REVIEW CHECKLIST

Перед merge проверяем:

```markdown
## Code Quality
- [ ] Код соответствует PEP 8 (black, flake8 прошли)
- [ ] Type hints везде (mypy прошел)
- [ ] Нет закомментированного кода
- [ ] Нет print() (используем logger)
- [ ] Нет TODO без issue номера

## Documentation
- [ ] Docstrings для всех публичных функций/классов
- [ ] Комментарии объясняют ПОЧЕМУ, не ЧТО
- [ ] README обновлен (если нужно)
- [ ] CHANGELOG обновлен

## Testing
- [ ] Unit тесты написаны
- [ ] Тесты проходят (pytest)
- [ ] Coverage не упал (>80%)
- [ ] Integration тесты (если применимо)

## Functionality
- [ ] Код работает (протестирован локально)
- [ ] Нет регрессий (старая функциональность работает)
- [ ] Feature Flags настроен (можно выключить)
- [ ] Логирование добавлено

## Security
- [ ] Нет hardcoded секретов
- [ ] Input validation (где нужно)
- [ ] Обработка ошибок

## Performance
- [ ] Нет n+1 запросов
- [ ] Нет блокирующих вызовов в async
- [ ] Memory leaks отсутствуют
```

---

## 🎯 PERFORMANCE GUIDELINES

### Эффективность кода:

```python
# ✅ ПРАВИЛЬНО - кэширование

class VolumeProfileAnalyzer:
    def __init__(self):
        self._cache = {}
        self._cache_ttl = 3600  # 1 час
    
    async def get_volume_profile(self, symbol):
        """Получить профиль с кэшированием"""
        # Проверяем кэш
        if symbol in self._cache:
            cached_data, cached_time = self._cache[symbol]
            if time.time() - cached_time < self._cache_ttl:
                return cached_data  # Возвращаем из кэша
        
        # Рассчитываем заново (дорогая операция)
        profile = await self._calculate_profile(symbol)
        self._cache[symbol] = (profile, time.time())
        return profile


# ❌ ПЛОХО - каждый раз пересчитываем

async def get_volume_profile(self, symbol):
    # Каждый раз заново! (медленно)
    return await self._calculate_profile(symbol)
```

---

### Батчинг запросов:

```python
# ✅ ПРАВИЛЬНО - параллельные запросы

async def get_all_balances(self, symbols):
    """Получить балансы параллельно"""
    tasks = [
        self.client.get_balance(symbol)
        for symbol in symbols
    ]
    balances = await asyncio.gather(*tasks)  # Параллельно!
    return dict(zip(symbols, balances))


# ❌ ПЛОХО - последовательно

async def get_all_balances(self, symbols):
    balances = {}
    for symbol in symbols:
        balance = await self.client.get_balance(symbol)  # По одному!
        balances[symbol] = balance
    return balances
```

---

## 📊 КОНСТАНТЫ И МАГИЧЕСКИЕ ЧИСЛА

### Правила:

```python
# ✅ ПРАВИЛЬНО - именованные константы

# В начале файла или класса
MAX_CONSECUTIVE_LOSSES = 3
EXTENDED_COOLDOWN_MINUTES = 15
MIN_ORDER_VALUE_USD = 30.0
COMMISSION_RATE = 0.001  # 0.1%

# Использование
if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
    self.active = False

# ИЛИ в конфигурации
class RiskConfig(BaseModel):
    max_consecutive_losses: int = 3
    extended_cooldown_minutes: int = 15

# Использование
if self.consecutive_losses >= self.config.max_consecutive_losses:
    self.active = False


# ❌ НЕПРАВИЛЬНО

if self.consecutive_losses >= 3:  # ❌ Магическое число!
    self.active = False

await asyncio.sleep(15 * 60)  # ❌ Откуда 15?
```

---

## 🎨 CODE STYLE ПРИМЕРЫ

### Хороший vs Плохой код:

```python
# ❌ ПЛОХОЙ КОД

def calc(d):
    r=0
    if d['rsi']>30 and d['rsi']<70:r+=2
    if d['vol']>1.2:r+=2
    return r


# ✅ ХОРОШИЙ КОД

def calculate_signal_score(indicators: Dict[str, float]) -> int:
    """
    Рассчитать score сигнала на основе индикаторов.
    
    Returns:
        int: Score от 0 до 12
    """
    score = 0
    
    # RSI в нейтральной зоне (+2 балла)
    rsi = indicators.get('rsi', 50)
    if 30 < rsi < 70:
        score += 2
        
    # Объем выше порога (+2 балла)
    volume_ratio = indicators.get('volume_ratio', 1.0)
    if volume_ratio > self.config.entry.volume_threshold:
        score += 2
    
    return score
```

---

## 🔐 БЕЗОПАСНОСТЬ КОДА

### Секреты:

```python
# ✅ ПРАВИЛЬНО

# В .env
OKX_API_KEY=your_key_here

# В коде
import os
api_key = os.getenv("OKX_API_KEY")

# В логах (sanitized)
logger.info(f"API Key: {api_key[:5]}***")  # Показываем только 5 символов


# ❌ НЕПРАВИЛЬНО

API_KEY = "6da89a9a-3aa3-4453-93ca-07629e7074a3"  # ❌ Hardcoded!

logger.info(f"API Key: {api_key}")  # ❌ В логах полностью!
```

---

### Input validation:

```python
# ✅ ПРАВИЛЬНО

def calculate_position_size(balance: float, risk_percent: float) -> float:
    """Расчет с валидацией"""
    
    # Валидация входов
    if balance <= 0:
        raise ValueError(f"Invalid balance: {balance}")
    
    if not 0 < risk_percent <= 5:
        raise ValueError(f"Risk percent must be 0-5%, got {risk_percent}")
    
    # Расчет
    return balance * (risk_percent / 100)


# ❌ ПЛОХО - нет проверок

def calculate_position_size(balance, risk_percent):
    return balance * (risk_percent / 100)  # Что если balance отрицательный?!
```

---

## 📏 МЕТРИКИ КАЧЕСТВА

### Цели проекта:

```
✅ Test Coverage: >80%
✅ Cyclomatic Complexity: <10 на функцию
✅ Maintainability Index: >70
✅ Duplicated Code: <5%
✅ Type Hints Coverage: 100%
✅ Docstring Coverage: 100% для публичных API
```

### Инструменты проверки:

```bash
# Линтеры
black src/                  # Форматирование
isort src/                  # Сортировка импортов
flake8 src/                 # PEP 8 проверка
mypy src/                   # Type checking

# Тесты
pytest tests/ --cov=src --cov-report=html

# Сложность
radon cc src/ -a          # Cyclomatic complexity
radon mi src/             # Maintainability index

# Дубликаты
pylint --disable=all --enable=duplicate-code src/
```

---

## 🎯 ИТОГОВЫЙ CHECKLIST

### Перед каждым коммитом:

```bash
# 1. Форматирование
black src/
isort src/

# 2. Линтинг
flake8 src/

# 3. Type checking
mypy src/

# 4. Тесты
pytest tests/

# 5. Git
git add .
git commit -m "feat: descriptive message"

# Pre-commit hook делает это автоматически!
```

---

**Эти стандарты обеспечивают**:
- ✅ Читаемый код
- ✅ Меньше багов
- ✅ Легкая поддержка
- ✅ Командная работа (даже если вы один!)

**Готов создать PROJECT_RULES.md и DEVELOPMENT_GUIDE.md!** 🚀

