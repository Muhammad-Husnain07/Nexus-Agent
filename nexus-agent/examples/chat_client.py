"""Interactive chat client for Nexus Agent with streaming SSE and HITL approval.

Usage:
    python examples/chat_client.py --token <jwt>

Scenarios:
    1. "list all tags"
    2. "list articles in the Tech category"
    3. "Write a draft about AI trends and publish it"
    4. "Update the latest article's title to 'Updated: AI in 2026' then preview it"
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from collections.abc import AsyncIterator

import httpx

API = "http://127.0.0.1:8000"


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
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        async with client.stream(
            "POST",
            f"{API}/api/v1/sessions/{session_id}/chat",
            headers=headers,
            json={"message": message, "stream": True},
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                yield {"event": "error", "data": {"payload": {"message": f"HTTP {resp.status_code}: {body.decode()[:200]}"}}}
                return
            buffer = ""
            current_type = None
            async for chunk in resp.aiter_bytes():
                if not chunk:
                    continue
                text = chunk.decode("utf-8", errors="replace")
                buffer += text
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event: "):
                        current_type = line[7:]
                    elif line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            yield {"event": current_type or data.get("type"), "data": data}
                        except json.JSONDecodeError as e:
                            yield {"event": "error", "data": {"payload": {"message": f"Parse error: {e}, data: {line[6:80]}"}}}
                    elif line.startswith(":"):
                        pass
                    else:
                        pass


def color(text: str, code: str) -> str:
    codes = {"blue": "34", "green": "32", "yellow": "33", "red": "31", "cyan": "36", "dim": "2"}
    return f"\033[{codes.get(code, '0')}m{text}\033[0m"


async def create_session(token: str, tenant_id: str | None) -> str | None:
    """Create a session via the API and return its ID, or None if it fails."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(
                f"{API}/api/v1/sessions",
                headers=headers,
                json={"title": "Demo Chat"},
            )
            if resp.status_code == 201:
                return resp.json()["id"]
            print(color(f"  Session creation returned {resp.status_code}, using auto-create via chat endpoint.", "dim"))
            return None
    except Exception as e:
        print(color(f"  Session creation failed ({e}), using auto-create via chat endpoint.", "dim"))
        return None


async def run(token: str) -> None:
    tenant_id = _extract_tenant(token)

    session_id = await create_session(token, tenant_id)

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

        print(color("   [Thinking...]", "dim"), flush=True)

        event_count = 0
        async for event in stream_events(session_id or "auto", user_input, token, tenant_id):
            event_count += 1
            etype = event["event"]
            payload = event["data"].get("payload", event["data"])

            if etype == "tool_selected":
                intent = payload.get("intent", "")
                params = payload.get("parameters", {})
                print(color(f"\n  [Intent] {intent}", "dim"))
                if params:
                    print(color(f"    Parameters: {json.dumps(params)}", "dim"))

            elif etype == "plan_created":
                steps = payload.get("steps", [])
                print(color(f"\n  [Plan] {len(steps)} step(s) planned:", "dim"))
                for s in steps:
                    t = s.get("tool_name", "?")
                    d = s.get("description", "")
                    print(color(f"    → {t}: {d}", "dim"))

            elif etype == "tool_call_completed":
                tn = payload.get("tool_name", "")
                st = payload.get("status", "")
                icon = "[OK]" if st == "success" else "[FAIL]"
                print(color(f"\n  [{icon}] {tn} → {st}", "green" if st == "success" else "red"))
                data = payload.get("data")
                if data:
                    snippet = json.dumps(data)[:200]
                    print(color(f"    Result: {snippet}", "dim"))

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
                print(color(f"\n  [!] Approval Required", "yellow"))
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

                try:
                    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                    if tenant_id:
                        headers["X-Tenant-ID"] = tenant_id
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
                print(color(f"\n  [FAIL] Error: {msg}", "red"))

            elif etype == "done":
                break

            # Capture session_id from first response if not set yet
            if not session_id:
                sid = event["data"].get("session_id")
                if sid:
                    session_id = sid

        if event_count == 0:
            print(color("  [!] No events received. The server might be processing or there may be an error.", "yellow"))
        print(color("  [OK] Ready", "dim"), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Nexus Agent demo chat client")
    parser.add_argument("--token", required=True, help="JWT token or path to token file")
    args = parser.parse_args()

    token = args.token
    if os.path.isfile(token):
        with open(token) as f:
            token = f.read().strip()
    token = token.strip().strip("'\"")

    print(color("Nexus Agent — Demo Chat Client", "cyan"))
    print(color("Type your request and press Enter. 'quit' to exit.", "dim"))

    import asyncio

    asyncio.run(run(token))


if __name__ == "__main__":
    main()
