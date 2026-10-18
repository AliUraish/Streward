"""Keep an Inkbox tunnel open from <handle>.inkboxwire.com to the local backend.

Usage: backend/.venv/bin/python -I scripts/inkbox_tunnel.py [handle] [forward_to]
Defaults: handle = INKBOX_IDENTITY_ATLAS from .env, forward_to = http://127.0.0.1:${BACKEND_PORT:-8001}
Writes STEWARD_PUBLIC_BASE_URL into .env and stays running (Ctrl+C to stop). Prints no secrets.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inkbox_setup import client, load_env, set_env  # noqa: E402


def main() -> int:
    env = load_env()
    handle = sys.argv[1] if len(sys.argv) > 1 else env.get("INKBOX_IDENTITY_ATLAS") or "steward-atlas"
    port = env.get("BACKEND_PORT") or "8001"
    forward_to = sys.argv[2] if len(sys.argv) > 2 else f"http://127.0.0.1:{port}"
    from inkbox.tunnels.client._listener import connect
    ib = client(env)
    listener = connect(ib, name=handle, forward_to=forward_to,
                       on_status=lambda s: print(f"tunnel status: {getattr(s, 'state', s)}", flush=True))
    url = listener.public_url
    set_env("STEWARD_PUBLIC_BASE_URL", url)
    print(f"tunnel up: {url} -> {forward_to} (saved as STEWARD_PUBLIC_BASE_URL)", flush=True)
    try:
        listener.wait()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
