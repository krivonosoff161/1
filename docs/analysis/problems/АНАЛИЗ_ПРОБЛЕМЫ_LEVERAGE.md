# АНАЛИЗ ПРОБЛЕМЫ: Leverage и размер позиций

## Проблема

Позиции открываются с маленькими размерами:
- **BTC-USDT**: $52.81 (ожидалось $122.28) - разница -57%
- **SOL-USDT**: $43.55 (ожидалось $91.71) - разница -53%

## Причина

1. **Leverage на бирже**: 3x (старое значение)
2. **Leverage в конфиге**: 5x (новое значение)
3. **Проблема**: В sandbox mode leverage **НЕ устанавливался** на бирже
4. **Результат**: Размер позиции рассчитывается с leverage = 5x, но на бирже используется leverage = 3x

## Расчет

### Текущие позиции (leverage = 3x):
- **BTC**: margin = $17.60 → notional = $17.60 × 3 = $52.80 ✅
- **SOL**: margin = $14.52 → notional = $14.52 × 3 = $43.56 ✅

### Ожидаемые позиции (leverage = 5x):
- **BTC**: notional = $122.28 → margin = $122.28 / 5 = $24.46
- **SOL**: notional = $91.71 → margin = $91.71 / 5 = $18.34

## Исправления

### 1. Установка leverage в sandbox mode ✅
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Устанавливаем leverage для всех символов (включая sandbox)
# Это необходимо, чтобы на бирже был правильный leverage
leverage_config = getattr(self.scalping_config, "leverage", None)
if leverage_config is None or leverage_config <= 0:
    logger.warning(f"⚠️ leverage не указан в конфиге, используем 3 (fallback)")
    leverage_config = 3

for symbol in self.scalping_config.symbols:
    try:
        # ✅ ВАРИАНТ B: Устанавливаем leverage даже в sandbox mode
        await self.client.set_leverage(symbol, leverage_config)
        logger.info(f"✅ Плечо {leverage_config}x установлено для {symbol} (sandbox={self.client.sandbox})")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось установить плечо {leverage_config}x для {symbol}: {e}")
```

### 2. Проверка leverage перед открытием позиции ✅
```python
# ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем и устанавливаем leverage перед открытием позиции
leverage_config = getattr(self.scalping_config, "leverage", None)
if leverage_config is None or leverage_config <= 0:
    logger.warning(f"⚠️ leverage не указан в конфиге для {symbol}, используем 3 (fallback)")
    leverage_config = 3
try:
    await self.client.set_leverage(symbol, leverage_config)
    logger.debug(f"✅ Плечо {leverage_config}x проверено/установлено для {symbol} перед открытием позиции")
except Exception as e:
    logger.warning(f"⚠️ Не удалось установить плечо {leverage_config}x для {symbol} перед открытием: {e}")
```

## Ожидаемый результат

После исправлений:
1. ✅ Leverage будет устанавливаться даже в sandbox mode
2. ✅ Leverage будет проверяться перед каждым открытием позиции
3. ✅ Размер позиции будет соответствовать расчетам:
   - **BTC**: ~$122 (вместо $52)
   - **SOL**: ~$92 (вместо $43)

## Следующие шаги

1. Перезапустить бота
2. Проверить логи на установку leverage
3. Дождаться закрытия старых позиций или закрыть их вручную
4. Проверить, что новые позиции открываются с правильными размерами

## Важно

- Старые позиции были открыты со старым leverage (3x)
- Новые позиции будут открываться с новым leverage (5x)
- Размер позиций увеличится примерно в 2.3 раза (5x / 3x = 1.67, но также учтены другие факторы)

