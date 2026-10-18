from src.env import env
from src.integrations import ModelAdapter


def test_canonical_environment_preserves_legacy_alias_and_precedence(monkeypatch):
    monkeypatch.delenv("STEWARD_MODEL_PROVIDER", raising=False)
    monkeypatch.setenv("PHY_MODEL_PROVIDER", "openai")
    assert env("STEWARD_MODEL_PROVIDER", "local") == "openai"
    assert ModelAdapter().provider == "openai"
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    assert ModelAdapter().provider == "local"
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "")
    assert env("STEWARD_MODEL_PROVIDER", "local") == ""
