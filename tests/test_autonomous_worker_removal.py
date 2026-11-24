from agents.autonomous_agent import AutonomousAgent


def test_removed_worker_directive_is_never_reinterpreted_as_shell():
    agent = object.__new__(AutonomousAgent)
    action, result = agent._parse("ACTION: WORKER\nOPENCODE|run a command")
    assert action == "final"
    assert "worker adapter has been removed" in result
