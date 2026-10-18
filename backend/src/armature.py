"""Armature MCP client adapter (read side), off by default.

Armature's own MCP server (https://mcp.armature.tech/mcp, Streamable HTTP JSON-RPC, `Authorization: Bearer
<workspace API key>`) exposes `list_sessions`, `list_issues`, `run_eval_suite` and `get_suite_run` among others
(https://docs.armature.tech/armature-mcp/tools). Steward calls it only when `STEWARD_ARMATURE_LIVE=true` **and**
`ARMATURE_API_KEY` holds a real workspace (dashboard/read) key. The SDK ingest key (`ANALYTICS_INGEST_API_KEY`)
can send telemetry but cannot read sessions, so without a read key Atlas's evidence is Steward's own telemetry
table (the same tool-call events the MCP ships to Armature).
"""
from __future__ import annotations

import json

import httpx

from .env import env
from .providers import clean_env

ARMATURE_MCP_URL = "https://mcp.armature.tech/mcp"
READ_TOOLS = ("list_sessions", "list_issues", "get_session", "get_issue", "list_eval_suites", "get_suite_run")
WRITE_TOOLS = ("run_eval_suite",)
PROTOCOL_VERSION = "2025-06-18"


class ArmatureError(RuntimeError):
    pass


def _parse_response(response: httpx.Response, request_id) -> dict:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in response.text.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                message = json.loads(line[5:].strip())
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("id") == request_id:
                return message
        raise ArmatureError("No JSON-RPC response in the event stream.")
    return response.json()


class ArmatureMCP:
    def __init__(self, transport=None, url: str | None = None):
        self.transport = transport
        self.url = url or env("STEWARD_ARMATURE_MCP_URL", ARMATURE_MCP_URL)

    @property
    def key(self) -> str:
        return clean_env("ARMATURE_API_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.key)

    @property
    def live(self) -> bool:
        return self.configured and env("STEWARD_ARMATURE_LIVE", "false").strip().lower() == "true"

    def _headers(self, session_id: str | None) -> dict:
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL_VERSION}
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        return headers

    def call(self, tool: str, arguments: dict | None = None) -> dict:
        """initialize → notifications/initialized → tools/call; returns the tool's JSON payload (text content parsed)."""
        if not self.live:
            raise ArmatureError("Armature MCP is off: set STEWARD_ARMATURE_LIVE=true and ARMATURE_API_KEY to a workspace read key.")
        if tool not in READ_TOOLS + WRITE_TOOLS:
            raise ArmatureError(f"Tool {tool} is not used by Steward.")
        with httpx.Client(transport=self.transport, timeout=30) as client:
            init = client.post(self.url, headers=self._headers(None), content=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "steward-atlas", "version": "0.3.0"}}}))
            init.raise_for_status()
            session_id = init.headers.get("mcp-session-id")
            _parse_response(init, 1)
            client.post(self.url, headers=self._headers(session_id), content=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
            response = client.post(self.url, headers=self._headers(session_id), content=json.dumps(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": arguments or {}}}))
            response.raise_for_status()
            message = _parse_response(response, 2)
        if message.get("error"):
            raise ArmatureError(f"Armature {tool} error: {str(message['error'].get('message'))[:200]}")
        result = message.get("result") or {}
        if result.get("isError"):
            raise ArmatureError(f"Armature {tool} returned an error result.")
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        texts = [block.get("text", "") for block in result.get("content", []) if isinstance(block, dict) and block.get("type") == "text"]
        joined = "\n".join(texts)
        try:
            return json.loads(joined)
        except ValueError:
            return {"text": joined}

    def findings_section(self) -> dict:
        if not self.live:
            detail = ("STEWARD_ARMATURE_LIVE is not true; findings use Steward telemetry." if self.configured else
                      "No Armature workspace read key (ARMATURE_API_KEY is unset). The SDK ingest key can send telemetry but cannot read "
                      "sessions, so findings use Steward telemetry, also delivered to Armature.")
            return dict(live=False, configured=self.configured, url=self.url, detail=detail)
        section = dict(live=True, configured=True, url=self.url)
        try:
            section["sessions"] = self.call("list_sessions", {"limit": 20})
            section["issues"] = self.call("list_issues", {"status": "open"})
        except Exception as error:
            section["error"] = f"Armature MCP call failed ({type(error).__name__}: {str(error)[:160]})"
        return section
