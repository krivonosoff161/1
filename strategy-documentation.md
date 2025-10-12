# Документация торговой стратегии и алгоритмов

## 🎯 Обзор стратегии Enhanced Scalping v2.0

### Основные принципы

**Enhanced Scalping v2.0** - это продвинутая высокочастотная торговая стратегия, разработанная для получения прибыли от краткосрочных движений цены на криптовалютном рынке. Стратегия использует комбинацию технических индикаторов, машинного обучения и адаптивных алгоритмов.

### Ключевые улучшения по сравнению с базовой версией

1. **Адаптивные индикаторы** - автоматическая подстройка параметров под волатильность рынка
2. **Мультирежимная работа** - различные настройки для трендовых и боковых рынков
3. **Корреляционный анализ** - защита от системного риска
4. **Kelly Criterion** - оптимизация размера позиций для максимизации долгосрочной прибыли
5. **Многоуровневые выходы** - пирамидинг take-profit для максимизации прибыли
6. **Фильтры времени** - торговля только в оптимальные периоды

---

## 📊 Технические индикаторы и их применение

### 1. Адаптивный RSI (Relative Strength Index)

**Назначение:** Определение условий перекупленности/перепроданности с адаптацией к волатильности.

**Улучшения:**
- Динамическая подстройка периода расчета (10-20) в зависимости от ATR
- Адаптивные границы overbought/oversold
- Учет скорости изменения RSI (momentum)

```python
class EnhancedRSI:
    def __init__(self, base_period=14, adaptive=True):
        self.base_period = base_period
        self.adaptive = adaptive
        self.min_period = 10
        self.max_period = 20
    
    def calculate(self, prices, atr_values=None):
        if self.adaptive and atr_values is not None:
            # Адаптация периода на основе волатильности
            volatility_ratio = atr_values[-1] / np.mean(atr_values[-20:])
            if volatility_ratio > 1.5:  # Высокая волатильность
                period = max(self.min_period, int(self.base_period * 0.7))
            elif volatility_ratio < 0.7:  # Низкая волатильность
                period = min(self.max_period, int(self.base_period * 1.3))
            else:
                period = self.base_period
        else:
            period = self.base_period
            
        # Стандартный расчет RSI с адаптивным периодом
        rsi = self._calculate_rsi(prices, period)
        
        # Определение адаптивных границ
        if atr_values is not None:
            market_regime = self._detect_market_regime(prices, atr_values)
            overbought, oversold = self._get_adaptive_levels(market_regime)
        else:
            overbought, oversold = 70, 30
            
        return {
            'value': rsi,
            'overbought': overbought,
            'oversold': oversold,
            'trend': self._calculate_rsi_trend(rsi),
            'divergence': self._detect_divergence(prices, rsi)
        }
```

**Сигналы:**
- **Long:** RSI < 30 (перепроданность) или RSI восстанавливается от oversold
- **Short:** RSI > 70 (перекупленность) или RSI снижается от overbought
- **Фильтр:** Дивергенция между ценой и RSI усиливает сигнал

### 2. Адаптивный MACD

**Назначение:** Определение трендов и точек разворота с подстройкой под рыночные условия.

**Улучшения:**
- Адаптивные периоды EMA в зависимости от волатильности
- Дополнительный анализ гистограммы MACD
- Детекция бычьих/медвежьих дивергенций

