"""Debug: reproduce the 500 error from the router."""
import asyncio
import sys

sys.stdout.reconfigure(encoding='utf-8')

async def main():

    # Import the actual app to see the middleware chain
    from fastapi.testclient import TestClient

    from dataworks_agent.main import create_app

    app = create_app()
    client = TestClient(app)

    # Test 1: greeting (should work)
    print("=== Test 1: greeting ===")
    resp = client.post("/agent/chat", json={
        "message": "hello",
        "execution_mode": "plan",
        "initialize_data": False,
        "publish": False,
    })
    print(f"  status: {resp.status_code}")
    print(f"  body: {resp.text[:200]}")
    print()

    # Test 2: forward model (fails with 500)
    print("=== Test 2: forward model ===")
    try:
        resp = client.post("/agent/chat", json={
            "message": "forward model DWD and DWS",
            "execution_mode": "plan",
            "initialize_data": False,
            "publish": False,
        })
        print(f"  status: {resp.status_code}")
        print(f"  body: {resp.text[:500]}")
    except Exception as e:
        print(f"  exception: {e}")
        import traceback
        traceback.print_exc()
    print()

    # Test 3: check status (should work)
    print("=== Test 3: check status ===")
    resp = client.post("/agent/chat", json={
        "message": "check status",
        "execution_mode": "plan",
        "initialize_data": False,
        "publish": False,
    })
    print(f"  status: {resp.status_code}")
    print(f"  body: {resp.text[:200]}")

if __name__ == "__main__":
    asyncio.run(main())
