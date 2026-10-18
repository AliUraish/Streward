"""Write Supabase-related lines into the root .env without ever printing a value.

Usage (from code): set_env_values({"STEWARD_AGENT_PASSWORD_OPERATOR": "..."}). Replaces an existing `NAME=` line in
place or appends one, writes atomically (temp file + rename) and keeps the file's mode. Only names starting with
SUPABASE_, STEWARD_AGENT_PASSWORD_ or NEXT_PUBLIC_SUPABASE_ may be written.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
ALLOWED = ("SUPABASE_", "STEWARD_AGENT_PASSWORD_", "NEXT_PUBLIC_SUPABASE_")


def set_env_values(values: dict[str, str], path: Path = ROOT_ENV) -> list[str]:
    for name, value in values.items():
        if not name.startswith(ALLOWED) or not re.fullmatch(r"[A-Z0-9_]+", name):
            raise ValueError(f"refusing to write {name}: not a Supabase setting")
        if "\n" in value or "\r" in value:
            raise ValueError(f"refusing to write {name}: value contains a newline")
    lines = path.read_text().splitlines() if path.exists() else []
    written = []
    for name, value in values.items():
        pattern = re.compile(rf"^\s*(export\s+)?{re.escape(name)}\s*=")
        line = f"{name}={value}"
        for index, existing in enumerate(lines):
            if pattern.match(existing):
                lines[index] = line
                break
        else:
            lines.append(line)
        written.append(name)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write("\n".join(lines) + "\n")
        os.chmod(temp, mode)
        os.replace(temp, path)
    except Exception:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
    return written
