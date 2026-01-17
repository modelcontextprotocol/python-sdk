import asyncio
import time


def fetch_sync(name: str, delay: float) -> str:
    time.sleep(delay)
    return f"{name} done"

async def fetch_async(name: str, delay: float) -> str:
    await asyncio.sleep(delay)  # yields control to event loop
    return f"{name} done"

async def main():
    start = time.perf_counter()

    
    result1 = await fetch_async("A", 1)
    
    result2 = fetch_sync("B", 1)
    # result2 = await fetch_async("B", 1)

    result3 = await fetch_async("C", 1)

    # print(f"{result1} | {result2} | {result3} | {result4}")
    print(f"{result1} | {result2} | {result3}")
    print("elapsed:", round(time.perf_counter() - start, 2), "seconds")

if __name__ == "__main__":
    asyncio.run(main())