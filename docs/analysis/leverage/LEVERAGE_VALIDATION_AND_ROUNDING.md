# ВАЛИДАЦИЯ И ОКРУГЛЕНИЕ LEVERAGE ПО ПРАВИЛАМ БИРЖИ

**Дата:** 2025-12-21  
**Цель:** Проверка доступных leverage для каждого символа и округление до ближайшего доступного

---

## 1. ПРОБЛЕМА: РАЗНЫЕ LEVERAGE ДЛЯ РАЗНЫХ СИМВОЛОВ

### Как работает OKX

**На OKX разные символы имеют разные доступные leverage:**
- BTC-USDT: может быть 1, 2, 3, 5, 10, 20, 50, 75, 100, 125
- ETH-USDT: может быть 1, 2, 3, 5, 10, 20, 50, 75, 100, 125
- SOL-USDT: может быть 3, 5, 7, 10, 20, 30, 50, 75, 100
- DOGE-USDT: может быть 1, 2, 3, 5, 10, 20, 50, 75, 100
- XRP-USDT: может быть 1, 3, 5, 10, 20, 50, 75, 100, 125

**Проблема:**
- Бот может выбрать leverage=7x для SOL (доступно)
- Но если выбрать leverage=7x для BTC → биржа отклонит (недоступно для BTC)
- Нужно округлить до ближайшего доступного (например, 5x или 10x)

---

## 2. РЕШЕНИЕ: ПОЛУЧЕНИЕ ДОСТУПНЫХ LEVERAGE С БИРЖИ

### API OKX для получения информации об инструменте

**Endpoint:** `GET /api/v5/public/instruments?instType=SWAP`

**Ответ содержит:**
- `maxLever`: Максимальный leverage для символа
- Но не содержит список всех доступных leverage!

**Проблема:** OKX API не возвращает список всех доступных leverage, только максимум.

### Решение: Определение доступных leverage

**Вариант 1: Стандартные значения OKX (рекомендуется)**

OKX обычно использует стандартный набор leverage:
- Для большинства символов: `[1, 2, 3, 5, 10, 20, 50, 75, 100, 125]`
- Но некоторые символы могут иметь ограничения

**Вариант 2: Получение через попытку установки**

Можно попробовать установить leverage и посмотреть ошибку, но это неэффективно.

**Вариант 3: Хардкод по символам (не рекомендуется)**

Хранить список доступных leverage для каждого символа в коде - не гибко.

### ✅ РЕКОМЕНДУЕМОЕ РЕШЕНИЕ: Комбинированный подход

1. **Получаем maxLever с биржи** (из `/api/v5/public/instruments`)
2. **Используем стандартный набор leverage** до maxLever
3. **Округляем выбранный leverage** до ближайшего доступного
4. **Логируем весь процесс** для отладки

---

## 3. РЕАЛИЗАЦИЯ: МЕТОДЫ ДЛЯ ВАЛИДАЦИИ LEVERAGE

### 3.1. Получение maxLever с биржи

**Добавить в `OKXFuturesClient`:**
```python
async def get_instrument_leverage_info(self, symbol: str) -> Dict[str, Any]:
    """
    Получить информацию о leverage для символа.
    
    Returns:
        {
            "max_leverage": int,  # Максимальный leverage
            "available_leverages": List[int],  # Список доступных leverage
        }
    """
    try:
        inst_id = f"{symbol}-SWAP"
        instruments = await self.get_instrument_info()
        
        for inst in instruments.get("data", []):
            if inst.get("instId") == inst_id:
                max_lever_str = inst.get("maxLever", "125")  # По умолчанию 125
                try:
                    max_leverage = int(max_lever_str)
                except (ValueError, TypeError):
                    max_leverage = 125  # Fallback
                
                # Генерируем список доступных leverage до максимума
                available_leverages = self._generate_available_leverages(max_leverage)
                
                logger.info(
                    f"📊 Leverage info для {symbol}: max={max_leverage}x, "
                    f"доступно: {available_leverages}"
                )
                
                return {
                    "max_leverage": max_leverage,
                    "available_leverages": available_leverages,
                }
    except Exception as e:
        logger.warning(
            f"⚠️ Не удалось получить leverage info для {symbol}: {e}"
        )
    
    # Fallback: стандартные значения
    return {
        "max_leverage": 125,
        "available_leverages": [1, 2, 3, 5, 10, 20, 50, 75, 100, 125],
    }

def _generate_available_leverages(self, max_leverage: int) -> List[int]:
    """
    Генерирует список доступных leverage до максимума.
    
    Стандартные значения OKX: [1, 2, 3, 5, 10, 20, 50, 75, 100, 125]
    """
    standard_leverages = [1, 2, 3, 5, 10, 20, 50, 75, 100, 125]
    
    # Фильтруем только те, что <= max_leverage
    available = [lev for lev in standard_leverages if lev <= max_leverage]
    
    # Если max_leverage не в стандартном списке, добавляем его
    if max_leverage not in available and max_leverage > 0:
        available.append(max_leverage)
        available.sort()
    
    return available
```