```python
class AdaptiveMACD:
    def __init__(self, fast=12, slow=26, signal=9, adaptive=True):
        self.base_fast = fast
        self.base_slow = slow
        self.base_signal = signal
        self.adaptive = adaptive
    
    def calculate(self, prices, volume=None, atr=None):
        if self.adaptive and atr is not None:
            # Адаптация под волатильность
            volatility_factor = np.mean(atr[-5:]) / np.mean(atr[-20:])
            
            if volatility_factor > 1.2:  # Высокая волатильность - быстрее реакция
                fast_period = max(8, int(self.base_fast * 0.8))
                slow_period = max(18, int(self.base_slow * 0.8))
            elif volatility_factor < 0.8:  # Низкая волатильность - медленнее
                fast_period = min(16, int(self.base_fast * 1.2))
                slow_period = min(35, int(self.base_slow * 1.2))
            else:
                fast_period = self.base_fast
                slow_period = self.base_slow
        else:
            fast_period = self.base_fast
            slow_period = self.base_slow
        
        # Расчет MACD с адаптивными периодами
        ema_fast = self._ema(prices, fast_period)
        ema_slow = self._ema(prices, slow_period)
        macd_line = ema_fast - ema_slow
        signal_line = self._ema(macd_line, self.base_signal)
        histogram = macd_line - signal_line
        
        return {
            'macd_line': macd_line,
            'signal_line': signal_line,
            'histogram': histogram,
            'crossover': self._detect_crossover(macd_line, signal_line),
            'divergence': self._detect_macd_divergence(prices, macd_line)
        }
```

**Сигналы:**
- **Long:** MACD пересекает signal line снизу вверх + положительная дивергенция
- **Short:** MACD пересекает signal line сверху вниз + отрицательная дивергенция
- **Фильтр:** Сила сигнала зависит от величины расхождения линий

### 3. Волатильностные полосы (Adaptive Bollinger Bands)

**Назначение:** Определение уровней поддержки/сопротивления и экстремальных движений.

**Улучшения:**
- Адаптивный мультипликатор стандартного отклонения
- Учет рыночного режима (trending/ranging)
- Дополнительные промежуточные полосы

```python
class VolatilityBands:
    def __init__(self, period=20, std_multiplier=2.0, adaptive=True):
        self.period = period
        self.base_multiplier = std_multiplier
        self.adaptive = adaptive
    
    def calculate(self, prices, atr=None, volume=None):
        sma = self._sma(prices, self.period)
        std = self._rolling_std(prices, self.period)
        
        if self.adaptive:
            # Адаптация мультипликатора
            market_regime = self._detect_regime(prices, atr)
            
            if market_regime == 'trending':
                multiplier = self.base_multiplier * 1.2  # Шире для трендов
            elif market_regime == 'ranging':
                multiplier = self.base_multiplier * 0.8  # Уже для бокового движения
            elif market_regime == 'high_volatility':
                multiplier = self.base_multiplier * 1.5  # Намного шире
            else:
                multiplier = self.base_multiplier
        else:
            multiplier = self.base_multiplier
        
        upper_band = sma + (std * multiplier)
        lower_band = sma - (std * multiplier)
        
        # Промежуточные уровни для частичных выходов
        upper_mid = sma + (std * multiplier * 0.5)
        lower_mid = sma - (std * multiplier * 0.5)
        
        return {
            'upper_band': upper_band,
            'middle_band': sma,
            'lower_band': lower_band,
            'upper_mid': upper_mid,
            'lower_mid': lower_mid,
            'bandwidth': (upper_band - lower_band) / sma * 100,
            'position': self._calculate_bb_position(prices[-1], lower_band, upper_band)
        }
```

### 4. Объемный анализ

**VWAP (Volume Weighted Average Price):**
- Определение справедливой цены с учетом объемов
- Использование как динамический уровень поддержки/сопротивления

**Volume Profile:**
- Анализ распределения объемов по ценовым уровням
- Определение зон высокой ликвидности

**Order Book Imbalance:**
- Анализ дисбаланса заявок в стакане
- Прогнозирование краткосрочного направления движения

---

## 🧠 Алгоритмы машинного обучения

### 1. Детектор рыночного режима

Классифицирует текущее состояние рынка для адаптации параметров стратегии:

