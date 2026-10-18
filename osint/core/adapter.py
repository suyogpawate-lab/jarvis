"""
Base interface for JARVIS OSINT engines.
"""


class OSINTAdapter:
    name = "unknown"

    def available(self):
        raise NotImplementedError

    def supports(self, operation):
        """
        Return True when this adapter supports the requested operation.
        """
        return True

    def investigate(self, target, target_type=None, operation=None):
        raise NotImplementedError