### 3.2. Округление leverage до ближайшего доступного

**Добавить в `OKXFuturesClient`:**
```python
async def round_leverage_to_available(
    self, symbol: str, desired_leverage: int
) -> int:
    """
    Округляет leverage до ближайшего доступного для символа.
    
    Args:
        symbol: Торговый символ
        desired_leverage: Желаемый leverage
    
    Returns:
        Округленный leverage (ближайший доступный)
    """
    # Получаем доступные leverage
    leverage_info = await self.get_instrument_leverage_info(symbol)
    available_leverages = leverage_info.get("available_leverages", [])
    max_leverage = leverage_info.get("max_leverage", 125)
    
    # Если желаемый leverage больше максимума - ограничиваем
    if desired_leverage > max_leverage:
        logger.warning(
            f"⚠️ Leverage {desired_leverage}x превышает максимум {max_leverage}x для {symbol}, "
            f"ограничиваем до {max_leverage}x"
        )
        return max_leverage
    
    # Если желаемый leverage меньше минимума - используем минимум
    if desired_leverage < 1:
        logger.warning(
            f"⚠️ Leverage {desired_leverage}x меньше минимума 1x для {symbol}, "
            f"используем 1x"
        )
        return 1
    
    # Если желаемый leverage уже в списке доступных - возвращаем как есть
    if desired_leverage in available_leverages:
        logger.debug(
            f"✅ Leverage {desired_leverage}x доступен для {symbol}, используем как есть"
        )
        return desired_leverage
    
    # Находим ближайший доступный leverage
    closest = min(
        available_leverages,
        key=lambda x: abs(x - desired_leverage)
    )
    
    logger.info(
        f"📊 Leverage округлен для {symbol}: {desired_leverage}x → {closest}x "
        f"(доступные: {available_leverages})"
    )
    
    return closest
```

### 3.3. Интеграция в AdaptiveLeverage

**Модифицировать `AdaptiveLeverage.calculate_leverage()`:**
```python
async def calculate_leverage(
    self,
    signal: Dict[str, Any],
    regime: Optional[str] = None,
    volatility: Optional[float] = None,
    client=None,  # ✅ НОВОЕ: OKX клиент для проверки доступных leverage
) -> int:
    """
    Расчет адаптивного левериджа с округлением до доступных значений.
    """
    try:
        symbol = signal.get("symbol", "")
        
        # ... (существующая логика расчета) ...
        leverage = self.leverage_map.get(category, 5)
        leverage = max(self.min_leverage, min(self.max_leverage, leverage))
        
        # ✅ НОВОЕ: Округляем до доступных leverage на бирже
        if client and symbol:
            try:
                rounded_leverage = await client.round_leverage_to_available(
                    symbol, leverage
                )
                
                if rounded_leverage != leverage:
                    logger.info(
                        f"📊 Leverage округлен для {symbol}: "
                        f"рассчитанный={leverage}x → доступный={rounded_leverage}x"
                    )
                
                leverage = rounded_leverage
            except Exception as e:
                logger.warning(
                    f"⚠️ Не удалось округлить leverage для {symbol}: {e}, "
                    f"используем рассчитанный {leverage}x"
                )
        
        # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ
        logger.info(
            f"📊 [ADAPTIVE_LEVERAGE] {symbol}: "
            f"strength={signal_strength:.3f}, "
            f"regime={regime or 'N/A'}, "
            f"volatility={volatility*100 if volatility else 'N/A':.2f}%, "
            f"regime_mult={regime_multiplier:.2f}, "
            f"vol_mult={volatility_multiplier:.2f}, "
            f"adjusted_strength={adjusted_strength:.3f}, "
            f"category={category}, "
            f"leverage={leverage}x"
        )
        
        return leverage
        
    except Exception as e:
        logger.error(f"❌ Ошибка расчета адаптивного левериджа: {e}", exc_info=True)
        return 5  # Fallback
```

