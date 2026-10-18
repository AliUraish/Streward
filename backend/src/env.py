"""Steward settings with a compatibility alias for pre-rename local environments."""
import os


def env(name: str, default=None):
    if name in os.environ:
        return os.environ[name]
    if name.startswith("STEWARD_"):
        return os.getenv("PHY_" + name.removeprefix("STEWARD_"), default)
    return os.getenv(name, default)
