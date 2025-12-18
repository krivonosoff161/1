# ИСПРАВЛЕНИЕ: СИНТАКСИЧЕСКИЕ ОШИБКИ

**Дата:** 2025-12-18  
**Статус:** ✅ ИСПРАВЛЕНИЯ ПРИМЕНЕНЫ

---

## 🔍 НАЙДЕННЫЕ ПРОБЛЕМЫ

### ПРОБЛЕМА #1: IndentationError в `futures_client.py` ✅

**Файл:** `src/clients/futures_client.py` (строка 68)

**Ошибка:**
```python
if not self.session.closed:
await self.session.close()  # ❌ Неправильный отступ
```

**Исправление:**
```python
if not self.session.closed:
    await self.session.close()  # ✅ Правильный отступ
```

---

### ПРОБЛЕМА #2: IndentationError в `private_websocket_manager.py` ✅

**Файл:** `src/strategies/scalping/futures/private_websocket_manager.py` (строка 456)

**Ошибка:**
```python
if not self.session.closed:
await self.session.close()  # ❌ Неправильный отступ
```

**Исправление:**
```python
if not self.session.closed:
    await self.session.close()  # ✅ Правильный отступ
```

---

### ПРОБЛЕМА #3: SyntaxError - await вне async функции ✅

**Файл:** `src/strategies/scalping/futures/signal_generator.py` (строка 3507)

**Ошибка:**
```python
def _detect_impulse_signals(...):  # ❌ Не async функция
    ...
    current_market_price = await self._get_current_market_price(...)  # ❌ await вне async
```

**Исправление:**
```python
async def _detect_impulse_signals(...):  # ✅ Async функция
    ...
    current_market_price = await self._get_current_market_price(...)  # ✅ Правильно
```

**Также исправлен вызов:**
```python
# Было:
impulse_signals = self._detect_impulse_signals(...)

# Стало:
impulse_signals = await self._detect_impulse_signals(...)
```

---

### ПРОБЛЕМА #4: Leverage 3x вместо 5x в сообщениях ✅

**Файлы:** `start.bat`, `scripts_bat/start.bat` (строка 127)

**Ошибка:**
```
- Trading with leverage (3x default)
```

**Исправление:**
```
- Trading with leverage (5x default)
```

---

## ✅ ПРИМЕНЕННЫЕ ИСПРАВЛЕНИЯ

1. ✅ Исправлен отступ в `futures_client.py:close()`
2. ✅ Исправлен отступ в `private_websocket_manager.py:disconnect()`
3. ✅ Добавлен `async` к `_detect_impulse_signals()` в `signal_generator.py`
4. ✅ Добавлен `await` перед вызовом `_detect_impulse_signals()`
5. ✅ Обновлено сообщение о leverage в `start.bat` и `scripts_bat/start.bat`

---

## 📊 РЕЗУЛЬТАТ

**Все синтаксические ошибки исправлены!** ✅

- ✅ Файлы компилируются без ошибок
- ✅ Отступы правильные
- ✅ Все async функции определены правильно
- ✅ Все await используются в правильном контексте

---

**Готово к запуску!** ✅
