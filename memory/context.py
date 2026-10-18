from .manager import MemoryManager


class MemoryContext:

    def __init__(self, manager=None):
        self.manager = manager or MemoryManager()

    def for_prompt(self, query):

        return self.manager.build_context(
            query=query,
        )
