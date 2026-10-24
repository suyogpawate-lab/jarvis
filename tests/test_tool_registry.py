"""Tests for the extension tool registry contract validation."""
import unittest

from tools.registry import ToolRegistry


class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.calls = []
        self.registry.register(
            "lookup",
            "Look up a record",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 20},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
            lambda args: self.calls.append(args) or {"ok": True, "count": 1},
        )

    def test_valid_arguments_reach_handler(self):
        result = self.registry.call("lookup", {"query": "status", "limit": 5})
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.calls), 1)

    def test_missing_required_argument_is_rejected_before_handler(self):
        result = self.registry.call("lookup", {"limit": 5})
        self.assertFalse(result["ok"])
        self.assertIn("query is required", result["error"])
        self.assertEqual(self.calls, [])

    def test_invalid_type_and_range_are_rejected(self):
        result = self.registry.call("lookup", {"query": "status", "limit": "5"})
        self.assertFalse(result["ok"])
        self.assertIn("must be integer", result["error"])
        result = self.registry.call("lookup", {"query": "status", "limit": 99})
        self.assertFalse(result["ok"])
        self.assertIn("at most 10", result["error"])
        self.assertEqual(self.calls, [])

    def test_unknown_tool_returns_structured_error(self):
        result = self.registry.call("missing", {})
        self.assertFalse(result["ok"])
        self.assertIn("Unknown tool", result["error"])


if __name__ == "__main__":
    unittest.main()