```python
class MarketRegimeDetector:
    def __init__(self):
        self.regimes = ['trending', 'ranging', 'high_volatility', 'low_volatility', 'news_event']
        self.features = []
        
    def extract_features(self, prices, volumes, atr):
        """Извлечение признаков для классификации"""
        return {
            'trend_strength': self._calculate_trend_strength(prices),
            'volatility_ratio': atr[-1] / np.mean(atr[-20:]),
            'volume_ratio': volumes[-1] / np.mean(volumes[-20:]),
            'price_momentum': (prices[-1] / prices[-20] - 1) * 100,
            'volatility_acceleration': self._volatility_acceleration(atr),
            'volume_trend': self._volume_trend(volumes)
        }
    
    def detect_regime(self, market_data):
        """Определение текущего режима рынка"""
        features = self.extract_features(
            market_data.prices, 
            market_data.volumes, 
            market_data.atr
        )
        
        # Логика определения режима
        if features['volatility_ratio'] > 2.0:
            return MarketRegime.HIGH_VOLATILITY
        elif features['volatility_ratio'] < 0.5:
            return MarketRegime.LOW_VOLATILITY
        elif abs(features['trend_strength']) > 0.7:
            return MarketRegime.TRENDING
        elif features['volume_ratio'] > 3.0:
            return MarketRegime.NEWS_EVENT
        else:
            return MarketRegime.RANGING
```

### 2. Корреляционный анализ

Предотвращает открытие коррелированных позиций для снижения системного риска:

```python
class CorrelationMatrix:
    def __init__(self, symbols, lookback_period=50):
        self.symbols = symbols
        self.lookback_period = lookback_period
        self.correlation_matrix = None
        
    def calculate_correlations(self, price_data):
        """Расчет корреляционной матрицы"""
        returns_data = {}
        
        for symbol in self.symbols:
            prices = price_data[symbol][-self.lookback_period:]
            returns = np.diff(np.log(prices))
            returns_data[symbol] = returns
        
        # Построение корреляционной матрицы
        df = pd.DataFrame(returns_data)
        self.correlation_matrix = df.corr()
        
        return self.correlation_matrix
    
    def get_correlation_risk(self, new_symbol, existing_positions):
        """Расчет корреляционного риска для новой позиции"""
        if self.correlation_matrix is None:
            return 0.0
        
        max_correlation = 0.0
        
        for existing_symbol in existing_positions.keys():
            if existing_symbol in self.correlation_matrix.columns and new_symbol in self.correlation_matrix.columns:
                correlation = abs(self.correlation_matrix.loc[new_symbol, existing_symbol])
                max_correlation = max(max_correlation, correlation)
        
        return max_correlation
```

---

## 💰 Система управления капиталом

### Kelly Criterion для оптимального sizing

Автоматический расчет оптимального размера позиции на основе исторической производительности:

```python
class KellyCriterionCalculator:
    def __init__(self, lookback_trades=100):
        self.lookback_trades = lookback_trades
        self.trade_history = []
        
    def add_trade_result(self, pnl_percent):
        """Добавление результата сделки"""
        self.trade_history.append(pnl_percent)
        
        # Ограничение размера истории
        if len(self.trade_history) > self.lookback_trades * 2:
            self.trade_history = self.trade_history[-self.lookback_trades:]
    
    def calculate_kelly_fraction(self):
        """Расчет оптимальной Kelly fraction"""
        if len(self.trade_history) < 20:
            return 0.25  # Консервативная стартовая фракция
        
        recent_trades = self.trade_history[-self.lookback_trades:]
        
        # Разделение на выигрышные и проигрышные
        wins = [trade for trade in recent_trades if trade > 0]
        losses = [abs(trade) for trade in recent_trades if trade < 0]
        
        if not wins or not losses:
            return 0.25
        
        # Kelly formula: f = (bp - q) / b
        win_rate = len(wins) / len(recent_trades)  # p
        loss_rate = 1 - win_rate  # q
        avg_win = np.mean(wins)  # среднее выигрыша
        avg_loss = np.mean(losses)  # среднее проигрыша
        win_loss_ratio = avg_win / avg_loss  # b
        
        kelly_fraction = (win_loss_ratio * win_rate - loss_rate) / win_loss_ratio
        
        # Применение ограничений безопасности
        kelly_fraction = max(0.01, min(0.4, kelly_fraction))  # От 1% до 40%
        
        # Дополнительные корректировки
        kelly_fraction = self._apply_market_adjustments(kelly_fraction)
        
        return kelly_fraction
    
    def _apply_market_adjustments(self, base_kelly):
        """Корректировки Kelly на основе рыночных условий"""
        # Консерватизм в периоды высокой волатильности
        recent_volatility = self._calculate_recent_volatility()
        
        if recent_volatility > 1.5:  # Высокая волатильность
            return base_kelly * 0.7
        elif recent_volatility < 0.7:  # Низкая волатильность
            return base_kelly * 1.1
        else:
            return base_kelly
```

