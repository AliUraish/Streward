"""Steward settings with a compatibility alias for pre-rename local environments."""
import os


def env(name: str, default=None):
    if name in os.environ:
        return os.environ[name]
    if name.startswith("STEWARD_"):
        return os.getenv("PHY_" + name.removeprefix("STEWARD_"), default)
    return os.getenv(name, default)


_SANITIZED_PREFIXES = ("INKBOX_", "STEWARD_", "SUPABASE_", "STRIPE_", "INSFORGE_", "SUPERMEMORY_", "ARMATURE_")


def sanitize_environment() -> list[str]:
    """Drop template artefacts loaded from a .env file: values that are only an inline comment become unset and
    trailing ` # comments` are stripped. The Inkbox SDK reads INKBOX_BASE_URL / INKBOX_VAULT_KEY straight from the
    environment, so this has to happen in the process environment, not only in our own readers."""
    import re
    changed = []
    for name, raw in list(os.environ.items()):
        if not name.startswith(_SANITIZED_PREFIXES):
            continue
        value = raw.strip()
        cleaned = "" if value.startswith("#") else re.split(r"\s+#", value, maxsplit=1)[0].strip().strip('"').strip("'").strip()
        if cleaned != raw or not cleaned:
            changed.append(name)
            if cleaned:
                os.environ[name] = cleaned
            else:
                os.environ.pop(name, None)  # an empty template value means unset, never ""
    return changed
