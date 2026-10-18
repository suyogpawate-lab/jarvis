from workers.registry import build_worker_registry


class OWLOrchestrator:

    name = "owl"

    def __init__(self):
        self.workers = build_worker_registry()

    def available_workers(self):
        return [
            name
            for name, worker in self.workers.items()
            if worker.available()
        ]

    def delegate(self, worker_name, task, workspace):

        worker = self.workers.get(worker_name)

        if worker is None:
            raise ValueError(
                f"Unknown worker: {worker_name}"
            )

        if not worker.available():
            raise RuntimeError(
                f"Worker unavailable: {worker_name}"
            )

        return worker.execute(
            task=task,
            workspace=workspace,
        )
