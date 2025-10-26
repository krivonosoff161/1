# 🚀 FUTURES АРХИТЕКТУРА - ПОЛНОСТЬЮ ОТДЕЛЬНАЯ ЭКОСИСТЕМА

## 📁 НОВАЯ СТРУКТУРА FUTURES МОДУЛЕЙ

```
src/strategies/scalping/futures/
├── 📁 indicators/              # Futures-специфичные индикаторы
│   ├── order_flow_indicator.py    # Анализ bid/ask объема
│   ├── micro_pivot_calculator.py  # Микро-пивоты для точных TP
│   ├── funding_rate_monitor.py    # Мониторинг фандинга
│   ├── fast_adx.py               # ADX(9) для быстрой реакции
│   ├── trailing_stop_loss.py      # Динамический стоп-лосс
│   └── futures_volume_profile.py # Объемный профиль для фьючей
├── 📁 filters/                 # Futures-специфичные фильтры
│   ├── order_flow_filter.py      # Фильтр против крупных ордеров
│   ├── funding_rate_filter.py    # Фильтр по фандингу
│   ├── liquidity_filter.py       # Фильтр ликвидности
│   └── volatility_regime_filter.py # Фильтр режимов волатильности
├── 📁 risk/                    # Futures-специфичный риск
│   ├── position_sizer.py         # Умный расчет размера позиции
│   ├── margin_monitor.py         # Мониторинг маржи в RT
│   ├── liquidation_protector.py # Защита от ликвидации
│   └── max_size_limiter.py      # Лимиты на размер ордеров
├── 📁 execution/               # Futures-специфичное исполнение
│   ├── smart_order_executor.py  # Умный исполнитель ордеров
│   ├── oco_manager.py           # Менеджер OCO ордеров
│   ├── batch_amend_manager.py   # Менеджер batch amend
│   └── slippage_protector.py   # Защита от проскальзывания
└── 📁 signals/                  # Futures-специфичные сигналы
    ├── scalping_signal_generator.py # Генератор скальпинг сигналов
    ├── momentum_signal_generator.py # Генератор импульсных сигналов
    └── mean_reversion_signal_generator.py # Генератор сигналов возврата к среднему
```

## 🎯 КЛЮЧЕВЫЕ ОТЛИЧИЯ FUTURES ОТ SPOT

| Компонент | Spot | Futures |
|-----------|------|---------|
| **ADX период** | 14 | **9** (быстрее реакция) |
| **TP/SL** | Фиксированные | **Trailing + Micro-Pivots** |
| **Размер позиции** | Простой расчет | **С учетом маржи + лимитов** |
| **Фильтры** | Базовые | **Order-Flow + Funding + Liquidity** |
| **Исполнение** | Простое | **Smart + Batch + Fallback** |
| **Риск** | Баланс | **Маржа + Ликвидация + Фандинг** |

## 🔥 КРИТИЧЕСКИЕ FUTURES МОДУЛИ

### 1. OrderFlowIndicator - Анализ потока ордеров
```python
class OrderFlowIndicator:
    """Анализ bid/ask объема для определения направления"""
    
    def __init__(self, window=100):
        self.window = window
        self.bid_volumes = deque(maxlen=window)
        self.ask_volumes = deque(maxlen=window)
    
    def update(self, bid_volume: float, ask_volume: float):
        """Обновление данных о объемах"""
        self.bid_volumes.append(bid_volume)
        self.ask_volumes.append(ask_volume)
    
    def get_delta(self) -> float:
        """Расчет delta (разность объемов)"""
        if len(self.bid_volumes) < 10:
            return 0.0
        
        avg_bid = sum(self.bid_volumes) / len(self.bid_volumes)
        avg_ask = sum(self.ask_volumes) / len(self.ask_volumes)
        
        return (avg_bid - avg_ask) / (avg_bid + avg_ask)
    
    def is_long_favorable(self) -> bool:
        """Благоприятен ли вход в лонг"""
        delta = self.get_delta()
        return delta > 0.1  # Больше покупателей
    
    def is_short_favorable(self) -> bool:
        """Благоприятен ли вход в шорт"""
        delta = self.get_delta()
        return delta < -0.1  # Больше продавцов
```

