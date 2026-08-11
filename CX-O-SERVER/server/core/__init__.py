# Lazy imports to avoid circular imports:
# server.config -> server.core.utils -> server.core.__init__ -> server.core.context -> server.config

__all__ = ["memory", "context", "tools", "acp", "llm"]


def __getattr__(name: str):
    _lazy = {
        "acp": ".acp",
        "context": ".context",
        "llm": ".llm",
        "memory": ".memory",
        "tools": ".tools",
    }
    if name in _lazy:
        import importlib
        module = importlib.import_module(_lazy[name], __package__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
