"""
Optional Tor transport for JARVIS Search Hub.

Uses Tor's local SOCKS5 proxy when available.
Default: 127.0.0.1:9050
"""

import os
import subprocess


class TorTransport:
    def __init__(
        self,
        host=None,
        port=None,
        timeout=15,
    ):
        self.host = host or os.environ.get(
            "JARVIS_TOR_HOST",
            "127.0.0.1",
        )
        self.port = int(
            port or os.environ.get(
                "JARVIS_TOR_SOCKS_PORT",
                "9150",
            )
        )
        self.timeout = int(timeout)

    @property
    def proxy(self):
        return f"socks5h://{self.host}:{self.port}"

    def available(self):
        try:
            result = subprocess.run(
                [
                    "curl",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    str(self.timeout),
                    "--socks5-hostname",
                    f"{self.host}:{self.port}",
                    "https://check.torproject.org/api/ip",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=self.timeout + 2,
            )

            return result.returncode == 0

        except Exception:
            return False

    def fetch(self, url):
        result = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                str(self.timeout),
                "--socks5-hostname",
                f"{self.host}:{self.port}",
                "--user-agent",
                "JARVIS-SearchHub/1.0",
                url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=self.timeout + 2,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or
                "Tor transport request failed"
            )

        return result.stdout
