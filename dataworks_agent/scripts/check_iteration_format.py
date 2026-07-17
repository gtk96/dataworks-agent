import sys

sys.stdout.reconfigure(encoding='utf-8')
async def main():
    from dataworks_agent.agent.core import ChatAgent
    agent = ChatAgent()
    r = await agent.chat("forward model DWD and DWS", execution_mode="plan", initialize_data=False)
    loop_data = r.data.get("loop", {})
    iters = loop_data.get("iterations", [])
    if iters:
        it0 = iters[0]
        print(f"iteration keys: {list(it0.keys())}")
        res = it0.get("result")
        print(f"result type: {type(res)}")
        if isinstance(res, dict):
            print(f"result keys: {list(res.keys())[:10]}")
            inner_data = res.get("data", {})
            print(f"result.data keys: {list(inner_data.keys())[:10]}")
            print(f"result.data.loop is loop_data: {inner_data.get('loop') is loop_data}")
        elif hasattr(res, '__dict__'):
            print(f"result attrs: {list(res.__dict__.keys())[:10]}")

import asyncio

asyncio.run(main())
