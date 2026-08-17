"""Minimal autonomous participant for Sovereign Agents Protocol v0.1.

Imports are intentionally lazy so read-only tooling can use the HTTP client without
loading the signing stack (or its native cryptography dependencies).
"""

from importlib import import_module

__all__ = ["AgentZero", "AgentZeroIdentity", "Decision", "DecisionModel", "DecisionRecord"]


def __getattr__(name: str):
    modules = {
        "AgentZero": (".agent", "AgentZero"),
        "AgentZeroIdentity": (".identity", "AgentZeroIdentity"),
        "Decision": (".decision", "Decision"),
        "DecisionModel": (".decision", "DecisionModel"),
        "DecisionRecord": (".decision", "DecisionRecord"),
    }
    if name not in modules:
        raise AttributeError(name)
    module, attribute = modules[name]
    return getattr(import_module(module, __name__), attribute)
