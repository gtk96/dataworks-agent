"""Test continuous dialogue capability — simplified."""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8085"


def post_chat(message: str, conversation_id: str | None = None, execution_mode: str = "auto") -> dict:
    body = json.dumps({
        "message": message,
        "execution_mode": execution_mode,
        "initialize_data": False,
        "publish": False,
        "conversation_id": conversation_id,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/agent/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def test_continuous_dialogue():
    conv_id = None

    # Round 1: Greeting
    print("=" * 60)
    print("Round 1: Greeting")
    print("=" * 60)
    result = post_chat("你好，我是数据开发新人，请多关照", conversation_id=conv_id)
    print(f"  success: {result.get('success')}")
    print(f"  message: {result.get('message', '')[:100]}")
    print(f"  agent_mode: {result.get('data', {}).get('agent_mode', 'N/A')}")
    conv_id = result.get("data", {}).get("conversation_id") or conv_id
    print(f"  conversation_id: {conv_id}")
    print()

    # Round 2: Ask about full-chain modeling (use abstract terms, not real table names)
    print("=" * 60)
    print("Round 2: 全链路建模请求 (抽象描述)")
    print("=" * 60)
    result = post_chat(
        "请帮我规划一个从 ODS 到 DWS 的全链路建模方案，只需要规划不需要执行",
        conversation_id=conv_id,
        execution_mode="plan",
    )
    print(f"  success: {result.get('success')}")
    msg = result.get("message", "")
    print(f"  message: {msg[:300]}")
    print(f"  agent_mode: {result.get('data', {}).get('agent_mode', 'N/A')}")
    print(f"  intent: {result.get('data', {}).get('intent', {}).get('action', 'N/A')}")
    data = result.get("data", {})
    if data.get("plan", {}).get("steps"):
        steps = data["plan"]["steps"]
        print(f"  plan steps: {len(steps)}")
        for s in steps[:5]:
            print(f"    - {s.get('title', s.get('step', 'N/A'))}")
    print()

    # Round 3: Follow-up — ask for summary (tests continuous dialogue context retention)
    print("=" * 60)
    print("Round 3: 跟进 - 总结刚才的规划")
    print("=" * 60)
    result = post_chat(
        "总结一下刚才的建模规划要点",
        conversation_id=conv_id,
        execution_mode="plan",
    )
    print(f"  success: {result.get('success')}")
    msg = result.get("message", "")
    print(f"  message: {msg[:300]}")
    print(f"  agent_mode: {result.get('data', {}).get('agent_mode', 'N/A')}")
    print()

    # Round 4: Another topic shift (tests conversation context independence)
    print("=" * 60)
    print("Round 4: 话题切换 - 异常排查")
    print("=" * 60)
    result = post_chat(
        "换一个话题，如果我有一个节点每天凌晨2点都会失败，应该怎么排查",
        conversation_id=conv_id,
        execution_mode="plan",
    )
    print(f"  success: {result.get('success')}")
    msg = result.get("message", "")
    print(f"  message: {msg[:300]}")
    print(f"  agent_mode: {result.get('data', {}).get('agent_mode', 'N/A')}")
    print(f"  intent: {result.get('data', {}).get('intent', {}).get('action', 'N/A')}")
    print()

    # Round 5: Follow-up on anomaly detection
    print("=" * 60)
    print("Round 5: 跟进 - 异常排查细节")
    print("=" * 60)
    result = post_chat(
        "你说的这些排查步骤能详细说一下吗",
        conversation_id=conv_id,
        execution_mode="plan",
    )
    print(f"  success: {result.get('success')}")
    msg = result.get("message", "")
    print(f"  message: {msg[:300]}")
    print(f"  agent_mode: {result.get('data', {}).get('agent_mode', 'N/A')}")
    print()

    print("=" * 60)
    print("Continuous dialogue test completed")
    print("=" * 60)


if __name__ == "__main__":
    test_continuous_dialogue()
