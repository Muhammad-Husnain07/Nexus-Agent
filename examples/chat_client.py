"""Interactive chat client for Nexus Agent with streaming SSE and HITL approval.

Usage:
    python examples/chat_client.py --token <jwt>

Scenarios:
    1. "Write a draft about AI trends and publish it"
    2. "List all articles in the Tech category"
    3. "Update the latest article's title to 'Updated: AI in 2026' then preview it"
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from collections.abc import AsyncIterator

import httpx

API = "http://localhost:8000"


def _extract_tenant(token: str) -> str | None:
    """Extract the tenant ID from the JWT payload (tid claim)."""
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get("tid")
    except Exception:
        return None


async def stream_events(session_id: str, message: str, token: str, tenant_id: str | None) -> AsyncIterator[dict]:
    """SSE event streamer."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        async with client.stream(
            "POST",
            f"{API}/api/v1/sessions/{session_id}/chat",
            headers=headers,
            json={"message": message, "stream": True},
        ) as resp:
            buffer = ""
            current_type = None
            async for chunk in resp.aiter_bytes():
                buffer += chunk.decode()
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.startswith("event: "):
                        current_type = line[7:]
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        yield {"event": current_type or data.get("type"), "data": data}


def color(text: str, code: str) -> str:
    codes = {"blue": "34", "green": "32", "yellow": "33", "red": "31", "cyan": "36", "dim": "2"}
    return f"\033[{codes.get(code, '0')}m{text}\033[0m"


async def run(token: str) -> None:
    tenant_id = _extract_tenant(token)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id

    # Create session
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(
            f"{API}/api/v1/sessions",
            headers=headers,
            json={"title": "Demo Chat"},
        )
        resp.raise_for_status()
        session_id = resp.json()["id"]
        print(color(f"\nSession: {session_id}", "cyan"))

    pending_approvals: list[dict] = []

    while True:
        try:
            user_input = input(color("\nYou: ", "blue"))
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input.strip():
            continue
        if user_input.strip().lower() in ("quit", "exit", "q"):
            break

        async for event in stream_events(session_id, user_input, token, tenant_id):
            etype = event["event"]
            payload = event["data"].get("payload", event["data"])

            if etype == "plan_created":
                steps = payload.get("steps", [])
                print(color(f"\n  [Plan] {len(steps)} step(s) planned:", "dim"))
                for s in steps:
                    t = s.get("tool_name", "?")
                    d = s.get("description", "")
                    print(color(f"    → {t}: {d}", "dim"))

            elif etype == "tool_call_completed":
                tn = payload.get("tool_name", "")
                st = payload.get("status", "")
                icon = "✓" if st == "success" else "✗"
                print(color(f"\n  [{icon}] {tn} → {st}", "green" if st == "success" else "red"))

            elif etype == "clarification_needed":
                q = payload.get("question", payload.get("text", ""))
                print(color(f"\n  [Agent asks] {q}", "yellow"))

            elif etype == "final_response":
                text = payload.get("text", "")
                print(color(f"\n  {text}", "green"))

            elif etype == "intermediate_preview":
                text = str(payload.get("text", ""))[:200]
                print(color(f"\n  [Preview] {text}", "cyan"))

            elif etype == "approval_required":
                tc = payload.get("tool_call", {})
                step = payload.get("step", {})
                risk = payload.get("risk_level", "?")
                print(color(f"\n  ⚠ Approval Required", "yellow"))
                print(color(f"    Tool: {tc.get('name', '?')}", "yellow"))
                print(color(f"    Inputs: {json.dumps(tc.get('inputs', {}), indent=2)}", "yellow"))
                print(color(f"    Risk: {risk}", "yellow"))
                if step:
                    print(color(f"    Step: {step.get('description', '')}", "yellow"))

                while True:
                    choice = input(color("  [A]pprove / [R]eject / [E]dit: ", "yellow")).strip().lower()
                    if choice in ("a", "approve"):
                        decision = {"action": "approve"}
                        break
                    elif choice in ("r", "reject"):
                        comment = input(color("  Reason: ", "yellow")).strip()
                        decision = {"action": "reject", "comment": comment or "Rejected by user"}
                        break
                    elif choice in ("e", "edit"):
                        print(color("  Enter edited inputs as JSON (e.g. {\"title\": \"new\"}):", "yellow"))
                        edited = input(color("  > ", "yellow")).strip()
                        try:
                            edited_inputs = json.loads(edited)
                            decision = {"action": "edit", "edited_inputs": edited_inputs}
                            break
                        except json.JSONDecodeError:
                            print(color("  Invalid JSON, try again.", "red"))
                            continue
                    else:
                        print(color("  Invalid choice. Enter A, R, or E.", "red"))

                # Fetch approval ID and decide
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                        resp = await client.get(
                            f"{API}/api/v1/approvals/pending/{session_id}",
                            headers=headers,
                        )
                        pending = resp.json()
                        if pending:
                            aid = pending[0]["id"]
                            await client.post(
                                f"{API}/api/v1/approvals/{aid}/decide",
                                headers=headers,
                                json=decision,
                            )
                            print(color(f"  → Decision sent: {decision['action']}", "green"))
                except Exception as e:
                    print(color(f"  → Decision failed: {e}", "red"))

            elif etype == "error":
                msg = payload.get("message") or str(payload.get("errors", [""])[0])
                print(color(f"\n  ✗ Error: {msg}", "red"))

            elif etype == "done":
                break


def main() -> None:
    parser = argparse.ArgumentParser(description="Nexus Agent demo chat client")
    parser.add_argument("--token", required=True, help="JWT or API key")
    args = parser.parse_args()

    print(color("Nexus Agent — Demo Chat Client", "cyan"))
    print(color("Type your request and press Enter. 'quit' to exit.", "dim"))

    import asyncio

    asyncio.run(run(args.token))


if __name__ == "__main__":
    main()
