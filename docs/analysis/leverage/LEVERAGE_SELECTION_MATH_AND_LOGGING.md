# ВЫБОР LEVERAGE, МАТЕМАТИКА И ЛОГИРОВАНИЕ

**Дата:** 2025-12-21  
**Цель:** Объяснить выбор leverage для первой позиции, правильная математика маржи, детальное логирование

---

## 1. КАК БОТ ВЫБИРАЕТ LEVERAGE ДЛЯ ПЕРВОЙ ПОЗИЦИИ?

### Логика AdaptiveLeverage

**Бот использует `AdaptiveLeverage.calculate_leverage()` для выбора leverage:**

```python
leverage = adaptive_leverage.calculate_leverage(
    signal,           # Торговый сигнал (содержит strength, symbol, price, ...)
    regime,           # Режим рынка: "trending" / "ranging" / "choppy"
    volatility        # Волатильность (ATR в процентах, например 0.02 = 2%)
)
```

### Шаг 1: Базовая категория по силе сигнала

**Сила сигнала (signal_strength) - от 0.0 до 1.0:**
- 0.0-0.3 → `very_weak` → leverage = **3x**
- 0.3-0.5 → `weak` → leverage = **5x**
- 0.5-0.7 → `medium` → leverage = **10x**
- 0.7-0.9 → `strong` → leverage = **20x**
- 0.9-1.0 → `very_strong` → leverage = **30x**

**Пример:**
- SOL-USDT: signal_strength=0.95 → `very_strong` → **30x** (но дальше корректируется!)
- BTC-USDT: signal_strength=0.55 → `medium` → **10x**
- DOGE-USDT: signal_strength=0.4 → `weak` → **5x**
- XRP-USDT: signal_strength=0.85 → `strong` → **20x**

### Шаг 2: Корректировка по режиму рынка

**Множители режима:**
- `trending` → ×1.2 (+20%)
- `ranging` → ×1.0 (без изменений)
- `choppy` → ×0.8 (-20%)

**Пример:**
- SOL в режиме `trending`: 30x × 1.2 = 36x → ограничивается до 30x (максимум)
- BTC в режиме `choppy`: 10x × 0.8 = **8x**
- DOGE в режиме `trending`: 5x × 1.2 = **6x**

### Шаг 3: Корректировка по волатильности

**Множители волатильности:**
- Высокая волатильность (>5%) → ×0.7 (-30%) - уменьшаем риск
- Низкая волатильность (<1%) → ×1.3 (+30%) - можно больше
- Средняя волатильность (1-5%) → ×1.0 (без изменений)

**Пример:**
- SOL с волатильностью 6%: 30x × 0.7 = **21x**
- BTC с волатильностью 0.5%: 8x × 1.3 = **10.4x** → округляется до **10x**
- XRP с волатильностью 3%: 20x × 1.0 = **20x**

### Шаг 4: Финальная корректировка силы сигнала

**Итоговая формула:**
```python
adjusted_strength = signal_strength × regime_multiplier × volatility_multiplier
adjusted_strength = max(0.0, min(1.0, adjusted_strength))  # Ограничение 0-1

# Затем определяется категория по adjusted_strength
if adjusted_strength < 0.3: category = "very_weak" → leverage = 3x
elif adjusted_strength < 0.5: category = "weak" → leverage = 5x
elif adjusted_strength < 0.7: category = "medium" → leverage = 10x
elif adjusted_strength < 0.9: category = "strong" → leverage = 20x
else: category = "very_strong" → leverage = 30x

# Ограничение: min_leverage=3, max_leverage=30
leverage = max(3, min(30, leverage))
```

### Примеры расчета для разных символов

**Пример 1: SOL-USDT**
```
signal_strength = 0.95
regime = "trending" → multiplier = 1.2
volatility = 0.04 (4%) → multiplier = 1.0

adjusted_strength = 0.95 × 1.2 × 1.0 = 1.14 → ограничивается до 1.0
category = "very_strong"
leverage = 30x (максимум)
```