### Многоуровневая система выходов

Пирамидинг take-profit для максимизации прибыли от сильных движений:

```python
class MultiLevelExitManager:
    def __init__(self):
        self.exit_levels = []
        self.partial_exits = {}
        
    def create_exit_strategy(self, entry_price, direction, atr, market_regime):
        """Создание многоуровневой стратегии выхода"""
        
        # Адаптация уровней под рыночный режим
        if market_regime == MarketRegime.HIGH_VOLATILITY:
            tp_multipliers = [1.8, 3.5, 6.0]  # Более широкие цели
            sl_multiplier = 2.2
            size_distribution = [0.4, 0.35, 0.25]  # Более равномерное распределение
        elif market_regime == MarketRegime.TRENDING:
            tp_multipliers = [1.5, 4.0, 8.0]  # Дальние цели для трендов
            sl_multiplier = 2.0
            size_distribution = [0.3, 0.3, 0.4]  # Больше для дальних уровней
        else:  # RANGING или обычный режим
            tp_multipliers = [1.2, 2.5, 4.0]
            sl_multiplier = 1.8
            size_distribution = [0.5, 0.3, 0.2]
        
        exit_strategy = []
        
        for i, (tp_mult, size_pct) in enumerate(zip(tp_multipliers, size_distribution)):
            if direction == 'long':
                tp_price = entry_price + (atr * tp_mult)
            else:
                tp_price = entry_price - (atr * tp_mult)
            
            exit_strategy.append({
                'type': 'take_profit',
                'level': i + 1,
                'price': tp_price,
                'size_percent': size_pct,
                'description': f'TP{i+1}'
            })
        
        # Stop Loss
        if direction == 'long':
            sl_price = entry_price - (atr * sl_multiplier)
        else:
            sl_price = entry_price + (atr * sl_multiplier)
        
        exit_strategy.append({
            'type': 'stop_loss',
            'level': 0,
            'price': sl_price,
            'size_percent': 1.0,  # Весь остаток позиции
            'description': 'SL'
        })
        
        return exit_strategy
    
    def check_exit_conditions(self, current_price, position, market_data):
        """Проверка условий выхода"""
        exits_to_execute = []
        
        # Проверка временного лимита
        if self._is_time_limit_exceeded(position):
            exits_to_execute.append({
                'type': 'time_exit',
                'reason': 'max_holding_time_exceeded',
                'size_percent': 1.0
            })
        
        # Проверка технических условий выхода
        technical_exit = self._check_technical_exit(position, market_data)
        if technical_exit:
            exits_to_execute.append(technical_exit)
        
        # Проверка уровней TP/SL
        for exit_level in position.exit_levels:
            if not exit_level.get('executed', False):
                if self._is_level_hit(current_price, exit_level, position.direction):
                    exits_to_execute.append(exit_level)
        
        return exits_to_execute
```

---

## 📈 Система мониторинга производительности

### Метрики в реальном времени

