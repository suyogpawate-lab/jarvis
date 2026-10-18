"""
JARVIS defensive threat-intelligence adapter.

Supported:
    hash_lookup
    threat_report
    onion_metadata

This adapter does NOT crawl or search onion services.
"""

import hashlib
import re
import time
from urllib.parse import urlparse

import requests

from osint.core.adapter import OSINTAdapter


class ThreatIntelAdapter(OSINTAdapter):

    name = "threat-intel"

    SAFE_OPERATIONS = {
        "hash_lookup",
        "threat_report",
        "onion_metadata",
    }

    MALWAREBAZAAR_URL = (
        "https://mb-api.abuse.ch/api/v1/"
    )

    ATTACK_BUNDLE = (
        "https://raw.githubusercontent.com/"
        "mitre-attack/attack-stix-data/master/"
        "enterprise-attack/enterprise-attack.json"
    )

    def available(self):
        return True

    def supports(self, operation):
        return operation in self.SAFE_OPERATIONS

    def investigate(
        self,
        target,
        target_type=None,
        operation=None,
    ):
        started = time.time()

        result = {
            "engine": self.name,
            "target": target,
            "target_type": target_type,
            "operation": operation,
            "observations": {},
            "sources": [],
            "errors": [],
            "ok": False,
        }

        try:

            if operation == "hash_lookup":

                result["observations"] = (
                    self._hash_lookup(target)
                )

                result["sources"].append(
                    "MalwareBazaar"
                )

            elif operation == "threat_report":

                result["observations"] = (
                    self._threat_report(target)
                )

                result["sources"].append(
                    "MITRE ATT&CK STIX"
                )

            elif operation == "onion_metadata":

                result["observations"] = (
                    self._onion_metadata(target)
                )

                result["sources"].append(
                    "local onion metadata parser"
                )

            else:
                raise ValueError(
                    "Unsupported threat-intelligence "
                    f"operation: {operation}"
                )

            result["ok"] = True

        except Exception as exc:

            result["errors"].append({
                "type": type(exc).__name__,
                "message": str(exc),
            })

        result["duration"] = round(
            time.time() - started,
            3,
        )

        return result

    # ---------------------------------------------------------
    # HASH INTELLIGENCE
    # ---------------------------------------------------------

    def _hash_lookup(self, target):

        value = str(target).strip().lower()

        if not re.fullmatch(
            r"[0-9a-f]{32}|"
            r"[0-9a-f]{40}|"
            r"[0-9a-f]{64}",
            value,
        ):
            raise ValueError(
                "Target must be an MD5, SHA1, or SHA256 hash"
            )

        api_key = __import__("os").getenv(
            "MALWAREBAZAAR_AUTH_KEY",
            "",
        )

        if not api_key:
            raise RuntimeError(
                "MALWAREBAZAAR_AUTH_KEY is not configured"
            )

        response = requests.post(
            self.MALWAREBAZAAR_URL,
            headers={
                "Auth-Key": api_key,
                "User-Agent": "JARVIS-ThreatIntel/1.0",
            },
            data={
                "query": "get_info",
                "hash": value,
            },
            timeout=20,
        )

        response.raise_for_status()

        payload = response.json()

        if payload.get("query_status") == "hash_not_found":
            return {
                "hash": value,
                "known": False,
            }

        data = payload.get("data") or []

        if not data:
            return {
                "hash": value,
                "known": False,
            }

        item = data[0]

        return {
            "hash": value,
            "known": True,
            "sha256": item.get("sha256_hash"),
            "sha1": item.get("sha1_hash"),
            "md5": item.get("md5_hash"),
            "first_seen": item.get("first_seen"),
            "last_seen": item.get("last_seen"),
            "file_name": item.get("file_name"),
            "file_type": item.get("file_type"),
            "file_format": item.get("file_format"),
            "architecture": item.get("file_arch"),
            "signature": item.get("signature"),
            "tags": item.get("tags"),
            "clamav": item.get("intelligence"),
        }

    # ---------------------------------------------------------
    # MITRE ATT&CK THREAT INTELLIGENCE
    # ---------------------------------------------------------

    def _threat_report(self, target):

        query = str(target).strip().lower()

        if not query:
            raise ValueError(
                "Empty threat-intelligence query"
            )

        response = requests.get(
            self.ATTACK_BUNDLE,
            timeout=30,
            headers={
                "User-Agent": "JARVIS-ThreatIntel/1.0",
            },
        )

        response.raise_for_status()

        bundle = response.json()

        matches = []

        for obj in bundle.get("objects", []):

            if obj.get("type") not in {
                "attack-pattern",
                "malware",
                "tool",
                "intrusion-set",
                "course-of-action",
            }:
                continue

            name = str(
                obj.get("name") or ""
            )

            external_ids = []

            for ref in obj.get(
                "external_references",
                [],
            ):
                external_id = ref.get(
                    "external_id"
                )

                if external_id:
                    external_ids.append(
                        external_id
                    )

            haystack = (
                name.lower()
                + " "
                + " ".join(
                    external_ids
                ).lower()
            )

            if query in haystack:

                matches.append({
                    "type": obj.get("type"),
                    "name": name,
                    "description": (
                        obj.get("description")
                    ),
                    "external_ids": external_ids,
                })

            if len(matches) >= 10:
                break

        return {
            "query": query,
            "count": len(matches),
            "results": matches,
        }

    # ---------------------------------------------------------
    # ONION METADATA ONLY
    # ---------------------------------------------------------

    def _onion_metadata(self, target):

        value = str(target).strip()

        candidate = value

        if "://" in value:
            parsed = urlparse(value)
            candidate = parsed.hostname or ""

        candidate = candidate.lower().rstrip(".")

        if not candidate.endswith(".onion"):
            raise ValueError(
                "Target is not an onion hostname"
            )

        hostname = candidate[:-6]

        valid_v3 = (
            len(hostname) == 56
            and bool(
                re.fullmatch(
                    r"[a-z2-7]{56}",
                    hostname,
                )
            )
        )

        valid_legacy = (
            len(hostname) == 16
            and bool(
                re.fullmatch(
                    r"[a-z2-7]{16}",
                    hostname,
                )
            )
        )

        return {
            "hostname": candidate,
            "version": (
                "v3"
                if valid_v3
                else "legacy"
                if valid_legacy
                else "unknown"
            ),
            "valid_format": (
                valid_v3 or valid_legacy
            ),
            "network_access": False,
            "crawler": False,
        }