**Пример 2: BTC-USDT**
```
signal_strength = 0.55
regime = "choppy" → multiplier = 0.8
volatility = 0.005 (0.5%) → multiplier = 1.3

adjusted_strength = 0.55 × 0.8 × 1.3 = 0.572
category = "medium"
leverage = 10x
```

**Пример 3: DOGE-USDT**
```
signal_strength = 0.4
regime = "ranging" → multiplier = 1.0
volatility = 0.025 (2.5%) → multiplier = 1.0

adjusted_strength = 0.4 × 1.0 × 1.0 = 0.4
category = "weak"
leverage = 5x
```

**Пример 4: XRP-USDT**
```
signal_strength = 0.85
regime = "trending" → multiplier = 1.2
volatility = 0.08 (8%) → multiplier = 0.7

adjusted_strength = 0.85 × 1.2 × 0.7 = 0.714
category = "medium" (0.714 попадает в диапазон 0.5-0.7, но ближе к strong)
# На самом деле в коде проверка: 0.714 < 0.7? НЕТ → category = "medium"
# Но это странно, давайте проверим код...
```

**⚠️ ВАЖНО:** В коде проверка идет по диапазонам:
- 0.714 >= 0.7 → category = "strong" → leverage = 20x

---

## 2. ПРАВИЛЬНАЯ МАТЕМАТИКА РАСЧЕТА МАРЖИ

### Формулы для изолированной маржи (Isolated Margin)

**Основные формулы:**

1. **Размер позиции в USD:**
```python
position_value_usd = size_in_coins × current_price
```

2. **Маржа для открытия позиции:**
```python
margin_required = position_value_usd / leverage
```

3. **Размер позиции в контрактах (для OKX):**
```python
size_in_contracts = size_in_coins / ct_val
# где ct_val = контрактный размер (обычно 0.01 для BTC/ETH, может быть другим)
```

4. **Маржа при добавлении к позиции:**
```python
# Используем leverage СУЩЕСТВУЮЩЕЙ позиции!
addition_margin = addition_size_usd / existing_leverage
```

### Проверка доступной маржи

**1. Общая доступная маржа:**
```python
total_balance = await client.get_balance()
total_margin_used = await get_total_margin_used()  # Сумма маржи всех позиций
available_margin = total_balance - total_margin_used
```

**2. Проверка для новой позиции:**
```python
# Для первой позиции
new_position_size_usd = calculated_size_usd
new_leverage = adaptive_leverage.calculate_leverage(signal, regime, volatility)
new_margin_needed = new_position_size_usd / new_leverage

if new_margin_needed > available_margin * 0.8:  # Оставляем 20% резерв
    # Блокируем открытие - недостаточно маржи
    return False
```

**3. Проверка для добавления к позиции:**
```python
# Для добавления к существующей позиции
existing_leverage = existing_position.get("lever", 3)  # ✅ Используем leverage позиции!
addition_size_usd = calculated_addition_size_usd
addition_margin_needed = addition_size_usd / existing_leverage

current_position_margin = existing_position.get("margin", 0)
new_total_margin = current_position_margin + addition_margin_needed

# Проверка 1: Достаточно ли общей маржи?
if addition_margin_needed > available_margin * 0.8:
    # Блокируем - недостаточно маржи
    return False

# Проверка 2: Не превысим ли максимальную маржу на позицию?
max_margin_per_position = calculate_max_margin_per_position(
    balance, balance_profile, regime
)
if new_total_margin > max_margin_per_position:
    # Блокируем - превысим максимум
    return False
```

### Расчет максимальной маржи на позицию

**По балансу и профилю:**
```python
def calculate_max_margin_per_position(
    balance: float,
    balance_profile: str,
    regime: str,
) -> float:
    """
    Рассчитать максимальную маржу на одну позицию.
    
    Логика:
    - Small баланс: 15% от баланса
    - Medium баланс: 20% от баланса
    - Large баланс: 25% от баланса
    
    С корректировкой по режиму:
    - Trending: +5%
    - Choppy: -5%
    """
    base_percent = {
        "small": 0.15,   # 15%
        "medium": 0.20,  # 20%
        "large": 0.25,   # 25%
    }.get(balance_profile, 0.20)
    
    # Корректировка по режиму
    regime_adjustment = {
        "trending": 0.05,   # +5%
        "ranging": 0.0,     # без изменений
        "choppy": -0.05,    # -5%
    }.get(regime, 0.0)
    
    adjusted_percent = base_percent + regime_adjustment
    max_margin = balance * adjusted_percent
    
    return max_margin
```

