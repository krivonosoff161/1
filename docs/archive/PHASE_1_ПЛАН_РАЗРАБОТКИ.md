# 🚀 PHASE 1: ПЛАН РАЗРАБОТКИ

## 🎯 ЦЕЛЬ PHASE 1:
Добавить 6 базовых модулей улучшений, которые повысят качество торговых сигналов и Win Rate с 45% до 65-70%.

---

## 📊 МОДУЛИ PHASE 1:

### 1️⃣ **Multi-Timeframe Confirmation** (MTF) ⭐
- **Приоритет**: ВЫСОКИЙ
- **Сложность**: СРЕДНЯЯ
- **Время**: 3-4 дня
- **Ожидаемый эффект**: +15-20% Win Rate

### 2️⃣ **Correlation Filter**
- **Приоритет**: ВЫСОКИЙ
- **Сложность**: СРЕДНЯЯ
- **Время**: 2-3 дня
- **Ожидаемый эффект**: Фильтрация 20-30% ложных сигналов

### 3️⃣ **Time-Based Filter** (улучшенные сессии)
- **Приоритет**: СРЕДНИЙ
- **Сложность**: НИЗКАЯ
- **Время**: 1-2 дня
- **Ожидаемый эффект**: +5-10% Win Rate

### 4️⃣ **Volatility Modes** (использование детекции режима)
- **Приоритет**: ВЫСОКИЙ
- **Сложность**: СРЕДНЯЯ
- **Время**: 2-3 дня
- **Ожидаемый эффект**: Адаптация к рынку, +10% Win Rate

### 5️⃣ **Pivot Points**
- **Приоритет**: СРЕДНИЙ
- **Сложность**: НИЗКАЯ
- **Время**: 1-2 дня
- **Ожидаемый эффект**: +5% Win Rate (уровни S/R)

### 6️⃣ **Volume Profile**
- **Приоритет**: СРЕДНИЙ
- **Сложность**: ВЫСОКАЯ
- **Время**: 3-4 дня
- **Ожидаемый эффект**: +10-15% Win Rate

---

## 🗓️ ГРАФИК РАЗРАБОТКИ (14-18 дней):

### **НЕДЕЛЯ 1: MTF + Correlation (КРИТИЧНЫЕ)**

#### День 1-2: Multi-Timeframe Confirmation
```
✅ Создание модуля
✅ Интеграция в скальпинг
✅ Тесты
✅ Backtest на исторических данных
```

#### День 3-4: Correlation Filter
```
✅ Создание корреляционного менеджера
✅ Фильтр для 3 пар
✅ Тесты
✅ Интеграция
```

#### День 5: Тестирование недели на DEMO
```
✅ Запуск бота с MTF + Correlation
✅ Мониторинг 24 часа
✅ Анализ результатов
```

---

### **НЕДЕЛЯ 2: Time + Volatility + Pivot (БАЗОВЫЕ)**

#### День 6-7: Time-Based Filter
```
✅ Умные торговые сессии
✅ Фильтрация низколиквидных часов
✅ Интеграция
```

#### День 8-9: Volatility Modes
```
✅ 3 режима (LOW/NORMAL/HIGH VOL)
✅ Адаптация параметров
✅ Интеграция с детекцией режима
```

#### День 10-11: Pivot Points
```
✅ Расчет классических Pivots
✅ Фильтр по уровням
✅ Интеграция
```

#### День 12: Тестирование недели на DEMO
```
✅ Все 5 модулей включены
✅ Мониторинг 24-48 часов
✅ Анализ
```

---

### **НЕДЕЛЯ 3: Volume Profile + ФИНАЛ**

#### День 13-15: Volume Profile
```
✅ Расчет профиля объема
✅ Определение POC, VAH, VAL
✅ Фильтр по зонам
✅ Интеграция
```

#### День 16-17: Финальное тестирование
```
✅ ВСЕ 6 модулей включены
✅ Backtest на 1 месяц данных
✅ DEMO торговля 48 часов
✅ Сравнение с базовой версией
```