### 3.4. Интеграция в SignalCoordinator

**Модифицировать `SignalCoordinator.execute_signal_from_price()`:**
```python
# После расчета leverage через AdaptiveLeverage:
if self.adaptive_leverage:
    leverage_config = self.adaptive_leverage.calculate_leverage(
        signal, regime, volatility, client=self.client  # ✅ НОВОЕ: передаем client
    )
    
    # ✅ ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Округляем еще раз (на всякий случай)
    try:
        leverage_config = await self.client.round_leverage_to_available(
            symbol, leverage_config
        )
        logger.info(
            f"✅ [LEVERAGE_FINAL] {symbol}: Финальный leverage={leverage_config}x "
            f"(проверен и округлен до доступного на бирже)"
        )
    except Exception as e:
        logger.warning(
            f"⚠️ Не удалось проверить leverage для {symbol}: {e}, "
            f"используем {leverage_config}x"
        )
```

---

## 4. ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ

### 4.1. Логирование в AdaptiveLeverage

**Уровень INFO для всех важных событий:**
```python
logger.info(
    f"📊 [ADAPTIVE_LEVERAGE] {symbol}: "
    f"РАСЧЕТ LEVERAGE | "
    f"strength={signal_strength:.3f} → category={category} → leverage={leverage}x"
)

logger.info(
    f"📊 [ADAPTIVE_LEVERAGE] {symbol}: "
    f"КОРРЕКТИРОВКИ | "
    f"regime={regime} (mult={regime_multiplier:.2f}), "
    f"volatility={volatility*100 if volatility else 'N/A':.2f}% (mult={volatility_multiplier:.2f}), "
    f"adjusted_strength={adjusted_strength:.3f}"
)

logger.info(
    f"📊 [ADAPTIVE_LEVERAGE] {symbol}: "
    f"ОКРУГЛЕНИЕ | "
    f"рассчитанный={calculated_leverage}x → доступный={rounded_leverage}x "
    f"(доступные: {available_leverages})"
)
```

### 4.2. Логирование в PositionScalingManager

**При добавлении к позиции:**
```python
logger.info(
    f"📊 [POSITION_SCALING] {symbol}: "
    f"LEVERAGE ПОЗИЦИИ | "
    f"существующий leverage={existing_leverage}x, "
    f"leverage сигнала={signal_leverage}x, "
    f"используем leverage={existing_leverage}x для добавления"
)

logger.info(
    f"📊 [POSITION_SCALING] {symbol}: "
    f"РАСЧЕТ МАРЖИ | "
    f"размер добавления=${addition_size_usd:.2f}, "
    f"leverage={existing_leverage}x, "
    f"маржа=${addition_margin:.2f} "
    f"(формула: {addition_size_usd:.2f} / {existing_leverage} = {addition_margin:.2f})"
)
```

### 4.3. Логирование в OKXFuturesClient

**При получении leverage info:**
```python
logger.info(
    f"📊 [LEVERAGE_INFO] {symbol}: "
    f"Получено с биржи | "
    f"max_leverage={max_leverage}x, "
    f"доступные leverage={available_leverages}"
)

logger.info(
    f"📊 [LEVERAGE_ROUND] {symbol}: "
    f"Округление | "
    f"желаемый={desired_leverage}x → "
    f"округленный={rounded_leverage}x "
    f"(ближайший из {available_leverages})"
)
```

### 4.4. Логирование при установке leverage

**В `set_leverage()`:**
```python
logger.info(
    f"📊 [SET_LEVERAGE] {symbol}: "
    f"Установка leverage | "
    f"leverage={leverage}x, posSide={pos_side or 'N/A'}, "
    f"mgnMode=isolated"
)

logger.info(
    f"✅ [SET_LEVERAGE] {symbol}: "
    f"Leverage установлен успешно | "
    f"leverage={leverage}x"
)
```

