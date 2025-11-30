# ✅ Финальный список изменений (29.11.2025)

## 📊 Полный анализ связанных участков кода

### ✅ Проверенные файлы:

1. **`src/strategies/scalping/futures/position_manager.py`**
   - ✅ `_update_peak_profit` (строка 3547) - **ИЗМЕНИТЬ**
   - ✅ `_check_profit_harvesting` (строка 1229) - **ИЗМЕНИТЬ**
   - ✅ `_check_profit_drawdown` (строка 3663) - **ИЗМЕНИТЬ**
   - ✅ `manage_position` (строка 408) - **НЕ ТРОГАТЬ** (только вызывает методы)

2. **`src/strategies/scalping/futures/core/position_registry.py`**
   - ✅ `PositionMetadata.peak_profit_usd` (строка 33) - **НЕ ТРОГАТЬ** (может быть отрицательным)
   - ✅ `PositionMetadata.peak_profit_time` (строка 34) - **НЕ ТРОГАТЬ** (используется для проверки)

3. **`config/config_futures.yaml`**
   - ✅ `adaptive_regime.ranging.ph_time_limit` (строка 284) - **ИЗМЕНИТЬ**
   - ✅ `adaptive_regime.trending.ph_time_limit` (строка 226) - **ИЗМЕНИТЬ** (опционально)

4. **`src/strategies/scalping/futures/signal_generator.py`**
   - ✅ `generate_signal` или `_generate_base_signals` - **ИЗМЕНИТЬ** (добавить фильтр XRP)

### ✅ Проверенные зависимости:

- ✅ `manage_position` → `_check_profit_harvesting` → `ph_time_limit` ✅
- ✅ `manage_position` → `_update_peak_profit` → `peak_profit_usd` ✅
- ✅ `manage_position` → `_check_profit_drawdown` → `peak_profit_usd` ✅
- ✅ `_update_peak_profit` → `_check_profit_drawdown` ✅ (уже есть проверка)
- ✅ `trailing_sl_coordinator` → `_check_profit_harvesting` ✅ (не влияет)
- ✅ `websocket_coordinator` → `manage_position` ✅ (не влияет)

---

## 📝 ФИНАЛЬНЫЙ СПИСОК ИЗМЕНЕНИЙ

### 1. **ИСПРАВИТЬ _update_peak_profit** (КРИТИЧНО)

**Файл:** `src/strategies/scalping/futures/position_manager.py`  
**Строка:** 3608-3632

**Изменение:**
```python
# БЫЛО:
if metadata:
    if net_pnl > metadata.peak_profit_usd:
        metadata.peak_profit_usd = net_pnl
        # ... сохранение

# СТАНЕТ:
if metadata:
    # ✅ ИСПРАВЛЕНИЕ: Обновляем peak_profit при первом обновлении или если PnL улучшился
    if metadata.peak_profit_usd == 0.0 and metadata.peak_profit_time is None:
        # Первое обновление - устанавливаем текущий PnL (даже если отрицательный)
        metadata.peak_profit_usd = net_pnl
        metadata.peak_profit_time = datetime.now(timezone.utc)
        metadata.peak_profit_price = current_price
        
        logger.debug(
            f"🔍 [UPDATE_PEAK_PROFIT] {symbol}: Первое обновление peak_profit | "
            f"установлен=${net_pnl:.4f}"
        )
        
        # Сохраняем в position_registry
        if hasattr(self, "orchestrator") and self.orchestrator:
            if hasattr(self.orchestrator, "position_registry"):
                await self.orchestrator.position_registry.update_position(
                    symbol,
                    metadata_updates={
                        "peak_profit_usd": net_pnl,
                        "peak_profit_time": metadata.peak_profit_time,
                        "peak_profit_price": current_price,
                    },
                )
    elif net_pnl > metadata.peak_profit_usd:
        # PnL улучшился (для прибыльных: больше, для убыточных: ближе к 0)
        metadata.peak_profit_usd = net_pnl
        metadata.peak_profit_time = datetime.now(timezone.utc)
        metadata.peak_profit_price = current_price
        
        logger.debug(
            f"🔍 [UPDATE_PEAK_PROFIT] {symbol}: Обновлен peak_profit | "
            f"новый=${net_pnl:.4f}, был=${metadata.peak_profit_usd:.4f}"
        )
        
        # Сохраняем в position_registry
        if hasattr(self, "orchestrator") and self.orchestrator:
            if hasattr(self.orchestrator, "position_registry"):
                await self.orchestrator.position_registry.update_position(
                    symbol,
                    metadata_updates={
                        "peak_profit_usd": net_pnl,
                        "peak_profit_time": metadata.peak_profit_time,
                        "peak_profit_price": current_price,
                    },
                )
        
        # ✅ НОВОЕ: Немедленная проверка profit_drawdown после обновления пика
        if size != 0:
            try:
                drawdown_should_close = await self._check_profit_drawdown(position)
                if drawdown_should_close:
                    logger.warning(
                        f"📉 Немедленное закрытие по Profit Drawdown после обновления пика для {symbol}"
                    )
                    await self._close_position_by_reason(position, "profit_drawdown")
                    return
            except Exception as e:
                logger.debug(f"⚠️ Ошибка немедленной проверки profit_drawdown для {symbol}: {e}")
```