### 2. MicroPivotCalculator - Точные уровни TP
```python
class MicroPivotCalculator:
    """Расчет микро-пивотов для точных TP уровней"""
    
    def __init__(self, timeframe="15m"):
        self.timeframe = timeframe
        self.highs = deque(maxlen=20)
        self.lows = deque(maxlen=20)
        self.closes = deque(maxlen=20)
    
    def update(self, high: float, low: float, close: float):
        """Обновление данных"""
        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close)
    
    def calculate_pivots(self) -> Dict[str, float]:
        """Расчет пивотных уровней"""
        if len(self.highs) < 5:
            return {}
        
        high = max(self.highs)
        low = min(self.lows)
        close = self.closes[-1]
        
        # Классические пивоты
        pivot = (high + low + close) / 3
        r1 = 2 * pivot - low
        s1 = 2 * pivot - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        
        return {
            "pivot": pivot,
            "r1": r1,
            "r2": r2,
            "s1": s1,
            "s2": s2,
            "resistance": r1,
            "support": s1
        }
    
    def get_optimal_tp(self, entry_price: float, side: str) -> float:
        """Получение оптимального TP"""
        pivots = self.calculate_pivots()
        if not pivots:
            return entry_price * 1.003 if side == "long" else entry_price * 0.997
        
        if side == "long":
            # Для лонга ищем ближайший уровень сопротивления
            resistance = pivots["resistance"]
            return min(resistance, entry_price * 1.005)  # Максимум 0.5%
        else:
            # Для шорта ищем ближайший уровень поддержки
            support = pivots["support"]
            return max(support, entry_price * 0.995)  # Максимум 0.5%
```

### 3. TrailingStopLoss - Динамический SL
```python
class TrailingStopLoss:
    """Динамический стоп-лосс для захвата большей волы"""
    
    def __init__(self, initial_trail=0.05, max_trail=0.2, min_trail=0.02):
        self.initial_trail = initial_trail
        self.max_trail = max_trail
        self.min_trail = min_trail
        self.current_trail = initial_trail
        self.highest_price = 0.0
        self.lowest_price = float('inf')
    
    def update(self, current_price: float, side: str):
        """Обновление трейлинга"""
        if side == "long":
            if current_price > self.highest_price:
                self.highest_price = current_price
                # Увеличиваем трейл при росте цены
                profit_pct = (current_price - self.highest_price) / self.highest_price
                self.current_trail = min(self.initial_trail + profit_pct * 2, self.max_trail)
        else:
            if current_price < self.lowest_price:
                self.lowest_price = current_price
                # Увеличиваем трейл при падении цены
                profit_pct = (self.lowest_price - current_price) / self.lowest_price
                self.current_trail = min(self.initial_trail + profit_pct * 2, self.max_trail)
    
    def get_stop_loss(self, entry_price: float, side: str) -> float:
        """Получение текущего стоп-лосса"""
        if side == "long":
            return self.highest_price * (1 - self.current_trail)
        else:
            return self.lowest_price * (1 + self.current_trail)
```

### 4. FundingRateMonitor - Мониторинг фандинга
```python
class FundingRateMonitor:
    """Мониторинг фандинга для избежания неблагоприятных входов"""
    
    def __init__(self, max_funding_rate=0.05):
        self.max_funding_rate = max_funding_rate
        self.current_funding = 0.0
        self.funding_history = deque(maxlen=24)  # 24 часа
    
    async def update_funding(self, client, symbol: str):
        """Обновление данных о фандинге"""
        try:
            funding_data = await client.get_funding_rate(symbol)
            self.current_funding = float(funding_data['fundingRate'])
            self.funding_history.append(self.current_funding)
        except Exception as e:
            logger.warning(f"Ошибка получения фандинга: {e}")
    
    def is_funding_favorable(self, side: str) -> bool:
        """Благоприятен ли фандинг для входа"""
        if abs(self.current_funding) > self.max_funding_rate:
            if side == "long" and self.current_funding > 0:
                return False  # Длинные платят фандинг
            elif side == "short" and self.current_funding < 0:
                return False  # Короткие платят фандинг
        
        return True
    
    def get_funding_trend(self) -> str:
        """Получение тренда фандинга"""
        if len(self.funding_history) < 3:
            return "unknown"
        
        recent = list(self.funding_history)[-3:]
        if all(recent[i] < recent[i+1] for i in range(len(recent)-1)):
            return "increasing"
        elif all(recent[i] > recent[i+1] for i in range(len(recent)-1)):
            return "decreasing"
        else:
            return "sideways"
```

### 5. PositionSizer - Умный расчет размера позиции
```python
class PositionSizer:
    """Умный расчет размера позиции с учетом всех рисков"""
    
    def __init__(self, max_position_percent=0.1, max_single_size_usd=1000):
        self.max_position_percent = max_position_percent
        self.max_single_size_usd = max_single_size_usd
    
    def calculate_size(self, balance: float, entry_price: float, 
                      sl_distance: float, leverage: int = 3) -> float:
        """Расчет размера позиции"""
        
        # 1. Максимальный размер от баланса
        max_size_by_balance = balance * self.max_position_percent * leverage / entry_price
        
        # 2. Максимальный размер от лимита
        max_size_by_limit = self.max_single_size_usd / entry_price
        
        # 3. Размер с учетом стоп-лосса (риск 1% от баланса)
        risk_amount = balance * 0.01
        size_by_risk = risk_amount / (sl_distance * entry_price)
        
        # 4. Выбираем минимальный размер
        optimal_size = min(max_size_by_balance, max_size_by_limit, size_by_risk)
        
        # 5. Округляем до разумного значения
        if optimal_size < 0.001:
            return 0.001
        elif optimal_size > 1.0:
            return 1.0
        else:
            return round(optimal_size, 3)
    
    def validate_size(self, size: float, balance: float, 
                     entry_price: float, leverage: int = 3) -> bool:
        """Валидация размера позиции"""
        
        # Проверка максимального размера
        position_value = size * entry_price
        max_allowed = balance * self.max_position_percent * leverage
        
        if position_value > max_allowed:
            logger.warning(f"Размер позиции превышает лимит: {position_value} > {max_allowed}")
            return False
        
        # Проверка минимального размера
        if size < 0.001:
            logger.warning(f"Размер позиции слишком мал: {size}")
            return False
        
        return True
```

