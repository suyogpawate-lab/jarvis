"""
JARVIS SIGIT-compatible public OSINT adapter.

Exposes SIGIT's public-source operations through a non-interactive
interface suitable for the JARVIS OSINT coordinator.

Authenticated Facebook friend-data extraction is intentionally not
implemented here. Use authorized APIs/data sources instead.
"""

import ipaddress
import os
import re
import socket
import time
from urllib.parse import quote

import requests

from osint.core.adapter import OSINTAdapter


class SIGITAdapter(OSINTAdapter):
    def supports(self, operation):
        return operation in {
            "userrecon",
            "mailfinder",
            "godorker",
            "phoneinfo",
            "subnetcalc",
            "hostsearch",
            "mtr",
            "reverseiplookup",
            "iplocation",
        }


    name = "sigit"

    HACKERTARGET = "https://api.hackertarget.com/{}/?q={}"

    USERRECON_SITES = (
        "https://facebook.com/{}",
        "https://instagram.com/{}",
        "https://twitter.com/{}",
        "https://youtube.com/{}",
        "https://vimeo.com/{}",
        "https://github.com/{}",
        "https://pinterest.com/{}",
        "https://flickr.com/people/{}",
        "https://vk.com/{}",
        "https://about.me/{}",
        "https://disqus.com/{}",
        "https://bitbucket.org/{}",
        "https://medium.com/@{}",
        "https://hackerone.com/{}",
        "https://keybase.io/{}",
        "https://soundcloud.com/{}",
        "https://imgur.com/user/{}",
        "https://pastebin.com/u/{}",
        "https://wattpad.com/user/{}",
        "https://canva.com/{}",
        "https://codecademy.com/{}",
        "https://last.fm/user/{}",
        "https://dribbble.com/{}",
        "https://foursquare.com/{}",
        "https://500px.com/{}",
        "https://tripadvisor.com/members/{}",
        "https://steamcommunity.com/id/{}",
        "https://www.wikipedia.org/wiki/User:{}",
        "https://www.freelancer.com/u/{}",
        "https://www.dailymotion.com/{}",
        "https://www.etsy.com/shop/{}",
        "https://www.patreon.com/{}",
        "https://www.behance.net/{}",
        "https://www.goodreads.com/{}",
        "https://www.gumroad.com/{}",
        "https://www.instructables.com/member/{}",
        "https://www.codementor.io/{}",
        "https://www.reverbnation.com/{}",
        "https://www.bandcamp.com/{}",
        "https://www.trakt.tv/users/{}",
        "https://www.okcupid.com/profile/{}",
        "https://www.zone-h.org/archive/notifier={}",
    )

    INFOGA_OPERATIONS = {
        "dnslookup",
        "whois",
        "subnetcalc",
        "hostsearch",
        "mtr",
        "reverseiplookup",
    }

    def available(self):
        return True

    def _request(self, url, timeout=20):
        response = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "JARVIS-OSINT/1.0",
            },
        )
        response.raise_for_status()
        return response.text.strip()

    def ip_location(self, target):
        response = requests.get(
            f"https://ipinfo.io/{quote(str(target), safe='')}/json",
            timeout=15,
            headers={"User-Agent": "JARVIS-OSINT/1.0"},
        )
        response.raise_for_status()

        data = response.json()

        fields = (
            "ip",
            "city",
            "region",
            "country",
            "loc",
            "org",
            "postal",
            "timezone",
        )

        return {
            key: data[key]
            for key in fields
            if key in data
        }

    def phone_metadata(self, target):
        key = os.getenv("VERIPHONE_API_KEY")

        if not key:
            return {
                "status": "UNAVAILABLE",
                "reason": "VERIPHONE_API_KEY not configured",
            }

        response = requests.get(
            "https://api.veriphone.io/v2/verify",
            params={
                "phone": target,
                "key": key,
            },
            timeout=20,
            headers={"User-Agent": "JARVIS-OSINT/1.0"},
        )

        response.raise_for_status()
        data = response.json()

        fields = (
            "phone_valid",
            "phone_type",
            "country_prefix",
            "country_code",
            "country",
            "international_number",
            "local_number",
            "carrier",
        )

        return {
            key: data[key]
            for key in fields
            if key in data
        }

    def infoga(self, operation, target):
        operation = str(operation).strip().lower()

        if operation not in self.INFOGA_OPERATIONS:
            raise ValueError(
                f"Unsupported SIGIT operation: {operation}"
            )

        normalized = str(target).strip()

        if not normalized:
            raise ValueError("Empty SIGIT target")

        try:
            normalized = socket.gethostbyname(normalized)
        except Exception:
            pass

        url = self.HACKERTARGET.format(
            operation,
            quote(normalized, safe=""),
        )

        return self._request(url)

    def userrecon(self, username, timeout=10):
        username = str(username).strip().lower()

        if not username:
            raise ValueError("Empty username")

        observations = []

        for template in self.USERRECON_SITES:
            url = template.format(username)

            try:
                response = requests.get(
                    url,
                    timeout=timeout,
                    allow_redirects=True,
                    headers={
                        "User-Agent": "JARVIS-OSINT/1.0",
                    },
                )

                observations.append({
                    "site": template.split("/")[2],
                    "url": url,
                    "status_code": response.status_code,
                    "found": response.status_code == 200,
                })

            except requests.RequestException as exc:
                observations.append({
                    "site": template.split("/")[2],
                    "url": url,
                    "status_code": None,
                    "found": False,
                    "error": str(exc),
                })

        return observations

    def mailfinder(self, fullname):
        """
        Generate candidate email addresses.

        No third-party validation credential is embedded.
        Candidates are returned for legitimate follow-up verification.
        """

        fullname = str(fullname).strip().lower()

        if not fullname:
            raise ValueError("Empty name")

        compact = fullname.replace(" ", "")

        usernames = {
            compact,
            compact + "123",
            compact + "1234",
        }

        for name in fullname.split():
            usernames.add(name)
            usernames.add(name + "123")
            usernames.add(name + "1234")

        domains = (
            "gmail.com",
            "yahoo.com",
            "hotmail.com",
            "outlook.com",
            "live.com",
            "rediffmail.com",
            "ymail.com",
            "googlemail.com",
            "mail.com",
            "gmx.net",
        )

        return sorted(
            f"{username}@{domain}"
            for username in usernames
            for domain in domains
        )

    def godorker(self, dork):
        """
        Public web-search operation.

        Uses DuckDuckGo HTML search rather than SIGIT's interactive
        Google-search implementation.
        """

        dork = str(dork).strip()

        if not dork:
            raise ValueError("Empty dork")

        response = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": dork},
            timeout=20,
            headers={
                "User-Agent": "JARVIS-OSINT/1.0",
            },
        )

        response.raise_for_status()

        text = response.text

        links = re.findall(
            r'class="result__a"[^>]+href="([^"]+)"',
            text,
        )

        return {
            "query": dork,
            "results": links[:30],
        }

    def investigate(
        self,
        target,
        target_type=None,
        operation=None,
    ):
        started = time.monotonic()

        normalized = str(target).strip()

        if not normalized:
            raise ValueError("Empty OSINT target")

        observations = {}
        sources = []
        errors = []

        if operation:
            operation = str(operation).strip().lower()

        try:
            if operation == "userrecon":
                observations["userrecon"] = self.userrecon(
                    normalized
                )
                sources.append("public profile URLs")

            elif operation == "mailfinder":
                observations["mailfinder"] = self.mailfinder(
                    normalized
                )

            elif operation == "godorker":
                observations["godorker"] = self.godorker(
                    normalized
                )
                sources.append(
                    "DuckDuckGo public web search"
                )

            elif operation == "phoneinfo":
                observations["phoneinfo"] = self.phone_metadata(
                    normalized
                )
                sources.append("Veriphone")

            elif operation in self.INFOGA_OPERATIONS:
                observations[operation] = self.infoga(
                    operation,
                    normalized,
                )
                sources.append("Hackertarget")

            elif operation == "iplocation":
                observations["iplocation"] = self.ip_location(
                    normalized
                )
                sources.append("ipinfo.io")

            elif operation == "facedumper":
                observations["facedumper"] = {
                    "status": "UNAVAILABLE",
                    "reason": (
                        "Authenticated Facebook friend-data "
                        "extraction is not exposed by this adapter."
                    ),
                }

            elif operation in {
                "dump_all",
                "dump_id",
                "dump_email",
                "dump_phone",
                "dump_birthday",
                "dump_location",
            }:
                observations[operation] = {
                    "status": "UNAVAILABLE",
                    "reason": (
                        "Requires authenticated Facebook "
                        "friend-data access."
                    ),
                }

            elif operation:
                raise ValueError(
                    f"Unsupported SIGIT operation: {operation}"
                )

            else:
                # Automatic target classification.

                try:
                    ipaddress.ip_address(normalized)

                    observations["ip_location"] = (
                        self.ip_location(normalized)
                    )
                    sources.append("ipinfo.io")

                    observations["reverseiplookup"] = (
                        self.infoga(
                            "reverseiplookup",
                            normalized,
                        )
                    )
                    sources.append("Hackertarget")

                except ValueError:
                    if self._looks_like_domain(normalized):
                        observations["dnslookup"] = (
                            self.infoga(
                                "dnslookup",
                                normalized,
                            )
                        )

                        observations["whois"] = (
                            self.infoga(
                                "whois",
                                normalized,
                            )
                        )

                        observations["hostsearch"] = (
                            self.infoga(
                                "hostsearch",
                                normalized,
                            )
                        )

                        sources.append("Hackertarget")

        except Exception as exc:
            errors.append(str(exc))

        return {
            "engine": self.name,
            "target": normalized,
            "target_type": target_type,
            "operation": operation,
            "observations": observations,
            "sources": sorted(set(sources)),
            "errors": errors,
            "duration": round(
                time.monotonic() - started,
                3,
            ),
        }

    @staticmethod
    def _looks_like_domain(value):
        return bool(
            re.match(
                r"^(?=.{1,253}$)"
                r"(?:[A-Za-z0-9]"
                r"(?:[A-Za-z0-9-]{0,61}"
                r"[A-Za-z0-9])?\.)+"
                r"[A-Za-z]{2,63}$",
                value,
            )
        )
