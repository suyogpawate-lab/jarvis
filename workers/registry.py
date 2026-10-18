from workers.opencode.worker import OpenCodeWorker


def build_worker_registry():
    return {
        "opencode": OpenCodeWorker(),
    }
