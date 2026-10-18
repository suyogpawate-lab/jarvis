"""
JARVIS OSINT Team Coordinator.

Runs compatible OSINT engines as a team and normalizes
their outputs for downstream correlation/synthesis.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed


class OSINTTeam:

    def __init__(self, adapters=None):
        self.adapters = adapters or []

    def available(self):
        return [
            adapter.name
            for adapter in self.adapters
            if adapter.available()
        ]

    def _run_adapter(
        self,
        adapter,
        target,
        target_type,
        operation,
    ):
        if operation is not None:
            return adapter.investigate(
                target,
                target_type,
                operation=operation,
            )

        return adapter.investigate(
            target,
            target_type,
        )

    def investigate(
        self,
        target,
        target_type=None,
        operation=None,
    ):
        results = {}

        available_adapters = [
            adapter
            for adapter in self.adapters
            if adapter.available()
            and (
                operation is None
                or adapter.supports(operation)
            )
        ]

        if not available_adapters:
            return {
                "target": target,
                "target_type": target_type,
                "operation": operation,
                "engines": {},
                "errors": [
                    {
                        "type": "NoAvailableEngines",
                        "message": (
                            "No OSINT engines support "
                            f"operation: {operation}"
                        ),
                    }
                ],
            }

        with ThreadPoolExecutor(
            max_workers=len(available_adapters)
        ) as executor:

            futures = {
                executor.submit(
                    self._run_adapter,
                    adapter,
                    target,
                    target_type,
                    operation,
                ): adapter
                for adapter in available_adapters
            }

            for future in as_completed(futures):
                adapter = futures[future]

                try:
                    result = future.result()

                    results[adapter.name] = {
                        "status": "SUCCESS",
                        "results": result,
                    }

                except Exception as exc:
                    results[adapter.name] = {
                        "status": "ERROR",
                        "error": str(exc),
                    }

        return {
            "target": target,
            "target_type": target_type,
            "operation": operation,
            "engines": results,
        }