#### День 18: Деплой в production
```
✅ Финальные правки
✅ Документация обновлена
✅ Commit + Push на GitHub
✅ Запуск на реальном demo
```

---

## 📝 ДЕТАЛЬНЫЙ ПЛАН: МОДУЛЬ 1 (MTF)

### **Что будем делать:**

#### 1. Создать файл `src/strategies/modules/multi_timeframe.py`

```python
"""
Multi-Timeframe Confirmation Module

Проверяет подтверждение сигнала на старшем таймфрейме (5m).
Если 1m показывает LONG, проверяем что 5m тоже бычий.
"""

from typing import Dict, Optional
from pydantic import BaseModel
from src.okx_client import OKXClient

class MTFConfig(BaseModel):
    """Конфигурация MTF модуля"""
    confirmation_timeframe: str = "5m"  # Таймфрейм для подтверждения
    score_bonus: int = 2                # Бонус к score
    block_opposite: bool = True         # Блокировать противоположные

class MTFResult(BaseModel):
    """Результат MTF проверки"""
    confirmed: bool
    blocked: bool
    bonus: int
    reason: str

class MultiTimeframeFilter:
    """MTF фильтр"""
    
    def __init__(self, client: OKXClient, config: MTFConfig):
        self.client = client
        self.config = config
        self._cache = {}  # Кэш свечей
        
    async def check_confirmation(
        self, 
        symbol: str, 
        signal_side: str  # "LONG" or "SHORT"
    ) -> MTFResult:
        """
        Проверить подтверждение сигнала на 5m.
        
        Logic:
        1. Получить последние свечи 5m
        2. Рассчитать EMA8 и EMA21
        3. Проверить направление тренда
        4. Вернуть результат
        """
        # TODO: Реализация
        pass
```

#### 2. Интегрировать в `src/strategies/scalping.py`

```python
# В __init__:
from src.strategies.modules.multi_timeframe import MultiTimeframeFilter

self.mtf_filter = None
if self.config.get("multi_timeframe_enabled"):
    self.mtf_filter = MultiTimeframeFilter(...)

# В _generate_signal (после scoring):
if self.mtf_filter:
    mtf_result = await self.mtf_filter.check_confirmation(symbol, "LONG")
    if mtf_result.blocked:
        logger.info(f"MTF blocked: {mtf_result.reason}")
        return None
    if mtf_result.confirmed:
        long_score += mtf_result.bonus
```

#### 3. Добавить в `config.yaml`

```yaml
scalping:
  # ... existing config
  
  # Multi-Timeframe Confirmation
  multi_timeframe_enabled: false  # Включим после тестов
  multi_timeframe:
    confirmation_timeframe: "5m"
    score_bonus: 2
    block_opposite: true
```

#### 4. Создать тесты `tests/unit/test_multi_timeframe.py`

```python
import pytest
from src.strategies.modules.multi_timeframe import MultiTimeframeFilter

class TestMultiTimeframe:
    def test_bullish_confirmation(self):
        """Тест бычьего подтверждения"""
        # Arrange: создаем бычьи свечи 5m
        # Act: проверяем LONG
        # Assert: confirmed=True, bonus=2
        pass
        
    def test_bearish_blocks_long(self):
        """Медвежий 5m блокирует LONG на 1m"""
        # Arrange: медвежьи свечи 5m
        # Act: проверяем LONG
        # Assert: blocked=True
        pass
```

---

## 🔧 ТЕХНИЧЕСКИЕ ДЕТАЛИ:

### **Порядок работы над каждым модулем:**

