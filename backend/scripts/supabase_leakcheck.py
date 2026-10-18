#!/usr/bin/env python
"""Leak check for the Supabase work: no secret in any file git would track, CLI state ignored, nothing secret in the
frontend bundle. Prints file names and what matched, never a value. No git commands: .gitignore rules are applied here.

Usage: backend/.venv/bin/python -I backend/scripts/supabase_leakcheck.py [--bundle frontend/.next]
Exit 0 when clean, 1 when something leaked.

Checks
1. Every file not ignored by the repo's .gitignore files: key-shaped strings (sb_secret_…, sk-ant-…, ami_us_…, Inkbox
   ApiKey_…, sm_…, legacy service_role JWTs) and the exact values of every secret-looking variable in the root .env and
   frontend/.env.local, including the ten STEWARD_AGENT_PASSWORD_* values.
2. supabase/.temp (CLI state) and every .env file are ignored.
3. The frontend bundle (.next/static and .next/server) contains no secret value; the publishable key is allowed.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".next", ".turbo"}
SECRET_NAME = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASS|PRIVATE)", re.I)
PUBLIC_NAMES = {"NEXT_PUBLIC_SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY", "INSFORGE_ANON_KEY"}
KEY_SHAPES = {
    "Supabase secret key": re.compile(r"sb_secret_[A-Za-z0-9_-]{20,}"),
    "Anthropic key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "Armature/analytics key": re.compile(r"ami_us_[A-Za-z0-9_-]{16,}"),
    "Inkbox key": re.compile(r"ApiKey_[A-Za-z0-9_-]{16,}"),
    "Supermemory key": re.compile(r"\bsm_[A-Za-z0-9]{24,}"),
    "Stripe secret key": re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{16,}"),
    "service_role JWT": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]*cm9sZSI6InNlcnZpY2Vfcm9sZS[A-Za-z0-9_-]*\.[A-Za-z0-9_-]{10,}"),
}


def env_values(path: Path) -> dict[str, str]:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(errors="replace").splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not match:
            continue
        name, value = match.group(1), match.group(2).strip()
        if value[:1] in "\"'" and value[-1:] == value[:1]:
            value = value[1:-1]
        value = value.split(" #", 1)[0].strip()
        if value and not value.startswith("#"):
            values[name] = value
    return values


class GitIgnore:
    """Enough of gitignore for this repo: per-directory files, comments, negation, anchored and directory patterns."""

    def __init__(self, root: Path):
        self.root = root
        self.rules: list[tuple[Path, str, bool, bool, bool]] = []  # (base, pattern, negate, dir_only, anchored)
        for ignore in [root / ".gitignore", *sorted(root.rglob(".gitignore"))]:
            if any(part in SKIP_DIRS for part in ignore.relative_to(root).parts[:-1]):
                continue
            for raw in ignore.read_text(errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                negate = line.startswith("!")
                line = line[1:] if negate else line
                dir_only = line.endswith("/")
                line = line.rstrip("/")
                anchored = "/" in line
                self.rules.append((ignore.parent, line.lstrip("/"), negate, dir_only, anchored))

    def ignored(self, path: Path) -> bool:
        verdict = False
        for base, pattern, negate, dir_only, anchored in self.rules:
            try:
                rel = path.relative_to(base)
            except ValueError:
                continue
            parts = rel.parts
            hit = False
            for depth in range(1, len(parts) + 1):  # the path itself or any parent directory
                candidate = "/".join(parts[:depth])
                is_dir = depth < len(parts) or path.is_dir()
                if dir_only and not is_dir:
                    continue
                if anchored:
                    if fnmatch.fnmatch(candidate, pattern) or fnmatch.fnmatch(candidate, pattern + "/**"):
                        hit = True
                elif fnmatch.fnmatch(parts[depth - 1], pattern):
                    hit = True
                if hit:
                    break
            if hit:
                verdict = not negate
        return verdict


def tracked_files(root: Path, ignore: GitIgnore):
    for directory, dirs, files in os.walk(root):
        current = Path(directory)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not ignore.ignored(current / d)]
        for name in files:
            path = current / name
            if not ignore.ignored(path):
                yield path


def scan(path: Path, secrets: dict[str, str]) -> list[str]:
    try:
        if path.stat().st_size > 20 * 1024 * 1024:
            return []
        text = path.read_bytes().decode("utf-8", errors="ignore")
    except OSError:
        return []
    found = [label for label, pattern in KEY_SHAPES.items() if pattern.search(text)]
    found += [f"value of {name}" for name, value in secrets.items() if value in text]
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", default=str(ROOT / "frontend" / ".next"))
    args = parser.parse_args()
    env = {**env_values(ROOT / "frontend" / ".env.local"), **env_values(ROOT / ".env")}
    secrets = {name: value for name, value in env.items()
               if SECRET_NAME.search(name) and name not in PUBLIC_NAMES and len(value) >= 12 and not value.startswith(("http://", "https://"))}
    ignore = GitIgnore(ROOT)
    problems = 0
    files = list(tracked_files(ROOT, ignore))
    print(f"1. scanned {len(files)} file(s) git would track for key-shaped strings and {len(secrets)} secret value(s) "
          f"(incl. {sum(1 for n in secrets if n.startswith('STEWARD_AGENT_PASSWORD_'))} agent passwords)")
    for path in files:
        hits = scan(path, secrets)
        if hits:
            problems += 1
            print(f"   LEAK {path.relative_to(ROOT)}: {', '.join(sorted(set(hits)))}")
    if not problems:
        print("   clean: no secret in any tracked file")
    print("2. ignored by .gitignore:")
    for rel in ("supabase/.temp", "supabase/.temp/linked-project.json", ".env", "frontend/.env.local", "backend/.env", "backend/data",
                "supabase/functions/inkbox-inbox/.env"):
        ok = ignore.ignored(ROOT / rel)
        problems += 0 if ok else 1
        print(f"   {'ok  ' if ok else 'MISS'} {rel}")
    env_like = [path for path in files if path.name.startswith(".env") or path.suffix == ".env"]
    print(f"   env-like files git would track: {', '.join(str(p.relative_to(ROOT)) for p in env_like) or 'none'}")
    for path in env_like:
        filled = sorted(name for name, value in env_values(path).items()
                        if SECRET_NAME.search(name) and name not in PUBLIC_NAMES and len(value) >= 12 and not value.startswith(("http://", "https://", "<")))
        if filled:
            problems += 1
            print(f"   LEAK {path.relative_to(ROOT)} carries filled secret-named values: {', '.join(filled)}")
    bundle = Path(args.bundle)
    print(f"3. frontend bundle {bundle.relative_to(ROOT) if bundle.is_relative_to(ROOT) else bundle}:")
    if not (bundle / "static").exists():
        print("   no production build found (run `npm run build` in frontend/); source checked instead:")
        targets = [p for p in (ROOT / "frontend" / "src").rglob("*") if p.is_file()]
    else:
        targets = [p for sub in ("static", "server") for p in (bundle / sub).rglob("*") if p.is_file()]
    bundle_hits = 0
    publishable_seen = False
    for path in targets:
        hits = scan(path, secrets)
        if env.get("NEXT_PUBLIC_SUPABASE_ANON_KEY") and env["NEXT_PUBLIC_SUPABASE_ANON_KEY"] in path.read_bytes().decode("utf-8", errors="ignore"):
            publishable_seen = True
        if hits:
            bundle_hits += 1
            print(f"   LEAK {path}: {', '.join(sorted(set(hits)))}")
    problems += bundle_hits
    print(f"   {len(targets)} file(s) scanned; secrets found: {bundle_hits}; publishable key present (public by design): {publishable_seen}")
    print("RESULT:", "clean" if not problems else f"{problems} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
