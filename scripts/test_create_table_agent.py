"""Run just the failing test"""
import asyncio
import sys

sys.path.insert(0, '.')

async def main():
    from dataworks_agent.agent.core import ChatAgent
    agent = ChatAgent()
    response = await agent.chat("创建ods_user表")
    print(f"Success: {response.success}")
    print(f"Message: {response.message[:100]}")
    print(f"Error: {response.error}")
    print(f"Data keys: {list(response.data.keys())}")

asyncio.run(main())
