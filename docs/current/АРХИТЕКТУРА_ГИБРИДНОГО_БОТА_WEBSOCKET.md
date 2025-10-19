# 🔬 АРХИТЕКТУРА ГИБРИДНОГО БОТА (WebSocket + REST)

**Дата:** 19 октября 2025  
**Статус:** 🚧 ПЛАНИРОВАНИЕ (НЕ РЕАЛИЗОВАНО!)  
**Цель:** Детальный план интеграции WebSocket для максимальной скорости

---

## 🎯 ЗАЧЕМ НУЖЕН ГИБРИД?

### Проблема сейчас (только REST):
```
❌ Проверка PH раз в 5 секунд
❌ PH не успевает сработать (OCO быстрее)
❌ Win Rate: 39% (60% сделок по SL!)
❌ Пропускаем быстрые движения цены
```

### С гибридом (REST + WebSocket):
```
✅ Проверка PH каждую секунду (WebSocket)
✅ PH срабатывает ДО OCO
✅ Win Rate: 60-70% (ловим быструю прибыль)
✅ Больше сделок (быстрее закрываем → быстрее открываем новые)
```

---

## 📊 РАЗДЕЛЕНИЕ ОТВЕТСТВЕННОСТИ

### 🔵 **REST API (Анализ и Сигналы)** - раз в 5 сек

| Модуль | Зачем REST | Частота |
|--------|-----------|---------|
| **Свечи** | Нужны OHLCV для индикаторов | 5 сек |
| **Индикаторы** | RSI, MACD, ATR, BB - рассчитываются по свечам | 5 сек |
| **ARM** | Определение режима (нужны свечи + ATR) | 5 сек |
| **ADX Filter** | Нужны +DI, -DI (рассчитываются по свечам) | 5 сек |
| **MTF Filter** | Нужны свечи 15m | 5 сек |
| **Correlation** | Нужны свечи для корреляции | 5 сек |
| **Volume Profile** | Нужны свечи 1H с volume | 5 сек |
| **Pivot Points** | Нужны daily свечи (H, L, C) | 5 сек |
| **SignalGenerator** | Генерация сигналов (нужны индикаторы) | 5 сек |
| **OrderExecutor** | Размещение ордеров (BUY/SELL, OCO) | По сигналу |

**ВЫВОД:** Всё что связано с **ОТКРЫТИЕМ** позиций → REST!

---

### 🟢 **WebSocket (Мониторинг)** - постоянно (1-2 раз/сек)

| Модуль | Зачем WebSocket | Частота |
|--------|----------------|---------|
| **Текущая цена** | Реал-тайм для PnL | Каждую 1 сек |
| **PH проверка** | Быстрая фиксация прибыли | При каждой цене |
| **OCO статус** | Узнать если OCO сработал | Раз в 5 сек (REST!) |

**ВЫВОД:** Всё что связано с **ЗАКРЫТИЕМ** при PH → WebSocket!

---

## 🏗️ АРХИТЕКТУРА ГИБРИДНОГО БОТА

```
┌─────────────────────────────────────────────────────────────────┐
│                    SCALPING ORCHESTRATOR                        │
│                                                                 │
│  ┌───────────────────┐         ┌──────────────────────────┐   │
│  │   REST ПОТОК      │         │    WebSocket ПОТОК        │   │
│  │   (Сигналы)       │         │    (Мониторинг)           │   │
│  └───────────────────┘         └──────────────────────────┘   │
│           │                               │                    │
│           ▼                               ▼                    │
│  ┌───────────────────┐         ┌──────────────────────────┐   │
│  │ Каждые 5 сек:     │         │ Постоянно (1-2 раз/сек): │   │
│  │                   │         │                          │   │
│  │ 1. Get candles    │         │ 1. Listen WS prices      │   │
│  │ 2. Calc indicators│         │ 2. Update LIVE_PRICES    │   │
│  │ 3. ARM regime     │         │ 3. For each position:    │   │
│  │ 4. Generate signal│         │    - Calc PnL            │   │
│  │ 5. Open position  │         │    - Check PH            │   │
│  │    + OCO          │         │    - Close if triggered  │   │
│  └───────────────────┘         └──────────────────────────┘   │
│           │                               │                    │
│           └───────────┬───────────────────┘                    │
│                       ▼                                        │
│            ┌──────────────────────┐                           │
│            │   SHARED STATE:      │                           │
│            │  - open_positions    │                           │
│            │  - LIVE_PRICES (WS)  │                           │
│            │  - market_data (REST)│                           │
│            └──────────────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 РЕАЛИЗАЦИЯ

### Файловая структура:

```
src/
├── utils/
│   ├── websocket_manager.py  🆕 WebSocket менеджер
│   └── shared_state.py       🆕 Общее состояние (цены, позиции)
│
├── strategies/scalping/
│   ├── orchestrator.py       ✏️ ИЗМЕНИТЬ: добавить WS поток
│   ├── position_manager.py   ✏️ ИЗМЕНИТЬ: использовать LIVE_PRICES
│   ├── signal_generator.py   ⚪ БЕЗ ИЗМЕНЕНИЙ
│   └── order_executor.py     ⚪ БЕЗ ИЗМЕНЕНИЙ
```

---

## ⚠️ ПОТЕНЦИАЛЬНЫЕ КОНФЛИКТЫ

### 1. **RACE CONDITIONS** (Два потока!)

**Проблема:**
```python
# REST поток:
position_manager.open_position(symbol)  # Добавляет в open_positions

