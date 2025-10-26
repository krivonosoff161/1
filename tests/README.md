# 🧪 Tests Directory Structure

## 📁 Структура папок

```
tests/
├── main/           # Основные тесты системы
├── unit/           # Unit тесты (модульные)
├── integration/    # Integration тесты (интеграционные)
├── debug/          # Debug скрипты и диагностика
├── check/          # Проверочные скрипты
├── emergency/      # Экстренные скрипты
└── backtest/       # Backtest тесты
```

## 📋 Описание папок

### 🎯 `main/` - Основные тесты
- **Назначение**: Основные тесты торговой системы
- **Файлы**: `test_*.py`, `analyze_trades.py`
- **Примеры**:
  - `test_full_trading_system.py` - полный тест торговой системы
  - `test_maker_strategy.py` - тест Maker стратегии
  - `test_manual_pool_strategy.py` - тест Manual Pool стратегии

### 🔬 `unit/` - Unit тесты
- **Назначение**: Тестирование отдельных модулей
- **Файлы**: `test_*.py` для каждого модуля
- **Примеры**:
  - `test_adaptive_regime.py` - тест Adaptive Regime Manager
  - `test_balance_checker.py` - тест Balance Checker
  - `test_correlation.py` - тест Correlation Manager

### 🔗 `integration/` - Integration тесты
- **Назначение**: Тестирование взаимодействия модулей
- **Файлы**: `test_*.py` для интеграционных тестов
- **Примеры**:
  - `test_okx_signature.py` - тест подписи OKX API

### 🐛 `debug/` - Debug скрипты
- **Назначение**: Диагностика и отладка проблем
- **Файлы**: `debug_*.py`, `diagnose_*.py`
- **Примеры**:
  - `debug_oco_orders.py` - отладка OCO ордеров
  - `debug_batch_api.py` - отладка Batch API
  - `debug_post_only.py` - отладка POST-ONLY ордеров

### ✅ `check/` - Проверочные скрипты
- **Назначение**: Проверка состояния системы
- **Файлы**: `check_*.py`, `final_*.py`
- **Примеры**:
  - `check_exchange_status.py` - проверка статуса биржи
  - `check_borrowed_funds.py` - проверка займов
  - `final_exchange_check.py` - финальная проверка биржи

### 🚨 `emergency/` - Экстренные скрипты
- **Назначение**: Экстренные действия и очистка
- **Файлы**: `emergency_*.py`, `cancel_*.py`
- **Примеры**:
  - `emergency_cancel_oco.py` - экстренная отмена OCO ордеров
  - `cancel_test_orders.py` - отмена тестовых ордеров

### 📊 `backtest/` - Backtest тесты
- **Назначение**: Тестирование стратегий на исторических данных
- **Файлы**: `test_*.py` для backtest

## 🚀 Как запускать тесты

### Основные тесты:
```bash
python tests/main/test_full_trading_system.py
python tests/main/test_maker_strategy.py
```

### Unit тесты:
```bash
python tests/unit/test_adaptive_regime.py
python tests/unit/test_balance_checker.py
```

### Debug скрипты:
```bash
python tests/debug/debug_oco_orders.py
python tests/debug/debug_batch_api.py
```

### Проверочные скрипты:
```bash
python tests/check/check_exchange_status.py
python tests/check/check_borrowed_funds.py
```

### Экстренные скрипты:
```bash
python tests/emergency/emergency_cancel_oco.py
python tests/emergency/cancel_test_orders.py
```

## 📝 Правила именования

- **Основные тесты**: `test_*.py`
- **Debug скрипты**: `debug_*.py`
- **Проверочные скрипты**: `check_*.py`
- **Экстренные скрипты**: `emergency_*.py`
- **Unit тесты**: `test_*.py`
- **Integration тесты**: `test_*.py`

## ⚠️ Важные замечания

1. **Все тесты должны быть в соответствующих папках**
2. **Не создавать тесты в корне проекта**
3. **Обновлять импорты при перемещении файлов**
4. **Документировать новые тесты в этом README**

## 🔧 Обновление импортов

При перемещении файлов обновляйте импорты:

```python
# Было (в корне):
from src.okx_client import OKXClient

# Стало (в tests/):
import sys
sys.path.append('..')
from src.okx_client import OKXClient
```

---

**Последнее обновление**: 26.10.2025  
**Автор**: Trading Bot Team