```python
class PerformanceTracker:
    def __init__(self):
        self.trades = []
        self.equity_curve = []
        self.daily_returns = []
        
    def calculate_comprehensive_metrics(self):
        """Расчет всесторонних метрик производительности"""
        
        if not self.trades:
            return {}
        
        # Базовые метрики
        total_trades = len(self.trades)
        winning_trades = len([t for t in self.trades if t.pnl > 0])
        
        # Расширенные метрики
        metrics = {
            # Основные
            'total_trades': total_trades,
            'win_rate': winning_trades / total_trades * 100,
            'total_pnl': sum(t.pnl for t in self.trades),
            
            # Риск-метрики
            'sharpe_ratio': self._calculate_sharpe_ratio(),
            'sortino_ratio': self._calculate_sortino_ratio(),
            'calmar_ratio': self._calculate_calmar_ratio(),
            'max_drawdown': self._calculate_max_drawdown(),
            
            # Консистентность
            'profit_factor': self._calculate_profit_factor(),
            'expectancy': self._calculate_expectancy(),
            'kelly_fraction': self._get_current_kelly(),
            
            # Временные метрики
            'avg_trade_duration': self._calculate_avg_duration(),
            'trades_per_day': self._calculate_trade_frequency(),
            
            # Распределение
            'win_loss_distribution': self._analyze_win_loss_distribution(),
            'monthly_returns': self._calculate_monthly_returns(),
            
            # Стрессовые периоды
            'worst_month': self._find_worst_period('month'),
            'worst_week': self._find_worst_period('week'),
            'recovery_factor': self._calculate_recovery_factor()
        }
        
        return metrics
    
    def _calculate_sharpe_ratio(self, risk_free_rate=0.02):
        """Коэффициент Шарпа"""
        if len(self.daily_returns) < 30:
            return 0.0
        
        excess_returns = np.array(self.daily_returns) - (risk_free_rate / 365)
        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(365)
    
    def _calculate_sortino_ratio(self, risk_free_rate=0.02):
        """Коэффициент Сортино (учитывает только downside риск)"""
        if len(self.daily_returns) < 30:
            return 0.0
        
        returns = np.array(self.daily_returns)
        excess_returns = returns - (risk_free_rate / 365)
        downside_returns = returns[returns < 0]
        
        if len(downside_returns) == 0:
            return float('inf')
        
        downside_deviation = np.std(downside_returns)
        return np.mean(excess_returns) / downside_deviation * np.sqrt(365)
```

### Система алертов и уведомлений

```python
class AlertSystem:
    def __init__(self):
        self.alert_rules = {
            'drawdown_alert': {'threshold': -3.0, 'enabled': True},
            'win_rate_alert': {'threshold': 45.0, 'enabled': True},
            'daily_loss_alert': {'threshold': -1.5, 'enabled': True},
            'technical_failure': {'threshold': 5, 'enabled': True},  # ошибок подряд
        }
        
    async def check_performance_alerts(self, metrics):
        """Проверка алертов по производительности"""
        alerts = []
        
        # Алерт по просадке
        if (metrics.get('current_drawdown', 0) < self.alert_rules['drawdown_alert']['threshold'] 
            and self.alert_rules['drawdown_alert']['enabled']):
            alerts.append({
                'type': 'drawdown',
                'level': 'WARNING',
                'message': f"Drawdown exceeded {self.alert_rules['drawdown_alert']['threshold']}%",
                'value': metrics['current_drawdown'],
                'action': 'Consider reducing position sizes'
            })
        
        # Алерт по винрейту
        if (metrics.get('win_rate', 100) < self.alert_rules['win_rate_alert']['threshold']
            and self.alert_rules['win_rate_alert']['enabled']):
            alerts.append({
                'type': 'win_rate',
                'level': 'INFO',
                'message': f"Win rate below {self.alert_rules['win_rate_alert']['threshold']}%",
                'value': metrics['win_rate'],
                'action': 'Review entry conditions'
            })
        
        return alerts
```

Эта документация обеспечивает полное понимание алгоритмов и принципов работы улучшенной торговой стратегии, а также методов мониторинга и оптимизации производительности.