---

### 2. **УБРАТЬ ph_time_limit ДЛЯ ЭКСТРЕМАЛЬНЫХ ПРИБЫЛЕЙ** (КРИТИЧНО)

**Файл:** `src/strategies/scalping/futures/position_manager.py`  
**Строка:** 1554-1595

**Изменение:**
```python
# БЫЛО:
if ignore_min_holding:
    # Экстремальная прибыль: игнорируем ph_time_limit
    if net_pnl_usd >= ph_threshold:
        should_close = True
        close_reason = "EXTREME PROFIT (ignoring time_limit)"

# СТАНЕТ:
if ignore_min_holding:
    # ✅ ИСПРАВЛЕНО: Для экстремальных прибылей (>= 2x порога) игнорируем ph_time_limit
    extreme_profit_2x = ph_threshold * 2.0
    if net_pnl_usd >= extreme_profit_2x:
        # Экстремальная прибыль >= 2x: игнорируем ph_time_limit
        if net_pnl_usd >= ph_threshold:
            should_close = True
            close_reason = "EXTREME PROFIT 2x+ (ignoring time_limit and min_holding)"
            logger.debug(
                f"✅ PH для {symbol}: Условие экстремальной прибыли 2x+ выполнено "
                f"(profit=${net_pnl_usd:.4f} >= 2x threshold=${extreme_profit_2x:.2f})"
            )
    elif net_pnl_usd >= ph_threshold:
        # Экстремальная прибыль >= 1.5x но < 2x: игнорируем min_holding, но проверяем ph_time_limit
        if time_since_open < ph_time_limit:
            should_close = True
            close_reason = "EXTREME PROFIT 1.5x+ (ignoring min_holding, within time_limit)"
            logger.debug(
                f"✅ PH для {symbol}: Условие экстремальной прибыли 1.5x+ выполнено "
                f"(profit=${net_pnl_usd:.4f} >= 1.5x threshold=${extreme_profit_threshold:.2f}, "
                f"time={time_since_open:.1f}с < {ph_time_limit}с)"
            )
        else:
            logger.debug(
                f"❌ PH для {symbol}: Экстремальная прибыль 1.5x+, но превышен time_limit "
                f"({time_since_open:.1f}с >= {ph_time_limit}с)"
            )
    else:
        logger.debug(
            f"❌ PH для {symbol}: Экстремальная прибыль, но недостаточно для закрытия "
            f"(profit=${net_pnl_usd:.4f} < threshold=${ph_threshold:.2f})"
        )
```

---

### 3. **УВЕЛИЧИТЬ ph_time_limit В КОНФИГЕ** (ВАЖНО)

**Файл:** `config/config_futures.yaml`  
**Строка:** 284

**Изменение:**
```yaml
# БЫЛО:
ranging:
  ph_time_limit: 300  # 5 минут

# СТАНЕТ:
ranging:
  ph_time_limit: 1200  # ✅ УВЕЛИЧЕНО: 20 минут (было 300 = 5 минут)
```

**Опционально для trending:**
```yaml
# БЫЛО:
trending:
  ph_time_limit: 180  # 3 минуты

# СТАНЕТ:
trending:
  ph_time_limit: 600  # ✅ УВЕЛИЧЕНО: 10 минут (было 180 = 3 минуты)
```

---

### 4. **ОБНОВИТЬ _check_profit_drawdown ДЛЯ ОТРИЦАТЕЛЬНЫХ peak_profit** (ВАЖНО)

**Файл:** `src/strategies/scalping/futures/position_manager.py`  
**Строка:** 3740-3745

**Изменение:**
```python
# БЫЛО:
if not metadata or metadata.peak_profit_usd <= 0:
    logger.debug(
        f"🔍 [PROFIT_DRAWDOWN] {symbol}: Нет peak_profit "
        f"(metadata={metadata is not None}, peak_profit={metadata.peak_profit_usd if metadata else 0})"
    )
    return False

# СТАНЕТ:
if not metadata:
    logger.debug(f"🔍 [PROFIT_DRAWDOWN] {symbol}: Нет metadata")
    return False

# ✅ ИСПРАВЛЕНО: Проверяем не только > 0, но и наличие peak_profit_time
# peak_profit_usd может быть отрицательным для убыточных позиций
if metadata.peak_profit_time is None:
    logger.debug(
        f"🔍 [PROFIT_DRAWDOWN] {symbol}: Нет peak_profit_time "
        f"(peak_profit=${metadata.peak_profit_usd:.4f})"
    )
    return False  # Нет максимума (позиция еще не обновлялась)

# ✅ НОВОЕ: Для убыточных позиций проверяем откат от минимального убытка
# Если убыток увеличился (стал больше по модулю), закрываем
if metadata.peak_profit_usd < 0:
    # Убыточная позиция: проверяем откат от минимального убытка
    # Если текущий убыток больше (по модулю) чем peak_profit_usd, значит убыток увеличился
    if net_pnl < metadata.peak_profit_usd:
        # Убыток увеличился - закрываем
        logger.warning(
            f"📉 Profit Drawdown для убыточной позиции {symbol}: "
            f"убыток увеличился с ${metadata.peak_profit_usd:.4f} до ${net_pnl:.4f}"
        )
        return True
    else:
        logger.debug(
            f"🔍 [PROFIT_DRAWDOWN] {symbol}: Убыточная позиция, убыток не увеличился "
            f"(текущий=${net_pnl:.4f}, peak=${metadata.peak_profit_usd:.4f})"
        )
        return False

# Прибыльная позиция: проверяем откат от максимума (существующая логика)
# ... (остальная логика без изменений, начиная со строки 3747)

# ⚠️ ВАЖНО: Также нужно исправить строку 3814 в _check_profit_drawdown:
# БЫЛО:
drawdown_percent = (
    (peak_profit - net_pnl) / peak_profit if peak_profit > 0 else 0
)

# СТАНЕТ:
# ✅ ИСПРАВЛЕНО: Работаем с положительными и отрицательными peak_profit
if peak_profit > 0:
    # Прибыльная позиция: рассчитываем откат от максимума
    drawdown_percent = (peak_profit - net_pnl) / peak_profit if peak_profit > 0 else 0
else:
    # Убыточная позиция: откат уже обработан выше, здесь не должно попасть
    drawdown_percent = 0
```

