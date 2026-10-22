"""Extension tool registry for JARVIS.

Skills and MCP servers register their tools here. FastAgent appends
registry.schemas() to its built-in tools and routes unknown tool names to
registry.call(). Thread-safe, so MCP servers can register while JARVIS boots.
"""

import threading


class ToolRegistry:
    def __init__(self):
        self._tools = {}
        self._lock = threading.Lock()

    def register(self, name, description, parameters, handler):
        """handler(arguments: dict) -> dict"""
        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
        with self._lock:
            self._tools[name] = (schema, handler)

    def unregister_prefix(self, prefix):
        with self._lock:
            for name in [n for n in self._tools if n.startswith(prefix)]:
                del self._tools[name]

    def schemas(self):
        with self._lock:
            return [schema for schema, _ in self._tools.values()]

    def has(self, name):
        with self._lock:
            return name in self._tools

    def call(self, name, arguments):
        with self._lock:
            entry = self._tools.get(name)
        if entry is None:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            result = entry[1](arguments or {})
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if isinstance(result, dict):
            return result
        return {"ok": True, "result": result}


registry = ToolRegistry()
