"""Thread-safe extension tool registry with lightweight JSON-schema validation.

The registry deliberately implements the common JSON Schema subset used by
OpenAI-compatible function tools. Unknown schema keywords are ignored so MCP
and provider-specific tools remain forward-compatible.
"""

import threading


class ToolRegistry:
    def __init__(self):
        self._tools = {}
        self._lock = threading.Lock()

    def register(self, name, description, parameters, handler):
        """Register a handler: handler(arguments: dict) -> dict."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Tool name must be a non-empty string.")
        if not callable(handler):
            raise TypeError("Tool handler must be callable.")
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

    @staticmethod
    def _type_matches(value, expected):
        if expected == "object":
            return isinstance(value, dict)
        if expected == "array":
            return isinstance(value, list)
        if expected == "string":
            return isinstance(value, str)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "null":
            return value is None
        return True

    @classmethod
    def _validate_value(cls, value, schema, path):
        if not isinstance(schema, dict):
            return None
        expected = schema.get("type")
        if expected and not cls._type_matches(value, expected):
            return f"{path} must be {expected}"
        if "enum" in schema and value not in schema["enum"]:
            return f"{path} must be one of: {', '.join(map(str, schema['enum']))}"
        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                return f"{path} is too short"
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                return f"{path} is too long"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                return f"{path} must be at least {schema['minimum']}"
            if "maximum" in schema and value > schema["maximum"]:
                return f"{path} must be at most {schema['maximum']}"
        if isinstance(value, dict):
            properties = schema.get("properties", {})
            for key in schema.get("required", []):
                if key not in value:
                    return f"{path}.{key} is required"
            for key, item in value.items():
                child = properties.get(key)
                # Unknown properties remain allowed unless a future tool
                # explicitly adopts additionalProperties=false.
                if child is not None:
                    error = cls._validate_value(item, child, f"{path}.{key}")
                    if error:
                        return error
        if isinstance(value, list) and isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                error = cls._validate_value(item, schema["items"], f"{path}[{index}]")
                if error:
                    return error
        return None

    @classmethod
    def _validate_arguments(cls, schema, arguments):
        parameters = schema.get("function", {}).get("parameters", {})
        if not isinstance(arguments, dict):
            return "Tool arguments must be a JSON object."
        return cls._validate_value(arguments, parameters, "arguments")

    def call(self, name, arguments):
        with self._lock:
            entry = self._tools.get(name)
        if entry is None:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        schema, handler = entry
        arguments = arguments or {}
        validation_error = self._validate_arguments(schema, arguments)
        if validation_error:
            return {"ok": False, "error": f"Invalid arguments for {name}: {validation_error}"}
        try:
            result = handler(arguments)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if isinstance(result, dict):
            return result
        return {"ok": True, "result": result}


registry = ToolRegistry()
