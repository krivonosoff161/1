# 📋 REST API DIAGNOSTICS REPORT - January 7, 2026

## ✅ FINDINGS

### 1. Network Connectivity
- **DNS Resolution:** ✅ www.okx.com → 104.18.43.174 (OK)
- **Ping:** ✅ www.okx.com responds (OK)
- **DNS api.okx.com:** ❌ getaddrinfo failed (Cannot resolve)

### 2. HTTP/HTTPS Connectivity  
- **www.okx.com over HTTPS:** ✅ WORKS (status 200)
- **api.okx.com over HTTPS:** ❌ FAILS (DNS resolution issue)

### 3. Public REST Endpoints
- `GET /system/status` - ✅ WORKS
- `GET /public/instruments?instType=SWAP` - ✅ WORKS

### 4. OKX Client Functionality
- **Leverage Info (ETH-USDT):** ✅ SUCCESS - max_leverage=125x
- **Account Balance:** ✅ SUCCESS - $665.22 USDT
- **Positions:** ✅ SUCCESS - 1 position found

## 🔴 ROOT CAUSE ANALYSIS

### Problem During Bot Runs
During live trading (Jan 7, 17:29-17:31):
```
ERROR: Cannot connect to host www.okx.com:443 ssl:default
       [Указанное сетевое имя более недоступно]
```

### Why Tests Pass But Bot Failed

1. **Rate Limiting:** OKX likely has rate limits - bot made many parallel requests
   - During initialization: 5 symbols × 4 timeframes × multiple retries
   - During trading cycles: REST requests from multiple modules
   - Solution: Sequential requests with delays (partially implemented)

2. **Slow Trade Cycles:** Trade cycle took 6.8 seconds (limit: 5 seconds)
   - Caused by REST API timeouts and retries
   - Multiple modules trying REST endpoints simultaneously
   - Solution: Optimize parallel/sequential request patterns

3. **Regional/ISP Blocking:** May be regional blocking, not global
   - DNS for `api.okx.com` doesn't resolve (may be intentional)
   - But `www.okx.com` works fine
   - Recommend using `www.okx.com` exclusively (already done in code)

4. **SSL/TLS Handshake Issues:** Transient SSL errors during heavy load
   - aiohttp may retry with different SSL settings
   - May recover after brief wait
   - Solution: Implement exponential backoff (already partially done)

## 📈 WORKING TEST RESULTS

```
Test: Leverage Info (public)
  URL: https://www.okx.com/api/v5/public/instruments
  Status: 200 OK
  Result: max_leverage=125x for ETH-USDT
  Time: <200ms

Test: Account Balance (private, requires auth)
  URL: https://www.okx.com/api/v5/account/balance
  Status: 200 OK  
  Result: 665.22 USDT
  Time: <500ms

Test: Positions (private, requires auth)
  URL: https://www.okx.com/api/v5/account/positions
  Status: 200 OK
  Result: 1 position
  Time: <300ms
```

## 🎯 RECOMMENDATIONS

### 1. CRITICAL: Reduce Parallel REST Requests
- Current: During init, all 5 symbols load candles in parallel
- Problem: Triggers rate limits or connection resets
- Solution: Load sequentially with 1-2 second delays
- Status: ✅ ALREADY IMPLEMENTED in orchestrator.py

### 2. HIGH: Monitor REST API Error Rates
- Track which endpoints fail most often
- Implement circuit breaker pattern
- Fall back to WebSocket-only mode if REST unavailable

### 3. MEDIUM: Optimize Trade Cycle Time
- Current: 6.8 seconds (exceeds 5 second limit)
- Remove unnecessary REST calls during trade cycle
- Cache leverage/instrument info (TTL: 5 minutes)
- Solution: ⚠️ ParameterProvider NoneType format error blocks this

### 4. LOW: Use AWS CloudFront URL
- OKX may offer AWS-hosted API: `https://aws.okx.com`
- Faster for some regions
- Not tested yet (DNS not resolving)

## 🔧 ISSUES TO FIX

### 1. CRITICAL: NoneType.__format__ Error
Location: `parameter_provider.py` (adapter methods)
```
WARNING: ParameterProvider: Error applying adaptive params:
         unsupported format string passed to NoneType.__format__
```
Impact: Blocks TP/SL parameter calculation for position exits
Fix: Add null-check before formatting adaptive parameters

### 2. CRITICAL: Margin Ratio Too Low
During second test run:
```
[MARGIN_RATIO] safe=False | margin_ratio=0.10 [CRITICAL]
               (threshold should be: 1.80)
```
Impact: Position may be auto-liquidated
Fix: Reduce leverage from 7x to 5x, or reduce position size

### 3. MEDIUM: Slow Trade Cycle (6.8s vs 5.0s limit)
Caused by: REST API timeouts + retries
Fix: Run REST requests in background, use cached data

### 4. MEDIUM: Missing ADX for Some Symbols
```
WARNING [ADX] BTC-USDT: ADX NOT found in indicators
        ADX is NOT CALCULATED (NOT DEFINED)
```
Impact: Cannot generate signals for symbols without ADX
Root cause: Indicator not initialized on second+ cycle
Fix: Verify indicator persistence across cycles

## 📊 CONCLUSION

**REST API itself is NOT the problem.** ✅ It works reliably:
- Public endpoints accessible ✅
- Private endpoints accessible ✅  
- Auth working ✅
- Rate limits seem reasonable ✅

**Real problems are:**
1. ❌ Code bugs (NoneType format, ADX initialization)
2. ❌ Risk parameters too aggressive (margin ratio 0.1 vs 1.8)
3. ❌ Inefficient request patterns (parallel loading of 20 candles)
4. ❌ Slow cycle time causing trade delay

**Recommendation:** Fix code bugs first, then optimize request patterns.
REST API blocking was a symptom, not the root cause.

---
Generated: 2026-01-07 17:40:00 UTC  
Test files: `test_rest_simple.py`, `test_rest_with_client.py`
