import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from automation.command_dispatcher import CommandDispatcher


class SchedulerNaturalLanguageTests(unittest.TestCase):
    def dispatcher(self, timezone_name="Asia/Kolkata"):
        dispatcher = CommandDispatcher.__new__(CommandDispatcher)
        dispatcher.automation = Mock()
        dispatcher.automation.timezone_name = timezone_name
        dispatcher.automation.timezone = ZoneInfo(timezone_name)
        return dispatcher

    def test_reschedule_command_updates_only_existing_scheduled_task(self):
        zone = ZoneInfo("Asia/Kolkata")
        old_run = (datetime.now(zone) + timedelta(hours=3)).replace(second=0, microsecond=0)
        new_run = (datetime.now(zone) + timedelta(days=2)).replace(second=0, microsecond=0)
        dispatcher = self.dispatcher()
        dispatcher.automation.get.return_value = {
            "id": "auto-96307a83",
            "status": "SCHEDULED",
            "next_run": old_run.timestamp(),
            "command": "research autonomous Android reliability",
        }
        dispatcher.automation.reschedule.return_value = {
            "id": "auto-96307a83",
            "status": "SCHEDULED",
            "next_run": new_run.timestamp(),
            "command": "research autonomous Android reliability",
        }
        request = (
            "Reschedule auto-96307a83 to "
            + new_run.strftime("%A, %Y-%m-%d at exactly %H:%M IST")
        )
        response = dispatcher._automation_route(request)
        self.assertIn("rescheduled", response)
        self.assertIn("existing command and task ID were preserved", response)
        dispatcher.automation.reschedule.assert_called_once_with(
            "auto-96307a83", new_run.timestamp()
        )

    def test_dispatch_routes_scheduler_command_before_research_parser(self):
        zone = ZoneInfo("Asia/Kolkata")
        target = (datetime.now(zone) + timedelta(days=2)).replace(second=0, microsecond=0)
        dispatcher = self.dispatcher()
        dispatcher.automation.get.return_value = {
            "id": "auto-96307a83",
            "status": "SCHEDULED",
            "next_run": (datetime.now(zone) + timedelta(hours=3)).timestamp(),
            "command": "research robotics",
        }
        dispatcher.automation.reschedule.return_value = {
            "id": "auto-96307a83",
            "status": "SCHEDULED",
            "next_run": target.timestamp(),
            "command": "research robotics",
        }
        dispatcher.research = Mock()
        request = "Reschedule auto-96307a83 to " + target.strftime("%Y-%m-%d at %H:%M IST")
        response = dispatcher.dispatch(request)
        self.assertIn("rescheduled", response)
        dispatcher.research.parse_request.assert_not_called()
        dispatcher.research.research_now.assert_not_called()

    def test_reschedule_rejects_non_pending_task(self):
        dispatcher = self.dispatcher()
        dispatcher.automation.get.return_value = {"status": "DONE"}
        response = dispatcher._automation_route(
            "Reschedule auto-96307a83 to 2026-11-06 at 05:00 IST"
        )
        self.assertIn("only pending scheduled tasks", response)
        dispatcher.automation.reschedule.assert_not_called()

    def test_ambiguous_ist_is_rejected_outside_india_timezone(self):
        dispatcher = self.dispatcher("America/Los_Angeles")
        with self.assertRaisesRegex(ValueError, "IST is ambiguous"):
            dispatcher._parse_automation_datetime("2026-11-06 at 05:00 IST")


if __name__ == "__main__":
    unittest.main()
