# 🚀 PHASE 2 - MAJOR BUGS (11 bugs)

**Status:** In Planning  
**Total Remaining Bugs:** 26 (after Phase 1's 13 fixes)  

---

## 📋 Phase 2 Bugs - TIER 2 (Major Impact)

### Bug #4: 30/50 Candles Threshold (Signal Blocking)
- **Problem:** Signal generator requires 30-50 candles before generating signals
- **Impact:** Misses 30-45 minutes of trading at market open
- **Severity:** HIGH - Causes trading delays
- **File:** `signal_generator.py`
- **Complexity:** MEDIUM

### Bug #5: BB Oversold Filter (Inverted Logic)
- **Problem:** Bollinger Bands oversold filter blocking when it should allow
- **Impact:** Blocks legitimate entry opportunities in choppy markets
- **Severity:** HIGH - Signal rejection
- **File:** `signal_generator.py` or `filters/`
- **Complexity:** MEDIUM

### Bug #6: ADX Case Sensitivity (regime != REGIME)
- **Problem:** regime name case mismatch causes ADX filter lookup failure
- **Impact:** ADX filter always skipped (already partially fixed in Phase 1 #38?)
- **Severity:** HIGH - Data pipeline
- **File:** `regime_manager.py`, `signal_generator.py`
- **Complexity:** LOW

---

## 🎯 Phase 2 Strategy

1. **Bug Analysis First** (30 min)
   - Read signal_generator.py thoroughly
   - Identify exact thresholds and blocking conditions
   - Find case sensitivity issues

2. **Bug Fixes in Order** (60 min)
   - Fix #4: Lower/remove candle threshold
   - Fix #5: Invert BB logic or remove redundancy
   - Fix #6: Normalize regime names

3. **Testing** (20 min)
   - Verify signals now generate earlier
   - Check BB filter behavior
   - Validate regime names

4. **Commit Phase 2** (10 min)
   - Create PHASE_2_FIXES_COMPLETE.md
   - Commit with message "fix: Phase 2 - 3 major signal bugs fixed"

---

## 📊 Expected Impact

**Before Phase 2:**
- 132k signals in downtrend (correct)
- But missing uptrend signals (if they exist)
- BB filter may reject good entries
- ADX filter skipped on case mismatch

**After Phase 2:**
- Earlier signal generation (no 30-50 candle delay)
- Better entry opportunities detection
- Correct ADX filtering

---

## 🔍 Next Steps

1. ✅ Start: Read signal_generator.py
2. ✅ Locate: Bugs #4, #5, #6
3. ✅ Fix: Apply corrections
4. ✅ Test: Verify changes
5. ✅ Commit: All 3 bugs

**Ready?** Let me start with analysis!
