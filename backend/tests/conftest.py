"""Test isolation: the repository root `.env` is a template with placeholder values that `src.main` loads at import.

Provider adapters treat any non-empty value as configured, so without this shim the suite would try Supabase
upserts and read placeholder Inkbox handles. Every test starts from a clean provider environment; tests that need a
provider set it explicitly with monkeypatch.
"""
import os

import pytest

_PREFIXES = ("INKBOX_", "SUPABASE_", "STRIPE_", "INSFORGE_", "SUPERMEMORY_", "STEWARD_", "NEXT_PUBLIC_", "ARMATURE_",
             "ANALYTICS_INGEST_", "AI_GATEWAY_", "PHY_")
_KEEP = {"STEWARD_DATA_DIR"}


@pytest.fixture(autouse=True)
def _clean_provider_environment(monkeypatch):
    for key in list(os.environ):
        if key.startswith(_PREFIXES) and key not in _KEEP:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("STEWARD_SIMULATION", "false")
    yield
