"""Typed errors for the reality layer. Every HTTP error body is {detail, code, recovery}."""
from __future__ import annotations


class RealityError(ValueError):
    """A client-visible failure with a stable code and a recovery hint."""

    def __init__(self, detail: str, code: str = "INVALID_REQUEST", recovery: str = "", status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.code = code
        self.recovery = recovery
        self.status = status

    def body(self) -> dict:
        return {"detail": self.detail, "code": self.code, "recovery": self.recovery}
