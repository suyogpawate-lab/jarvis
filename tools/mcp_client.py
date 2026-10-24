"""Minimal MCP (Model Context Protocol) stdio client for JARVIS.

Standard library only, so it installs cleanly on Termux (the official `mcp`
package needs compiled dependencies that often fail there).

Config: mcp_servers.json in the JARVIS folder (or JARVIS_MCP_CONFIG):

    {
      "servers": {
        "name": {
          "enabled": true,
          "command": "npx",
          "args": ["-y", "some-mcp-server"],
          "env": {"TOKEN": "${SOME_ENV_VAR}"},
          "tools": ["only_these", "tools_are_exposed"]
        }
      }
    }

Each server tool is registered as mcp_<server>_<tool>. "tools" is an optional
allowlist; use it so the model only sees what you want (smaller prompt, less
risk). Servers start in the background so JARVIS boot is never blocked.
"""

import atexit
import itertools
import json
import os
import queue
import re
import shutil
import subprocess
import threading
from pathlib import Path

from tools.registry import registry

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.getenv("JARVIS_MCP_CONFIG", str(ROOT / "mcp_servers.json")))
PROTOCOL_VERSION = "2024-11-05"
MAX_RESULT_CHARS = 4000
MAX_DESC_CHARS = 300
MAX_TOOLS = int(os.getenv("JARVIS_MAX_MCP_TOOLS", "12"))

_servers = []
_tool_count = 0
_count_lock = threading.Lock()


class MCPError(Exception):
    pass


class MCPServer:
    def __init__(self, name, command, args=None, env=None, allow=None):
        self.name = name
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.allow = set(allow) if allow else None
        self.proc = None
        self._ids = itertools.count(1)
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stderr_log = None

    # ---- process + transport -------------------------------------------

    def start(self, timeout=45):
        executable = shutil.which(self.command) or self.command
        env = os.environ.copy()
        for key, value in self.env.items():
            env[key] = os.path.expandvars(str(value))

        log_dir = ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._stderr_log = (log_dir / f"mcp-{self.name}.stderr.log").open(
            "a", encoding="utf-8"
        )
        self.proc = subprocess.Popen(
            [executable] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_log,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
        )
        threading.Thread(target=self._read_loop, daemon=True).start()

        self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "jarvis", "version": "1.0"},
            },
            timeout,
        )
        self.notify("notifications/initialized")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        if self._stderr_log:
            try:
                self._stderr_log.close()
            except Exception:
                pass
            self._stderr_log = None

    def _send(self, message):
        with self._write_lock:
            if self.proc is None or self.proc.poll() is not None or self.proc.stdin is None:
                raise MCPError(f"MCP server {self.name!r} is not running")
            try:
                self.proc.stdin.write(json.dumps(message) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise MCPError(f"MCP server {self.name!r} transport closed: {exc}") from exc

    def _read_loop(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    continue

                if "method" in message:
                    if "id" in message:
                        self._answer_server_request(message)
                    continue

                with self._pending_lock:
                    waiter = self._pending.pop(message.get("id"), None)
                if waiter is not None:
                    waiter.put(message)
        except Exception:
            pass
        finally:
            with self._pending_lock:
                waiters = list(self._pending.values())
                self._pending.clear()
            for waiter in waiters:
                waiter.put({"error": {"message": "MCP server closed"}})

    def _answer_server_request(self, message):
        if message.get("method") == "ping":
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": {}}
        else:
            reply = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": -32601, "message": "Method not supported"},
            }
        try:
            self._send(reply)
        except Exception:
            pass

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def request(self, method, params, timeout=30):
        request_id = next(self._ids)
        waiter = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = waiter

        try:
            self._send(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
        except Exception:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise

        try:
            message = waiter.get(timeout=timeout)
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise MCPError(f"{method} timed out after {timeout}s")

        error = message.get("error")
        if error:
            raise MCPError(
                str(error.get("message", error)) if isinstance(error, dict) else str(error)
            )
        return message.get("result", {})

    # ---- tools ----------------------------------------------------------

    def list_tools(self, timeout=30):
        tools = []
        cursor = None
        for _ in range(20):
            params = {"cursor": cursor} if cursor else {}
            result = self.request("tools/list", params, timeout)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, tool_name, arguments):
        result = self.request(
            "tools/call", {"name": tool_name, "arguments": arguments}, timeout=60
        )
        parts = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(f"[{item.get('type', 'unknown')} content omitted]")
        text = "\n".join(parts)[:MAX_RESULT_CHARS]

        if result.get("isError"):
            return {"ok": False, "error": text or "MCP tool reported an error."}
        return {"ok": True, "untrusted_external_content": True, "result": text}


def _safe_name(server, tool):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", f"mcp_{server}_{tool}")[:64]


def _make_handler(server, tool_name):
    def handler(arguments):
        return server.call_tool(tool_name, arguments)

    return handler


def _register_server_tools(server):
    global _tool_count
    added = 0
    for tool in server.list_tools():
        name = tool.get("name", "")
        if not name:
            continue
        if server.allow is not None and name not in server.allow:
            continue

        with _count_lock:
            if _tool_count >= MAX_TOOLS:
                _log_failure("registry", f"tool cap ({MAX_TOOLS}) reached; skipping {name}")
                break
            _tool_count += 1  # Reserve a slot while concurrent servers register.

        schema = tool.get("inputSchema") or {}
        if schema.get("type") != "object":
            schema = {"type": "object", "properties": {}}

        try:
            registry.register(
                _safe_name(server.name, name),
                str(tool.get("description") or name)[:MAX_DESC_CHARS],
                schema,
                _make_handler(server, name),
            )
            added += 1
        except Exception as exc:
            with _count_lock:
                _tool_count = max(0, _tool_count - 1)
            _log_failure(server.name, f"tool registration failed for {name}: {type(exc).__name__}: {exc}")
    return added


def _log_failure(name, message):
    """Keep asynchronous MCP failures out of the interactive YOU > prompt."""
    log_dir = ROOT / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "mcp.log").open("a", encoding="utf-8") as log:
            log.write(f"[MCP] {name}: {message}\n")
    except OSError:
        pass


def _boot(name, config):
    env = {key: os.path.expandvars(str(value)) for key, value in (config.get("env") or {}).items()}
    args = [os.path.expandvars(str(value)) for value in (config.get("args") or [])]

    # The filesystem MCP server exits if its permitted root does not exist.
    # Create the configured root before launching it (last positional argument).
    if name == "filesystem" and args:
        try:
            Path(args[-1]).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _log_failure(name, f"cannot prepare filesystem root: {exc}")
            return

    server = MCPServer(
        name=name,
        command=config["command"],
        args=args,
        env=env,
        allow=config.get("tools"),
    )
    try:
        server.start()
        _servers.append(server)
        count = _register_server_tools(server)
        _log_failure(name, f"{count} tool(s) ready")
    except Exception as exc:
        server.stop()
        _log_failure(name, f"failed to start: {type(exc).__name__}: {exc}")


def start_all_async():
    """Read the config and start every enabled server in the background."""
    if not CONFIG_PATH.is_file():
        return
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        _log_failure("config", f"bad config {CONFIG_PATH}: {exc}")
        return

    for name, config in (data.get("servers") or {}).items():
        if not config.get("enabled", True) or not config.get("command"):
            continue
        threading.Thread(target=_boot, args=(name, config), daemon=True).start()


def stop_all():
    for server in _servers:
        server.stop()


atexit.register(stop_all)
