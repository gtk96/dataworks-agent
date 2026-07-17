"""Real end-to-end verification of any_ods_modeling workflow"""
import asyncio
import sys

sys.stdout.reconfigure(encoding='utf-8')

async def test():
    from dataworks_agent.agent.core import ChatAgent

    # Test 1: Simple greeting
    print("=== Test 1: Greeting ===")
    agent = ChatAgent()
    resp = await agent.chat("你好")
    print(f"Success: {resp.success}")
    print(f"Message: {resp.message[:100]}")

    # Test 2: Check order table (the original failing case)
    print("\n=== Test 2: 查一下订单表 ===")
    resp2 = await agent.chat("查一下订单表")
    print(f"Success: {resp2.success}")
    print(f"Message: {resp2.message[:200]}")
    print(f"Error: {resp2.error}")
    if resp2.data:
        print(f"Data keys: {list(resp2.data.keys())}")

    # Test 3: Forward modeling request
    print("\n=== Test 3: 帮我搭建从OSS订单数据到DWS汇总的全链路 ===")
    resp3 = await agent.chat("帮我搭建从OSS订单数据到DWS汇总的全链路")
    print(f"Success: {resp3.success}")
    print(f"Message: {resp3.message[:200]}")
    print(f"Error: {resp3.error}")
    if resp3.data:
        print(f"Intent: {resp3.data.get('intent', {}).get('action', 'N/A')}")
        print(f"Agent mode: {resp3.data.get('agent_mode', 'N/A')}")

asyncio.run(test())
