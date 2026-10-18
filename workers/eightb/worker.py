"""
8B frontend worker.

The transport is intentionally separated from the worker interface
until the actual 8B programmatic interface is verified.
"""

from workers.common.base import Worker


class EightBWorker(Worker):

    name = "8b"

    def __init__(self, transport=None):
        self.transport = transport

    def available(self):
        return self.transport is not None

    def execute(self, task, workspace):
        if self.transport is None:
            raise RuntimeError(
                "8B transport is not configured"
            )

        return self.transport.execute(
            task=task,
            workspace=workspace,
        )
