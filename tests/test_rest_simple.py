#!/usr/bin/env python3
"""
Простой REST API тест без emoji и Unicode
"""

import asyncio
import time

import aiohttp


async def test_connection(url, name):
    """Тест простого подключения"""
    print(f"\nTesting: {name}")
    print(f"URL: {url}")
    print("-" * 60)

    timeout = aiohttp.ClientTimeout(total=10)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            print(f"[1] Creating session...")

            print(f"[2] Making GET request...")
            start = time.time()

            async with session.get(url, ssl=True) as response:
                elapsed = time.time() - start
                status = response.status

                print(f"[3] Response: status={status}, time={elapsed:.2f}s")

                try:
                    data = await response.json()
                    print(f"[4] JSON parsed OK")
                    return {"status": "OK", "code": status, "time": elapsed}
                except:
                    text = await response.text()
                    print(f"[4] Text response ({len(text)} bytes)")
                    return {"status": "OK", "code": status, "time": elapsed}

    except asyncio.TimeoutError as e:
        print(f"TIMEOUT: {e}")
        return {"status": "TIMEOUT", "error": str(e)}

    except aiohttp.ClientSSLError as e:
        print(f"SSL ERROR: {e}")
        return {"status": "SSL_ERROR", "error": str(e)[:100]}

    except aiohttp.ClientConnectorError as e:
        print(f"CONNECTION ERROR: {e}")
        return {"status": "CONN_ERROR", "error": str(e)[:100]}

    except Exception as e:
        print(f"ERROR ({type(e).__name__}): {e}")
        return {"status": "ERROR", "error": str(e)[:100]}


async def main():
    print("=" * 60)
    print("REST API CONNECTION TEST")
    print("=" * 60)

    tests = [
        ("https://www.okx.com/api/v5/system/status", "www.okx.com - system/status"),
        ("https://api.okx.com/api/v5/system/status", "api.okx.com - system/status"),
        (
            "https://www.okx.com/api/v5/public/instruments?instType=SWAP",
            "www.okx.com - instruments",
        ),
        (
            "https://api.okx.com/api/v5/public/instruments?instType=SWAP",
            "api.okx.com - instruments",
        ),
    ]

    results = {}

    for url, name in tests:
        result = await test_connection(url, name)
        results[name] = result
        await asyncio.sleep(2)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for name, result in results.items():
        status = result.get("status", "?")
        print(f"{status:15} | {name}")
        if result.get("error"):
            print(f"                | Error: {result['error'][:50]}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
