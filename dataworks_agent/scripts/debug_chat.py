"""Debug: test ChatAgent.chat() directly."""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")

async def main():
    from dataworks_agent.agent.core import ChatAgent
    
    agent = ChatAgent()
    
    # Test 1: Greeting
    print("--- Test 1: Greeting ---")
    result = await agent.chat("hello")
    print(f"  success: {result.success}")
    print(f"  message: {result.message[:100]}")
    print(f"  data keys: {list(result.data.keys())}")
    print()
    
    # Test 2: Non-greeting (should fail gracefully)
    print("--- Test 2: Full chain modeling (abstract) ---")
    result = await agent.chat(
        "帮我规划一个从 ODS 到 DWS 的全链路建模方案",
        execution_mode="plan",
        initialize_data=False,
    )
    print(f"  success: {result.success}")
    print(f"  message: {result.message[:200]}")
    if result.error:
        print(f"  error: {result.error[:200]}")
    print()
    
    # Test 3: English non-greeting
    print("--- Test 3: Forward model (English) ---")
    result = await agent.chat(
        "forward model DWD and DWS tables",
        execution_mode="plan",
        initialize_data=False,
    )
    print(f"  success: {result.success}")
    print(f"  message: {result.message[:200]}")
    if result.error:
        print(f"  error: {result.error[:200]}")
    print()

if __name__ == "__main__":
    asyncio.run(main())
