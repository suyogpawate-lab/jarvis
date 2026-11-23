import unittest
from unittest.mock import Mock

from automation.command_dispatcher import CommandDispatcher


class OvernightResumeRoutingTests(unittest.TestCase):
    def dispatcher(self):
        dispatcher = CommandDispatcher.__new__(CommandDispatcher)
        dispatcher.research = Mock()
        dispatcher.automation = Mock()
        dispatcher.aie_nl = Mock()
        dispatcher.aie_nl.handle.return_value = "[AIE] incorrectly intercepted"
        return dispatcher

    def test_bare_overnight_id_routes_to_research_before_aie(self):
        dispatcher = self.dispatcher()
        dispatcher.research.resume_overnight.return_value = "[RESEARCH] resumed"
        result = dispatcher.dispatch("resume overnight-2dc27af7e4", source="text")
        self.assertEqual(result, "[RESEARCH] resumed")
        dispatcher.research.resume_overnight.assert_called_once_with("overnight-2dc27af7e4")
        dispatcher.aie_nl.handle.assert_not_called()

    def test_explicit_research_overnight_id_routes_to_research(self):
        dispatcher = self.dispatcher()
        dispatcher.research.resume_overnight.return_value = "[RESEARCH] resumed"
        result = dispatcher.dispatch("resume research overnight-2dc27af7e4", source="text")
        self.assertEqual(result, "[RESEARCH] resumed")
        dispatcher.research.resume_overnight.assert_called_once_with("overnight-2dc27af7e4")
        dispatcher.aie_nl.handle.assert_not_called()

    def test_non_overnight_research_mission_routes_to_research_manager(self):
        dispatcher = self.dispatcher()
        dispatcher.research.resume_mission.return_value = "[RESEARCH] resumed"
        result = dispatcher.dispatch("resume research mission-abc123", source="text")
        self.assertEqual(result, "[RESEARCH] resumed")
        dispatcher.research.resume_mission.assert_called_once_with("mission-abc123", dispatcher.automation)
        dispatcher.aie_nl.handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