### Расчет размера добавления с учетом leverage позиции

**Важно:** При добавлении используем leverage существующей позиции!

```python
async def calculate_addition_size_with_leverage(
    self,
    symbol: str,
    existing_position: Dict[str, Any],
    base_size_usd: float,  # Базовый размер из лестницы
    current_price: float,
) -> float:
    """
    Рассчитать размер добавления с учетом leverage существующей позиции.
    """
    # 1. Получаем leverage существующей позиции
    existing_leverage = self._get_position_leverage(existing_position)
    
    # 2. Размер добавления в USD (из лестницы)
    addition_size_usd = base_size_usd
    
    # 3. Маржа для добавления
    addition_margin = addition_size_usd / existing_leverage
    
    # 4. Проверяем доступную маржу
    available_margin = await self._get_available_margin()
    if addition_margin > available_margin * 0.8:
        # Уменьшаем размер добавления до доступной маржи
        max_addition_margin = available_margin * 0.8
        addition_size_usd = max_addition_margin * existing_leverage
        logger.warning(
            f"⚠️ Размер добавления уменьшен из-за недостатка маржи: "
            f"было {base_size_usd:.2f} USD, стало {addition_size_usd:.2f} USD"
        )
    
    return addition_size_usd
```

---

## 3. АНАЛИЗ РИСКОВ С РАЗНЫМИ LEVERAGE

### Риск ликвидации

**Формула цены ликвидации для LONG:**
```python
liquidation_price = entry_price × (1 - 1/leverage + maintenance_margin_ratio)
```

**Где:**
- `maintenance_margin_ratio` = 0.005 (0.5% для большинства инструментов на OKX)

**Примеры:**
- Leverage 3x: liquidation = entry × (1 - 1/3 + 0.005) = entry × 0.6717 → ликвидация при -33%
- Leverage 5x: liquidation = entry × (1 - 1/5 + 0.005) = entry × 0.805 → ликвидация при -20%
- Leverage 10x: liquidation = entry × (1 - 1/10 + 0.005) = entry × 0.905 → ликвидация при -10%
- Leverage 20x: liquidation = entry × (1 - 1/20 + 0.005) = entry × 0.955 → ликвидация при -4.5%
- Leverage 30x: liquidation = entry × (1 - 1/30 + 0.005) = entry × 0.9717 → ликвидация при -2.8%

**⚠️ КРИТИЧНО:** Чем выше leverage, тем ближе цена ликвидации к цене входа!

### Убыток при движении против позиции

**Формула убытка в процентах:**
```python
# Для LONG позиции:
loss_percent = (entry_price - current_price) / entry_price × leverage

# Для SHORT позиции:
loss_percent = (current_price - entry_price) / entry_price × leverage
```

**Примеры:**
- Leverage 3x, цена упала на 5%: убыток = 5% × 3 = **15%**
- Leverage 10x, цена упала на 5%: убыток = 5% × 10 = **50%**
- Leverage 30x, цена упала на 2%: убыток = 2% × 30 = **60%**

### Учет разных leverage при анализе открытых позиций

**Проблема:** Разные позиции с разным leverage требуют разного анализа рисков.

**Решение:** Учитывать leverage каждой позиции отдельно:

