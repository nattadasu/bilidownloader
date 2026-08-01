import importlib

__all__ = [
    "apis",
    "cli",
    "commons",
    "download",
    "downmux",
    "history",
    "subtitles",
    "watchlist",
]


def __getattr__(name: str):
    if name in __all__:
        if name == "download":
            mod = importlib.import_module(".downmux.orchestrator", __name__)
            return mod.download
        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
