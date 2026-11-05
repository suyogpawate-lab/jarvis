import unittest
from workspace.manager import WorkspaceManager


class WorkspaceIntentTests(unittest.TestCase):
    def test_app_and_normal_browser_requests_are_not_workspace_windows(self):
        from workspace.bridge import _classify_window_intent
        for prompt in ("open Chrome", "open YouTube", "launch WhatsApp",
                       "open https://example.com"):
            self.assertIsNone(_classify_window_intent(prompt), prompt)

    def test_explicit_floating_url_routes_to_workspace(self):
        from workspace.bridge import _classify_window_intent
        intent = _classify_window_intent(
            "Open https://youtu.be/example in a floating window"
        )
        self.assertEqual(intent["action"], "open")
        self.assertEqual(intent["kind"], "youtube")

    def test_live_screen_and_terminal_window_intents(self):
        from workspace.bridge import _classify_window_intent
        self.assertEqual(
            _classify_window_intent("Show my live screen in a window")["kind"],
            "live_screen",
        )
        self.assertEqual(
            _classify_window_intent("Show terminal output in a panel")["kind"],
            "terminal",
        )

    def test_window_controls_do_not_claim_app_controls(self):
        from workspace.bridge import _classify_window_intent
        self.assertEqual(
            _classify_window_intent("Minimize the browser window")["command"],
            "minimize",
        )
        self.assertEqual(
            _classify_window_intent("Maximize the research window")["command"],
            "maximize",
        )
        self.assertEqual(
            _classify_window_intent("Close all windows")["title"],
            "",
        )
        self.assertIsNone(_classify_window_intent("close Chrome"))


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.manager = WorkspaceManager()

    def test_six_surface_limit(self):
        for i in range(6):
            self.manager.open_surface("task", f"Task {i}")
        with self.assertRaises(OverflowError):
            self.manager.open_surface("task", "seventh")

    def test_close_surface(self):
        item = self.manager.open_surface("task", "Research")
        self.assertTrue(self.manager.close_surface(item["id"]))
        self.assertFalse(self.manager.close_surface(item["id"]))

    def test_reject_unsafe_embeds(self):
        for url in ("file:///etc/passwd", "javascript:alert(1)", "http://127.0.0.1:21339/screen"):
            with self.assertRaises(ValueError):
                self.manager.open_surface("web", "unsafe", url)

    def test_telemetry_is_bounded(self):
        result = self.manager.telemetry({"input_tokens": -1, "output_tokens": 42, "confidence": 1.7})
        self.assertIsNone(result["input_tokens"])
        self.assertEqual(result["output_tokens"], 42)
        self.assertIsNone(result["confidence"])

    def test_task_events(self):
        item = self.manager.task_event("task-1", "Research", "active", "Searching")
        self.assertEqual(item["status"], "active")
        self.assertTrue(self.manager.events_after(0))

    def test_maximize_and_focus_emit_window_actions(self):
        item = self.manager.open_surface("web", "Research", "https://example.com")
        self.manager.control_surfaces("maximize", "research")
        self.manager.control_surfaces("focus", "research")
        actions = [event for event in self.manager.events_after(0)
                   if event["event"] == "surface.action"]
        self.assertEqual([event["data"]["action"] for event in actions],
                         ["maximize", "focus"])
        self.assertEqual(actions[0]["data"]["id"], item["id"])

    def test_minimize_restore_and_close_by_title(self):
        first = self.manager.open_surface("web", "Research", "https://example.com")
        second = self.manager.open_surface("image", "Diagram", "https://example.com/a.png")
        self.assertEqual(self.manager.control_surfaces("minimize", "research"), [first["id"]])
        self.assertEqual(self.manager.snapshot()["surfaces"][0]["status"], "minimized")
        self.assertEqual(self.manager.control_surfaces("restore", "research"), [first["id"]])
        self.assertEqual(self.manager.control_surfaces("close", "diagram"), [second["id"]])
        self.assertEqual(len(self.manager.snapshot()["surfaces"]), 1)

    def test_presence_is_exposed_in_snapshot(self):
        self.manager.presence("thinking")
        self.assertEqual(self.manager.snapshot()["jarvis_state"], "thinking")

    def test_supports_document_and_audio_surfaces(self):
        self.manager.open_surface("pdf", "Manual", "https://example.com/manual.pdf")
        self.manager.open_surface("audio", "Audio", "https://example.com/audio.mp3")
        self.assertEqual(len(self.manager.snapshot()["surfaces"]), 2)

    def test_reject_private_network_urls(self):
        for url in ("http://10.0.0.2/", "http://192.168.1.1/", "http://172.16.0.1/"):
            with self.assertRaises(ValueError):
                self.manager.open_surface("web", "private", url)



if __name__ == "__main__":
    unittest.main()
