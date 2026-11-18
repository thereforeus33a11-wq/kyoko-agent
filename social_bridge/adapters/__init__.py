"""Importing this package registers every platform adapter."""
import importlib
import logging

_MODULES = ["mastodon"]

for _m in _MODULES:
    try:
        importlib.import_module(f"{__name__}.{_m}")
    except ImportError as _e:  # a missing optional dependency only disables that one platform
        logging.getLogger("social_bridge").warning("adapter %s unavailable: %s", _m, _e)
