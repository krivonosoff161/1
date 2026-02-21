# 🚨 CRITICAL FIXES REQUIRED - Priority List

## ISSUE #1: NoneType.__format__ Error in ParameterProvider 🔴 CRITICAL

**Location:** `src/strategies/scalping/futures/config/parameter_provider.py`

**Symptom in logs:**
```
ParameterProvider: Error applying adaptive params for ETH-USDT:
unsupported format string passed to NoneType.__format__
```

**Impact:** Blocks calculation of TP/SL parameters for position exits

**Where it happens:** During `_apply_adaptive_exit_params()` when formatting None value

**Solution:** Add null-check before using f-string formatting

**Action:** Find the line with f-string formatting of potentially None value
Example problematic code:
```python
f"some value = {none_variable:>10}"  # ❌ Crashes
```

Fix:
```python
none_variable = none_variable or "0"  # ✅ Safe
f"some value = {none_variable:>10}"
```

---

## ISSUE #2: Margin Ratio = 0.10 (CRITICAL) 🔴 CRITICAL

**Location:** `src/strategies/scalping/futures/calculations/margin_calculator.py`

**Symptom in logs:**
```
[MARGIN_RATIO] safe=False | margin_ratio=0.10 [CRITICAL]
(threshold=1.80)
```

**Impact:** 
- Margin ratio of 0.10 means available margin is ONLY 10% of needed
- Normal threshold: 1.80 (180%)
- Position can be LIQUIDATED

**Root cause:** Leverage too high (7x) relative to position size and account

**Solution:** 
1. Lower leverage from 7x to 5x, OR
2. Reduce position size by 30%, OR  
3. Increase min_holding_minutes to exit faster

**Recommended fix:**
```yaml
# In config_futures.yaml
trading:
  default_leverage: 5x  # Was: 7x
  
risk:
  max_margin_ratio: 0.90  # 90% available margin before blocking
```

---

## ISSUE #3: ADX Not Calculated for BTC-USDT, DOGE-USDT 🟠 HIGH

**Location:** `src/strategies/scalping/futures/indicators/`

**Symptom in logs:**
```
[ADX] BTC-USDT: ADX NOT found in indicators
      ADX is NOT CALCULATED (NOT DEFINED)
```

**Impact:** Cannot generate signals for these symbols (blocks trades)

**Root cause:** ADX indicator initialization fails on second+ trade cycle

**Solution:** Ensure FastADX is re-initialized or cached correctly

**Check:**
- [ ] Is FastADX.__init__() called each cycle?
- [ ] Is indicator state properly stored in DataRegistry?
- [ ] Are candles loaded for 1m before ADX calculation?

---

## ISSUE #4: Slow Trade Cycle (6.8s vs 5.0s limit) 🟡 MEDIUM

**Location:** `src/strategies/scalping/futures/core/trading_control_center.py`

**Symptom in logs:**
```
TCC: Slow cycle 6808.9ms (limit: 5000ms). Optimization needed!
```

**Impact:** Delayed signal processing, missed trades

**Root cause:** REST API timeouts during phase initialization

**Solution:** 
1. Run REST requests in background tasks (don't wait for all)
2. Use cached data from previous cycle if available
3. Implement timeout of 2 seconds per REST call, fail gracefully

**Code pattern:**
```python
# ❌ Current (blocks everything)
balance = await client.get_balance()  # Times out
positions = await client.get_positions()  # Never reached

# ✅ Fixed (non-blocking)
try:
    balance = await asyncio.wait_for(client.get_balance(), timeout=2)
except asyncio.TimeoutError:
    balance = self.cached_balance or 0  # Use cached value
```

---

## ACTION PLAN

### Step 1: Fix NoneType Error (5 min)
```bash
grep -n "f\".*{.*:>" src/strategies/scalping/futures/config/parameter_provider.py
# Find line with None formatting issue
# Add null-check: variable = variable or "0"
```

### Step 2: Reduce Leverage (2 min)
```bash
# In config/config_futures.yaml
# Change default_leverage from 7x to 5x
```

### Step 3: Fix ADX Calculation (10 min)
```bash
# Check indicator_manager.py or fast_adx.py
# Ensure FastADX is initialized with candles before use
# Add safeguard: if no ADX, return default trend
```

### Step 4: Optimize REST Calls (15 min)
```bash
# In trading_control_center.py
# Wrap REST calls in asyncio.wait_for() with timeout
# Use cached values as fallback
# Run non-critical REST in background
```

### Step 5: Test
```bash
python run.py --mode futures
# Watch for:
# - No NoneType errors ✅
# - Margin ratio > 1.0 ✅
# - ADX values for all symbols ✅
# - Cycle time < 5s ✅
```

---

## FILES TO MODIFY

1. **parameter_provider.py** - Add null-checks before f-string formatting
2. **config_futures.yaml** - Reduce leverage to 5x
3. **fast_adx.py or indicator_manager.py** - Ensure ADX always initialized
4. **trading_control_center.py** - Add timeouts to REST calls
5. **margin_calculator.py** - Add more conservative margin check

---

Generated: 2026-01-07 17:40:00  
Status: READY TO FIX
