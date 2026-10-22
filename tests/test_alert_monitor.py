import json
import unittest
from unittest.mock import patch

from monitoring.alert_monitor import AlertMonitor


class AlertMonitorTests(unittest.TestCase):
    def test_boolean_unplugged_does_not_suppress_low_battery_warning(self):
        monitor = AlertMonitor()
        monitor._termux_api = True
        response = type(
            "Response",
            (),
            {"stdout": json.dumps({
                "percentage": 15,
                "status": "DISCHARGING",
                "plugged": False,
            })},
        )()
        with patch("monitoring.alert_monitor.subprocess.run", return_value=response), \
             patch("monitoring.alert_monitor.alerts.post") as post:
            monitor._check_battery()

        self.assertTrue(
            any("Battery at 15 percent" in str(call) for call in post.call_args_list),
            "A boolean plugged=false must not be treated as charging.",
        )


if __name__ == "__main__":
    unittest.main()
