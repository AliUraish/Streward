#!/usr/bin/env python
"""Create the Inkbox webhook subscription that delivers inbound replies to /api/inbound/inkbox.

Usage: backend/.venv/bin/python backend/scripts/inkbox_subscribe.py <propertyId>
Needs INKBOX_API_KEY, the site identity handle (INKBOX_IDENTITY_<SITE> or INKBOX_IDENTITY),
STEWARD_PUBLIC_BASE_URL (https tunnel) and STEWARD_INBOUND_SECRET. Prints the per-identity signing key once
if Inkbox mints one; store it as INKBOX_WEBHOOK_SIGNING_KEY. Nothing is sent to any recipient.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

from src.providers import InkboxAdapter, ProviderNotConfigured  # noqa: E402


def main() -> int:
    property_id = sys.argv[1] if len(sys.argv) > 1 else "harbor"
    base = os.getenv("STEWARD_PUBLIC_BASE_URL", "")
    secret = os.getenv("STEWARD_INBOUND_SECRET", "")
    if not base or not secret:
        print("Set STEWARD_PUBLIC_BASE_URL (https tunnel) and STEWARD_INBOUND_SECRET first.")
        return 2
    try:
        result = InkboxAdapter().ensure_webhook(property_id, base, secret)
    except (ProviderNotConfigured, ValueError) as error:
        print(str(error))
        return 2
    print(f"Subscription {result['id']} {'created' if result['created'] else 'already present'} for {result['url']}")
    if result.get("signingKey"):
        print("Inkbox minted a signing key for this identity (shown once). Save it as INKBOX_WEBHOOK_SIGNING_KEY:")
        print(result["signingKey"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
