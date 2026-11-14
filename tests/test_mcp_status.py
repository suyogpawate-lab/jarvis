"""Tests for MCP runtime status reporting."""
import unittest
from unittest.mock import patch

from tools import mcp_client


class MCPStatusTests(unittest.TestCase):
    def test_status_text_lists_state_and_tool_count_without_secrets(self):
        states = {
            "filesystem": {
                "name": "filesystem", "status": "RUNNING",
                "tools": 3, "pid": 123, "error": None,
            },
            "github": {
                "name": "github", "status": "ERROR",
                "tools": 0, "error": "startup failed",
                "env": {"TOKEN": "should-not-appear"},
            },
        }
        with patch.object(mcp_client, "_server_states", states), patch.object(mcp_client, "_servers", []):
            text = mcp_client.status_text()
        self.assertIn("filesystem: EXITED", text)
        self.assertIn("github: ERROR", text)
        self.assertNotIn("should-not-appear", text)

    def test_tools_view_includes_only_registered_mcp_tool_names(self):
        with patch.object(mcp_client, "_server_states", {
            "filesystem": {"name": "filesystem", "status": "DISABLED", "tools": 0}
        }), patch.object(mcp_client.registry, "schemas", return_value=[
            {"function": {"name": "mcp_filesystem_read_file"}},
            {"function": {"name": "ordinary_tool"}},
        ]):
            text = mcp_client.status_text(show_tools=True)
        self.assertIn("mcp_filesystem_read_file", text)
        self.assertNotIn("ordinary_tool", text)


if __name__ == "__main__":
    unittest.main()