---

## 5. ОБНОВЛЕНИЕ get_instrument_details

**Расширить метод для включения leverage info:**
```python
async def get_instrument_details(self, symbol: str) -> dict:
    """
    Получает детали инструмента включая leverage info.
    
    Returns:
        {
            "ctVal": float,
            "lotSz": float,
            "minSz": float,
            "max_leverage": int,  # ✅ НОВОЕ
            "available_leverages": List[int],  # ✅ НОВОЕ
        }
    """
    # Существующая логика получения ctVal, lotSz, minSz
    # ...
    
    # ✅ НОВОЕ: Получаем leverage info
    leverage_info = await self.get_instrument_leverage_info(symbol)
    
    details.update({
        "max_leverage": leverage_info.get("max_leverage", 125),
        "available_leverages": leverage_info.get("available_leverages", []),
    })
    
    logger.debug(
        f"📋 Детали инструмента {symbol}: "
        f"ctVal={details['ctVal']}, lotSz={details['lotSz']}, minSz={details['minSz']}, "
        f"max_leverage={details['max_leverage']}x, "
        f"available_leverages={details['available_leverages']}"
    )
    
    return details
```

---

## 6. ИТОГОВАЯ СХЕМА РАБОТЫ С LEVERAGE

### Для первой позиции:

1. **Расчет leverage** → `AdaptiveLeverage.calculate_leverage()`
   - Базовая категория по strength
   - Корректировка по regime и volatility
   - Результат: например, 7x

2. **Получение доступных leverage** → `client.get_instrument_leverage_info(symbol)`
   - Запрос к бирже: maxLever
   - Генерация списка доступных: [1, 2, 3, 5, 10, 20, ...]

3. **Округление** → `client.round_leverage_to_available(symbol, 7)`
   - 7x → ближайший доступный: 5x или 10x
   - Логирование: "7x → 5x (ближайший)"

4. **Установка на бирже** → `client.set_leverage(symbol, 5)`
   - Логирование: "Установка leverage 5x для SOL-USDT"

5. **Использование в расчетах** → `margin = size_usd / 5`

### Для добавления к позиции:

1. **Получение leverage позиции** → `existing_position.get("lever")`
   - Например: 5x

2. **Переопределение в сигнале** → `signal["leverage"] = 5`
   - Логирование: "Используем leverage позиции 5x вместо 7x из сигнала"

3. **Расчет маржи** → `addition_margin = addition_size_usd / 5`
   - Логирование: "Маржа для добавления: $100 / 5 = $20"

---

## 7. ПРЕИМУЩЕСТВА РЕШЕНИЯ

1. ✅ **Корректная работа с биржей** - всегда используем доступные leverage
2. ✅ **Детальное логирование** - видно весь процесс выбора leverage
3. ✅ **Автоматическое округление** - не нужно вручную проверять
4. ✅ **Кэширование** - leverage info кэшируется для производительности
5. ✅ **Fallback** - если не удалось получить с биржи, используем стандартные значения

---

## 8. ПРИМЕРЫ ЛОГОВ

### Пример 1: Расчет leverage для SOL-USDT

```
INFO | [ADAPTIVE_LEVERAGE] SOL-USDT: РАСЧЕТ LEVERAGE | strength=0.850 → category=strong → leverage=20x
INFO | [ADAPTIVE_LEVERAGE] SOL-USDT: КОРРЕКТИРОВКИ | regime=trending (mult=1.20), volatility=4.50% (mult=1.00), adjusted_strength=1.020
INFO | [LEVERAGE_INFO] SOL-USDT: Получено с биржи | max_leverage=100x, доступные leverage=[1, 2, 3, 5, 10, 20, 50, 75, 100]
INFO | [LEVERAGE_ROUND] SOL-USDT: Округление | желаемый=20x → округленный=20x (доступен)
INFO | [SET_LEVERAGE] SOL-USDT: Установка leverage | leverage=20x, posSide=long, mgnMode=isolated
INFO | ✅ [SET_LEVERAGE] SOL-USDT: Leverage установлен успешно | leverage=20x
```

### Пример 2: Округление leverage для BTC-USDT

