#!/usr/bin/env python3
"""Install one or many SKILL.md skills from a GitHub repository using the stdlib."""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
API = "https://api.github.com"


def _get_json(url):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "JARVIS-Multi-Skill-Installer",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_github_url(value):
    """Accept repo URLs or tree/blob URLs; reject non-GitHub and malformed URLs."""
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"https"} or parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValueError("Use an https://github.com/owner/repository URL.")
    parts = [urllib.parse.unquote(p) for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2 or any(p in {".", ".."} for p in parts):
        raise ValueError("Expected a GitHub owner/repository URL.")
    owner, repo = parts[0], parts[1]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid owner or repository name.")
    branch, subpath = None, ""
    if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
        branch = parts[3]
        subpath = "/".join(parts[4:])
    return owner, repo.removesuffix(".git"), branch, subpath


def discover_skills(owner, repo, branch=None, subpath=""):
    repo_info = _get_json(f"{API}/repos/{owner}/{repo}")
    branch = branch or repo_info.get("default_branch") or "main"
    branch_q = urllib.parse.quote(branch, safe="")
    tree = _get_json(f"{API}/repos/{owner}/{repo}/git/trees/{branch_q}?recursive=1")
    if tree.get("truncated"):
        raise RuntimeError("GitHub tree was truncated; use a narrower folder URL.")
    prefix = subpath.strip("/")
    found = []
    for entry in tree.get("tree", []):
        path = entry.get("path", "")
        if entry.get("type") != "blob" or Path(path).name.lower() != "skill.md":
            continue
        if prefix and not (path == prefix + "/SKILL.md" or path.startswith(prefix + "/")):
            continue
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        found.append((parent, path))
    return branch, sorted(found)


def install_skills(owner, repo, branch, skills, destination=SKILLS_DIR):
    destination = Path(destination).resolve()
    installed, failed = [], []
    for folder, skill_path in skills:
        slug = Path(folder).name if folder else repo
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", slug).strip(".-")[:80]
        if not slug:
            failed.append((skill_path, "could not derive a safe skill name"))
            continue
        target_dir = (destination / slug).resolve()
        if destination not in target_dir.parents:
            failed.append((skill_path, "unsafe destination"))
            continue
        if target_dir.exists():
            failed.append((skill_path, "destination already exists; refusing to overwrite"))
            continue
        raw_url = "https://raw.githubusercontent.com/{}/{}/{}/{}".format(
            owner, repo, urllib.parse.quote(branch, safe=""), "/".join(urllib.parse.quote(p, safe="") for p in skill_path.split("/"))
        )
        try:
            request = urllib.request.Request(raw_url, headers={"User-Agent": "JARVIS-Multi-Skill-Installer"})
            with urllib.request.urlopen(request, timeout=20) as response:
                content = response.read(512 * 1024 + 1)
            if len(content) > 512 * 1024:
                raise ValueError("SKILL.md exceeds 512 KiB")
            text = content.decode("utf-8")
            if not text.strip():
                raise ValueError("empty SKILL.md")
            target_dir.mkdir(parents=True, exist_ok=False)
            (target_dir / "SKILL.md").write_text(text, encoding="utf-8")
            installed.append((slug, str(target_dir)))
        except Exception as exc:
            if target_dir.exists() and not (target_dir / "SKILL.md").exists():
                try:
                    target_dir.rmdir()
                except OSError:
                    pass
            failed.append((skill_path, str(exc)))
    return installed, failed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install all SKILL.md files found in a GitHub repo or folder.")
    parser.add_argument("github_url", help="GitHub repository, tree/<branch>, or tree/<branch>/<folder> URL")
    parser.add_argument("--list", action="store_true", help="list discovered skills without installing")
    parser.add_argument("--yes", action="store_true", help="install all discovered skills without interactive confirmation")
    args = parser.parse_args(argv)
    try:
        owner, repo, branch, subpath = parse_github_url(args.github_url)
        branch, skills = discover_skills(owner, repo, branch, subpath)
        if not skills:
            print("No SKILL.md files found. Use a repository/folder that contains Agent Skills.")
            return 1
        print("Found {} skill(s) in {}/{} @ {}:".format(len(skills), owner, repo, branch))
        for index, (folder, path) in enumerate(skills, 1):
            print("  {}. {}".format(index, folder or path))
        if args.list:
            return 0
        if not args.yes:
            if not sys.stdin.isatty():
                print("Non-interactive install requires --yes.", file=sys.stderr)
                return 2
            answer = input("Install all {} skill(s) into {}? [y/N]: ".format(len(skills), SKILLS_DIR)).strip().lower()
            if answer not in {"y", "yes"}:
                print("Cancelled; no files changed.")
                return 0
        installed, failed = install_skills(owner, repo, branch, skills)
        for name, path in installed:
            print("INSTALLED {} -> {}".format(name, path))
        for path, error in failed:
            print("SKIPPED {}: {}".format(path, error))
        print("Summary: {} installed, {} skipped.".format(len(installed), len(failed)))
        return 0 if installed and not failed else (1 if failed else 0)
    except (ValueError, RuntimeError, urllib.error.URLError, TimeoutError) as exc:
        print("Skill installation failed: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
