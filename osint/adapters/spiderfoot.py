from osint.core.adapter import OSINTAdapter


class SpiderFootAdapter(OSINTAdapter):

    name = "spiderfoot"

    def available(self):
        return False

    def investigate(self, target, target_type=None):
        raise RuntimeError("SpiderFoot adapter not configured")