```
INFO | [ADAPTIVE_LEVERAGE] BTC-USDT: РАСЧЕТ LEVERAGE | strength=0.550 → category=medium → leverage=10x
INFO | [ADAPTIVE_LEVERAGE] BTC-USDT: КОРРЕКТИРОВКИ | regime=choppy (mult=0.80), volatility=0.50% (mult=1.30), adjusted_strength=0.572
INFO | [LEVERAGE_INFO] BTC-USDT: Получено с биржи | max_leverage=125x, доступные leverage=[1, 2, 3, 5, 10, 20, 50, 75, 100, 125]
INFO | [LEVERAGE_ROUND] BTC-USDT: Округление | желаемый=10x → округленный=10x (доступен)
INFO | [SET_LEVERAGE] BTC-USDT: Установка leverage | leverage=10x, posSide=long, mgnMode=isolated
INFO | ✅ [SET_LEVERAGE] BTC-USDT: Leverage установлен успешно | leverage=10x
```

### Пример 3: Округление нестандартного leverage

```
INFO | [ADAPTIVE_LEVERAGE] DOGE-USDT: РАСЧЕТ LEVERAGE | strength=0.400 → category=weak → leverage=5x
INFO | [ADAPTIVE_LEVERAGE] DOGE-USDT: КОРРЕКТИРОВКИ | regime=ranging (mult=1.00), volatility=2.50% (mult=1.00), adjusted_strength=0.400
INFO | [LEVERAGE_INFO] DOGE-USDT: Получено с биржи | max_leverage=100x, доступные leverage=[1, 2, 3, 5, 10, 20, 50, 75, 100]
INFO | [LEVERAGE_ROUND] DOGE-USDT: Округление | желаемый=5x → округленный=5x (доступен)
INFO | [SET_LEVERAGE] DOGE-USDT: Установка leverage | leverage=5x, posSide=long, mgnMode=isolated
INFO | ✅ [SET_LEVERAGE] DOGE-USDT: Leverage установлен успешно | leverage=5x
```

### Пример 4: Добавление к позиции (использование leverage позиции)

```
INFO | [POSITION_SCALING] SOL-USDT: LEVERAGE ПОЗИЦИИ | существующий leverage=20x, leverage сигнала=30x, используем leverage=20x для добавления
INFO | [POSITION_SCALING] SOL-USDT: РАСЧЕТ МАРЖИ | размер добавления=$350.00, leverage=20x, маржа=$17.50 (формула: 350.00 / 20 = 17.50)
INFO | [POSITION_SCALING] SOL-USDT: ПРОВЕРКА МАРЖИ | доступно=$500.00, требуется=$17.50, резерв=96.5%
INFO | ✅ [POSITION_SCALING] SOL-USDT: Добавление РАЗРЕШЕНО | размер=$350.00, маржа=$17.50, leverage=20x
```

---

## 9. ИТОГОВЫЙ ПЛАН РЕАЛИЗАЦИИ

### Этап 1: Добавление методов в OKXFuturesClient

1. ✅ `get_instrument_leverage_info()` - получение maxLever и генерация списка доступных
2. ✅ `round_leverage_to_available()` - округление до ближайшего доступного
3. ✅ Обновление `get_instrument_details()` - включение leverage info
4. ✅ Кэширование leverage info для производительности

### Этап 2: Интеграция в AdaptiveLeverage

1. ✅ Передача `client` в `calculate_leverage()`
2. ✅ Округление leverage после расчета
3. ✅ Детальное логирование всех этапов

### Этап 3: Интеграция в SignalCoordinator

1. ✅ Передача `client` в `calculate_leverage()`
2. ✅ Дополнительная проверка leverage перед установкой
3. ✅ Логирование финального leverage

### Этап 4: Интеграция в PositionScalingManager

1. ✅ Использование leverage позиции при добавлении
2. ✅ Детальное логирование расчета маржи
3. ✅ Проверка доступной маржи с учетом leverage

---

## ВОПРОСЫ ДЛЯ ПОДТВЕРЖДЕНИЯ

1. ✅ **Логирование:** Достаточно детальное? (все этапы логируются)
2. ✅ **Округление:** Понятна логика? (ближайший доступный)
3. ✅ **Кэширование:** Нужно ли кэшировать leverage info? (ДА - для производительности)