# WebSocket поток (одновременно!):
position_manager.check_ph(symbol)  # Читает open_positions

→ КОНФЛИКТ! Может быть неконсистентное состояние!
```

**Решение:**
```python
import asyncio

# Используем asyncio.Lock для синхронизации
positions_lock = asyncio.Lock()

# REST:
async with positions_lock:
    open_positions[symbol] = position

# WebSocket:
async with positions_lock:
    position = open_positions.get(symbol)
```

---

### 2. **ARM ПЕРЕКЛЮЧЕНИЕ РЕЖИМОВ**

**Проблема:**
```
REST поток меняет ARM режим каждые 5 сек
→ Параметры PH меняются (threshold, time_limit)
→ WebSocket использует старые параметры!
```

**Решение:**
```python
# ARM параметры тоже в shared_state
class SharedState:
    live_prices: Dict[str, float]
    open_positions: Dict[str, Position]
    current_arm_params: Dict  # 🆕 Текущие параметры ARM
    
# REST обновляет:
shared_state.current_arm_params = arm.get_current_params()

# WebSocket читает:
ph_threshold = shared_state.current_arm_params['ph_threshold']
```

---

### 3. **ЦЕНА ИЗ РАЗНЫХ ИСТОЧНИКОВ**

**Проблема:**
```
REST получает цену: $3900.00 (из ticker)
WS получает цену:  $3900.50 (реал-тайм)

Какую использовать для сигнала?
```

**Решение:**
```python
# SignalGenerator ВСЕГДА использует LIVE цену из WS!
def generate_signal(candles, indicators):
    # Текущая цена ИЗ WEBSOCKET
    current_price = shared_state.live_prices[symbol]
    
    # Если WS еще не обновился (первый запуск)
    if not current_price:
        current_price = candles[-1].close  # Fallback
```

---

### 4. **ЗАКРЫТИЕ ПОЗИЦИИ ДВАЖДЫ**

**Проблема:**
```
00:05:00 WS: PH triggered → начинаем закрывать
00:05:00 OCO: TP сработал → биржа закрывает

→ Попытка закрыть дважды!
```

**Решение:**
```python
# Флаг "closing_in_progress"
async def close_position(symbol, reason):
    async with positions_lock:
        position = open_positions.get(symbol)
        
        if not position:
            return  # Уже закрыта
        
        if position.closing_in_progress:
            return  # Уже закрываем
        
        position.closing_in_progress = True
    
    # Закрываем
    await place_market_order(...)
    await cancel_oco(...)
    
    async with positions_lock:
        del open_positions[symbol]
```

---

### 5. **ОБНОВЛЕНИЕ ПАРАМЕТРОВ МОДУЛЕЙ**

**Проблема:**
```
REST поток обновляет параметры ADX:
signal_generator.update_regime_parameters(regime)

WebSocket в это время читает старые параметры!
```

**Решение:**
```python
# Параметры модулей тоже в shared_state (атомарное обновление)
class SharedState:
    module_params: Dict  # Параметры всех модулей
    
# REST:
shared_state.module_params = signal_generator.module_params

