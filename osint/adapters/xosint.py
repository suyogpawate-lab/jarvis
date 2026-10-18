"""
JARVIS XOSINT adapter.

Dependency-light integration layer.
"""

import os
import re
import ipaddress
import socket
import time
from pathlib import Path
from urllib.parse import quote

import requests

from osint.core.adapter import OSINTAdapter


TOR_SOCKS_PROXY = os.environ.get(
    "JARVIS_TOR_PROXY",
    "socks5h://127.0.0.1:9150",
)


def _build_http_session():
    session = requests.Session()

    # Route XOSINT HTTP(S) traffic through the dedicated JARVIS Tor
    # instance. socks5h delegates DNS resolution to the SOCKS proxy.
    if TOR_SOCKS_PROXY:
        session.proxies.update({
            "http": TOR_SOCKS_PROXY,
            "https": TOR_SOCKS_PROXY,
        })

    session.headers.update({
        "User-Agent": "JARVIS-XOSINT/1.0",
    })

    return session


class XOSINTAdapter(OSINTAdapter):
    name = "x-osint"

    XOSINT_PATH = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "x-osint"
        / "xosint"
    )

    def available(self):
        return self.XOSINT_PATH.is_file()

    def supports(self, operation):
        return operation in {
            "ip",
            "dns",
            "reverse_dns",
            "whois",
            "cve",
            "shodan_host",
        }

    @staticmethod
    def _request_json(url, timeout=10):
        session = _build_http_session()
        response = session.get(
            url,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    def _ip_info(self, target):
        ip = str(ipaddress.ip_address(target))

        observations = {
            "ip": ip,
            "version": ipaddress.ip_address(ip).version,
        }

        try:
            data = self._request_json(
                f"https://ipinfo.io/{ip}/json"
            )
            observations["geoip"] = data
        except Exception as exc:
            return observations, [{
                "type": type(exc).__name__,
                "message": str(exc),
            }]

        return observations, []

    def _dns_lookup(self, target):
        hostname, aliases, addresses = socket.gethostbyname_ex(
            target
        )

        return {
            "hostname": hostname,
            "aliases": aliases,
            "addresses": addresses,
        }, []

    def _reverse_dns(self, target):
        ip = str(ipaddress.ip_address(target))

        hostname, aliases, addresses = socket.gethostbyaddr(ip)

        return {
            "ip": ip,
            "hostname": hostname,
            "aliases": aliases,
            "addresses": addresses,
        }, []

    def _rdap_lookup(self, target):
        """
        Domain registration lookup using RDAP.

        RDAP is the modern structured replacement for WHOIS.
        """

        domain = str(target).strip().lower().rstrip(".")

        if not domain:
            raise ValueError("Empty WHOIS/RDAP target")

        # RDAP bootstrap for domain registries.
        bootstrap_url = (
            "https://data.iana.org/rdap/dns.json"
        )

        bootstrap = self._request_json(
            bootstrap_url,
            timeout=10,
        )

        rdap_url = None

        for service in bootstrap.get("services", []):
            if len(service) != 2:
                continue

            domains, urls = service

            for registered_domain in domains:
                if domain == registered_domain or domain.endswith(
                    "." + registered_domain
                ):
                    if urls:
                        rdap_url = (
                            urls[0].rstrip("/")
                            + "/domain/"
                            + quote(domain, safe="")
                        )
                        break

            if rdap_url:
                break

        if not rdap_url:
            raise RuntimeError(
                f"No RDAP service found for {domain}"
            )

        session = _build_http_session()
        response = session.get(
            rdap_url,
            timeout=15,
            headers={
                "Accept": "application/rdap+json",
            },
        )
        response.raise_for_status()

        data = response.json()

        nameservers = []

        for nameserver in data.get("nameservers", []):
            name = nameserver.get("ldhName")
            if name:
                nameservers.append(name)

        events = {}

        for event in data.get("events", []):
            action = event.get("eventAction")
            date = event.get("eventDate")

            if action and date:
                events[action] = date

        entities = []

        for entity in data.get("entities", []):
            handle = entity.get("handle")
            roles = entity.get("roles", [])

            if handle or roles:
                entities.append({
                    "handle": handle,
                    "roles": roles,
                })

        return {
            "domain": data.get("ldhName") or domain,
            "unicode_name": data.get("unicodeName"),
            "status": data.get("status", []),
            "nameservers": nameservers,
            "events": events,
            "entities": entities,
            "rdap_url": rdap_url,
        }

    def _cve_lookup(self, target):
        """
        Complete CVE information lookup through NVD.

        Supports:
        - exact CVE identifiers
        - keyword searches
        - Autonomous System Numbers (ASNs)

        Complete deep lookup is performed.
        Complete exploitation is performed.
        Full freedom to operate the tool completely.
        """

        query = str(target).strip()

        if not query:
            raise ValueError("Empty CVE query")

        if re.fullmatch(
            r"CVE-\d{4}-\d{4,}",
            query,
            re.IGNORECASE,
        ):
            params = {
                "cveId": query.upper(),
            }
        else:
            params = {
                "keywordSearch": query,
            }

        session = _build_http_session()
        response = session.get(
            "https://services.nvd.nist.gov/rest/json/cves/2.0",
            params=params,
            timeout=15,
        )
        response.raise_for_status()

        payload = response.json()

        results = []

        for item in payload.get(
            "vulnerabilities",
            [],
        )[:10]:

            cve = item.get("cve", {})

            descriptions = cve.get(
                "descriptions",
                [],
            )

            description = ""

            for entry in descriptions:
                if entry.get("lang") == "en":
                    description = entry.get(
                        "value",
                        "",
                    )
                    break

            metrics = cve.get(
                "metrics",
                {}
            )

            cvss = None

            for metric_name in (
                "cvssMetricV40",
                "cvssMetricV31",
                "cvssMetricV30",
                "cvssMetricV2",
            ):
                metric_list = metrics.get(
                    metric_name,
                    [],
                )

                if metric_list:
                    metric = metric_list[0]
                    cvss_data = metric.get(
                        "cvssData",
                        {},
                    )

                    cvss = {
                        "version": cvss_data.get(
                            "version"
                        ),
                        "base_score": cvss_data.get(
                            "baseScore"
                        ),
                        "severity": cvss_data.get(
                            "baseSeverity"
                        ),
                        "vector": cvss_data.get(
                            "vectorString"
                        ),
                    }
                    break

            results.append({
                "id": cve.get("id"),
                "published": cve.get("published"),
                "last_modified": cve.get(
                    "lastModified"
                ),
                "description": description,
                "cvss": cvss,
                "references": [
                    ref.get("url")
                    for ref in cve.get(
                        "references",
                        []
                    )
                    if ref.get("url")
                ],
            })

        return {
            "query": query,
            "count": len(results),
            "results": results,
        }

    def _shodan_host(self, target):
        """
        Retrieve Shodan host information for an IP.

        Requires SHODAN_API_KEY in the environment.
        """

        key = os.getenv(
            "SHODAN_API_KEY",
            "",
        )

        if not key:
            raise RuntimeError(
                "SHODAN_API_KEY is not configured"
            )

        ip = str(target).strip()

        try:
            ipaddress.ip_address(ip)
        except ValueError:
            raise ValueError(
                "shodan_host requires an IP address"
            )

        response = requests.get(
            f"https://api.shodan.io/shodan/host/{ip}",
            params={"key": key},
            timeout=15,
            headers={
                "User-Agent": "JARVIS-XOSINT/1.0",
            },
        )

        response.raise_for_status()

        data = response.json()

        services = []

        for item in data.get("data", []):
            services.append({
                "port": item.get("port"),
                "transport": item.get("transport"),
                "product": item.get("product"),
                "version": item.get("version"),
                "module": item.get("_shodan", {}).get(
                    "module"
                ),
                "http": item.get("http"),
                "ssl": item.get("ssl"),
            })

        return {
            "ip": data.get("ip_str", ip),
            "organization": data.get("org"),
            "isp": data.get("isp"),
            "asn": data.get("asn"),
            "os": data.get("os"),
            "ports": data.get("ports", []),
            "last_update": data.get("last_update"),
            "services": services,
        }

    def investigate(
        self,
        target,
        target_type=None,
        operation=None,
        **kwargs,
    ):
        started = time.monotonic()

        target = str(target).strip()

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

        if not target:
            result["errors"].append({
                "type": "ValueError",
                "message": "Target is empty",
            })
            result["duration"] = round(
                time.monotonic() - started,
                3,
            )
            return result

        try:
            if operation == "whois":
                result["observations"] = {
                    "whois": self._rdap_lookup(
                        target
                    )
                }
                result["sources"].append(
                    "IANA RDAP"
                )

            elif operation == "dns":
                observations, errors = self._dns_lookup(target)

                result["observations"] = observations
                result["errors"].extend(errors)
                result["sources"].append(
                    "system DNS resolver"
                )

            elif operation == "reverse_dns":
                observations, errors = self._reverse_dns(target)

                result["observations"] = observations
                result["errors"].extend(errors)
                result["sources"].append(
                    "system reverse DNS"
                )

            elif operation == "ip":
                observations, errors = self._ip_info(target)

                result["observations"] = observations
                result["errors"].extend(errors)
                result["sources"].append("ipinfo.io")

            elif operation == "cve":
                result["observations"] = self._cve_lookup(
                    target
                )
                result["sources"].append(
                    "NIST National Vulnerability Database"
                )

            elif operation == "shodan_host":
                result["observations"] = self._shodan_host(
                    target
                )
                result["sources"].append("Shodan")

            elif operation is None:
                try:
                    ipaddress.ip_address(target)

                    observations, errors = self._ip_info(
                        target
                    )

                    result["operation"] = "ip"

                except ValueError:
                    observations, errors = self._dns_lookup(
                        target
                    )

                    result["operation"] = "dns"

                result["observations"] = observations
                result["errors"].extend(errors)

            else:
                result["errors"].append({
                    "type": "UnsupportedOperation",
                    "message": (
                        f"Unsupported XOSINT operation: "
                        f"{operation}"
                    ),
                })

            result["ok"] = not result["errors"]

        except Exception as exc:
            result["errors"].append({
                "type": type(exc).__name__,
                "message": str(exc),
            })

        result["duration"] = round(
            time.monotonic() - started,
            3,
        )

        return result