---

### 5. **ДОБАВИТЬ ФИЛЬТР ДЛЯ XRP-USDT SHORT** (ВАЖНО)

**Файл:** `src/strategies/scalping/futures/signal_generator.py`  
**Метод:** `_generate_base_signals` или место, где проверяются сигналы перед возвратом

**Изменение:**
```python
# ✅ НОВОЕ: Фильтр для XRP-USDT SHORT - блокируем если сильный BULLISH тренд
# Добавить в конец _generate_base_signals перед return signals

filtered_signals = []
for signal in signals:
    symbol = signal.get("symbol", "")
    side = signal.get("side", "")
    
    # Фильтр для XRP-USDT SHORT
    if symbol == "XRP-USDT" and side == "sell":
        # Проверяем ADX тренд - блокируем SHORT если тренд BULLISH
        try:
            if market_data and market_data.ohlcv_data:
                adx_data = self.adx_filter.check_trend_strength(
                    symbol, OrderSide.BUY, market_data.ohlcv_data
                )
                if adx_data.direction == "bullish" and adx_data.adx_value >= self.adx_filter.config.adx_threshold:
                    logger.warning(
                        f"🚫 XRP-USDT SHORT заблокирован: сильный BULLISH тренд "
                        f"(ADX={adx_data.adx_value:.1f}, +DI={adx_data.plus_di:.1f}, -DI={adx_data.minus_di:.1f})"
                    )
                    continue  # Пропускаем этот сигнал
        except Exception as e:
            logger.debug(f"⚠️ Ошибка проверки ADX для XRP-USDT SHORT: {e}, разрешаем сигнал")
    
    filtered_signals.append(signal)

return filtered_signals
```

---

## ✅ ИТОГОВЫЙ ЧЕКЛИСТ

- [x] ✅ Проверены все связанные участки кода
- [x] ✅ Проверены все зависимости
- [x] ✅ Составлен полный список изменений
- [ ] ⏳ Исправить `_update_peak_profit` для убыточных позиций
- [ ] ⏳ Убрать `ph_time_limit` для экстремальных прибылей (>= 2x threshold)
- [ ] ⏳ Увеличить `ph_time_limit` в конфиге для ranging режима
- [ ] ⏳ Обновить `_check_profit_drawdown` для работы с отрицательными `peak_profit_usd`
- [ ] ⏳ Добавить фильтр для XRP-USDT SHORT (ADX фильтр)

---

## ⚠️ ВАЖНО: Ничего не сломаем!

### ✅ Проверенные зависимости:

1. **`peak_profit_usd` может быть отрицательным:**
   - ✅ `PositionMetadata` - поддерживает float (может быть отрицательным)
   - ✅ `to_dict` / `from_dict` - поддерживают float (не требуют изменений)
   - ✅ `_check_profit_drawdown` - **БУДЕТ ИСПРАВЛЕНО** для работы с отрицательными значениями

2. **`ph_time_limit` изменения:**
   - ✅ Читается из конфига динамически - изменения в конфиге применятся автоматически
   - ✅ Используется только в `_check_profit_harvesting` - **БУДЕТ ИСПРАВЛЕНО**

3. **Фильтр XRP SHORT:**
   - ✅ Добавляется в `_generate_base_signals` - не влияет на существующую логику
   - ✅ Использует существующий `adx_filter` - не требует новых зависимостей

### ✅ Безопасность изменений:

- ✅ Все изменения изолированы в отдельных методах
- ✅ Не затрагивают критичные части системы (orchestrator, websocket)
- ✅ Добавляют проверки, а не удаляют существующие
- ✅ Сохраняют обратную совместимость

---

## 🎯 Готово к реализации!

Все изменения проанализированы, зависимости проверены, риски оценены. **Можно приступать к реализации!**