```python
async def analyze_position_risk(
    self,
    position: Dict[str, Any],
    current_price: float,
) -> Dict[str, Any]:
    """
    Анализ риска позиции с учетом leverage.
    """
    symbol = position.get("instId", "").replace("-SWAP", "")
    entry_price = float(position.get("avgPx", 0))
    leverage = int(position.get("lever", 3))
    side = position.get("posSide", "long")
    
    # 1. Расчет цены ликвидации
    maintenance_margin = 0.005  # 0.5%
    if side == "long":
        liquidation_price = entry_price * (1 - 1/leverage + maintenance_margin)
        distance_to_liquidation_pct = ((current_price - liquidation_price) / current_price) * 100
    else:  # short
        liquidation_price = entry_price * (1 + 1/leverage - maintenance_margin)
        distance_to_liquidation_pct = ((liquidation_price - current_price) / current_price) * 100
    
    # 2. Расчет текущего PnL с учетом leverage
    if side == "long":
        pnl_percent = ((current_price - entry_price) / entry_price) * leverage
    else:
        pnl_percent = ((entry_price - current_price) / entry_price) * leverage
    
    # 3. Уровень риска
    risk_level = "low"
    if distance_to_liquidation_pct < 5:  # Меньше 5% до ликвидации
        risk_level = "critical"
    elif distance_to_liquidation_pct < 10:  # Меньше 10% до ликвидации
        risk_level = "high"
    elif distance_to_liquidation_pct < 20:
        risk_level = "medium"
    
    return {
        "symbol": symbol,
        "leverage": leverage,
        "entry_price": entry_price,
        "current_price": current_price,
        "liquidation_price": liquidation_price,
        "distance_to_liquidation_pct": distance_to_liquidation_pct,
        "pnl_percent": pnl_percent,
        "risk_level": risk_level,
    }
```

---

## 4. ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ ДЛЯ PositionScalingManager

### Структура логирования

**Уровни логирования:**
- `INFO` - важные события (разрешение/блокировка добавления, расчеты)
- `DEBUG` - детальные расчеты (промежуточные значения)
- `WARNING` - предупреждения (недостаток маржи, превышение лимитов)

### Примеры логов

**1. Начало проверки добавления:**
```python
logger.info(
    f"🔍 [POSITION_SCALING] {symbol}: Начало проверки добавления к позиции | "
    f"текущий размер={current_size:.6f} контрактов, "
    f"текущая маржа=${current_margin:.2f}, leverage={existing_leverage}x"
)
```

**2. Расчет размера добавления:**
```python
logger.info(
    f"📊 [POSITION_SCALING] {symbol}: Расчет размера добавления | "
    f"добавлений сделано={additions_count}, уровень лестницы={ladder_level}, "
    f"базовый размер=${base_size_usd:.2f}, коэффициент={ladder_coefficient:.2f}, "
    f"скорректированный размер=${addition_size_usd:.2f}, leverage={existing_leverage}x"
)
logger.debug(
    f"🔍 [POSITION_SCALING] {symbol}: Детали расчета | "
    f"баланс=${balance:.2f}, профиль={balance_profile}, режим={regime}, "
    f"режимный множитель={regime_multiplier:.2f}, балансный множитель={balance_multiplier:.2f}"
)
```

**3. Расчет маржи:**
```python
logger.info(
    f"💰 [POSITION_SCALING] {symbol}: Расчет маржи для добавления | "
    f"размер добавления=${addition_size_usd:.2f}, leverage={existing_leverage}x, "
    f"маржа=${addition_margin:.2f}, текущая маржа позиции=${current_position_margin:.2f}, "
    f"новая общая маржа позиции=${new_total_margin:.2f}"
)
logger.debug(
    f"🔍 [POSITION_SCALING] {symbol}: Проверка маржи | "
    f"общий баланс=${total_balance:.2f}, использовано маржи=${total_margin_used:.2f}, "
    f"доступно=${available_margin:.2f}, требуется=${addition_margin:.2f}, "
    f"резерв={reserve_percent:.0f}%"
)
```

**4. Проверка лимитов:**
```python
logger.info(
    f"✅ [POSITION_SCALING] {symbol}: Проверка лимитов | "
    f"количество добавлений: {additions_count}/{max_additions}, "
    f"интервал: {seconds_since_last_add:.1f}с (мин: {min_interval}с), "
    f"текущий PnL: {pnl_percent:.2f}% (макс убыток: {max_loss_percent:.2f}%)"
)

if additions_count >= max_additions:
    logger.warning(
        f"⚠️ [POSITION_SCALING] {symbol}: Достигнут максимум добавлений "
        f"({additions_count}/{max_additions})"
    )
```