```
1. СОЗДАНИЕ
   ├── Написать модуль (src/strategies/modules/xxx.py)
   ├── Добавить конфигурацию (config.yaml)
   └── Обновить features.yaml (оставить false)

2. ИНТЕГРАЦИЯ
   ├── Импортировать в scalping.py
   ├── Инициализировать в __init__
   └── Вызвать в _generate_signal

3. ТЕСТИРОВАНИЕ
   ├── Unit тесты (tests/unit/test_xxx.py)
   ├── Pytest (coverage >80%)
   └── Исправить баги

4. BACKTEST
   ├── Запустить на исторических данных
   ├── Сравнить метрики (Win Rate, PnL)
   └── Оптимизировать параметры

5. DEMO
   ├── Включить в features.yaml
   ├── Запустить бот на 24-48 часов
   ├── Мониторить логи
   └── Анализ результатов

6. COMMIT
   ├── git add .
   ├── git commit -m "feat: add XXX module"
   └── git push
```

---

## 📊 КРИТЕРИИ УСПЕХА PHASE 1:

### **Метрики "До" (текущие):**
```
Win Rate: ~45%
Avg Win: +1.5%
Avg Loss: -2.5%
Profit Factor: ~0.9
Total Trades: ~50/день
```

### **Метрики "После" (цель):**
```
Win Rate: 65-70%          ← +20-25%
Avg Win: +1.2%            ← Меньше, но чаще
Avg Loss: -2.0%           ← Меньше потери
Profit Factor: 1.5-2.0    ← Прибыльно!
Total Trades: ~30/день    ← Меньше, но качественнее
```

### **Требования:**
- ✅ Все 6 модулей реализованы
- ✅ Тесты написаны (coverage >80%)
- ✅ Backtest показывает улучшение
- ✅ Demo торговля 48 часов успешна
- ✅ Документация обновлена
- ✅ Код соответствует CODING_STANDARDS.md

---

## 🚨 ВАЖНО: БЕЗОПАСНОСТЬ

### **Feature Flags:**
```yaml
# Все модули ВЫКЛЮЧЕНЫ по умолчанию
multi_timeframe_enabled: false
correlation_filter_enabled: false
# ...

# Включаем ТОЛЬКО после:
# 1. Unit тесты прошли
# 2. Backtest показал улучшение
# 3. Код проверен
```

### **Постепенное включение:**
```
Day 1-2:   Разработка MTF
Day 3:     MTF тесты + backtest
Day 4:     MTF на DEMO (multi_timeframe_enabled: true)
Day 5:     Анализ, если ОК → оставляем
Day 6-7:   Correlation (MTF уже включен)
...
```

---

## 🎯 НАЧИНАЕМ С МОДУЛЯ 1: MTF

### **Сейчас сделаем:**

#### ✅ Шаг 1: Создать базовый модуль MTF
```python
src/strategies/modules/multi_timeframe.py
```

#### ✅ Шаг 2: Добавить конфигурацию
```yaml
config.yaml → scalping.multi_timeframe
```

#### ✅ Шаг 3: Интегрировать в scalping.py
```python
Импорт, инициализация, использование
```

#### ✅ Шаг 4: Написать тесты
```python
tests/unit/test_multi_timeframe.py
```

#### ✅ Шаг 5: Запустить тесты
```bash
pytest tests/unit/test_multi_timeframe.py -v
```

---

## 📚 ССЫЛКИ НА ДОКУМЕНТАЦИЮ:

- **Архитектура**: `docs/current/АРХИТЕКТУРА_ГИБРИДНОГО_ПРОЕКТА.md`
- **Детали модулей**: `docs/current/ДЕТАЛЬНОЕ_ОПИСАНИЕ_МОДУЛЕЙ.md`
- **Стандарты кода**: `CODING_STANDARDS.md`
- **Правила проекта**: `PROJECT_RULES.md`

---

## ✅ ГОТОВЫ НАЧАТЬ?

**Модуль 1**: Multi-Timeframe Confirmation  
**Время**: 3-4 дня  
**Файлы**:
1. `src/strategies/modules/multi_timeframe.py`
2. `tests/unit/test_multi_timeframe.py`
3. Обновления в `config.yaml` и `scalping.py`

**Начинаем?** 🚀