# WebSocket не читает module_params - только PH параметры!
```

---

## 📝 ПОШАГОВЫЙ ПЛАН РЕАЛИЗАЦИИ

### **ЭТАП 1: ПОДГОТОВКА** (НЕ ТРОГАЕМ РАБОЧИЙ БОТ!)

1. ✅ Создать `src/utils/websocket_manager.py` (отдельный класс)
2. ✅ Создать `src/utils/shared_state.py` (общее состояние)
3. ✅ Протестировать WS подключение отдельно
4. ✅ Протестировать получение цен

---

### **ЭТАП 2: ИНТЕГРАЦИЯ В ТЕСТОВОЙ ВЕТКЕ**

5. Создать `src/strategies/scalping/orchestrator_hybrid.py` (копия!)
6. Добавить WebSocket поток в `run()`
7. Протестировать параллельную работу потоков
8. Убедиться что нет race conditions

---

### **ЭТАП 3: ТЕСТИРОВАНИЕ**

9. Запустить гибридный бот на 1 час
10. Проверить:
    - ✅ Сигналы генерируются правильно
    - ✅ PH срабатывает быстрее OCO
    - ✅ Нет конфликтов при закрытии
    - ✅ ARM корректно переключается
    - ✅ Параметры обновляются без ошибок

---

### **ЭТАП 4: ПЕРЕХОД**

11. Если тесты OK → переносим в основной бот
12. Иначе → остаёмся на REST!

---

## 🤔 АЛЬТЕРНАТИВНЫЙ ВАРИАНТ (ПРОЩЕ!)

### **HYBRID-LITE: WebSocket ТОЛЬКО для PH**

Вместо двух потоков, добавить WebSocket **ВНУТРИ** текущего цикла:

```python
# В orchestrator.py

async def run(self):
    # 1. Запускаем WebSocket listener в фоне
    ws_task = asyncio.create_task(self._ws_ph_monitor())
    
    # 2. Основной REST цикл (как сейчас!)
    while True:
        for symbol in self.symbols:
            await self._process_symbol(symbol)  # Без изменений!
        
        await asyncio.sleep(5)

async def _ws_ph_monitor(self):
    """ТОЛЬКО для PH - не трогает сигналы!"""
    ws = WebSocketManager()
    await ws.connect()
    
    async for symbol, price in ws.listen():
        # ТОЛЬКО проверяем PH
        if symbol in self.position_manager.open_positions:
            await self.position_manager.check_and_close_ph(symbol, price)
```

**ПЛЮСЫ:**
- ✅ Минимальные изменения (1 новый метод)
- ✅ Нет конфликтов с ARM/сигналами
- ✅ PH становится быстрым
- ✅ Все модули работают БЕЗ ИЗМЕНЕНИЙ

**МИНУСЫ:**
- ⚠️ Сигналы всё еще раз в 5 сек (но это OK!)

---

## 📋 ТАБЛИЦА: ЧТО КУДА?

| Компонент | REST | WebSocket | Зачем |
|-----------|------|-----------|-------|
| **Получение свечей** | ✅ | ❌ | WS не даёт OHLCV |
| **Расчёт индикаторов** | ✅ | ❌ | Нужны свечи |
| **ARM режимы** | ✅ | ❌ | Нужны индикаторы |
| **ADX Filter** | ✅ | ❌ | Нужны свечи для +DI/-DI |
| **MTF Filter** | ✅ | ❌ | Нужны свечи 15m |
| **Correlation** | ✅ | ❌ | Нужны исторические свечи |
| **Volume Profile** | ✅ | ❌ | Нужны свечи 1H |
| **Pivot Points** | ✅ | ❌ | Нужны daily свечи |
| **Balance Checker** | ✅ | ❌ | Проверка раз в цикл OK |
| **SignalGenerator** | ✅ | ❌ | Нужны индикаторы |
| **OrderExecutor (open)** | ✅ | ❌ | Открытие по сигналу |
| **Текущая цена** | ❌ | ✅ | WS быстрее! |
| **PH проверка** | ❌ | ✅ | Нужна скорость! |
| **PH закрытие** | ❌ | ✅ | Мгновенно! |
| **OCO отмена** | ❌ | ✅ | При PH закрытии |

---

## 🚨 КРИТИЧЕСКИЕ ВОПРОСЫ (НУЖНО РЕШИТЬ!)

### **1. КАК ARM ОБНОВЛЯЕТ ПАРАМЕТРЫ?**

**Сейчас:**
```python
# Раз в 5 сек (REST)
regime = arm.detect_regime(candles, indicators)
signal_generator.update_regime_parameters(regime)
```

**С гибридом:**
```
REST обновляет параметры → shared_state
WebSocket читает из shared_state

НО! Нужна синхронизация чтобы WS не читал в момент обновления!
```

**Решение:**
```python
import asyncio

