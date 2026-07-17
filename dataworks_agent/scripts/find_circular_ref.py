"""Find the circular reference — drill deeper."""

import asyncio
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")


async def main():
    from dataworks_agent.agent.core import ChatAgent

    agent = ChatAgent()
    r = await agent.chat(
        "forward model DWD and DWS",
        execution_mode="plan",
        initialize_data=False,
    )

    data = r.data
    print(f"data keys: {list(data.keys())}")

    def find_circular(obj, path="", seen=None, depth=0, max_depth=8):
        if seen is None:
            seen = set()
        if depth > max_depth:
            return

        obj_id = id(obj)

        if isinstance(obj, dict):
            if obj_id in seen:
                print(f"CIRCULAR at {path} (id={obj_id})")
                return
            seen.add(obj_id)
            for k, v in obj.items():
                find_circular(v, f"{path}.{k}", seen, depth + 1)
        elif isinstance(obj, (list, tuple)):
            if obj_id in seen:
                print(f"CIRCULAR at {path} (id={obj_id})")
                return
            seen.add(obj_id)
            for i, item in enumerate(obj):
                find_circular(item, f"{path}[{i}]", seen, depth + 1)
        elif hasattr(obj, "__dict__"):
            if obj_id in seen:
                print(f"CIRCULAR at {path} -> {type(obj).__name__} (id={obj_id})")
                return
            seen.add(obj_id)
            for k, v in obj.__dict__.items():
                find_circular(v, f"{path}.{k}", seen, depth + 1)

    find_circular(data)

    # Also try json.dumps with default=str to see what fails
    print("\nTrying json.dumps with default=str...")
    try:
        json.dumps(data, default=str)
        print("  OK")
    except Exception as e:
        print(f"  FAIL: {e}")

    # Check the 'loop' key specifically (it sounds suspicious)
    print("\nChecking 'loop' key:")
    loop = data.get("loop")
    if loop:
        print(f"  type: {type(loop)}")
        if hasattr(loop, "__dict__"):
            print(f"  attrs: {list(loop.__dict__.keys())}")
            for k, v in loop.__dict__.items():
                print(f"    {k}: {type(v).__name__} = {str(v)[:100]}")
                if hasattr(v, "__dict__"):
                    print(f"      sub-attrs: {list(v.__dict__.keys())}")


asyncio.run(main())
