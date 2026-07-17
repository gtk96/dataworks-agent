import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")


async def main():
    from dataworks_agent.agent.core import ChatAgent

    agent = ChatAgent()
    r = await agent.chat("forward model DWD and DWS", execution_mode="plan", initialize_data=False)
    loop_data = r.data["loop"]
    iters = loop_data.get("iterations", [])
    if iters:
        res = iters[0]["result"]
        print(f"result type: {type(res).__name__}")
        if hasattr(res, "data"):
            print(f"data keys: {list(res.data.keys())}")
            print(f"has loop in data: {'loop' in res.data}")
        else:
            print(f"res keys: {list(res.keys())}")
            print(f"data keys: {list(res.get('data', {}).keys())}")
            print(f"has loop in data: {'loop' in res.get('data', {})}")


asyncio.run(main())
