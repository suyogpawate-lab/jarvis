"""Pure app-name and package-ID resolution helpers for JARVIS.

Kept separate from Android subprocess calls so aliases can be regression-tested on any OS.
"""
from __future__ import annotations

import re


def normalize_app_name(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def resolve_app_candidates(query, explicit, apps, nicknames=None):
    """Resolve a name/alias to package IDs without guessing between ambiguous apps."""
    nicknames = nicknames or {}
    raw = normalize_app_name(query)
    q = normalize_app_name(nicknames.get(raw, query))
    if not q:
        return []

    def pick(found):
        found = sorted(
            found,
            key=lambda app: (
                app.get("launchable") is False,
                bool(app.get("system")),
                normalize_app_name(app.get("name", "")),
            ),
        )
        return [app["package"] for app in found if app.get("package")]

    exact_names = [
        app for app in apps
        if q == normalize_app_name(app.get("name", ""))
        and app.get("package")
    ]
    exact_names = list({app["package"]: app for app in exact_names}.values())
    if len(exact_names) == 1:
        return pick(exact_names)
    if len(exact_names) > 1:
        return []

    named = [
        app for app in apps
        if q in {normalize_app_name(alias) for alias in app.get("short", [])}
        and app.get("package")
    ]
    named = list({app["package"]: app for app in named}.values())
    if len(named) == 1:
        return pick(named)
    if len(named) > 1:
        return []

    ids = [
        app for app in apps
        if q == normalize_app_name(app.get("package", ""))
        or q == normalize_app_name(app.get("package", "").rsplit(".", 1)[-1])
    ]
    if len(ids) == 1:
        return pick(ids)
    if not explicit or len(q) < 3:
        return []

    launchable = [app for app in apps if app.get("launchable") is not False]
    partial = [app for app in launchable if q in normalize_app_name(app.get("name", ""))]
    prefix = [app for app in partial if normalize_app_name(app.get("name", "")).startswith(q)]
    for group in (prefix, partial):
        unique = {app.get("package"): app for app in group if app.get("package")}
        if len(unique) == 1:
            return pick(list(unique.values()))

    # Allow phrases such as "open google chrome" to resolve the unique app name
    # contained in the phrase, but never choose between equally good matches.
    inside = [
        app for app in launchable
        if len(normalize_app_name(app.get("name", ""))) >= 4
        and re.search(
            rf"\b{re.escape(normalize_app_name(app.get('name', '')))}\b",
            q,
        )
    ]
    if inside:
        longest = max(len(normalize_app_name(app.get("name", ""))) for app in inside)
        best = [app for app in inside if len(normalize_app_name(app.get("name", ""))) == longest]
        unique = {app.get("package"): app for app in best if app.get("package")}
        if len(unique) == 1:
            return pick(list(unique.values()))
    return []


def resolve_installed_packages(query, package_ids):
    """Return one unambiguous installed package for a human app name or package tail."""
    q = normalize_app_name(query)
    if not q:
        return []
    norm = lambda value: normalize_app_name(value).replace(" ", "")
    compact = norm(q)
    exact = [
        package for package in package_ids
        if q == normalize_app_name(package)
        or q == normalize_app_name(package.rsplit(".", 1)[-1])
        or compact == norm(package.rsplit(".", 1)[-1])
    ]
    if len(exact) == 1:
        return exact
    if len(exact) > 1 or len(compact) < 3:
        return []
    matches = [
        package for package in package_ids
        if compact in norm(package)
    ]
    return matches if len(matches) == 1 else []