**5. Проверка максимального размера позиции:**
```python
logger.info(
    f"📏 [POSITION_SCALING] {symbol}: Проверка максимального размера | "
    f"текущий размер=${current_size_usd:.2f}, добавление=${addition_size_usd:.2f}, "
    f"новый размер=${new_size_usd:.2f}, максимум=${max_position_size_usd:.2f}"
)

if new_size_usd > max_position_size_usd:
    logger.warning(
        f"⚠️ [POSITION_SCALING] {symbol}: Превышение максимального размера | "
        f"новый размер ${new_size_usd:.2f} > максимум ${max_position_size_usd:.2f}, "
        f"уменьшаем до ${max_position_size_usd:.2f}"
    )
```

**6. Использование leverage позиции:**
```python
if signal_leverage != existing_leverage:
    logger.info(
        f"📊 [POSITION_SCALING] {symbol}: Использование leverage позиции | "
        f"leverage сигнала={signal_leverage}x, leverage позиции={existing_leverage}x, "
        f"используем leverage={existing_leverage}x для добавления"
    )
```

**7. Финальное решение:**
```python
if can_add:
    logger.info(
        f"✅ [POSITION_SCALING] {symbol}: Добавление РАЗРЕШЕНО | "
        f"размер=${addition_size_usd:.2f}, маржа=${addition_margin:.2f}, "
        f"leverage={existing_leverage}x, уровень лестницы={ladder_level}"
    )
else:
    logger.warning(
        f"❌ [POSITION_SCALING] {symbol}: Добавление ЗАБЛОКИРОВАНО | "
        f"причина: {reason}"
    )
```

### Структура класса с логированием

```python
class PositionScalingManager:
    def __init__(self, ...):
        # ...
        self._logger = logger.bind(module="PositionScalingManager")
    
    async def can_add_to_position(self, ...) -> Tuple[bool, str]:
        """Проверка возможности добавления с детальным логированием."""
        symbol = existing_position.get("instId", "").replace("-SWAP", "")
        
        self._logger.info(
            f"🔍 [CAN_ADD] {symbol}: Начало проверки",
            extra={"symbol": symbol, "action": "can_add_check_start"}
        )
        
        # Все проверки с логированием
        # ...
        
        return can_add, reason
    
    async def calculate_next_addition_size(self, ...) -> Optional[float]:
        """Расчет размера добавления с детальным логированием."""
        self._logger.info(
            f"📊 [CALC_SIZE] {symbol}: Расчет размера добавления",
            extra={"symbol": symbol, "action": "calculate_size_start"}
        )
        
        # Все расчеты с логированием
        # ...
        
        return addition_size_usd
```

---

## 5. ИТОГОВАЯ СХЕМА РАБОТЫ

### Для первой позиции:

1. **Генерация сигнала** → `signal_strength`, `regime`, `volatility`
2. **Расчет leverage** → `AdaptiveLeverage.calculate_leverage()`
   - Базовая категория по strength
   - Корректировка по regime
   - Корректировка по volatility
   - Ограничение 3-30x
3. **Установка leverage на бирже** → `client.set_leverage(symbol, leverage)`
4. **Расчет размера позиции** → с учетом этого leverage
5. **Проверка маржи** → `margin = size_usd / leverage`
6. **Открытие позиции**

### Для добавления к позиции:

1. **Генерация сигнала** → новый сигнал с потенциально другим leverage
2. **Получение leverage позиции** → `existing_position.get("lever")`
3. **Переопределение leverage в сигнале** → `signal["leverage"] = existing_leverage`
4. **Расчет размера добавления** → с учетом leverage позиции (не сигнала!)
5. **Проверка маржи** → `addition_margin = addition_size_usd / existing_leverage`
6. **Проверка лимитов** → количество, интервал, убыток, максимальный размер
7. **Добавление к позиции**

---

## ВОПРОСЫ ДЛЯ ПОДТВЕРЖДЕНИЯ

1. ✅ **Leverage для первой позиции:** Понятно как работает AdaptiveLeverage? (объяснено выше)
2. ✅ **Математика маржи:** Правильные формулы? (проверено выше)
3. ✅ **Логирование:** Достаточно детальное? (можно еще добавить)

