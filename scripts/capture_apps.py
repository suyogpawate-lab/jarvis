#!/usr/bin/env python3
"""Capture every installed Android app into data/installed_apps.json.

Each entry: package id, the normal name shown under the launcher icon, and shortform names
(initials, first word, compact form, package tail). Run by install.sh; re-run any time:
    python scripts/capture_apps.py
Names come from `aapt` (pkg install aapt) when it can read the APK; otherwise they are
derived from the package id. Shortforms used by more than one app are dropped.
"""
import json, os, re, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "installed_apps.json")
GENERIC = {"android", "app", "apps", "mobile", "main", "client", "free", "lite", "com", "org", "net", "google"}


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""


def pkg_list(args):
    out = {}
    for line in run(["pm", "list", "packages"] + args, 30).splitlines():
        line = line.strip()
        if line.startswith("package:"):
            body = line[8:]
            path, _, pid = body.rpartition("=") if "=" in body else ("", "", body)
            out[pid] = path
    return out


def launchable():
    txt = run(["cmd", "package", "query-activities", "--brief", "-a", "android.intent.action.MAIN",
               "-c", "android.intent.category.LAUNCHER"], 30)
    ids = {m.group(1) for m in re.finditer(r"^\s*([A-Za-z0-9_.]+)/", txt, re.M)}
    return ids or None


def aapt_label(apk):
    if not (AAPT and apk):
        return None
    m = re.search(r"application-label:'([^']*)'", run([AAPT, "dump", "badging", apk], 8))
    return m.group(1).strip() if m and m.group(1).strip() else None


def pretty(pid):
    parts = [p for p in pid.split(".") if p.lower() not in GENERIC] or pid.split(".")
    return re.sub(r"[_-]+", " ", parts[-1]).title()


def shorts(name, pid):
    low = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    words = low.split()
    cand = [low, "".join(words), words[0] if words else "", pid.split(".")[-1].lower()]
    if 2 <= len(words) <= 4:
        cand.append("".join(w[0] for w in words))
    seen, out = set(), []
    for c in cand:
        if c and c != name.lower() and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def main():
    global AAPT
    AAPT = shutil.which("aapt")
    allp = pkg_list(["-f"]) or {p: "" for p in pkg_list([])}
    if not allp:
        print("[capture_apps] 'pm list packages' returned nothing; cannot capture apps.")
        return 1
    third, launch = set(pkg_list(["-3"])), launchable()
    todo = [p for p in allp if (p in launch if launch else p in third)]
    with ThreadPoolExecutor(8) as ex:
        labels = dict(zip(todo, ex.map(lambda p: aapt_label(allp[p]), todo)))
    apps = []
    for pid, path in allp.items():
        is_l = (pid in launch) if launch else None
        if launch and not is_l and pid not in third:
            continue  # skip background-only system packages
        name = labels.get(pid) or pretty(pid)
        apps.append({"package": pid, "name": name, "short": shorts(name, pid),
                     "system": pid not in third, "launchable": is_l})
    count = {}
    for a in apps:
        for s in a["short"]:
            count[s] = count.get(s, 0) + 1
    for a in apps:
        a["short"] = [s for s in a["short"] if count[s] == 1]
    apps.sort(key=lambda a: a["name"].lower())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "count": len(apps), "apps": apps},
                  f, indent=2, ensure_ascii=False)
    os.replace(tmp, OUT)
    named = sum(1 for p in todo if labels.get(p))
    print(f"[capture_apps] {len(apps)} apps saved to {OUT} ({named} real names via aapt, rest derived).")
    return 0


AAPT = None
if __name__ == "__main__":
    sys.exit(main())