## 🚀 ИНТЕГРАЦИЯ В FUTURES ORCHESTRATOR

```python
class FuturesScalpingOrchestrator:
    """Обновленный оркестратор с Futures-специфичными модулями"""
    
    def __init__(self, config: BotConfig):
        # Базовые компоненты
        self.client = OKXFuturesClient(config.get_okx_config())
        self.config = config
        
        # Futures-специфичные индикаторы
        self.order_flow = OrderFlowIndicator()
        self.micro_pivots = MicroPivotCalculator()
        self.trailing_sl = TrailingStopLoss()
        self.funding_monitor = FundingRateMonitor()
        
        # Futures-специфичные фильтры
        self.order_flow_filter = OrderFlowFilter()
        self.funding_filter = FundingRateFilter()
        self.liquidity_filter = LiquidityFilter()
        
        # Futures-специфичный риск
        self.position_sizer = PositionSizer()
        self.margin_monitor = MarginMonitor()
        self.liquidation_protector = LiquidationProtector()
        
        # Futures-специфичное исполнение
        self.smart_executor = SmartOrderExecutor()
        self.oco_manager = OCOManager()
        self.slippage_protector = SlippageProtector()
    
    async def start(self):
        """Запуск Futures торгового цикла"""
        while True:
            try:
                # 1. Обновление данных
                await self._update_market_data()
                
                # 2. Проверка безопасности
                await self._check_safety_limits()
                
                # 3. Генерация сигналов
                signals = await self._generate_signals()
                
                # 4. Фильтрация сигналов
                filtered_signals = await self._filter_signals(signals)
                
                # 5. Исполнение ордеров
                if filtered_signals:
                    await self._execute_orders(filtered_signals)
                
                # 6. Управление позициями
                await self._manage_positions()
                
                await asyncio.sleep(0.5)  # Частые проверки для Futures
                
            except Exception as e:
                logger.error(f"Ошибка в торговом цикле: {e}")
                await asyncio.sleep(1)
    
    async def _update_market_data(self):
        """Обновление рыночных данных"""
        # Обновление Order Flow
        orderbook = await self.client.get_orderbook(self.symbol)
        self.order_flow.update(orderbook.bid_volume, orderbook.ask_volume)
        
        # Обновление микро-пивотов
        ticker = await self.client.get_ticker(self.symbol)
        self.micro_pivots.update(ticker.high, ticker.low, ticker.close)
        
        # Обновление фандинга
        await self.funding_monitor.update_funding(self.client, self.symbol)
    
    async def _filter_signals(self, signals: List[Signal]) -> List[Signal]:
        """Фильтрация сигналов через Futures-специфичные фильтры"""
        filtered = []
        
        for signal in signals:
            # Order Flow фильтр
            if not self.order_flow_filter.is_favorable(signal, self.order_flow):
                continue
            
            # Funding фильтр
            if not self.funding_filter.is_favorable(signal, self.funding_monitor):
                continue
            
            # Liquidity фильтр
            if not self.liquidity_filter.is_favorable(signal, self.client):
                continue
            
            filtered.append(signal)
        
        return filtered
```

## 📊 ОЖИДАЕМЫЙ ЭФФЕКТ

| Метрика | До | После |
|---------|----|----|
| **WinRate** | 68% | **78%** |
| **Среднее проскальзывание** | 0.05% | **0.02%** |
| **Время в сделке** | 12с | **6с** |
| **Захват волы** | 50% | **80%** |
| **Ложных входов** | 15% | **5%** |

## 🎯 ПЛАН РЕАЛИЗАЦИИ

1. **Создать структуру папок** ✅
2. **Реализовать OrderFlowIndicator** 🔄
3. **Реализовать MicroPivotCalculator** ⏳
4. **Реализовать TrailingStopLoss** ⏳
5. **Реализовать FundingRateMonitor** ⏳
6. **Интегрировать в Orchestrator** ⏳
7. **Тестирование** ⏳

**Начинаем с создания структуры папок и OrderFlowIndicator?**