class SharedState:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._arm_params = {}
    
    async def update_arm_params(self, params):
        async with self._lock:
            self._arm_params = params
    
    async def get_arm_params(self):
        async with self._lock:
            return self._arm_params.copy()
```

---

### **2. МОЖНО ЛИ ГЕНЕРИРОВАТЬ СИГНАЛЫ ЧАЩЕ?**

**Вопрос:** Если WS даёт цену каждую секунду, может генерировать сигналы чаще?

**Ответ:** ❌ НЕТ!

**Почему:**
- Индикаторы (RSI, MACD) рассчитываются по **ЗАКРЫТЫМ свечам**
- Свеча 5m закрывается раз в 5 минут
- Если проверять каждую секунду → **те же индикаторы!**
- **Бесполезно!**

**Исключение:**
- Можно использовать **текущую цену из WS** для финальной проверки
- Но индикаторы всё равно обновляются раз в 5 мин

---

### **3. КАК ИЗБЕЖАТЬ ДВОЙНОГО ЗАКРЫТИЯ?**

**Сценарий:**
```
WS: PH triggered → начинаем закрывать (async!)
OCO: В это же время TP сработал на бирже!

→ Две попытки закрыть одну позицию!
```

**Решение 1:** Флаг `closing_in_progress` ✅

**Решение 2:** Перед закрытием проверить статус на бирже:
```python
async def close_for_ph(symbol):
    # Проверяем не закрыта ли уже
    fills = await client.get_recent_fills(symbol)
    
    if position закрыта fills:
        # OCO уже сработал!
        remove_from_open_positions(symbol)
        return
    
    # Закрываем сами
    await place_market_order(...)
```

---

### **4. ЧТО С КОМИССИЯМИ?**

**Проблема из теста:**
```
Gross PnL: $0.0368
Fee:       $0.1400
Net PnL:   -$0.1032  ❌
```

**ДВА ПУТИ:**

**А) Увеличить PH порог:**
```yaml
ph_threshold: 0.20  # Покрывает комиссию $0.14
```
→ Но тогда PH редко срабатывает!

**Б) Увеличить размер позиции:**
```yaml
min_order_value: 150  # Вместо $70

Тогда:
  Gross PnL: $0.10 (при том же % движения)
  Fee: $0.30
  
  Но если движение больше:
    Gross: $0.40
    Fee: $0.30
    Net: $0.10 ✅
```

**Вопрос:** Какой путь выбрать?

---

## 💡 МОИ РЕКОМЕНДАЦИИ

### **ВАРИАНТ 1: HYBRID-LITE** ✅ Рекомендую!

```
✅ Добавляем ТОЛЬКО WebSocket для PH
✅ ВСЁ остальное без изменений
✅ Минимальный риск багов
✅ Можем откатить за 5 минут
```

**Изменения:**
- 1 новый файл: `websocket_manager.py`
- 1 новый метод в `orchestrator.py`
- 1 изменение в `position_manager.py`

**Время:** 2-3 часа работы + тесты

---

### **ВАРИАНТ 2: FULL HYBRID** ⚠️ Рискованно!

```
⚠️ Переделываем всю архитектуру
⚠️ Два параллельных потока
⚠️ Shared state с lock'ами
⚠️ Много мест для багов
```

**Изменения:**
- 3 новых файла
- Изменения в 5+ файлах
- Полная переработка `orchestrator.py`

**Время:** 1-2 дня работы + неделя тестов!

---

## 🎯 ПЛАН ДЕЙСТВИЙ

### **СЕГОДНЯ:**

1. ✅ **ИСПРАВИТЬ ADX** (di_difference=1.5) - **УЖЕ СДЕЛАНО!**
2. ✅ **Почистить кэш:**
   ```bash
   Get-ChildItem -Path src -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
   ```
3. ✅ **Запустить бота** с исправленным ADX
4. ✅ **Мониторить** - сигналов должно быть больше!

---

### **ЗАВТРА (если ADX работает):**

5. ⚡ Реализовать **HYBRID-LITE**
6. ⚡ Протестировать на demo
7. ⚡ Если OK → включить в основной бот!

---

## ❓ ВОПРОСЫ К ТЕБЕ:

1. **Запускаем сначала текущий бот с ADX=1.5?** (рекомендую!)
2. **Или сразу делаем HYBRID-LITE?** (рискованно без проверки ADX)
3. **Какой размер позиции?** $70 или $150? (для комиссий)

---

**ЧТО ВЫБИРАЕМ?** 🤔💪
