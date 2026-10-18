"""
JARVIS OSINT human-readable formatter.
"""


class OSINTFormatter:

    @staticmethod
    def format(result):
        target = result.get("target", "unknown")
        requested_operation = result.get("operation")
        engines = result.get("engines", {})

        lines = [
            f"[OSINT] {target}"
        ]

        # Prevent duplicate output if two engines happen
        # to return the same logical observation.
        rendered_operations = set()

        for engine_data in engines.values():

            if engine_data.get("status") != "SUCCESS":
                continue

            data = engine_data.get("results", {})

            if not data.get("ok", True):
                continue

            observations = data.get(
                "observations",
                {},
            )

            operation = (
                requested_operation
                or data.get("operation")
            )

            if operation in rendered_operations:
                continue

            handlers = {
                "dns": OSINTFormatter._dns,
                "ip": OSINTFormatter._ip,
                "reverse_dns": OSINTFormatter._reverse_dns,
                "whois": OSINTFormatter._whois,
                "subnetcalc": OSINTFormatter._generic,
                "hostsearch": OSINTFormatter._generic,
                "reverseiplookup": OSINTFormatter._generic,
                "iplocation": OSINTFormatter._generic,
                "mtr": OSINTFormatter._generic,
                "cve": OSINTFormatter._cve,
                "shodan_host": OSINTFormatter._shodan,
            }

            handler = handlers.get(operation)

            if handler:
                handler(
                    lines,
                    observations,
                )
                rendered_operations.add(operation)

        if len(lines) == 1:
            lines.append("• No results")

        return "\n".join(lines)

    @staticmethod
    def _dns(lines, observations):
        addresses = observations.get(
            "addresses",
            [],
        )

        aliases = observations.get(
            "aliases",
            [],
        )

        if addresses:
            lines.append(
                "• DNS: " + ", ".join(addresses)
            )

        if aliases:
            lines.append(
                "• Aliases: " + ", ".join(aliases)
            )

    @staticmethod
    def _reverse_dns(lines, observations):
        hostname = observations.get("hostname")

        if hostname:
            lines.append(
                f"• Host: {hostname}"
            )

        aliases = observations.get(
            "aliases",
            [],
        )

        if aliases:
            lines.append(
                "• Aliases: " + ", ".join(aliases)
            )

    @staticmethod
    def _ip(lines, observations):
        geo = observations.get(
            "geoip",
            {},
        )

        hostname = geo.get("hostname")
        city = geo.get("city")
        region = geo.get("region")
        country = geo.get("country")
        organization = geo.get("org")
        anycast = geo.get("anycast")

        if hostname:
            lines.append(
                f"• Host: {hostname}"
            )

        location = ", ".join(
            value
            for value in (
                city,
                region,
                country,
            )
            if value
        )

        if location:
            lines.append(
                f"• Location: {location}"
            )

        if organization:
            lines.append(
                f"• Organization: {organization}"
            )

        if anycast is not None:
            lines.append(
                f"• Anycast: "
                f"{'Yes' if anycast else 'No'}"
            )

    @staticmethod
    def _whois(lines, observations):
        whois = observations.get(
            "whois",
            observations,
        )

        if not isinstance(whois, dict):
            lines.append(
                f"• Result: {whois}"
            )
            return

        domain = whois.get("domain")

        if domain:
            lines.append(
                f"• Domain: {domain}"
            )

        for status in whois.get("status", []):
            if status:
                lines.append(
                    f"• Status: {status}"
                )

        nameservers = whois.get(
            "nameservers",
            [],
        )

        if nameservers:
            lines.append(
                "• Nameservers: "
                + ", ".join(nameservers)
            )

        events = whois.get(
            "events",
            {},
        )

        event_labels = (
            ("registration", "Registration"),
            ("expiration", "Expiration"),
            ("last changed", "Last changed"),
        )

        for key, label in event_labels:
            value = events.get(key)

            if value:
                # Keep only YYYY-MM-DD for clean output.
                value = str(value)[:10]

                lines.append(
                    f"• {label}: {value}"
                )

        entities = whois.get(
            "entities",
            [],
        )

        registrar_handles = []

        for entity in entities:
            if not isinstance(entity, dict):
                continue

            roles = entity.get(
                "roles",
                [],
            )

            if "registrar" in roles:
                handle = entity.get("handle")

                if handle:
                    registrar_handles.append(
                        str(handle)
                    )

        if registrar_handles:
            lines.append(
                "• Registrar handle: "
                + ", ".join(registrar_handles)
            )

        rdap_url = whois.get("rdap_url")

        if rdap_url:
            lines.append(
                "• Source: IANA RDAP"
            )

    @staticmethod
    def _cve(lines, observations):
        count = observations.get(
            "count",
            0,
        )

        results = observations.get(
            "results",
            [],
        )

        if not results:
            lines.append(
                f"• CVE matches: {count}"
            )
            return

        for item in results[:10]:

            cve_id = item.get(
                "id",
                "unknown",
            )

            # CVSS
            cvss = item.get("cvss")

            if isinstance(cvss, dict):
                score = cvss.get("base_score")
                severity = cvss.get("severity")

                if score is not None:
                    if severity:
                        lines.append(
                            f"• CVSS: {score} — "
                            f"{str(severity).upper()}"
                        )
                    else:
                        lines.append(
                            f"• CVSS: {score}"
                        )

            published = item.get(
                "published"
            )

            if published:
                lines.append(
                    f"• Published: "
                    f"{str(published)[:10]}"
                )

            modified = item.get(
                "last_modified"
            )

            if modified:
                lines.append(
                    f"• Last modified: "
                    f"{str(modified)[:10]}"
                )

            description = item.get(
                "description",
                "",
            )

            if description:
                lines.append(
                    f"• Description: "
                    f"{description}"
                )

            references = item.get(
                "references",
                [],
            )

            if references:
                lines.append(
                    "• References:"
                )

                for ref in references[:5]:
                    lines.append(
                        f"  {ref}"
                    )

    @staticmethod
    def _shodan(lines, observations):

        fields = (
            ("organization", "Organization"),
            ("isp", "ISP"),
            ("asn", "ASN"),
            ("country", "Country"),
            ("city", "City"),
            ("os", "OS"),
        )

        for key, label in fields:

            value = observations.get(key)

            if value not in (
                None,
                "",
                [],
                {},
            ):
                lines.append(
                    f"• {label}: {value}"
                )

        ports = observations.get(
            "ports",
            [],
        )

        if ports:
            # Build a clean unique service list.
            service_ports = []

            for service in observations.get(
                "services",
                [],
            ):
                if not isinstance(service, dict):
                    continue

                port = service.get("port")
                transport = service.get("transport")

                if port is None:
                    continue

                entry = (
                    f"{port}/{transport}"
                    if transport
                    else str(port)
                )

                if entry not in service_ports:
                    service_ports.append(entry)

            if service_ports:
                lines.append(
                    "• Ports: "
                    + ", ".join(service_ports)
                )
            else:
                lines.append(
                    "• Ports: "
                    + ", ".join(
                        str(p)
                        for p in ports
                    )
                )

        # Extract useful HTTP information without dumping
        # Shodan's complete nested HTTP/TLS structures.
        http_products = []
        https_seen = False

        for service in observations.get(
            "services",
            [],
        ):
            if not isinstance(service, dict):
                continue

            module = str(
                service.get("module") or ""
            ).lower()

            http = service.get("http")

            if http and isinstance(http, dict):
                title = http.get("title")

                if title:
                    http_products.append(
                        str(title)
                    )

                if "https" in module:
                    https_seen = True

        if http_products:
            unique_titles = []

            for title in http_products:
                if title not in unique_titles:
                    unique_titles.append(title)

            lines.append(
                "• HTTP: "
                + ", ".join(unique_titles)
            )

        if https_seen:
            lines.append(
                "• HTTPS: enabled"
            )

        hostnames = observations.get(
            "hostnames",
            [],
        )

        if hostnames:
            lines.append(
                "• Hostnames: "
                + ", ".join(hostnames)
            )

        domains = observations.get(
            "domains",
            [],
        )

        if domains:
            lines.append(
                "• Domains: "
                + ", ".join(domains)
            )

        last_update = observations.get(
            "last_update"
        )

        if last_update:
            lines.append(
                "• Last updated: "
                + str(last_update)
            )

    @staticmethod
    def _generic(lines, observations):
        if isinstance(observations, dict):

            for key, value in observations.items():

                if value in (
                    None,
                    "",
                    [],
                    {},
                ):
                    continue

                if isinstance(value, str) and "\n" in value:
                    lines.append(
                        f"• {key}:"
                    )

                    for item in value.splitlines()[:30]:

                        if item.strip():
                            lines.append(
                                f"  {item.strip()}"
                            )
                else:
                    lines.append(
                        f"• {key}: {value}"
                    )

        else:
            lines.append(
                f"• Result: {observations}"
            )
