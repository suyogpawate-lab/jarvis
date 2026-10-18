class Worker:
    name = "unknown"

    def available(self):
        return False

    def execute(self, task, workspace):
        raise NotImplementedError
