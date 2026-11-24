"""Minimal MCP (streamable HTTP) client for mcp.slack.com, no AI involved.

Reuses the OAuth sign-in Claude Code keeps for your Slack MCP server (name set by
`slack_mcp_server` in config.json; Keychain item "Claude Code-credentials" or
~/.claude/.credentials.json). The token is only held in memory and only sent to
mcp.slack.com.

Only read tools are callable from here (READ_ONLY_TOOLS); drafting still goes
through a guarded `claude -p` run.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    _CFG = json.loads((HERE / "config.json").read_text())
except Exception:
    _CFG = {}
SERVER = _CFG.get("slack_mcp_server") or "work-slack"
URL = "https://mcp.slack.com/mcp"
ROOT = Path(_CFG.get("workspace_root") or str(HERE.parent)).expanduser().resolve()
READ_ONLY_TOOLS = {"slack_search_public_and_private", "slack_read_thread", "slack_read_user_profile"}


class AuthError(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


CREDS_FILE = Path.home() / ".claude" / ".credentials.json"


def _credential_stores() -> list[dict]:
    """Claude Code keeps sign-ins in the login Keychain, or in ~/.claude/.credentials.json
    (owner-only) when the Keychain is locked, as it is when the listener runs as a boot
    LaunchDaemon with nobody logged in. Read both; either may be missing."""
    stores = []
    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        stores.append(json.loads(raw))
    except Exception:
        pass
    try:
        stores.append(json.loads(CREDS_FILE.read_text()))
    except Exception:
        pass
    return stores


def _token() -> str:
    entries = [
        entry
        for store in _credential_stores()
        for key, entry in store.get("mcpOAuth", {}).items()
        if key.split("|")[0] == SERVER and entry.get("accessToken")
    ]
    if not entries:
        raise AuthError(f"no {SERVER} sign-in in Keychain or ~/.claude/.credentials.json")
    entry = max(entries, key=lambda e: e.get("expiresAt", 0))
    if entry.get("expiresAt", 0) / 1000 < time.time() + 60:
        raise AuthError("token expired")
    return entry["accessToken"]


def refresh_via_claude() -> None:
    """Let Claude Code refresh the token (it connects to every server)."""
    subprocess.run(["claude", "mcp", "list"], cwd=ROOT, capture_output=True, timeout=120)


class SlackMCP:
    def __init__(self) -> None:
        self.session_id = ""
        self._id = 0
        self._token = ""

    def _post(self, payload: dict) -> dict | None:
        if not self._token:
            self._token = _token()
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                body = resp.read().decode()
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                self._token = ""
                raise AuthError(f"HTTP {e.code}") from None
            if e.code == 429:
                raise RateLimited(float(e.headers.get("Retry-After") or 60)) from None
            raise
        if not body.strip():
            return None
        if "text/event-stream" in ctype:
            msgs = [json.loads(l[5:]) for l in body.splitlines() if l.startswith("data:") and l[5:].strip()]
            msgs = [m for m in msgs if m.get("id") == payload.get("id")] or msgs
            return msgs[-1] if msgs else None
        return json.loads(body)

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        out = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}) or {}
        if "error" in out:
            raise RuntimeError(f"MCP error: {out['error']}")
        return out.get("result", {})

    def connect(self) -> None:
        self.session_id = ""
        self._rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "slack-draft-listener", "version": "1.0"},
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, tool: str, args: dict) -> str:
        if tool not in READ_ONLY_TOOLS:
            raise PermissionError(f"{tool} is not a read-only tool")
        if not self.session_id:
            self.connect()
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        if res.get("isError"):
            raise RuntimeError(f"{tool} failed: {str(res.get('content'))[:300]}")
        return "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
