import unittest

from automation.routines import RoutineRunner


class RoutineTests(unittest.TestCase):
    def test_unknown_routine_is_rejected(self):
        result = RoutineRunner(lambda *_: "should not run").run("arbitrary")
        self.assertFalse(result["ok"])
        self.assertIn("device_check", result["error"])

    def test_device_check_runs_allowlisted_steps(self):
        calls = []
        runner = RoutineRunner(lambda action, arg: calls.append((action, arg)) or "ok")
        result = runner.run("device_check")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(action == "doctor" for action, _ in calls))

    def test_failure_stops_following_steps(self):
        calls = []
        def handler(action, arg):
            calls.append(arg)
            if arg == "local":
                raise RuntimeError("expected")
            return "ok"
        result = RoutineRunner(handler).run("device_check")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(calls, ["local"])


if __name__ == "__main__":
    unittest.main()
